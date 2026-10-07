"""Live2D 视线、口型状态与发丝衣摆的纯数值驱动，不增加计时器。"""

import math
from dataclasses import dataclass

from PySide6.QtCore import QPoint
from PySide6.QtGui import QCursor

HAIR_SWAY_PARAMETER_IDS = ("ParamHairFront", "ParamHairSide", "ParamHairBack")


HAIR_SWAY_PERIOD_SECONDS = 2.8


CLOTH_SWAY_PERIOD_SECONDS = 4.2


MAX_SWAY_FRAME_SECONDS = 0.1


SWAY_INTEGRATION_STEP_SECONDS = 1 / 60


CLOTH_SWAY_PHASE_OFFSET = math.pi / 2


@dataclass(frozen=True, slots=True)
class HairSwayState:
    """保存发根、发中、发梢的位移与速度，供连续的轻量弹簧链使用。"""

    root: float = 0.0
    middle: float = 0.0
    tip: float = 0.0
    root_velocity: float = 0.0
    middle_velocity: float = 0.0
    tip_velocity: float = 0.0


def _gaze_axis(position, origin, low, high, minimum_span):
    """按眼睛到鼠标所在方向的屏幕边缘映射，避免在桌宠附近就锁死视线。"""
    distance = position - origin
    span = origin - low if distance < 0 else high - origin
    return max(-1.0, min(1.0, distance / max(1.0, minimum_span, span)))


def _advance_sway_phase(phase, elapsed, period_seconds=HAIR_SWAY_PERIOD_SECONDS):
    """按独立周期推进摆动相位，并限制单帧步长以避免卡顿后突然甩动。"""
    step = max(0.0, min(float(elapsed), MAX_SWAY_FRAME_SECONDS))
    return (phase + math.tau * step / period_seconds) % math.tau


def _hair_wind_force(phase):
    """用两个低频分量形成持续但不完全匀速的轻风驱动。"""
    return math.sin(phase) + 0.13 * math.sin(2.0 * phase + 0.9)


def _cloth_sway_parameter(phase):
    """衣摆保持原有周期和参数范围，继续与头发错相运动。"""
    return 10.0 * math.sin(phase + CLOTH_SWAY_PHASE_OFFSET)


def _advance_spring_component(position, velocity, target, elapsed, stiffness, damping):
    """以半隐式欧拉推进单段弹簧；小步积分保持桌宠绘制帧稳定。"""
    acceleration = (target - position) * stiffness - velocity * damping
    velocity += acceleration * elapsed
    position += velocity * elapsed
    return position, velocity


def _advance_hair_sway(state, wind_force, elapsed):
    """逐段推进带阻尼的三段发束，越靠近发梢越晚跟随、位移越大。"""
    step = max(0.0, min(float(elapsed), MAX_SWAY_FRAME_SECONDS))
    if step == 0.0:
        return state

    substeps = math.ceil(step / SWAY_INTEGRATION_STEP_SECONDS)
    substep = step / substeps
    root, middle, tip = state.root, state.middle, state.tip
    root_velocity = state.root_velocity
    middle_velocity = state.middle_velocity
    tip_velocity = state.tip_velocity

    for _ in range(substeps):
        root, root_velocity = _advance_spring_component(
            root, root_velocity, wind_force * 0.10, substep, 30.0, 10.0
        )
        middle_target = root + wind_force * 0.22
        middle, middle_velocity = _advance_spring_component(
            middle, middle_velocity, middle_target, substep, 18.0, 7.0
        )
        tip_target = middle + wind_force * 0.45
        tip, tip_velocity = _advance_spring_component(tip, tip_velocity, tip_target, substep, 12.0, 5.0)

    return HairSwayState(
        root=max(-1.0, min(1.0, root)),
        middle=max(-1.0, min(1.0, middle)),
        tip=max(-1.0, min(1.0, tip)),
        root_velocity=root_velocity,
        middle_velocity=middle_velocity,
        tip_velocity=tip_velocity,
    )


class AvatarDynamics:
    """Live2D 视线、口型状态与发丝衣摆的纯数值驱动，不增加计时器。"""

    def _init_parameter_state(self):
        """保留原初始化顺序与中立值，状态仍由 Avatar 持有。"""
        self._mouth_target = 0.0
        self._mouth_level = 0.0
        self._hair_sway_phase = 0.0
        self._cloth_sway_phase = 0.0
        self._hair_sway = HairSwayState()
        self._gaze_x = 0.0
        self._gaze_y = 0.0

    def _update_sway(self, elapsed):
        """以不同自然频率推进发丝与衣摆，不创建额外计时器。"""
        self._hair_sway_phase = _advance_sway_phase(
            self._hair_sway_phase,
            elapsed,
            HAIR_SWAY_PERIOD_SECONDS,
        )
        self._cloth_sway_phase = _advance_sway_phase(
            self._cloth_sway_phase,
            elapsed,
            CLOTH_SWAY_PERIOD_SECONDS,
        )
        self._hair_sway = _advance_hair_sway(
            self._hair_sway,
            _hair_wind_force(self._hair_sway_phase),
            elapsed,
        )
        hair_values = (
            self._hair_sway.root,
            self._hair_sway.middle,
            self._hair_sway.tip,
        )
        for parameter, value in zip(HAIR_SWAY_PARAMETER_IDS, hair_values, strict=True):
            self._live2d_model.SetParameterValue(parameter, value)
        self._live2d_model.SetParameterValue(
            "ParamBodyAngleX",
            _cloth_sway_parameter(self._cloth_sway_phase),
        )

    def _update_gaze(self, elapsed):
        if self.animation == "sleep":
            target_x, target_y = 0.0, 0.0
        else:
            cursor = QCursor.pos()
            center = self.mapToGlobal(QPoint(self.width() // 2, round(self.height() * 0.38)))
            # 固定使用桌宠所在屏幕，避免越过边缘时在多个屏幕的范围之间切换。
            bounds = self.screen().geometry()
            target_x = _gaze_axis(cursor.x(), center.x(), bounds.left(), bounds.right(), self.width() * 0.5)
            # 屏幕 Y 轴向下，Live2D 眼球 Y 轴向上；临近边缘时保留最小过渡距离。
            target_y = -_gaze_axis(cursor.y(), center.y(), bounds.top(), bounds.bottom(), self.height() * 0.3)
        smoothing = min(1.0, elapsed * 9.0)
        self._gaze_x += (target_x - self._gaze_x) * smoothing
        self._gaze_y += (target_y - self._gaze_y) * smoothing
