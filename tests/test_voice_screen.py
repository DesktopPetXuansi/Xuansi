"""用合成识别文字核对两条语音路径的截图入口，不读取真实屏幕或声卡。"""

import asyncio
import threading
from dataclasses import replace
from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt

from pet.app import DesktopPet
from pet.config import Settings
from pet.conversation import converse
from pet.events import MouseEvent, ObservationGate
from pet.live_input import VoiceUpdate
from pet.memory import MemoryStore
from pet.runtime import Runtime

# 同时覆盖每个关键词、相似但不命中的文字以及勾选框的显式附图行为。
SCREEN_CASES = [
    (keyword, False, True)
    for keyword in ("屏幕", "鼠标", "画面", "看一眼", "看一下", "看看", "这个", "这里")
] + [
    ("你好", False, False),
    ("看一会", False, False),
    ("看两眼", False, False),
    ("看一\n眼", False, False),
    ("看看", True, True),
    ("你好", True, True),
]


def realtime_owner(runtime, settings, checked):
    """保留真实事件入口所需状态，窗口文字更新使用无界面替身。"""
    transcript = SimpleNamespace(setText=lambda _: None)
    return SimpleNamespace(
        paused=False,
        settings=settings,
        last_external=(321, 432),
        panel=SimpleNamespace(
            with_screen=SimpleNamespace(isChecked=lambda: checked),
            live_transcript=transcript,
            append=lambda *_: None,
        ),
        ui=SimpleNamespace(quick=SimpleNamespace(live_transcript=transcript)),
        runtime=runtime,
        _begin=lambda: None,
    )


@pytest.fixture
def realtime_runtime(monkeypatch, tmp_path):
    """运行真实异步调度与对话，不加载模型、声卡或用户记忆。"""
    monkeypatch.setattr("pet.runtime.sd.stop", lambda: None)
    runtime = Runtime()
    runtime.audio_activity.set_enabled(False)
    runtime.memory = MemoryStore(tmp_path / "memory.json")
    runtime.microphone_epoch = 7
    runtime.listening = True
    try:
        yield runtime
    finally:
        try:
            runtime.cancel(release=True).result(5)
        finally:
            # 断言失败或取消超时也必须结束循环；to_thread 的默认执行器单独回收。
            runtime.loop.call_soon_threadsafe(runtime.loop.stop)
            runtime.thread.join(5)
            assert not runtime.thread.is_alive(), "实时测试运行线程未结束"
            try:
                runtime.loop.run_until_complete(runtime.loop.shutdown_asyncgens())
                runtime.loop.run_until_complete(runtime.loop.shutdown_default_executor(timeout=3))
            finally:
                runtime.loop.close()


@pytest.mark.parametrize("capture_scope", ["screen", "nearby"])
@pytest.mark.parametrize("text, checked, expected_screen", SCREEN_CASES)
def test_realtime_voice_preserves_position_only_when_screen_is_requested(
    realtime_runtime, monkeypatch, text, checked, expected_screen, capture_scope,
):
    """串联最终转写、LiveDialogue、真实 converse、模拟截图和模型图像参数。"""
    captures, inputs, failures = [], [], []
    completed = threading.Event()
    settings = replace(Settings(), speak_replies=False, capture_scope=capture_scope)
    owner = realtime_owner(realtime_runtime, settings, checked)

    def capture(*args):
        captures.append(args)
        return "synthetic-screen"

    async def chat(_settings, recognized, images, _history, **_kwargs):
        inputs.append((recognized, images))
        return "合成测试回复。"

    monkeypatch.setattr("pet.conversation.capture_screen", capture)
    realtime_runtime.engine.chat = chat
    realtime_runtime.finished.connect(lambda _: completed.set(), Qt.ConnectionType.DirectConnection)
    realtime_runtime.failed.connect(lambda *args: failures.append(args), Qt.ConnectionType.DirectConnection)
    update = VoiceUpdate(1, text, final=True)

    DesktopPet.on_voice_update(owner, 7, update)

    assert completed.wait(3), "实时话段未完成"
    assert not failures
    assert captures == ([(*owner.last_external, capture_scope)] if expected_screen else [])
    assert inputs == [(text, ["synthetic-screen"] if expected_screen else [])]
    assert realtime_runtime.history[-2]["content"] == text
    assert not realtime_runtime.microphone.muted.is_set()


