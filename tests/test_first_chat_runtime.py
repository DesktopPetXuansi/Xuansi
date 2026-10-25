"""首次文字成功与可恢复错误；隔离模型、声卡和用户文件。"""

import asyncio
import threading
from concurrent.futures import CancelledError
from dataclasses import replace

import numpy as np
import pytest
from PySide6.QtCore import Qt

from pet.ai.providers.base import ProviderError
from pet.config import Settings
from pet.memory import MemoryStore
from pet.runtime import Runtime
from pet.speech_output import play_samples
from pet.tool_protocol import AssistantReply, ToolCall


@pytest.fixture
def runtime(monkeypatch, tmp_path):
    monkeypatch.setattr("pet.runtime.sd.stop", lambda: None)
    monkeypatch.setattr("pet.runtime.sd.play", lambda *_: None)
    monkeypatch.setattr("pet.runtime.sd.wait", lambda: None)
    result = Runtime()
    result.audio_activity.set_enabled(False)
    result.memory = MemoryStore(tmp_path / "memory.json")
    monkeypatch.setattr(result.audio, "configure_root", lambda _: None)

    async def start(_settings):
        pass  # 不启动真实推理服务，不读取凭据。

    monkeypatch.setattr(result.engine, "start", start)
    yield result
    result.cancel(release=True).result(5)
    result.loop.call_soon_threadsafe(result.loop.stop)
    result.thread.join(2)


def collect(signal):
    values = []
    signal.connect(lambda *args: values.append(args), Qt.ConnectionType.DirectConnection)
    return values


def run(runtime, settings=None, kind="chat"):
    return runtime.schedule(runtime._conversation(
        0, settings or replace(Settings(), speak_replies=False), "合成测试输入", kind, None, None,
    )).result(3)


def test_final_text_succeeds_before_tts_and_survives_tts_failure(runtime):
    succeeded = collect(runtime.chat_succeeded)
    issues = collect(runtime.request_issue)
    states = collect(runtime.state)

    async def complete(*_, **__):
        assert not succeeded
        return AssistantReply("第一句有效回复。")

    def synthesize(*_):
        assert succeeded == [(0,)]
        raise RuntimeError("synthetic secret must stay private")

    runtime.engine.complete = complete
    runtime.audio.synthesize = synthesize
    run(runtime, Settings())
    assert succeeded == [(0,)]
    assert issues[-1][1].action == "preferences"
    assert "语音合成失败" in states[-1][1]


@pytest.mark.parametrize("kind", ["observation", "preview", "voice", "chat-screen"])
def test_other_request_kinds_do_not_complete_first_text_chat(runtime, kind):
    succeeded = collect(runtime.chat_succeeded)

    async def complete(*_, **__):
        return AssistantReply("其他模式回复。")

    runtime.engine.complete = complete
    run(runtime, kind=kind)
    assert not succeeded


@pytest.mark.parametrize("mode", ["empty", "tool_failure", "stale", "cancelled"])
def test_nonfinal_or_cancelled_reply_does_not_succeed(runtime, mode):
    succeeded = collect(runtime.chat_succeeded)

    async def complete(*_, **__):
        if mode == "cancelled":
            raise asyncio.CancelledError
        if mode == "stale":
            runtime.epoch = 1
        if mode == "tool_failure":
            call = ToolCall("duplicate", "set_speech_enabled", '{"enabled":false}')
            return AssistantReply("这是工具前说明。", (call, call), "tool_calls")
        return AssistantReply("" if mode == "empty" else "迟到回复。")

    runtime.engine.complete = complete
    if mode == "cancelled":
        with pytest.raises(CancelledError):
            run(runtime)
    else:
        run(runtime)
    assert not succeeded


@pytest.mark.parametrize("category, reason, expected", [
    ("authentication", "在线请求被拒绝。", "权限"),
    ("quota", "额度不足。", "额度"),
    ("rate_limit", "请求过于频繁。", "稍后"),
    ("timeout", "在线请求超时。", "网络"),
    ("resource", "所选本地模型或计算后端尚未安装。", "尚未安装"),
    ("resource", "可用内存与显存不足。", "显存不足"),
])
def test_provider_failure_has_safe_specific_next_step(runtime, category, reason, expected):
    issues = collect(runtime.request_issue)
    failures = collect(runtime.failed)

    async def complete(*_, **__):
        raise ProviderError(category, reason)

    runtime.engine.complete = complete
    run(runtime)
    issue = issues[-1][1]
    assert expected in issue.message
    assert issue.action == "model" and issue.action_label
    assert failures == [(0, issue.message)]


