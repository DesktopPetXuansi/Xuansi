"""开麦前只预热控制缓存；合成建议不可执行，失败与取消不打开真实输入。"""

import asyncio
import json
import logging
import threading
from dataclasses import replace

import httpx
import numpy as np
import pytest
from PySide6.QtCore import Qt

from pet.config import Settings
from pet.inference import LocalEngine, request_messages
from pet.memory import MemoryStore
from pet.model_control import control_prompt
from pet.runtime import Runtime

LOG = logging.getLogger(__name__)


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled, actions", [(True, ()), (False, ("blink",))])
async def test_warmup_uses_actual_control_prompt_and_discards_all_execution_suggestions(
    monkeypatch, enabled, actions
):
    settings = Settings(temperature=1.1, persona="测试人设，不参与控制分类")
    payloads = []

    async def start(value):
        assert value is settings

    def unexpected_save(*_args):
        pytest.fail("预热不得执行模型提出的记忆保存")

    async def handle(request):
        if request.url.path == "/tokenize":
            return httpx.Response(200, json={"tokens": [1]})
        payload = json.loads(request.content)
        payloads.append(payload)
        grammar = payload["grammar"]
        if "voice" not in grammar:
            decision = {"memory_intent": "save"}
        else:
            # 返回合法但有副作用的建议，缓存预热仍必须全部丢弃。
            decision = {
                "memory_intent": "save", "voice": "off" if enabled else "on",
                "motion": "blink" if actions else "none", "memory": "预热合成事项",
            }
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(decision)}}]})

    engine = LocalEngine()
    monkeypatch.setattr(engine, "start", start)
    monkeypatch.setattr(MemoryStore, "remember", unexpected_save)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle), base_url="http://127.0.0.1") as client:
        engine.client = client
        result = await engine.prepare_controls(settings, speech_enabled=enabled, available_motions=actions)
    assert result is None
    expected = replace(settings, persona="", max_tokens=256, system_prompt=control_prompt(enabled, actions, True))
    assert payloads[0]["messages"] == request_messages(expected, "你好", [], [])
    assert payloads[0]["max_tokens"] == 256
    assert all(payload["temperature"] == 0.0 and payload["top_p"] == 1.0 for payload in payloads)
    assert all(payload["stream"] is False for payload in payloads)
    assert "save ::= " in payloads[0]["grammar"], "预热需覆盖实际允许保存记忆的完整控制协议"
    assert ('\\\"blink\\\"' in payloads[0]["grammar"]) is bool(actions)


@pytest.mark.asyncio
async def test_cancelled_control_warmup_stops_owned_inference(monkeypatch):
    entered = asyncio.Event()
    stopped = []

    async def start(_settings):
        pass

    async def stop():
        stopped.append(True)

    async def handle(request):
        if request.url.path == "/tokenize":
            return httpx.Response(200, json={"tokens": [1]})
        entered.set()
        await asyncio.Event().wait()

    engine = LocalEngine()
    monkeypatch.setattr(engine, "start", start)
    monkeypatch.setattr(engine, "stop", stop)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle), base_url="http://127.0.0.1") as client:
        engine.client = client
        task = asyncio.create_task(engine.prepare_controls(Settings()))
        try:
            await asyncio.wait_for(entered.wait(), 1)
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
    assert stopped == [True]


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

    async def prepare(settings, *, speech_enabled=True, available_motions=()):
        prepared.append((settings, speech_enabled, available_motions))
        LOG.info("模拟完整控制预热 speech_enabled=%s", speech_enabled)

    def synthesize(*_args):
        synthesized.append(True)
        return np.zeros(1), 8000

    monkeypatch.setattr(runtime.engine, "prepare_controls", prepare, raising=False)
    monkeypatch.setattr(runtime.audio, "synthesize", synthesize)
    settings = Settings()
    runtime.schedule(runtime._prepare_voice(settings)).result(2)
    assert prepared == [(settings, enabled, ("blink",))]
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

    monkeypatch.setattr(runtime.engine, "prepare_controls", prepare, raising=False)
    runtime.toggle_microphone(True, 7, realtime=True, settings=Settings()).result(2)
    assert not opened and not played
    assert any("麦克风无法开启" in state for state in states)


def test_cancelled_control_warmup_never_opens_microphone(isolated_runtime, monkeypatch):
    runtime, opened, played = isolated_runtime
    started = threading.Event()

    async def prepare(*_args, **_kwargs):
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(runtime.engine, "prepare_controls", prepare, raising=False)
    warming = runtime.toggle_microphone(True, 7, realtime=True, settings=Settings())
    assert started.wait(1)
    runtime.toggle_microphone(False).result(2)
    warming.result(2)
    assert not opened and not played and not runtime.listening
