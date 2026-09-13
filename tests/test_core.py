"""核心边界：设置校验、跨屏裁剪、鼠标意图和语音断句。"""

import numpy as np
import pytest

from pet.config import Settings, load_settings, save_settings
from pet.events import MouseTracker, ObservationGate, crop_rect
from pet.segmentation import Segmenter


def test_persona_persists_and_invalid_settings_are_rejected(tmp_path):
    path = tmp_path / "settings.json"
    settings = Settings(name="团子", persona="说话温柔，喜欢猫。", interval=25)
    save_settings(settings, path)
    assert load_settings(path) == settings
    with pytest.raises(ValueError):
        Settings(interval=0).validate()


def test_corrupt_settings_are_not_silently_overwritten(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{broken", encoding="utf-8")
    assert load_settings(path) == Settings()
    assert path.read_text(encoding="utf-8") == "{broken"


def test_crop_clamps_to_negative_coordinate_monitor():
    rect = crop_rect(-1910, 8, (-1920, 0, 0, 1080), 640, 448)
    assert rect == (-1920, 0, -1280, 448)
    assert crop_rect(98, 78, (0, 0, 100, 80), 640, 448) == (0, 0, 100, 80)


def test_drag_is_classified_from_press_to_release():
    tracker = MouseTracker()
    tracker.press(10, 20, 1.0)
    event = tracker.release(200, 100, 1.4)
    assert event.kind == "drag"
    assert event.start == (10, 20)
    tracker.press(20, 20, 2.0)
    assert tracker.release(22, 20, 2.1).kind == "click"


def test_observation_gate_drops_stale_and_limits_rate():
    gate = ObservationGate(interval=15)
    assert gate.allowed(now=20, event_time=19, blocked=False)
    gate.mark_sent(20)
    assert not gate.allowed(now=21, event_time=21, blocked=False)
    assert not gate.allowed(now=40, event_time=20, blocked=False)
    assert not gate.allowed(now=40, event_time=39, blocked=True)
    assert gate.allowed(now=40, event_time=39, blocked=False)


def test_speech_segmenter_never_emits_silence_and_has_max_duration():
    vad = Segmenter(sample_rate=16000, silence_seconds=0.3, max_seconds=1)
    silence = np.zeros(1600, dtype=np.float32)
    assert all(vad.feed(silence) is None for _ in range(20))
    result = None
    for _ in range(12):
        chunk = vad.feed(np.full(1600, 0.1, dtype=np.float32))
        if chunk is not None:
            result = chunk
    assert result is not None and len(result) <= 19200


def test_speech_segmenter_emits_after_end_of_sentence():
    vad = Segmenter(sample_rate=16000, silence_seconds=0.3)
    for _ in range(7):
        assert vad.feed(np.full(1600, 0.08, dtype=np.float32)) is None
    emitted = [vad.feed(np.zeros(1600, dtype=np.float32)) for _ in range(4)]
    assert sum(x is not None for x in emitted) == 1
