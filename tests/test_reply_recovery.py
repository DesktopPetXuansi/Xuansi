"""使用隔离记忆和假声卡复现回复丢失、失败通知及取消后收音恢复。"""

import asyncio
import threading
from dataclasses import replace

import pytest
from PySide6.QtCore import Qt

from pet.config import Settings
from pet.memory import MemoryStore
from pet.runtime import Runtime


@pytest.fixture
def isolated_runtime(monkeypatch, tmp_path):
    # 不打开输入设备，不访问用户的记忆文件，也不调用音频播放接口。
    monkeypatch.setattr("pet.runtime.sd.stop", lambda: None)
    monkeypatch.setattr("pet.runtime.sd.play", lambda *_: None)
    monkeypatch.setattr("pet.runtime.sd.wait", lambda: None)
    runtime = Runtime()
    runtime.memory = MemoryStore(tmp_path / "memory.json")
    runtime.audio_activity.clock = lambda: 10.0
    runtime.audio_activity.update(False, now=10.0)
    yield runtime
    runtime.listening = False
    runtime.cancel(release=True).result(timeout=5)
    runtime.loop.call_soon_threadsafe(runtime.loop.stop)
    runtime.thread.join(2)


def test_direct_request_can_receive_no_response_phrase(isolated_runtime):
    """自动观察的静默标记不能吞掉用户主动要求的正文。"""
    runtime = isolated_runtime
    replies = []
    runtime.reply.connect(
        lambda _, text, kind: replies.append((kind, text)), Qt.ConnectionType.DirectConnection
    )

    async def chat(*_, **_kwargs):
        return "无需回应"

    runtime.engine.chat = chat
    runtime.schedule(runtime._conversation(
        runtime.epoch, replace(Settings(), speak_replies=False),
        "请回复无需回应这四个字", "chat", None, None,
    )).result(3)

    assert replies == [("chat", "无需回应")]


def test_empty_model_reply_emits_visible_failure(isolated_runtime):
    """直接提问没有得到正文时，应留下明确失败事件而非回到就绪。"""
    runtime = isolated_runtime
    failures = []
    runtime.failed.connect(
        lambda epoch, message: failures.append((epoch, message)), Qt.ConnectionType.DirectConnection
    )

    async def chat(*_, **_kwargs):
        return "   "

    runtime.engine.chat = chat
    runtime.schedule(runtime._conversation(
        runtime.epoch, replace(Settings(), speak_replies=False), "你好", "chat", None, None,
    )).result(3)

    assert len(failures) == 1
    assert failures[0][0] == runtime.epoch
    assert failures[0][1].strip()


def test_backend_failure_does_not_expose_private_error_body(isolated_runtime):
    """底层异常可能带用户输入或路径，失败提示应只包含可公开的说明。"""
    runtime = isolated_runtime
    failures = []
    runtime.failed.connect(
        lambda _, message: failures.append(message), Qt.ConnectionType.DirectConnection
    )

    async def chat(*_, **_kwargs):
        raise OSError("private-test-marker: synthetic personal input")

    runtime.engine.chat = chat
    runtime.schedule(runtime._conversation(
        runtime.epoch, replace(Settings(), speak_replies=False), "你好", "voice-final", None, None,
    )).result(3)

    assert len(failures) == 1
    assert failures[0].strip()
    assert "private-test-marker" not in failures[0]
    assert "synthetic personal input" not in failures[0]


def test_cancel_recovers_listening_and_accepts_next_turn(isolated_runtime):
    """停止回答只中断本轮；已开启的麦克风需要恢复以接受下一句话。"""
    runtime = isolated_runtime
    started = threading.Event()
    replies = []
    runtime.reply.connect(
        lambda _, text, _kind: replies.append(text), Qt.ConnectionType.DirectConnection
    )

    async def chat(_settings, text, *_args, **_kwargs):
        if text == "第一轮":
            started.set()
            await asyncio.sleep(30)
        return "第二轮正常回复"

    runtime.engine.chat = chat
    runtime.listening = True
    settings = replace(Settings(), speak_replies=False)
    runtime.ask(settings, "第一轮")
    assert started.wait(3)
    assert runtime.microphone.muted.is_set()
    runtime.cancel().result(3)

    assert runtime.listening
    assert not runtime.microphone.muted.is_set()

    # 用真实提交路径接收新的最终话段；仅识别器本身由假事件替代。
    from pet.live_input import VoiceUpdate

    runtime.accept_voice(
        runtime.microphone_epoch, VoiceUpdate(1, "第二轮", final=True), settings,
    ).result(3)

    async def wait_reply():
        await runtime.job

    runtime.schedule(wait_reply()).result(3)
    assert replies == ["第二轮正常回复"]
    assert not runtime.microphone.muted.is_set()


def test_synthesis_failure_keeps_text_and_emits_durable_failure(isolated_runtime):
    """文字成功不应清除合成失败通知，用户需知道本轮为何没有声音。"""
    runtime = isolated_runtime
    failures, replies = [], []
    runtime.failed.connect(
        lambda _, message: failures.append(message), Qt.ConnectionType.DirectConnection
    )
    runtime.reply.connect(
        lambda _, text, _kind: replies.append(text), Qt.ConnectionType.DirectConnection
    )

    async def chat(*_, on_chunk=None, **_kwargs):
        await on_chunk("这是完整的文字回复。")
        return "这是完整的文字回复。"

    def synthesize(*_):
        raise RuntimeError("private-synthesis-marker")

    runtime.engine.chat = chat
    runtime.audio.synthesize = synthesize
    runtime.schedule(runtime._conversation(
        runtime.epoch, Settings(), "你好", "chat", None, None,
    )).result(3)

    assert replies == ["这是完整的文字回复。"]
    assert any("语音合成失败" in message for message in failures)
    assert all("private-synthesis-marker" not in message for message in failures)


@pytest.mark.parametrize("recognized", ["", "   "])
def test_empty_offline_recognition_skips_failure_and_resumes_listening(isolated_runtime, recognized):
    """整句识别的空结果也不能触发气泡对应的故障事件，且下句仍可正常回复。"""
    runtime = isolated_runtime
    failures, replies, states, heard, finished = [], [], [], [], []
    runtime.failed.connect(lambda *args: failures.append(args), Qt.ConnectionType.DirectConnection)
    runtime.reply.connect(lambda *args: replies.append(args), Qt.ConnectionType.DirectConnection)
    runtime.state.connect(lambda _, text: states.append(text), Qt.ConnectionType.DirectConnection)
    runtime.heard.connect(lambda *args: heard.append(args), Qt.ConnectionType.DirectConnection)
    runtime.finished.connect(finished.append, Qt.ConnectionType.DirectConnection)
    runtime.audio.transcribe = lambda _: recognized
    runtime.listening = True

    async def chat(*_, **_kwargs):
        return "下一轮正常回复"

    runtime.engine.chat = chat
    settings = replace(Settings(), speak_replies=False, realtime_voice=False)
    runtime.schedule(runtime._conversation(
        runtime.epoch, settings, "", "voice", None, [0.0],
    )).result(3)

    assert not failures and not replies and not heard
    assert finished == [runtime.epoch] and "继续聆听" in states[-1]
    assert runtime.listening and not runtime.microphone.muted.is_set()

    runtime.schedule(runtime._conversation(
        runtime.epoch, settings, "你好", "chat", None, None,
    )).result(3)
    assert len(replies) == 1 and replies[0][1] == "下一轮正常回复"
