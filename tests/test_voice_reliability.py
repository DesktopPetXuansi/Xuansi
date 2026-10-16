"""以受控模型验证上下文、工具语义和保存顺序；不宣称替代真实模型语义验收。"""

import copy
import json
from dataclasses import replace

import httpx
import pytest
from PySide6.QtCore import Qt

from pet.config import Settings
from pet.inference import LocalEngine, request_messages
from pet.memory import MemoryStore
from pet.runtime import Runtime
from pet.tool_protocol import AssistantReply, ToolCall

BODY = "我理解你的意思，继续陪你聊。"
CONTEXT = [
    {"role": "user", "content": "先不要出声，等我说现在可以了，你再恢复语音。"},
    {"role": "assistant", "content": "好的，我先安静地用文字陪你。"},
]
MEMORY_CONTEXT = [
    {"role": "user", "content": "我喜欢喝绿茶。"},
    {"role": "assistant", "content": "绿茶的清香确实适合午后。"},
]


@pytest.fixture
def runtime(monkeypatch, tmp_path):
    monkeypatch.setattr("pet.runtime.sd.stop", lambda: None)
    monkeypatch.setattr("pet.runtime.sd.play", lambda *_: None)
    monkeypatch.setattr("pet.runtime.sd.wait", lambda: None)
    result = Runtime()
    result.audio_activity.set_enabled(False)
    result.memory = MemoryStore(tmp_path / "memory.json")

    async def start(_settings):
        # 仅替换 GPU 启动边界，保留真实运行时和工具执行器。
        pass

    monkeypatch.setattr(result.engine, "start", start)
    yield result
    result.cancel(release=True).result(5)
    result.loop.call_soon_threadsafe(result.loop.stop)
    result.thread.join(2)


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [True, False])
@pytest.mark.parametrize("temperature", [0.35, 0.7, 1.1])
async def test_ordinary_reply_preserves_temperature_without_control_preflight(monkeypatch, streaming, temperature):
    payloads = []
    settings = Settings(temperature=temperature)
    engine = LocalEngine()

    async def start(_settings):
        pass

    async def handle(request):
        if request.url.path.endswith("/input_tokens"):
            return httpx.Response(200, json={"input_tokens": 20})
        payload = json.loads(request.content)
        payloads.append(payload)
        if not payload["stream"]:
            return httpx.Response(200, json={"choices": [{"message": {"content": BODY}, "finish_reason": "stop"}]})
        events = [
            {"choices": [{"delta": {"content": BODY[:5]}}]},
            {"choices": [{"delta": {"content": BODY[5:]}}]},
            {"choices": [{"delta": {}, "finish_reason": "stop"}]},
        ]
        return httpx.Response(200, text="".join("data: " + json.dumps(event) + "\n\n" for event in events) + "data: [DONE]\n\n")

    monkeypatch.setattr(engine, "start", start)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle), base_url="http://127.0.0.1") as client:
        engine.client = client
        answer = await engine.complete(settings, request_messages(settings, "你好，用一句话介绍自己", [], []), stream=streaming)
    assert answer.content == BODY and not answer.tool_calls
    assert len(payloads) == 1
    assert payloads[0]["temperature"] == temperature
    assert "grammar" not in payloads[0]


