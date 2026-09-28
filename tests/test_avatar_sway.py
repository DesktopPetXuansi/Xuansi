"""验证玄司头发与衣摆摆动的纯数值驱动。"""

import math

import pytest
from PySide6.QtCore import QPoint, QRect
from PySide6.QtGui import QRegion

from pet.avatar import (
    MAX_SWAY_FRAME_SECONDS,
    SWAY_PERIOD_SECONDS,
    Avatar,
    _advance_sway_phase,
    _expand_mask_region,
    _sway_parameters,
)


def test_sway_phase_advances_at_a_fixed_period():
    """按设定周期连续前进，并在完整周期后回到起点。"""
    assert _advance_sway_phase(0.0, 0.1) == pytest.approx(math.tau * 0.1 / SWAY_PERIOD_SECONDS)

    phase = 0.0
    for _ in range(round(SWAY_PERIOD_SECONDS / MAX_SWAY_FRAME_SECONDS)):
        phase = _advance_sway_phase(phase, MAX_SWAY_FRAME_SECONDS)
    assert phase == pytest.approx(0.0)


def test_sway_phase_caps_slow_frames_and_ignores_negative_time():
    """卡顿帧最多前进 100 毫秒，负时间不会让相位倒退。"""
    expected = _advance_sway_phase(0.25, MAX_SWAY_FRAME_SECONDS)
    assert _advance_sway_phase(0.25, 5.0) == pytest.approx(expected)
    assert _advance_sway_phase(0.25, -1.0) == pytest.approx(0.25)


def test_sway_parameters_are_bounded_and_out_of_phase():
    """头发使用归一化幅度，衣摆使用模型参数范围并错相运动。"""
    for phase in (0.0, math.pi / 2, math.pi, math.tau):
        hair, cloth = _sway_parameters(phase)
        assert -1.0 <= hair <= 1.0
        assert -10.0 <= cloth <= 10.0

    hair, cloth = _sway_parameters(0.0)
    assert hair == pytest.approx(0.0)
    assert cloth > 0.0


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
            self._sway_phase = 0.0

    avatar = SwayHarness()
    Avatar._update_sway(avatar, 0.1)
    hair, cloth = _sway_parameters(avatar._sway_phase)

    assert avatar._live2d_model.values == {
        "ParamHairBack": pytest.approx(hair),
        "ParamBodyAngleX": pytest.approx(cloth),
    }


def test_expanded_window_mask_keeps_rendered_hair_inside_click_region():
    """透明窗口掩码留出安全边界，避免裁掉摆动到原轮廓外的发丝。"""
    original = QRegion(QRect(20, 30, 10, 10))

    expanded = _expand_mask_region(original, 2)

    assert original.subtracted(expanded).isEmpty()
    assert expanded.contains(QPoint(18, 28))
    assert expanded.contains(QPoint(31, 41))
    assert not expanded.contains(QPoint(17, 30))
    assert not expanded.contains(QPoint(32, 30))
