"""验证工具闭环的真实历史、正文保真与取消后已完成的写入。"""

import asyncio
import json
import threading
from types import SimpleNamespace

import pytest

from pet.config import Settings
from pet.memory import MemoryStore
from pet.tool_dialogue import run_dialogue
from pet.tool_protocol import AssistantReply, ToolCall


@pytest.fixture
def runtime(tmp_path):
    replies = []
    responses = []
    requests = []

    async def complete(_settings, messages, tools=(), **kwargs):
        requests.append((list(messages), tools, kwargs))
        reply = responses.pop(0)
        return reply

    async def start(_settings):
        return None

    return SimpleNamespace(
        epoch=0, history=[], motion_actions=(),
        engine=SimpleNamespace(complete=complete, start=start),
        memory=MemoryStore(tmp_path / "memory.json"),
        should_speak=lambda *_: False,
        reply=SimpleNamespace(emit=lambda _, text, kind: replies.append((text, kind))),
        state=SimpleNamespace(emit=lambda *_: None),
        memory_loaded=SimpleNamespace(emit=lambda *_: None),
        responses=responses, requests=requests, replies=replies,
    )


async def run(runtime, kind="chat"):
    return await run_dialogue(runtime, 0, Settings(speak_replies=False), "本轮原始输入", [], kind, None, None)


@pytest.mark.asyncio
async def test_plain_reply_is_verbatim_single_request(runtime):
    text = "  无需回应，也可以正常解释。\n"
    runtime.responses.append(AssistantReply(text))
    result = await run(runtime)
    assert result.content == text
    assert runtime.replies == [(text, "chat")]
    assert len(runtime.requests) == 1
    assert runtime.history[-1]["content"] == text


@pytest.mark.asyncio
async def test_attached_image_is_tool_data_separate_from_user_instruction(runtime):
    runtime.responses.append(AssistantReply("这是资料中的文字。"))
    await run_dialogue(runtime, 0, Settings(speak_replies=False), "只描述画面，保持原状态。",
                       [b"synthetic-image"], "chat-screen", (1, 1), None)
    messages, tools, _ = runtime.requests[0]
    user = next(message for message in messages if message["role"] == "user")
    assert user["content"] == [{"type": "text", "text": "只描述画面，保持原状态。"}]
    receipt = messages[-1]
    assert receipt["role"] == "tool"
    assert receipt["tool_call_id"] == messages[-2]["tool_calls"][0]["id"]
    assert receipt["content"][0]["type"] == "image_url"
    assert json.loads(receipt["content"][-1]["text"])["source"] == "user_attached_screen"
    assert "capture_screen" not in {tool["function"]["name"] for tool in tools}
    assert len(runtime.requests) == 1


@pytest.mark.asyncio
async def test_save_receipt_precedes_final_reply_and_preserves_prelude(runtime):
    runtime.responses.extend([
        AssistantReply("我来保存。", (ToolCall("save-1", "save_memory", '{"note":"我喜欢绿茶"}'),), "tool_calls"),
        AssistantReply("已经保存。"),
    ])
    await run(runtime)
    assert runtime.memory.read() == "我喜欢绿茶"
    assert runtime.replies == [("我来保存。", "chat"), ("已经保存。", "chat")]
    receipt = runtime.history[-2]
    assert receipt["role"] == "tool" and receipt["tool_call_id"] == "save-1"
    assert json.loads(receipt["content"])["ok"] is True
    assert runtime.requests[1][0][-1] == receipt


@pytest.mark.asyncio
async def test_observation_finishes_by_tool_without_touching_chat_history(runtime):
    runtime.responses.append(AssistantReply("", (ToolCall("quiet-1", "finish_observation", "{}"),), "tool_calls"))
    result = await run(runtime, "observation")
    assert result.content is None
    assert runtime.replies == [] and runtime.history == []
    assert len(runtime.requests) == 1


