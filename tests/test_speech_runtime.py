"""模型决定开关；用假音频验证真实运行时、麦克风代次及同轮恢复。"""

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
    result.audio_activity.set_enabled(False)
    result.memory = MemoryStore(tmp_path / "memory.json")

    async def start(_settings):
        # 替换模型进程边界，不触碰真实 GPU。
        pass

    monkeypatch.setattr(result.engine, "start", start)
    yield result
    result.cancel(release=True).result(5)
    result.loop.call_soon_threadsafe(result.loop.stop)
    result.thread.join(2)


def test_model_can_mute_keep_silent_and_resume_in_same_turn(runtime):
    clips, replies = [], []
    decisions = iter([False, None, True])
    runtime.listening = True  # 仅模拟状态，不打开真实设备。
    runtime.reply.connect(lambda _, text, kind: replies.append(text), Qt.ConnectionType.DirectConnection)

    async def chat(_settings, messages, *_args, **_kwargs):
        if messages[-1]["role"] != "tool":
            decision = next(decisions)
            if decision is not None:
                return AssistantReply("", (ToolCall("speech", "set_speech_enabled", json.dumps({"enabled": decision})),), "tool_calls")
        return AssistantReply("完整的确认回复。")

    def synthesize(text, *_):
        clips.append(text)
        return np.zeros(80), 8000

    runtime.engine.complete = chat
    runtime.audio.synthesize = synthesize
    for index, should_speak in enumerate([False, False, True]):
        # 刻意使用无关键词输入：执行的是模型动作，不能根据输入词语猜测。
        runtime.schedule(runtime._conversation(0, Settings(), f"测试{index}", "chat", None, None)).result(3)
        assert runtime.should_speak(Settings()) is should_speak
        assert runtime.listening and runtime.microphone_epoch == 0
        assert not runtime.microphone.muted.is_set()
        assert len(clips) == (1 if should_speak else 0)
    assert len(replies) == 3
    assert sum(turn["role"] == "user" for turn in runtime.history) == 3


@pytest.mark.parametrize("kind", ["observation", "preview"])
def test_mute_blocks_observation_and_preview_without_opening_microphone(runtime, kind):
    clips, calls = [], []

    async def chat(_settings, _messages, tools, **_kwargs):
        calls.append({tool["function"]["name"] for tool in tools})
        return AssistantReply("观察回应。")

    runtime.engine.complete = chat
    runtime.audio.synthesize = lambda *_: clips.append(True)
    runtime.set_speech_enabled(False)
    settings = replace(Settings(), speak_observations=True)
    runtime.schedule(runtime._conversation(0, settings, "测试", kind, None, None)).result(3)
    assert not clips and not runtime.listening
    assert runtime.speech_override is False
    assert not calls or "set_speech_enabled" not in calls[0]


def test_preview_is_silent_when_saved_reply_preference_is_off(runtime):
    """试听使用真实 converse 入口；保存的关闭偏好也必须阻止合成。"""
    clips = []

    def synthesize(text, *_):
        clips.append(text)
        return np.zeros(80), 8000

    runtime.audio.synthesize = synthesize
    settings = replace(Settings(), speak_replies=False)
    runtime.schedule(runtime._conversation(0, settings, "试听内容。", "preview", None, None)).result(3)

    assert not clips
    assert runtime.speech_override is None and not runtime.listening


def test_observation_fallback_speaks_when_only_reply_preference_is_off(runtime):
    """自动观察走非流式回退，必须使用观察偏好，不能误用默认 chat 门控。"""
    clips = []

    async def chat(*_, **_kwargs):
        return AssistantReply("观察回应。")

    def synthesize(text, *_):
        clips.append(text)
        return np.zeros(80), 8000

    runtime.engine.complete = chat
    runtime.audio.synthesize = synthesize
    settings = replace(Settings(), speak_replies=False, speak_observations=True)
    runtime.schedule(runtime._conversation(0, settings, "观察画面", "observation", None, None)).result(3)

    assert clips == ["观察回应。"]
    assert not runtime.history and not runtime.listening


def test_observation_voice_uses_model_selected_engine(runtime):
    """观察通过原生工具选择引擎，试听沿用明确设置而不请求模型。"""
    clips = []

    async def chat(_settings, messages, *_args, **_kwargs):
        if messages[-1]["role"] != "tool":
            return AssistantReply("", (ToolCall("tts", "select_tts_engine", '{"engine":"natural"}'),), "tool_calls")
        return AssistantReply("Hello there.")

    def synthesize(text, _speaker, _speed, engine):
        clips.append((text, engine))
        return np.zeros(80), 8000

    runtime.engine.complete = chat
    runtime.audio.synthesize = synthesize
    runtime.schedule(runtime._conversation(
        0, replace(Settings(), speak_observations=True), "Hello there.", "observation", None, None,
    )).result(3)
    assert clips == [("Hello there.", "natural")]


