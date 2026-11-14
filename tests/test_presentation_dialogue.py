"""表情随最终回复传递，不能改变普通正文或放宽其他工具权限。"""

import json
from types import SimpleNamespace

import pytest

from pet.config import Settings
from pet.memory import MemoryStore
from pet.tool_dialogue import run_dialogue
from pet.tool_protocol import AssistantReply, ToolCall


def make_runtime(tmp_path, responses, *, supported=True):
    requests, replies, expressions = [], [], []

    async def complete(_settings, messages, tools=(), **kwargs):
        requests.append((list(messages), list(tools), kwargs))
        return responses.pop(0)

    async def start(_settings):
        return None

    return SimpleNamespace(
        epoch=0, history=[], motion_actions=(), memory=MemoryStore(tmp_path / "memory.json"),
        engine=SimpleNamespace(complete=complete, start=start, supports_presentation=supported),
        should_speak=lambda *_: False,
        reply=SimpleNamespace(emit=lambda epoch, text, kind: replies.append((epoch, text, kind))),
        reply_expression=SimpleNamespace(emit=lambda epoch, expression: expressions.append((epoch, expression))),
        state=SimpleNamespace(emit=lambda *_: None), requests=requests, replies=replies, expressions=expressions,
    )


def present(text, expression="happy", *, call_id="present-1", prefix=""):
    arguments = json.dumps({"text": text, "expression": expression}, ensure_ascii=False)
    return AssistantReply(prefix, (ToolCall(call_id, "present_reply", arguments),), "tool_calls")


@pytest.mark.asyncio
async def test_terminal_presentation_emits_exact_body_and_pairs_history(tmp_path):
    text = "  谢谢你，[voice:off] 在这里是普通文字。\n"
    runtime = make_runtime(tmp_path, [present(text)])
    result = await run_dialogue(runtime, 0, Settings(), "今天成功了", [], "chat", None, None)
    assert result.content == text
    assert runtime.replies == [(0, text, "chat")]
    assert runtime.expressions == [(0, "happy")]
    assert len(runtime.requests) == 1
    assert "present_reply" in {tool["function"]["name"] for tool in runtime.requests[0][1]}
    assert [item["role"] for item in runtime.history] == ["user", "assistant", "tool", "assistant"]
    assert runtime.history[2]["tool_call_id"] == "present-1"
    assert runtime.history[-1]["content"] == text


@pytest.mark.asyncio
async def test_plain_reply_falls_back_without_losing_text(tmp_path):
    text = "  先休息一下。\n"
    runtime = make_runtime(tmp_path, [AssistantReply(text)])
    result = await run_dialogue(runtime, 0, Settings(), "今天累了", [], "chat", None, None)
    assert result.content == text
    assert runtime.replies == [(0, text, "chat")]
    assert runtime.expressions == [(0, "neutral")]


@pytest.mark.asyncio
async def test_invalid_expression_preserves_valid_body(tmp_path):
    runtime = make_runtime(tmp_path, [present("有效正文", "unknown")])
    result = await run_dialogue(runtime, 0, Settings(), "你好", [], "chat", None, None)
    assert result.content == "有效正文"
    assert runtime.expressions == [(0, "neutral")]


@pytest.mark.asyncio
async def test_presentation_preserves_model_prelude_and_final_body(tmp_path):
    runtime = make_runtime(tmp_path, [present("最终正文", prefix="工具前的原话。")])
    result = await run_dialogue(runtime, 0, Settings(), "你好", [], "chat", None, None)
    assert result.content == "最终正文"
    assert runtime.replies == [(0, "工具前的原话。", "chat"), (0, "最终正文", "chat")]
    assert runtime.history[1]["content"] == "工具前的原话。"


@pytest.mark.asyncio
@pytest.mark.parametrize("suffix", ["", "\n</think>\n\n"])
async def test_repeated_presentation_prelude_is_shown_only_once(tmp_path, suffix):
    """有些本机回复会先重复正文再调用展示工具，不能让用户看到两份。"""
    text = "这件事听起来让你很失落。"
    runtime = make_runtime(tmp_path, [present(text, prefix=text + suffix)])

    result = await run_dialogue(runtime, 0, Settings(), "今天不太顺利", [], "chat", None, None)

    assert result.content == text
    assert runtime.replies == [(0, text, "chat")]
    assert runtime.history[1]["content"] == ""
    assert runtime.history[-1]["content"] == text