@pytest.mark.parametrize("own_foreground, own_point", [(True, False), (False, True)])
def test_voice_screen_keeps_last_external_position_after_pet_window_input(
    monkeypatch, own_foreground, own_point,
):
    """本应用前景与窗口内坐标均不能覆盖最近外部位置，跨屏语音沿用该位置。"""
    submitted = []
    runtime = SimpleNamespace(
        microphone_epoch=7, listening=True, accept_voice=lambda *args: submitted.append(args),
    )
    owner = realtime_owner(runtime, Settings(), False)
    owner.busy, owner.fullscreen, owner.gate = False, False, ObservationGate()
    states = iter([
        SimpleNamespace(own_window=False, hwnd=1, fullscreen=False),
        SimpleNamespace(own_window=own_foreground, hwnd=2, fullscreen=False),
    ])
    monkeypatch.setattr("pet.app.desktop_state", lambda: next(states))
    monkeypatch.setattr("pet.app.point_is_own_window", lambda x, _y: x == 2320 and own_point)

    DesktopPet.on_mouse(owner, MouseEvent("click", 320, 430, 0.0))
    DesktopPet.on_mouse(owner, MouseEvent("click", 2320, 430, 1.0))
    DesktopPet.on_voice_update(owner, 7, VoiceUpdate(1, "看看", final=True))

    assert owner.last_external == (320, 430)
    assert submitted[0][-1] == (320, 430)


@pytest.mark.parametrize("text, checked, expected_screen", SCREEN_CASES)
def test_sentence_voice_and_voice_screen_keep_the_existing_capture_boundary(
    monkeypatch, text, checked, expected_screen,
):
    """勾选框经 on_segment 选择 kind，再由真实整句识别对话决定是否截图。"""
    submitted, captures, replies, failures = [], [], [], []
    signal = SimpleNamespace(emit=lambda *_: None)
    settings = Settings(realtime_voice=False)
    runtime = SimpleNamespace(
        epoch=1,
        microphone_epoch=7,
        listening=True,
        speech_override=None,
        microphone=SimpleNamespace(muted=threading.Event()),
        audio=SimpleNamespace(transcribe=lambda _: text),
        memory=SimpleNamespace(context=lambda _: ""),
        state=signal,
        heard=signal,
        finished=signal,
        failed=SimpleNamespace(emit=lambda *args: failures.append(args)),
        ask=lambda *args, **kwargs: submitted.append((args, kwargs)),
    )
    owner = SimpleNamespace(
        paused=False,
        settings=settings,
        last_external=(321, 432),
        runtime=runtime,
        panel=SimpleNamespace(with_screen=SimpleNamespace(isChecked=lambda: checked)),
        _begin=lambda: None,
    )
    samples = [0.0]  # 仅占位；识别器返回上面的合成文字。

    def capture(*args):
        captures.append(args)
        return "synthetic-screen"

    async def generate(_runtime, _epoch, _settings, recognized, images, kind, _observation):
        replies.append((recognized, images, kind))

    monkeypatch.setattr("pet.conversation.capture_screen", capture)
    monkeypatch.setattr("pet.conversation.generate_reply", generate)
    DesktopPet.on_segment(owner, 7, samples)
    args, kwargs = submitted[0]
    assert args == (settings, "")
    assert kwargs["kind"] == ("voice-screen" if checked else "voice")
    assert kwargs["position"] == owner.last_external
    asyncio.run(converse(runtime, 1, settings, "", **kwargs))

    assert not failures
    assert captures == ([(*owner.last_external, settings.capture_scope)] if expected_screen else [])
    assert replies == [(text, ["synthetic-screen"] if expected_screen else [], kwargs["kind"])]
    assert not runtime.microphone.muted.is_set()
