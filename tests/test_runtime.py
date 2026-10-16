"""用假声卡和延迟任务复现取消、记忆及开关竞态，不读取真实设备。"""

import asyncio
import json
import threading
from dataclasses import replace

import numpy as np
import pytest
from PySide6.QtCore import Qt

from pet.config import Settings
from pet.live_input import VoiceUpdate
from pet.memory import MemoryStore
from pet.runtime import Runtime
from pet.tool_protocol import AssistantReply, ToolCall


@pytest.fixture
def runtime(monkeypatch, tmp_path):
    monkeypatch.setattr("pet.runtime.sd.stop", lambda: None)
    monkeypatch.setattr("pet.runtime.sd.play", lambda *_: None)
    monkeypatch.setattr("pet.runtime.sd.wait", lambda: None)
    result = Runtime()
    # 音频回避单独验证；运行时测试固定为安静环境。
    result.audio_activity.clock = lambda: 10.0
    result.audio_activity.update(False, now=10.0)
    result.memory = MemoryStore(tmp_path / "memory.json")

    async def start(_settings):
        # 测试不得启动真实 GPU 服务。
        pass

    monkeypatch.setattr(result.engine, "start", start)
    yield result
    result.microphone.stop()
    result.microphone.join()
    result.cancel(release=True).result(timeout=5)
    result.loop.call_soon_threadsafe(result.loop.stop)
    result.thread.join(2)


def test_selected_voice_engine_reaches_synthesizer(runtime):
    seen = []

    async def chat(*_, on_chunk=None, **_kwargs):
        return AssistantReply("你好")

    def synthesize(text, speaker, speed, engine="fast"):
        seen.append(engine)
        return np.zeros(100, dtype=np.float32), 8000

    runtime.engine.complete = chat
    runtime.audio.synthesize = synthesize
    runtime.schedule(
        runtime._conversation(0, replace(Settings(), tts_engine="natural"), "你好", "chat", None, None)
    ).result(3)
    assert seen == ["natural"]


def test_native_tool_chain_selects_tts_before_synthesis(runtime):
    """工具回执先进入模型上下文，最终正文再使用所选引擎朗读。"""
    events = []

    async def complete(_settings, messages, *_args, **_kwargs):
        if messages[-1]["role"] != "tool":
            events.append("tool")
            return AssistantReply("", (ToolCall("tts-1", "select_tts_engine", '{"engine":"natural"}'),), "tool_calls")
        events.append("body")
        assert json.loads(messages[-1]["content"])["ok"]
        return AssistantReply("Hello, how are you?")

    def synthesize(text, _speaker, _speed, engine):
        events.append(("audio", engine, text))
        return np.zeros(80, dtype=np.float32), 8000

    runtime.engine.complete = complete
    runtime.audio.synthesize = synthesize
    runtime.schedule(runtime._conversation(0, Settings(), "用英语向我问好", "chat", None, None)).result(3)
    assert events[:2] == ["tool", "body"]
    assert all(event[:2] == ("audio", "natural") for event in events[2:])
    assert "".join(event[2] for event in events[2:]) == "Hello, how are you?"
    assert runtime.history[-1]["content"] == "Hello, how are you?"


def test_live_waits_for_endpoint_and_deduplicates(runtime):
    calls = []

    async def chat(_settings, messages, *_args, **_kwargs):
        if messages[-1]["role"] == "tool":
            return AssistantReply("已保存这项偏好。")
        calls.append(messages[-1]["content"][0]["text"])
        return AssistantReply("", (ToolCall("save-1", "save_memory", '{"note":"我喜欢喝绿茶"}'),), "tool_calls")

    runtime.engine.complete = chat
    runtime.listening = True
    settings = replace(Settings(), speak_replies=False)
    for text in ("记住我喜欢", "记住我喜欢喝绿茶"):
        runtime.accept_voice(0, VoiceUpdate(0, text), settings).result(2)
    assert not calls and not runtime.memory.read() and not runtime.history
    event = VoiceUpdate(0, "记住我喜欢喝绿茶", final=True)
    runtime.accept_voice(0, event, settings).result(2)

    async def wait_reply():
        await runtime.job

    runtime.schedule(wait_reply()).result(3)
    runtime.accept_voice(0, event, settings).result(2)
    assert "绿茶" in runtime.memory.read()
    assert calls == [event.text]
    assert next(turn for turn in runtime.history if turn["role"] == "user")["content"][0]["text"] == event.text
    runtime.microphone_epoch += 1
    runtime.accept_voice(0, VoiceUpdate(1, "旧麦克风的话", final=True), settings).result(2)
    assert len(calls) == 1