@pytest.mark.asyncio
async def test_requested_think_marker_is_not_deduplicated(tmp_path):
    """用户明确要求原样输出标记时，不能把它视为模型控制残留。"""
    runtime = make_runtime(tmp_path, [present("示例", prefix="示例</think>")])
    await run_dialogue(runtime, 0, Settings(), "请输出字面量 </think>", [], "chat", None, None)

    assert runtime.replies == [(0, "示例</think>", "chat"), (0, "示例", "chat")]


@pytest.mark.asyncio
async def test_empty_terminal_body_fails_without_inventing_a_reply(tmp_path):
    runtime = make_runtime(tmp_path, [present("  ")])
    with pytest.raises(RuntimeError, match="没有生成有效回复"):
        await run_dialogue(runtime, 0, Settings(), "你好", [], "chat", None, None)
    assert not runtime.replies and not runtime.expressions
    assert runtime.history[-1]["role"] == "tool"
    assert not json.loads(runtime.history[-1]["content"])["ok"]


@pytest.mark.asyncio
async def test_invalid_terminal_body_still_preserves_independent_prelude(tmp_path):
    runtime = make_runtime(tmp_path, [present("  ", prefix="已经生成的说明。")])
    with pytest.raises(RuntimeError, match="没有生成有效回复"):
        await run_dialogue(runtime, 0, Settings(), "你好", [], "chat", None, None)
    assert runtime.replies == [(0, "已经生成的说明。", "chat")]
    assert runtime.history[1]["content"] == "已经生成的说明。"


@pytest.mark.asyncio
async def test_cancelled_terminal_result_never_reaches_interface(tmp_path):
    runtime = make_runtime(tmp_path, [])

    async def cancelled(_settings, _messages, _tools=(), **_kwargs):
        runtime.epoch += 1
        return present("迟到的回复")

    runtime.engine.complete = cancelled
    result = await run_dialogue(runtime, 0, Settings(), "你好", [], "chat", None, None)
    assert result.content is None
    assert not runtime.replies and not runtime.expressions


@pytest.mark.asyncio
async def test_unverified_model_never_receives_presentation_tool(tmp_path):
    runtime = make_runtime(tmp_path, [AssistantReply("正常回答")], supported=False)
    result = await run_dialogue(runtime, 0, Settings(), "你好", [], "chat", None, None)
    assert result.content == "正常回答"
    assert "present_reply" not in {tool["function"]["name"] for tool in runtime.requests[0][1]}
    assert runtime.expressions == [(0, "neutral")]


@pytest.mark.asyncio
async def test_mixed_presentation_and_write_tool_cannot_execute_side_effect(tmp_path):
    mixed = AssistantReply("", (
        ToolCall("present", "present_reply", '{"text":"你好","expression":"happy"}'),
        ToolCall("save", "save_memory", '{"note":"未经授权的记忆"}'),
    ), "tool_calls")
    runtime = make_runtime(tmp_path, [mixed, AssistantReply("这一轮没有保存。")])
    result = await run_dialogue(runtime, 0, Settings(), "只是聊聊", [], "chat", None, None)
    assert result.content == "这一轮没有保存。"
    assert runtime.memory.read() == ""
    receipts = [item for item in runtime.history if item["role"] == "tool"]
    assert {item["tool_call_id"] for item in receipts} == {"present", "save"}
    assert all(not json.loads(item["content"])["ok"] for item in receipts)


@pytest.mark.asyncio
async def test_explicit_no_tool_request_does_not_offer_presentation(tmp_path):
    runtime = make_runtime(tmp_path, [AssistantReply("无需回应")])
    result = await run_dialogue(
        runtime, 0, Settings(), "请仅回复四个汉字：无需回应。不要调用工具。", [], "chat", None, None
    )
    assert result.content == "无需回应"
    assert "present_reply" not in {tool["function"]["name"] for tool in runtime.requests[0][1]}
    assert "present_reply" not in runtime.requests[0][0][0]["content"]


@pytest.mark.asyncio
async def test_presentation_not_offered_after_a_real_tool_has_run(tmp_path):
    runtime = make_runtime(tmp_path, [
        AssistantReply("", (ToolCall("save", "save_memory", '{"note":"用户喜欢绿茶"}'),), "tool_calls"),
        AssistantReply("已经记住。"),
    ])
    result = await run_dialogue(runtime, 0, Settings(), "请记住我喜欢绿茶", [], "chat", None, None)
    assert result.content == "已经记住。"
    assert runtime.memory.read() == "用户喜欢绿茶"
    assert "present_reply" in {tool["function"]["name"] for tool in runtime.requests[0][1]}
    assert "present_reply" not in {tool["function"]["name"] for tool in runtime.requests[1][1]}
