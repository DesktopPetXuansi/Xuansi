"""声音回避使用虚拟电平和声卡，验证阻止及中断，不播放测试声音。"""

import asyncio
import threading
from types import SimpleNamespace

import numpy as np
import pytest

from pet.audio_activity import AudioActivity
from pet.speech_output import speak
from pet.windows_audio import SessionMeter


def test_only_audible_external_sessions_block(monkeypatch):
    monkeypatch.setattr("pet.windows_audio.os.getpid", lambda: 10)

    def audible(pid, state, muted, volume, peak):
        control = SimpleNamespace(GetProcessId=lambda: pid, GetState=lambda: state)
        meter = SessionMeter(control)
        meter.volume = SimpleNamespace(GetMute=lambda: muted, GetMasterVolume=lambda: volume)
        meter.meter = SimpleNamespace(GetPeakValue=lambda: peak)
        return meter.audible()

    assert audible(20, 1, False, 1.0, 0.01)
    assert not audible(10, 1, False, 1.0, 1.0)
    assert not audible(20, 0, False, 1.0, 1.0)
    assert not audible(20, 1, True, 1.0, 1.0)
    assert not audible(20, 1, False, 0.0, 1.0)
    assert not audible(20, 1, False, 1.0, 0.0)


def test_silence_hold_errors_and_stale_samples_fail_quiet():
    gate = AudioActivity(clock=lambda: 10.0)
    assert gate.blocked
    gate.update(True, now=8.8)
    gate.update(False, now=10.0)
    assert gate.blocked
    gate.update(False, now=10.4)
    gate.clock = lambda: 10.4
    assert not gate.blocked
    gate.clock = lambda: 11.5
    assert gate.blocked  # 工作线程卡住时不能沿用过去的“安静”。
    gate.update(None, now=11.5)
    assert gate.blocked


@pytest.mark.asyncio
async def test_skip_synthesis_when_other_audio_is_present():
    class Gate:
        blocked = True

    calls = []
    await speak(Gate(), lambda: calls.append("synth"), lambda: True, lambda _: None)
    assert not calls


@pytest.mark.asyncio
async def test_other_audio_interrupts_playback_and_is_not_replayed(monkeypatch):
    class Gate:
        blocked = False

    gate = Gate()
    started, stopped = threading.Event(), threading.Event()
    calls = []
    monkeypatch.setattr("pet.speech_output.sd.play", lambda *_: (started.set(), calls.append("play")))
    monkeypatch.setattr("pet.speech_output.sd.wait", lambda: stopped.wait(2))
    monkeypatch.setattr("pet.speech_output.sd.stop", stopped.set)
    job = asyncio.create_task(speak(gate, lambda: (np.zeros(10), 8000), lambda: True, lambda _: None))
    assert await asyncio.to_thread(started.wait, 1)
    gate.blocked = True
    await asyncio.wait_for(job, 1)
    assert stopped.is_set()
    gate.blocked = False
    await asyncio.sleep(0.1)
    assert calls == ["play"]


@pytest.mark.asyncio
async def test_audio_started_during_synthesis_prevents_play(monkeypatch):
    class Gate:
        blocked = False

    gate = Gate()
    calls = []

    def synthesize():
        gate.blocked = True
        return np.zeros(10), 8000

    monkeypatch.setattr("pet.speech_output.sd.play", lambda *_: calls.append("play"))
    await speak(gate, synthesize, lambda: True, lambda _: None)
    assert not calls