def test_late_model_decision_cannot_change_new_request_state(runtime):
    entered, release = threading.Event(), threading.Event()

    async def chat(*_, **_kwargs):
        entered.set()
        await asyncio.to_thread(release.wait, 2)
        return AssistantReply("", (ToolCall("late", "set_speech_enabled", '{"enabled":false}'),), "tool_calls")

    runtime.engine.complete = chat
    future = runtime.schedule(runtime._conversation(0, Settings(), "旧请求", "chat", None, None))
    assert entered.wait(1)
    runtime.epoch += 1
    release.set()
    future.result(3)
    assert runtime.speech_override is None
    # 用户输入属于已经发生的事实；迟到工具及其虚构结果不得写入历史。
    assert [turn["role"] for turn in runtime.history] == ["user"]


def test_final_voice_can_resume_when_saved_reply_preference_is_off(runtime):
    clips = []
    runtime.listening = True
    runtime.set_speech_enabled(False)

    async def chat(_settings, messages, *_args, **_kwargs):
        if messages[-1]["role"] != "tool":
            assert runtime.speech_override is False
            return AssistantReply("", (ToolCall("resume", "set_speech_enabled", '{"enabled":true}'),), "tool_calls")
        return AssistantReply("现在可以听到我了。")

    def synthesize(text, *_):
        clips.append(text)
        return np.zeros(80), 8000

    runtime.engine.complete = chat
    runtime.audio.synthesize = synthesize
    settings = replace(Settings(), speak_replies=False)
    runtime.accept_voice(0, VoiceUpdate(1, "恢复", final=True), settings).result(2)

    async def finish():
        await runtime.job

    runtime.schedule(finish()).result(3)
    assert clips == ["现在可以听到我了。"]
    assert runtime.listening and not runtime.microphone.muted.is_set()


@pytest.mark.parametrize("text, model_note", [
    ("帮我把刚才那个偏好保存下来", "我喜欢喝绿茶"),
    ("记住我喜欢喝绿茶", None),
    ("请翻译：记住我喜欢喝绿茶", None),
])
def test_memory_is_written_only_after_model_understands_the_request(runtime, text, model_note):
    """文字是否含口令不能触发写入；只执行模型返回的明确事项。"""
    loaded = []
    runtime.memory_loaded.connect(loaded.append, Qt.ConnectionType.DirectConnection)

    async def chat(_settings, messages, *_args, **_kwargs):
        if model_note is not None and messages[-1]["role"] != "tool":
            return AssistantReply("", (ToolCall("save", "save_memory", json.dumps({"note": model_note})),), "tool_calls")
        return AssistantReply("处理完毕。")

    runtime.engine.complete = chat
    runtime.schedule(runtime._conversation(
        0, replace(Settings(), speak_replies=False), text, "chat", None, None,
    )).result(3)
    assert runtime.memory.read() == (model_note or "")
    assert loaded == ([model_note] if model_note is not None else [])


@pytest.mark.parametrize("text, history, sensitive", [
    ("记住我的密码是123456", [], True),
    ("把刚才那个记下来", [
        {"role": "user", "content": "我的验证码是123456"},
        {"role": "assistant", "content": "请不要保存验证码。"},
    ], True),
    ("请保存我的普通编号123456", [], False),
    ("请保存我的普通编号123456", [
        {"role": "assistant", "content": "长期记忆不能保存密码或验证码。"},
    ], False),
])
def test_model_rewriting_cannot_remove_source_secret_labels(runtime, text, history, sensitive):
    """敏感资料过滤检查原始输入，不能被模型提取掉标签后绕过。"""
    failures, replies = [], []
    runtime.history = history
    runtime.failed.connect(lambda _, message: failures.append(message), Qt.ConnectionType.DirectConnection)
    runtime.reply.connect(lambda _, answer, kind: replies.append(answer), Qt.ConnectionType.DirectConnection)

    async def chat(_settings, messages, *_args, **_kwargs):
        if messages[-1]["role"] != "tool":
            return AssistantReply("", (ToolCall("secret", "save_memory", '{"note":"123456"}'),), "tool_calls")
        receipt = json.loads(messages[-1]["content"])
        assert receipt["ok"] is not sensitive
        return AssistantReply("不能保存敏感资料。" if sensitive else "已保存。")

    runtime.engine.complete = chat
    runtime.schedule(runtime._conversation(
        0, replace(Settings(), speak_replies=False), text, "chat", None, None,
    )).result(3)
    assert runtime.memory.read() == ("" if sensitive else "123456")
    assert not failures
    assert replies == (["不能保存敏感资料。"] if sensitive else ["已保存。"])
    assert "123456" not in "".join(failures)