def test_unknown_online_failure_does_not_expose_exception_or_claim_local(runtime, caplog):
    issues = collect(runtime.request_issue)

    async def complete(*_, **__):
        raise RuntimeError("https://private.example?key=sk-secret user@example.com")

    runtime.engine.complete = complete
    settings = replace(Settings(), speak_replies=False, ai=replace(Settings().ai, policy="online_first"))
    run(runtime, settings)
    message = issues[-1][1].message
    assert "本地" not in message
    assert "sk-secret" not in message + caplog.text
    assert "user@example.com" not in message + caplog.text


def test_model_directory_failure_finishes_and_offers_recovery(runtime, monkeypatch):
    issues = collect(runtime.request_issue)
    finished = collect(runtime.finished)

    def fail(_):
        raise OSError("private directory")

    monkeypatch.setattr(runtime.audio, "configure_root", fail)
    run(runtime)
    assert finished == [(0,)]
    assert issues[-1][1].action == "model"
    assert "private directory" not in issues[-1][1].message


@pytest.mark.parametrize("gate, expected", [
    ("components", "组件"), ("saved", "已保存"), ("temporary", "临时"), ("activity", "声音回避"),
])
def test_preview_explains_suppression_without_changing_voice_preferences(runtime, gate, expected):
    issues = collect(runtime.request_issue)
    states = collect(runtime.state)
    settings = Settings()
    if gate == "components":
        settings = replace(settings, ai=replace(settings.ai, voice_components=()))
    elif gate == "saved":
        settings = replace(settings, speak_replies=False)
    elif gate == "temporary":
        runtime.speech_override = False
    else:
        runtime.audio_activity.set_enabled(True)
    before = runtime.speech_override
    run(runtime, settings, "preview")
    issue = issues[-1][1]
    assert expected in issue.message
    assert issue.action == {"components": "model", "temporary": "chat"}.get(gate, "preferences")
    assert states[-1] == (0, issue.message)
    assert not runtime.listening and runtime.speech_override is before


def test_preview_reports_audio_avoidance_during_synthesis(runtime):
    issues = collect(runtime.request_issue)
    states = collect(runtime.state)

    def synthesize(*_):
        runtime.audio_activity.set_enabled(True)
        return np.zeros(40), 8000

    runtime.audio.synthesize = synthesize
    run(runtime, Settings(), "preview")
    assert "声音回避" in issues[-1][1].message
    assert states[-1] == (0, issues[-1][1].message)


def test_stale_preview_does_not_emit_recovery(runtime):
    issues = collect(runtime.request_issue)

    def synthesize(*_):
        runtime.epoch = 1
        return np.zeros(40), 8000

    runtime.audio.synthesize = synthesize
    run(runtime, Settings(), "preview")
    assert not issues


def test_late_provider_error_cannot_replace_new_request_state(runtime):
    issues = collect(runtime.request_issue)
    failures = collect(runtime.failed)
    states = collect(runtime.state)

    async def complete(*_, **__):
        runtime.epoch = 1
        raise ProviderError("network", "在线连接失败。")

    runtime.engine.complete = complete
    run(runtime)
    assert not issues and not failures
    assert all("连接失败" not in text for _, text in states)


@pytest.mark.asyncio
async def test_playback_interruption_remains_incomplete_after_sound_becomes_quiet(monkeypatch):
    """已打断的试听不能因声卡等待结束前再次安静而变成播放成功。"""
    stopped = threading.Event()

    class Activity:
        blocked = False

    activity = Activity()
    monkeypatch.setattr("pet.speech_output.sd.play", lambda *_: setattr(activity, "blocked", True))

    def stop():
        activity.blocked = False
        stopped.set()

    monkeypatch.setattr("pet.speech_output.sd.stop", stop)
    monkeypatch.setattr("pet.speech_output.sd.wait", lambda: stopped.wait(2))
    played = await play_samples(activity, np.zeros(40), 8000, lambda: True, lambda _: None)
    assert not played and not activity.blocked