def test_cancel_during_warmup_never_opens_microphone(runtime, monkeypatch):
    started = threading.Event()
    opened = []

    async def prepare(_):
        started.set()
        await asyncio.sleep(30)

    monkeypatch.setattr(runtime, "_prepare_voice", prepare)
    monkeypatch.setattr("pet.runtime.Microphone", lambda *_: opened.append(True))
    warming = runtime.toggle_microphone(True, realtime=True, settings=Settings())
    assert started.wait(2)
    runtime.toggle_microphone(False).result(3)
    warming.result(3)
    assert not opened and not runtime.listening


def test_text_request_interrupting_warmup_clears_listening_state(runtime, monkeypatch):
    started = threading.Event()

    async def prepare(_):
        started.set()
        await asyncio.sleep(30)

    async def chat(*_, **__):
        return AssistantReply("文字回复继续正常工作。")

    monkeypatch.setattr(runtime, "_prepare_voice", prepare)
    runtime.engine.complete = chat
    warming = runtime.toggle_microphone(True, realtime=True, settings=Settings())
    assert started.wait(2)
    runtime.ask(replace(Settings(), speak_replies=False), "你好")
    warming.result(3)
    assert not runtime.listening


def test_clear_memory_cancels_old_request_and_history(runtime):
    runtime.memory.save("喜欢绿茶")
    runtime.history = [{"role": "user", "content": "记住，我喜欢绿茶"}]
    started = threading.Event()
    stopped = threading.Event()

    async def chat(*_, on_chunk=None, **_kwargs):
        started.set()
        try:
            await asyncio.sleep(60)
        finally:
            stopped.set()

    runtime.engine.complete = chat
    runtime.ask(Settings(), "我喜欢什么")
    assert started.wait(2)
    saved = runtime.save_memory("")
    assert saved is not None
    saved.result(timeout=3)
    assert stopped.is_set()
    assert runtime.memory.read() == ""
    assert runtime.history == []


def test_clear_memory_cancels_pending_tool_retrieval(runtime):
    """按需检索发生时清空记忆，仍取消在途请求与旧历史。"""
    runtime.memory.save("我偏好清淡饮品")
    entered, stopped = threading.Event(), threading.Event()
    replies = []

    async def complete(_settings, messages, *_args, **_kwargs):
        return AssistantReply("", (ToolCall("lookup", "search_memory", '{"query":"饮品"}'),), "tool_calls")

    async def select_memory(*_):
        entered.set()
        try:
            await asyncio.Future()
        finally:
            stopped.set()

    runtime.engine.complete = complete
    runtime.engine.select_memory = select_memory
    runtime.reply.connect(lambda *args: replies.append(args), Qt.ConnectionType.DirectConnection)
    runtime.ask(Settings(), "推荐一种饮品")
    assert entered.wait(2)
    runtime.save_memory("").result(3)
    assert stopped.is_set() and not replies
    assert not runtime.history and runtime.memory.read() == ""


def test_voice_switch_discards_late_start(runtime, monkeypatch):
    started = threading.Event()
    release = threading.Event()
    opened = []

    def prepare():
        started.set()
        assert release.wait(3)

    class FakeMicrophone:
        def __init__(self, on_segment, on_state):
            self.muted = threading.Event()

        def stop(self):
            pass

        def join(self):
            pass

        def start(self, device):
            opened.append(device)

    monkeypatch.setattr("pet.runtime.Microphone", FakeMicrophone)
    runtime.microphone = FakeMicrophone(None, None)
    runtime.audio.prepare_recognition = prepare
    runtime.toggle_microphone(True, 2)
    assert started.wait(2)
    runtime.toggle_microphone(False)
    runtime.toggle_microphone(True, 3)
    release.set()

    # 队列屏障：等待此前的麦克风切换顺序完成。
    async def barrier():
        async with runtime.microphone_control:
            pass

    runtime.schedule(barrier()).result(3)
    assert opened == [3]
    assert runtime.listening


