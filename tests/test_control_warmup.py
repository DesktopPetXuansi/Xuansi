"""开麦前只预热控制缓存；合成建议不可执行，失败与取消不打开真实输入。"""

import asyncio
import logging
import threading

import numpy as np
import pytest
from PySide6.QtCore import Qt

from pet.config import Settings
from pet.inference import LocalEngine
from pet.memory import MemoryStore
from pet.runtime import Runtime

LOG = logging.getLogger(__name__)


@pytest.mark.asyncio
async def test_warmup_only_loads_model_without_generating_execution_suggestions(monkeypatch):
    """预热仅准备资源，任何推理和保存都属于错误副作用。"""
    engine = LocalEngine()
    settings = Settings()
    loaded = []

    async def start(value):
        loaded.append(value)

    async def unexpected_complete(*_args, **_kwargs):
        pytest.fail("资源预热不得发起对话或工具建议")

    def unexpected_save(*_args):
        pytest.fail("资源预热不得写入用户记忆")

    monkeypatch.setattr(engine, "start", start)
    monkeypatch.setattr(engine, "complete", unexpected_complete)
    monkeypatch.setattr(MemoryStore, "remember", unexpected_save)
    assert await engine.warmup(settings) is None
    assert loaded == [settings]
    assert engine.last_used > 0


@pytest.mark.asyncio
async def test_cancelled_model_warmup_propagates_to_resource_loading(monkeypatch):
    entered, stopped = asyncio.Event(), asyncio.Event()
    engine = LocalEngine()

    async def start(_settings):
        entered.set()
        try:
            await asyncio.Future()
        finally:
            stopped.set()

    monkeypatch.setattr(engine, "start", start)
    task = asyncio.create_task(engine.warmup(Settings()))
    await asyncio.wait_for(entered.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert stopped.is_set()


@pytest.fixture
def isolated_runtime(monkeypatch, tmp_path):
    opened, played = [], []

    class FakeMicrophone:
        def __init__(self, *_args, **_kwargs):
            self.muted = threading.Event()

        def stop(self):
            pass

        def join(self):
            return True

        def start(self, device):
            opened.append(device)

    async def start(_settings):
        pass

    monkeypatch.setattr("pet.runtime.Microphone", FakeMicrophone)
    monkeypatch.setattr("pet.runtime.sd.stop", lambda: None)
    monkeypatch.setattr("pet.runtime.sd.play", lambda *_args: played.append(True))
    monkeypatch.setattr("pet.runtime.sd.wait", lambda: None)
    runtime = Runtime()
    runtime.audio_activity.set_enabled(False)
    runtime.memory = MemoryStore(tmp_path / "memory.json")
    runtime.memory.save("原有人工测试记忆")
    runtime.history = [{"role": "user", "content": "原有人工测试话题"}]
    monkeypatch.setattr(runtime.engine, "start", start)
    monkeypatch.setattr(runtime.audio, "synthesize", lambda *_args: (np.zeros(1), 8000))
    yield runtime, opened, played
    runtime.listening = False
    runtime.microphone.stop()
    runtime.cancel(release=True).result(3)
    runtime.loop.call_soon_threadsafe(runtime.loop.stop)
    runtime.thread.join(2)


@pytest.mark.parametrize("enabled", [True, False])
def test_runtime_warms_current_control_state_without_playback_or_user_state_changes(
    isolated_runtime, monkeypatch, enabled
):
    runtime, opened, played = isolated_runtime
    prepared, synthesized = [], []
    runtime.speech_override = enabled
    runtime.motion_actions = ("blink",)
    history = list(runtime.history)

    async def prepare(settings):
        prepared.append(settings)
        LOG.info("模拟模型资源预热")

    def synthesize(*_args):
        synthesized.append(True)
        return np.zeros(1), 8000

    monkeypatch.setattr(runtime.engine, "warmup", prepare, raising=False)
    monkeypatch.setattr(runtime.audio, "synthesize", synthesize)
    settings = Settings()
    runtime.schedule(runtime._prepare_voice(settings)).result(2)
    assert prepared == [settings]
    assert bool(synthesized) is enabled
    assert not played and not opened
    assert runtime.history == history and runtime.memory.read() == "原有人工测试记忆"
    assert runtime.speech_override is enabled


def test_failed_control_warmup_reports_failure_without_opening_microphone(isolated_runtime, monkeypatch):
    runtime, opened, played = isolated_runtime
    states = []
    runtime.microphone_state.connect(lambda _epoch, text: states.append(text), Qt.ConnectionType.DirectConnection)

    async def prepare(*_args, **_kwargs):
        raise RuntimeError("合成控制预热失败")

    monkeypatch.setattr(runtime.engine, "warmup", prepare, raising=False)
    runtime.toggle_microphone(True, 7, realtime=True, settings=Settings()).result(2)
    assert not opened and not played
    assert any("麦克风无法开启" in state for state in states)


def test_cancelled_control_warmup_never_opens_microphone(isolated_runtime, monkeypatch):
    runtime, opened, played = isolated_runtime
    started = threading.Event()

    async def prepare(*_args, **_kwargs):
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(runtime.engine, "warmup", prepare, raising=False)
    warming = runtime.toggle_microphone(True, 7, realtime=True, settings=Settings())
    assert started.wait(1)
    runtime.toggle_microphone(False).result(2)
    warming.result(2)
    assert not opened and not played and not runtime.listening
