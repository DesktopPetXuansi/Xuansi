"""用假声卡和延迟任务复现取消、记忆及开关竞态，不读取真实设备。"""

import asyncio
import threading
from dataclasses import replace

import numpy as np
import pytest
from PySide6.QtCore import Qt

from pet.config import Settings
from pet.memory import MemoryStore
from pet.runtime import Runtime


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
    yield result
    result.microphone.stop()
    result.microphone.join()
    result.cancel(release=True).result(timeout=5)
    result.loop.call_soon_threadsafe(result.loop.stop)
    result.thread.join(2)


def test_selected_voice_engine_reaches_synthesizer(runtime):
    seen = []

    async def chat(*_):
        return "你好"

    def synthesize(text, speaker, speed, engine="fast"):
        seen.append(engine)
        return np.zeros(100, dtype=np.float32), 8000

    runtime.engine.chat = chat
    runtime.audio.synthesize = synthesize
    runtime.schedule(
        runtime._conversation(0, replace(Settings(), tts_engine="natural"), "你好", "chat", None, None)
    ).result(3)
    assert seen == ["natural"]


def test_clear_memory_cancels_old_request_and_history(runtime):
    runtime.memory.save("喜欢绿茶")
    runtime.history = [{"role": "user", "content": "记住，我喜欢绿茶"}]
    started = threading.Event()
    stopped = threading.Event()

    async def chat(*_):
        started.set()
        try:
            await asyncio.sleep(60)
        finally:
            stopped.set()

    runtime.engine.chat = chat
    runtime.ask(Settings(), "我喜欢什么")
    assert started.wait(2)
    saved = runtime.save_memory("")
    assert saved is not None
    saved.result(timeout=3)
    assert stopped.is_set()
    assert runtime.memory.read() == ""
    assert runtime.history == []


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

    async def chat(*_):
        nonlocal current
        current = False
        return "现在的画面已经过期了"

    monkeypatch.setattr("pet.runtime.observation_current", lambda _: current)
    runtime.engine.chat = chat
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

    async def chat(*_):
        return "无需回应"

    runtime.engine.chat = chat
    runtime.schedule(runtime._conversation(0, Settings(), "观察", "observation", None, None)).result(3)
    assert states[-1] == "已就绪 · 麦克风关闭"
