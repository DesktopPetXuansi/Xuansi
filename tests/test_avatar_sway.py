"""验证玄司头发与衣摆摆动的纯数值驱动。"""

import math

import pytest
from PySide6.QtCore import QPoint, QRect
from PySide6.QtGui import QRegion

from pet.avatar import (
    CLOTH_SWAY_PERIOD_SECONDS,
    HAIR_SWAY_PARAMETER_IDS,
    HAIR_SWAY_PERIOD_SECONDS,
    MAX_SWAY_FRAME_SECONDS,
    Avatar,
    HairSwayState,
    _advance_hair_sway,
    _advance_sway_phase,
    _cloth_sway_parameter,
    _expand_mask_region,
    _hair_wind_force,
)


def test_sway_phase_advances_at_a_fixed_period():
    """按设定周期连续前进，并在完整周期后回到起点。"""
    assert _advance_sway_phase(0.0, 0.1) == pytest.approx(
        math.tau * 0.1 / HAIR_SWAY_PERIOD_SECONDS
    )

    phase = 0.0
    for _ in range(round(HAIR_SWAY_PERIOD_SECONDS / MAX_SWAY_FRAME_SECONDS)):
        phase = _advance_sway_phase(phase, MAX_SWAY_FRAME_SECONDS)
    assert phase == pytest.approx(0.0)


def test_clothing_uses_a_slower_frequency_than_hair():
    """衣摆周期长于头发；等长时间推进时，衣摆相位变化更小。"""
    hair_phase = _advance_sway_phase(0.0, 0.1, HAIR_SWAY_PERIOD_SECONDS)
    cloth_phase = _advance_sway_phase(0.0, 0.1, CLOTH_SWAY_PERIOD_SECONDS)

    assert CLOTH_SWAY_PERIOD_SECONDS > HAIR_SWAY_PERIOD_SECONDS
    assert hair_phase > cloth_phase > 0.0


def test_sway_phase_caps_slow_frames_and_ignores_negative_time():
    """卡顿帧最多前进 100 毫秒，负时间不会让相位倒退。"""
    expected = _advance_sway_phase(0.25, MAX_SWAY_FRAME_SECONDS)
    assert _advance_sway_phase(0.25, 5.0) == pytest.approx(expected)
    assert _advance_sway_phase(0.25, -1.0) == pytest.approx(0.25)


def test_hair_spring_chain_delays_and_amplifies_motion_toward_the_tips():
    """发根先动、发中跟随、发梢滞后且振幅逐段增加。"""
    state = HairSwayState()
    samples = []
    phase = 0.0

    for frame in range(300):
        phase = _advance_sway_phase(phase, 1 / 30)
        state = _advance_hair_sway(state, _hair_wind_force(phase), 1 / 30)
        if frame >= 216:
            samples.append((state.root, state.middle, state.tip))

    peak_amplitudes = [max(abs(sample[index]) for sample in samples) for index in range(3)]
    peak_frames = [max(range(len(samples)), key=lambda frame: samples[frame][index]) for index in range(3)]
    assert peak_amplitudes[0] < peak_amplitudes[1] < peak_amplitudes[2] <= 1.0
    assert peak_frames[0] < peak_frames[1] < peak_frames[2]


def test_hair_spring_chain_returns_to_neutral_after_the_sway_stops():
    """风力停止后，三段发束靠阻尼逐渐回到中立位置。"""
    state = HairSwayState()
    for _ in range(90):
        state = _advance_hair_sway(state, 1.0, 1 / 30)
    peak_tip = abs(state.tip)

    for _ in range(90):
        state = _advance_hair_sway(state, 0.0, 1 / 30)

    assert peak_tip > 0.1
    assert abs(state.tip) < peak_tip * 0.1
    assert abs(state.tip_velocity) < 0.1


def test_hair_spring_chain_caps_stalled_frames_and_ignores_negative_time():
    """长卡顿最多推进 100 毫秒，负时间不改变头发状态。"""
    initial = HairSwayState(root=0.1, middle=0.2, tip=0.3)

    assert _advance_hair_sway(initial, 0.5, -1.0) == initial
    assert _advance_hair_sway(initial, 0.5, 5.0) == _advance_hair_sway(
        initial, 0.5, MAX_SWAY_FRAME_SECONDS
    )


def test_cloth_sway_stays_bounded_and_out_of_phase():
    """衣摆仍使用模型参数范围，并与头发主驱动错相。"""
    for phase in (0.0, math.pi / 2, math.pi, math.tau):
        assert -10.0 <= _cloth_sway_parameter(phase) <= 10.0

    assert _cloth_sway_parameter(0.0) > 0.0


def test_avatar_writes_both_sway_values_to_the_model():
    """绘制帧将归一化摆动值写入对应 Live2D 参数。"""

    class RecordingModel:
        def __init__(self):
            """记录驱动器写入的模型参数。"""
            self.values = {}

        def SetParameterValue(self, parameter, value):
            """模拟 Cubism 的参数赋值接口。"""
            self.values[parameter] = value

    class SwayHarness:
        def __init__(self):
            """提供摆动更新所需的最小对象状态。"""
            self._live2d_model = RecordingModel()
            self._hair_sway_phase = 0.0
            self._cloth_sway_phase = 0.0
            self._hair_sway = HairSwayState()

    avatar = SwayHarness()
    Avatar._update_sway(avatar, 0.1)
    cloth = _cloth_sway_parameter(avatar._cloth_sway_phase)
    hair_phase = math.tau * 0.1 / HAIR_SWAY_PERIOD_SECONDS
    cloth_phase = math.tau * 0.1 / CLOTH_SWAY_PERIOD_SECONDS

    expected = dict(
        zip(
            HAIR_SWAY_PARAMETER_IDS,
            (avatar._hair_sway.root, avatar._hair_sway.middle, avatar._hair_sway.tip),
            strict=True,
        )
    )
    expected["ParamBodyAngleX"] = pytest.approx(cloth)
    assert avatar._live2d_model.values == expected
    assert avatar._hair_sway_phase == pytest.approx(hair_phase)
    assert avatar._cloth_sway_phase == pytest.approx(cloth_phase)


def test_expanded_window_mask_keeps_rendered_hair_inside_click_region():
    """透明窗口掩码留出安全边界，避免裁掉摆动到原轮廓外的发丝。"""
    original = QRegion(QRect(20, 30, 10, 10))

    expanded = _expand_mask_region(original, 2)

    assert original.subtracted(expanded).isEmpty()
    assert expanded.contains(QPoint(18, 28))
    assert expanded.contains(QPoint(31, 41))
    assert not expanded.contains(QPoint(17, 30))
    assert not expanded.contains(QPoint(32, 30))