def test_changed_window_discards_observation_before_speech(runtime, monkeypatch):
    current = True
    spoken = []

    async def chat(*_, **_kwargs):
        nonlocal current
        current = False
        return AssistantReply("现在的画面已经过期了")

    monkeypatch.setattr("pet.conversation.observation_current", lambda _: current)
    runtime.engine.complete = chat
    runtime.audio.synthesize = lambda *_: spoken.append(True)
    runtime.schedule(
        runtime._conversation(
            0, replace(Settings(), speak_observations=True), "观察", "observation", None, None, (100, 0)
        )
    ).result(3)
    assert spoken == []
    assert runtime.history == []


def test_quiet_observation_finishes_with_ready_state(runtime):
    states = []
    runtime.state.connect(lambda _, text: states.append(text), Qt.ConnectionType.DirectConnection)

    async def chat(*_, **_kwargs):
        return AssistantReply("", (ToolCall("quiet", "finish_observation", "{}"),), "tool_calls")

    runtime.engine.complete = chat
    runtime.schedule(runtime._conversation(0, Settings(), "观察", "observation", None, None)).result(3)
    assert states[-1] == "已就绪 · 麦克风关闭"


def test_capture_scope_reaches_worker_and_image_request(runtime, monkeypatch):
    captures, images_seen = [], []
    main_thread = threading.get_ident()

    def capture(x, y, scope):
        captures.append((x, y, scope, threading.get_ident()))
        return b"synthetic-screen"

    async def chat(_settings, messages, *_args, **_kwargs):
        images_seen.append(messages[-1]["content"])
        return AssistantReply("测试已看到整屏")

    monkeypatch.setattr("pet.conversation.capture_screen", capture)
    runtime.engine.complete = chat
    for scope in ("screen", "nearby"):
        settings = replace(Settings(), speak_replies=False, capture_scope=scope)
        runtime.schedule(runtime._conversation(0, settings, "看画面", "chat-screen", (-100, 50), None)).result(3)
    assert [(x, y, scope) for x, y, scope, _ in captures] == [(-100, 50, "screen"), (-100, 50, "nearby")]
    assert all(thread != main_thread and thread != runtime.thread.ident for _, _, _, thread in captures)
    assert all(any(part.get("type") == "image_url" for part in content) for content in images_seen)


def test_voice_starts_after_complete_reply_and_keeps_full_history(runtime, monkeypatch):
    played = threading.Event()
    heard, replies = [], []
    runtime.reply.connect(lambda _, text, kind: replies.append(text), Qt.ConnectionType.DirectConnection)

    async def chat(*_, **_kwargs):
        # 完整回复前不知道模型是否还会调用工具，不得抢先朗读。
        assert not played.is_set()
        await asyncio.sleep(0)
        assert not played.is_set()
        return AssistantReply("这是第一段。后面还有第二段。")

    def synthesize(text, *_):
        heard.append(text)
        return np.zeros(80, dtype=np.float32), 8000

    runtime.engine.complete = chat
    runtime.audio.synthesize = synthesize
    monkeypatch.setattr("pet.runtime.sd.play", lambda *_: played.set())
    runtime.schedule(runtime._conversation(0, Settings(), "聊两句", "chat", None, None)).result(3)
    assert played.is_set()
    assert "".join(heard) == replies[0] == runtime.history[-1]["content"]


def test_streaming_tts_failure_still_delivers_complete_text(runtime):
    replies = []
    runtime.reply.connect(lambda _, text, kind: replies.append(text), Qt.ConnectionType.DirectConnection)

    async def chat(*_, on_chunk=None, **_kwargs):
        return AssistantReply("文字回复仍然可用。")

    def fail(*_):
        raise RuntimeError("synthetic tts failure")

    runtime.engine.complete = chat
    runtime.audio.synthesize = fail
    runtime.schedule(runtime._conversation(0, Settings(), "你好", "chat", None, None)).result(3)
    assert replies == ["文字回复仍然可用。"]
    assert runtime.history[-1]["content"] == replies[0]