@pytest.mark.parametrize("text, enabled, decision, history", [
    pytest.param("今天工作有点累", True, None, [], id="ordinary-enabled"),
    pytest.param("今天工作有点累", False, None, [], id="ordinary-muted"),
    pytest.param("把‘请不要说话’翻译成英文。", True, None, [], id="quoted-request"),
    pytest.param("不要关闭语音，我还想听你说。", True, True, [], id="negated-stop"),
    pytest.param("我正在开会，你用文字陪我就好。", True, False, [], id="indirect-stop"),
    pytest.param("现在可以了。", False, True, CONTEXT, id="contextual-resume"),
])
def test_native_tool_choice_preserves_model_semantics_and_recent_context(runtime, text, enabled, decision, history):
    seen, changes = [], []
    runtime.history = copy.deepcopy(history)
    runtime.set_speech_enabled(enabled)
    runtime.speech_changed.connect(lambda: changes.append(runtime.speech_override), Qt.ConnectionType.DirectConnection)

    async def complete(_settings, messages, *_args, **_kwargs):
        seen.append(copy.deepcopy(messages))
        if decision is not None and messages[-1]["role"] != "tool":
            return AssistantReply("", (ToolCall("speech", "set_speech_enabled", json.dumps({"enabled": decision})),), "tool_calls")
        return AssistantReply(BODY)

    runtime.engine.complete = complete
    # 关闭保存偏好即可隔离音频；显式工具启用时仍会合成，因此使用无声合成替身。
    import numpy as np
    runtime.audio.synthesize = lambda *_: (np.zeros(80), 8000)
    runtime.schedule(runtime._conversation(0, Settings(), text, "chat", None, None)).result(3)
    assert runtime.speech_override is (enabled if decision is None else decision)
    assert changes == ([] if decision is None else [decision])
    assert seen[0][-1]["content"][0]["text"] == text
    assert seen[0][1:1 + len(history)] == history
    assert len(seen) == (1 if decision is None else 2)
    if decision is not None:
        assert json.loads(seen[-1][-1]["content"])["ok"]


@pytest.mark.parametrize("text, note, history", [
    pytest.param("我喜欢喝绿茶。", None, [], id="ordinary-preference"),
    pytest.param("把‘记住我喜欢喝绿茶’翻译成英文。", None, [], id="quoted-memory"),
    pytest.param("不要记住我喜欢喝绿茶。", None, [], id="negated-memory"),
    pytest.param("如果我说记住这个口味，你会怎么办？", None, [], id="hypothetical-memory"),
    pytest.param("这个故事让我记住了主角。", None, [], id="ordinary-mention"),
    pytest.param("昨天我让你记住喜欢喝绿茶，你还记得吗？", None, [], id="historical-memory-request"),
    pytest.param("记住我喜欢喝绿茶。", None, [], id="model-result-over-keyword"),
    pytest.param("帮我把刚才那个口味偏好记下来。", "我喜欢喝绿茶", MEMORY_CONTEXT, id="contextual-memory"),
])
def test_only_model_tool_choice_saves_once_before_reply(runtime, monkeypatch, text, note, history):
    seen, saved = [], []
    runtime.history = copy.deepcopy(history)
    remember = runtime.memory.remember

    def save(value, source):
        saved.append(value)
        return remember(value, source)

    async def complete(_settings, messages, *_args, **_kwargs):
        seen.append(copy.deepcopy(messages))
        if note is not None and messages[-1]["role"] != "tool":
            assert not saved
            return AssistantReply("", (ToolCall("save", "save_memory", json.dumps({"note": note})),), "tool_calls")
        # 只有收到已执行结果，模型才进入确认轮次。
        assert saved == ([] if note is None else [note])
        if note is not None:
            receipt = json.loads(messages[-1]["content"])
            assert receipt["ok"] and receipt["result"]["saved"]
        return AssistantReply(BODY)

    monkeypatch.setattr(runtime.memory, "remember", save)
    runtime.engine.complete = complete
    runtime.schedule(runtime._conversation(0, replace(Settings(), speak_replies=False), text, "chat", None, None)).result(3)
    assert runtime.memory.read() == (note or "")
    assert saved == ([] if note is None else [note])
    assert seen[0][-1]["content"][0]["text"] == text
    assert seen[0][1:1 + len(history)] == history
    assert len(seen) == (1 if note is None else 2)


def test_unclear_model_request_asks_confirmation_without_saving(runtime):
    replies = []
    runtime.reply.connect(lambda _, answer, kind: replies.append(answer), Qt.ConnectionType.DirectConnection)

    async def complete(*_args, **_kwargs):
        return AssistantReply("你希望长期保存这个口味偏好吗？")

    runtime.engine.complete = complete
    runtime.schedule(runtime._conversation(0, replace(Settings(), speak_replies=False), "地重我喜欢喝绿茶", "chat", None, None)).result(3)
    assert replies == ["你希望长期保存这个口味偏好吗？"]
    assert not runtime.memory.read()