@pytest.mark.asyncio
async def test_mixed_finish_observation_does_not_swallow_visible_content(runtime):
    runtime.responses.extend([
        AssistantReply("无需回应", (ToolCall("quiet-1", "finish_observation", "{}"),), "tool_calls"),
        AssistantReply("本次画面已看清。"),
    ])
    await run(runtime, "observation")
    assert runtime.replies == [("无需回应", "observation"), ("本次画面已看清。", "observation")]
    receipt = runtime.requests[1][0][-1]
    assert json.loads(receipt["content"])["ok"] is False


@pytest.mark.asyncio
async def test_limit_returns_matching_failures_and_one_no_tools_summary(runtime):
    runtime.responses.extend([
        AssistantReply("", tuple(ToolCall(f"bad-{i}", "unknown_tool", "{}") for i in range(7)), "tool_calls"),
        AssistantReply("已达到本轮调用上限。"),
    ])
    await run(runtime)
    receipts = [item for item in runtime.history if item["role"] == "tool"]
    assert len(receipts) == 7 and all(not json.loads(item["content"])["ok"] for item in receipts)
    assert runtime.requests[-1][2]["tool_choice"] == "none"


@pytest.mark.asyncio
async def test_cancelled_save_keeps_real_success_in_history(runtime):
    entered = threading.Event()
    release = threading.Event()
    remember = runtime.memory.remember

    def slow_save(*args):
        entered.set()
        release.wait(3)
        return remember(*args)

    runtime.memory.remember = slow_save
    runtime.responses.append(AssistantReply("", (ToolCall("save-1", "save_memory", '{"note":"我喜欢绿茶"}'),),
                                           "tool_calls"))
    task = asyncio.create_task(run(runtime))
    assert await asyncio.to_thread(entered.wait, 2)
    runtime.epoch += 1
    task.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert runtime.memory.read() == "我喜欢绿茶"
    assert runtime.history[-1]["role"] == "tool"
    assert json.loads(runtime.history[-1]["content"])["ok"] is True
    assert runtime.replies == []

@pytest.mark.asyncio
async def test_double_cancel_keeps_completed_save_and_remaining_receipt(runtime):
    entered, release = threading.Event(), threading.Event()
    remember = runtime.memory.remember

    def slow_save(*args):
        entered.set()
        release.wait(3)
        return remember(*args)

    runtime.memory.remember = slow_save
    runtime.responses.append(AssistantReply('', (
        ToolCall('save-1', 'save_memory', '{"note":"我喜欢绿茶"}'),
        ToolCall('save-2', 'save_memory', '{"note":"不能写入"}'),
    ), 'tool_calls'))
    task = asyncio.create_task(run(runtime))
    assert await asyncio.to_thread(entered.wait, 2)
    runtime.epoch += 1
    task.cancel()
    await asyncio.sleep(0)
    task.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    receipts = [item for item in runtime.history if item['role'] == 'tool']
    assert len(receipts) == 2
    assert json.loads(receipts[0]['content'])['ok'] is True
    assert json.loads(receipts[1]['content'])['status'] == 'cancelled'
    assert runtime.memory.read() == '我喜欢绿茶'
    assert len(runtime.requests) == 1


@pytest.mark.asyncio
async def test_duplicate_ids_preserve_body_and_pair_failures_without_side_effects(runtime):
    text = '  无需回应，原文仍应保留。\n'
    runtime.responses.append(AssistantReply(text, (
        ToolCall('duplicate', 'save_memory', '{"note":"不能写入一"}'),
        ToolCall('duplicate', 'save_memory', '{"note":"不能写入二"}'),
    ), 'tool_calls'))
    with pytest.raises(RuntimeError, match='标识'):
        await run(runtime)
    assert runtime.replies == [(text, 'chat')]
    assert runtime.history[1]['content'] == text
    receipts = [item for item in runtime.history if item['role'] == 'tool']
    assert len(receipts) == 2
    assert all(not json.loads(item['content'])['ok'] for item in receipts)
    assert runtime.memory.read() == ''
    assert len(runtime.requests) == 1
