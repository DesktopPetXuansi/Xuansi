"""故障恢复使用虚拟等待与 COM 替身，不访问真实声卡或耗时重试。"""

from types import SimpleNamespace

import pytest

from pet.audio_activity import AudioActivity


class StepEvent:
    def __init__(self, now, limit=6):
        self.now = now
        self.limit = limit
        self.waits = []
        self.stopped = False
        self.on_wait = lambda _: None

    def is_set(self):
        return self.stopped or len(self.waits) >= self.limit

    def wait(self, delay):
        self.waits.append(delay)
        self.now[0] += delay
        self.on_wait(delay)
        return self.is_set()

    def set(self):
        self.stopped = True


@pytest.fixture
def loop(monkeypatch):
    now = [0.0]
    gate = AudioActivity(clock=lambda: now[0])
    gate._stop = StepEvent(now)
    initialized, uninitialized = [], []
    monkeypatch.setattr("pet.audio_activity.comtypes.CoInitializeEx", initialized.append)
    monkeypatch.setattr("pet.audio_activity.comtypes.CoUninitialize", lambda: uninitialized.append(True))
    return SimpleNamespace(
        gate=gate, stop=gate._stop, initialized=initialized, uninitialized=uninitialized,
    )


def fail():
    raise RuntimeError("模拟音频设备失效")


def test_persistent_sampling_errors_back_off_and_eventually_allow_speech(loop, monkeypatch, caplog):
    probes, closed = [], []

    def create():
        probe = SimpleNamespace(sample=fail, close=lambda: closed.append(True))
        probes.append(probe)
        return probe

    monkeypatch.setattr("pet.audio_activity.CoreAudioProbe", create)
    with caplog.at_level("INFO", logger="pet.audio_activity"):
        loop.gate._run()

    assert loop.stop.waits == [0.5, 1.0, 2.0, 4.0, 5.0, 5.0]
    assert len(probes) == len(closed) == 6
    assert not loop.gate.blocked
    assert sum("已暂时放行朗读" in record.message for record in caplog.records) == 1
    assert len(loop.initialized) == len(loop.uninitialized) == 1


def test_success_resets_backoff_and_reuses_healthy_probe(loop, monkeypatch, caplog):
    readings = iter([RuntimeError(), False, RuntimeError(), False, False, False])
    created = []

    def sample():
        reading = next(readings)
        if isinstance(reading, Exception):
            raise reading
        return reading

    def create():
        created.append(True)
        return SimpleNamespace(sample=sample, close=lambda: None)

    monkeypatch.setattr("pet.audio_activity.CoreAudioProbe", create)
    with caplog.at_level("INFO", logger="pet.audio_activity"):
        loop.gate._run()

    assert loop.stop.waits == [0.5, 0.1, 0.5, 0.1, 0.1, 0.1]
    assert len(created) == 3
    assert not loop.gate.blocked
    assert "声音检测已恢复" in caplog.text


def test_initialization_failure_retries_then_recovers_on_same_worker(loop, monkeypatch):
    def initialize(flags):
        loop.initialized.append(flags)
        if len(loop.initialized) == 1:
            raise RuntimeError("模拟 COM 初始化失败")

    monkeypatch.setattr("pet.audio_activity.comtypes.CoInitializeEx", initialize)
    monkeypatch.setattr(
        "pet.audio_activity.CoreAudioProbe", lambda: SimpleNamespace(sample=lambda: False, close=lambda: None),
    )
    loop.gate._run()

    assert loop.stop.waits == [0.5, 0.1, 0.1, 0.1, 0.1, 0.1]
    assert len(loop.initialized) == 2
    assert len(loop.uninitialized) == 1
    assert not loop.gate.blocked


def test_unsuccessful_initialization_is_not_uninitialized(loop, monkeypatch):
    monkeypatch.setattr("pet.audio_activity.comtypes.CoInitializeEx", lambda _: fail())
    monkeypatch.setattr("pet.audio_activity.CoreAudioProbe", lambda: pytest.fail("初始化失败不能创建探针"))
    loop.gate._run()

    assert loop.stop.waits == [0.5, 1.0, 2.0, 4.0, 5.0, 5.0]
    assert not loop.uninitialized
    assert not loop.gate.blocked


def test_cleanup_errors_do_not_stop_sampling_recovery(loop, monkeypatch):
    created = []

    def create():
        created.append(True)
        return SimpleNamespace(sample=fail if len(created) == 1 else lambda: False, close=fail)

    monkeypatch.setattr("pet.audio_activity.CoreAudioProbe", create)
    loop.gate._run()

    assert loop.stop.waits == [0.5, 0.1, 0.1, 0.1, 0.1, 0.1]
    assert len(created) == 2
    assert not loop.gate.blocked
    assert len(loop.uninitialized) == 1


def test_disabled_gate_releases_probe_and_does_not_poll(loop, monkeypatch):
    samples, closed = [], []
    monkeypatch.setattr(
        "pet.audio_activity.CoreAudioProbe",
        lambda: SimpleNamespace(sample=lambda: samples.append(True) or False, close=lambda: closed.append(True)),
    )
    loop.stop.on_wait = lambda _: loop.gate.set_enabled(False)
    loop.gate._run()

    assert len(samples) == len(closed) == 1
    assert not loop.gate.blocked


def test_close_interrupts_backoff_wait(loop, monkeypatch):
    monkeypatch.setattr("pet.audio_activity.CoreAudioProbe", fail)
    loop.stop.on_wait = lambda _: loop.gate.close()
    loop.gate._run()

    assert loop.stop.waits == [0.5]
    assert loop.stop.is_set()
    assert loop.gate.blocked


def test_start_replaces_dead_thread_but_preserves_live_thread(monkeypatch):
    created = []

    def thread(**kwargs):
        worker = SimpleNamespace(is_alive=lambda: True, start=lambda: None, **kwargs)
        created.append(worker)
        return worker

    monkeypatch.setattr("pet.audio_activity.threading.Thread", thread)
    gate = AudioActivity()
    gate.thread = SimpleNamespace(is_alive=lambda: False)
    gate.start()
    gate.start()

    assert len(created) == 1
    assert gate.thread is created[0]


def test_closed_gate_cannot_restart_worker(monkeypatch):
    monkeypatch.setattr("pet.audio_activity.threading.Thread", lambda **_: pytest.fail("关闭后不能创建线程"))
    gate = AudioActivity()
    gate.close()
    gate.start()
