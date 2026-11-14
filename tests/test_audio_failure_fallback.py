"""持续检测故障在三秒后放行朗读；只用虚拟时钟和播放替身。"""

import threading
from types import SimpleNamespace

import numpy as np
import pytest

from pet.audio_activity import AudioActivity
from pet.config import Settings
from pet.conversation_issues import preview_issue
from pet.speech_output import speak


def test_repeated_errors_do_not_extend_failure_grace_forever():
    now = [0.0]
    gate = AudioActivity(clock=lambda: now[0])
    for moment in (0.0, 0.5, 1.5, 2.99):
        now[0] = moment
        gate.update(None)
        assert gate.blocked
    for moment in (3.0, 3.5, 10.0, 3600.0):
        now[0] = moment
        gate.update(None)
        assert not gate.blocked
        assert "已暂时放行朗读" in gate.status


def test_no_initial_sample_only_blocks_during_grace():
    now = [10.0]
    gate = AudioActivity(clock=lambda: now[0])
    now[0] = 12.99
    assert gate.blocked
    now[0] = 13.0
    assert not gate.blocked


@pytest.mark.parametrize("sound", [False, True])
def test_stalled_worker_cannot_keep_speech_blocked_forever(sound):
    now = [0.0]
    gate = AudioActivity(clock=lambda: now[0])
    gate.update(sound)
    now[0] = 0.7
    assert gate.blocked
    now[0] = 3.59
    assert gate.blocked
    now[0] = 3.6
    assert not gate.blocked
    assert "声音检测不可用" in gate.status


def test_late_error_does_not_reset_grace_of_already_stale_sample():
    now = [0.0]
    gate = AudioActivity(clock=lambda: now[0])
    gate.update(False)
    now[0] = 4.0
    gate.update(None)
    assert not gate.blocked


def test_recovery_restores_sound_avoidance_and_next_failure_gets_new_grace():
    now = [0.0]
    gate = AudioActivity(clock=lambda: now[0])
    now[0] = 3.0
    assert not gate.blocked
    gate.update(True)
    assert gate.blocked
    assert "其他软件正在发声" in gate.status
    now[0] = 4.6
    gate.update(False)
    assert not gate.blocked
    assert "已开启" in gate.status
    now[0] = 4.7
    gate.update(None)
    assert gate.blocked
    now[0] = 7.7
    gate.update(None)
    assert not gate.blocked


def test_reenable_starts_fresh_grace_after_previous_degraded_period():
    now = [0.0]
    gate = AudioActivity(clock=lambda: now[0])
    now[0] = 10.0
    assert not gate.blocked
    gate.set_enabled(False)
    assert not gate.blocked
    gate.set_enabled(True)
    assert gate.blocked
    now[0] = 12.99
    gate.update(None)
    assert gate.blocked
    now[0] = 13.0
    assert not gate.blocked


def test_closing_detector_does_not_allow_speech_after_grace():
    now = [0.0]
    gate = AudioActivity(clock=lambda: now[0])
    now[0] = 3.0
    assert not gate.blocked
    gate.close()
    now[0] = 100.0
    assert gate.blocked


def test_degraded_detector_does_not_report_preview_as_suppressed():
    now = [0.0]
    gate = AudioActivity(clock=lambda: now[0])
    now[0] = 3.0
    runtime = SimpleNamespace(speech_override=None, audio_activity=gate)
    assert preview_issue(runtime, Settings()) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("moment, expected", [(0.5, False), (3.0, True)])
async def test_real_speech_path_resumes_after_failure_grace(monkeypatch, moment, expected):
    now = [0.0]
    gate = AudioActivity(clock=lambda: now[0])
    now[0] = moment
    gate.update(None)
    played = []
    monkeypatch.setattr("pet.speech_output.sd.play", lambda *_: played.append(True))
    monkeypatch.setattr("pet.speech_output.sd.wait", lambda: None)
    monkeypatch.setattr("pet.speech_output.sd.stop", lambda: None)

    result = await speak(gate, lambda: (np.zeros(16), 8000), lambda: True, lambda _: None)

    assert result is expected
    assert bool(played) is expected


@pytest.mark.asyncio
async def test_sound_detection_recovery_interrupts_degraded_playback(monkeypatch):
    now = [0.0]
    gate = AudioActivity(clock=lambda: now[0])
    now[0] = 3.0
    stopped = threading.Event()
    played = []

    def play(*_):
        played.append(True)
        gate.update(True)

    monkeypatch.setattr("pet.speech_output.sd.play", play)
    monkeypatch.setattr("pet.speech_output.sd.wait", lambda: stopped.wait(1))
    monkeypatch.setattr("pet.speech_output.sd.stop", stopped.set)

    result = await speak(gate, lambda: (np.zeros(16), 8000), lambda: True, lambda _: None)

    assert played and stopped.is_set()
    assert not result and gate.blocked
