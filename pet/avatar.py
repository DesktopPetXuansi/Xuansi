"""玄司原生桌宠；自动展示永不取得输入焦点。"""

import logging
import math
import time
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QCursor, QGuiApplication, QPainter, QRegion, QSurfaceFormat
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import QGraphicsOpacityEffect, QLabel

from .character_frames import build_frames
from .idle_blade_animation import (
    IDLE_BLADE_FADE_SECONDS,
    idle_blade_opacity,
    idle_blade_pose,
    load_idle_blade_frames,
)
from .live2d_session import SESSION

LOG = logging.getLogger(__name__)
LIVE2D_MODEL = Path(__file__).resolve().parents[1] / "assets/xuansi/rigging/xuansi.model3.json"
HAIR_SWAY_PARAMETER_IDS = ("ParamHairFront", "ParamHairSide", "ParamHairBack")
LIVE2D_PARAMETERS = (
    "ParamEyeBallX",
    "ParamEyeBallY",
    "ParamEyeLOpen",
    "ParamEyeROpen",
    "ParamMouthOpenY",
    *HAIR_SWAY_PARAMETER_IDS,
    "ParamBodyAngleX",
)
HAIR_SWAY_PERIOD_SECONDS = 2.8
CLOTH_SWAY_PERIOD_SECONDS = 4.2
MAX_SWAY_FRAME_SECONDS = 0.1
SWAY_INTEGRATION_STEP_SECONDS = 1 / 60
CLOTH_SWAY_PHASE_OFFSET = math.pi / 2
LIVE2D_MASK_PADDING_RATIO = 0.03125
BLINK_CLOSE_SECONDS = 0.075
BLINK_HOLD_SECONDS = 0.025
BLINK_OPEN_SECONDS = 0.12
ARM_RAISE_VALUE = 30.0
ARM_RAISE_SECONDS = 0.45
ARM_HOLD_SECONDS = 0.7
# 只有在 CMO3 中建立并验收原生手臂关键形后才启用这项能力。
ARM_RAISE_BINDING_VERIFIED = False
PASSIVE = (
    Qt.WindowType.Tool
    | Qt.WindowType.FramelessWindowHint
    | Qt.WindowType.WindowStaysOnTopHint
    | Qt.WindowType.WindowDoesNotAcceptFocus
)


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


def _smoothstep(value):
    """动作关键阶段使用平滑插值，避免眨眼和抬手突然跳变。"""
    value = max(0.0, min(1.0, value))
    return value * value * (3.0 - 2.0 * value)


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
        tip, tip_velocity = _advance_spring_component(
            tip, tip_velocity, tip_target, substep, 12.0, 5.0
        )

    return HairSwayState(
        root=max(-1.0, min(1.0, root)),
        middle=max(-1.0, min(1.0, middle)),
        tip=max(-1.0, min(1.0, tip)),
        root_velocity=root_velocity,
        middle_velocity=middle_velocity,
        tip_velocity=tip_velocity,
    )


def _expand_mask_region(region, padding):
    """扩展 Live2D 点击区域，给模型移动后的抗锯齿发丝留出空间。"""
    padding = max(0, int(padding))
    if padding == 0 or region.isEmpty():
        return region

    horizontal = QRegion()
    for offset in range(-padding, padding + 1):
        horizontal = horizontal.united(region.translated(offset, 0))

    expanded = QRegion()
    for offset in range(-padding, padding + 1):
        expanded = expanded.united(horizontal.translated(0, offset))
    return expanded


class Bubble(QLabel):
    def __init__(self):
        super().__init__(None, PASSIVE | Qt.WindowType.WindowTransparentForInput)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setWordWrap(True)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setFixedWidth(280)
        self.setMargin(14)
        self.setStyleSheet(
            'QLabel { background: #fffdf6; color: #344239; border: 1px solid #ccd5c8; border-radius: 10px; font: 11pt "Microsoft YaHei UI"; }'
        )
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.hide)

    def present(self, text, pet):
        self.setText(text[:350])
        self.adjustSize()
        bounds = pet.screen().availableGeometry()
        x = max(bounds.left(), min(pet.x() + pet.width() - self.width(), bounds.right() - self.width() + 1))
        y = max(bounds.top(), pet.y() - self.height() - 12)
        self.move(x, y)
        self.show()
        self.timer.start(10000)


class Avatar(QOpenGLWidget):
    open_requested = Signal()
    motion_capabilities_changed = Signal(object)

    def __init__(self, size=160, image_id=""):
        super().__init__(None, PASSIVE)
        surface = QSurfaceFormat()
        surface.setRenderableType(QSurfaceFormat.RenderableType.OpenGL)
        # Cubism 渲染器使用 GLSL 1.20，因此请求兼容模式上下文。
        surface.setVersion(2, 1)
        surface.setAlphaBufferSize(8)
        surface.setDepthBufferSize(24)
        self.setFormat(surface)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.frames = {}
        self.image_id = image_id
        self.animation = "idle"
        self.frame = 0
        self.follow = False
        self.paused = False
        self._live2d_requested = not bool(image_id)
        self._live2d_active = False
        self._live2d_failed = False
        self._live2d_ready = False
        self._live2d_module = None
        self._live2d_model = None
        self._live2d_parameter_ids = frozenset()
        self._motion_capabilities = ()
        self._motion_name = None
        self._motion_started = None
        self._mouth_target = 0.0
        self._mouth_level = 0.0
        self._hair_sway_phase = 0.0
        self._cloth_sway_phase = 0.0
        self._hair_sway = HairSwayState()
        self._gaze_x = 0.0
        self._gaze_y = 0.0
        self._idle_blade_frames = ()
        self._idle_blade_mask = QRegion()
        self._idle_blade_started = None
        self._idle_blade_fade_out = None
        self._idle_blade_visible_pose = None
        self._idle_blade_visible_opacity = -1.0
        self._idle_blade_overlay = QLabel(self)
        self._idle_blade_overlay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._idle_blade_overlay.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._idle_blade_overlay.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._idle_blade_overlay.setStyleSheet("background: transparent; border: none;")
        self._idle_blade_effect = QGraphicsOpacityEffect(self._idle_blade_overlay)
        self._idle_blade_effect.setOpacity(0.0)
        self._idle_blade_overlay.setGraphicsEffect(self._idle_blade_effect)
        self._idle_blade_overlay.hide()
        self._last_render = time.monotonic()
        self.drag_start = None
        self.move_start = None
        self.last_follow_step = 0.0
        self.set_size(size)
        bounds = QGuiApplication.primaryScreen().availableGeometry()
        self.move(bounds.right() - self.width() - 32, bounds.bottom() - self.height() - 24)
        self.clock = QTimer(self)
        self.clock.setTimerType(Qt.TimerType.PreciseTimer)
        self.clock.setInterval(self.durations[self.frame % len(self.durations)])
        self.clock.timeout.connect(self._tick)
        self.clock.start()
        self.render_clock = QTimer(self)
        self.render_clock.setInterval(33)
        self.render_clock.timeout.connect(self.update)
        self.bubble = Bubble()
        self.setToolTip("点击打开对话 · 拖动调整位置")

    def set_size(self, size):
        if self.frames and self.height() == size:
            return
        self.interrupt_idle_blade(fade=False)
        self.frames, self.durations, self.native_animation = build_frames(size, self.image_id)
        self.setFixedSize(self.frames["idle"][0][0].size())
        self._idle_blade_overlay.setGeometry(self.rect())
        self._load_idle_blade_frames()
        self._shown_frame = None
        if self._live2d_active:
            self.setMask(self._live2d_window_mask())
        else:
            self._frame_mask()
        # 增大形象后仍完整留在当前工作区，不伸进任务栏或屏幕外。
        bounds = self.screen().availableGeometry()
        self.move(
            max(bounds.left(), min(self.x(), bounds.right() - self.width() + 1)),
            max(bounds.top(), min(self.y(), bounds.bottom() - self.height() + 1)),
        )

    def set_animation(self, name):
        if name != "idle":
            self.interrupt_idle_blade()
        if name == "sleep":
            self.cancel_motion()
        if name in self.frames and name != self.animation:
            self.animation = name
            if not self.native_animation:
                self.frame = 0
        if self._live2d_active:
            model = self._live2d_model
            if model is not None:
                sleeping = self.animation == "sleep"
                model.SetAutoBlinkEnable(not sleeping and self._motion_name != "blink")
                if sleeping:
                    model.SetParameterValue("ParamEyeLOpen", 0.0)
                    model.SetParameterValue("ParamEyeROpen", 0.0)
                elif self._motion_name != "blink":
                    model.SetParameterValue("ParamEyeLOpen", 1.0)
                    model.SetParameterValue("ParamEyeROpen", 1.0)
            self._mouth_target = 0.0
            self.update()
            return
        self._frame_mask()

    def set_image(self, identifier, force=False):
        if identifier == self.image_id and not force:
            return
        self.cancel_motion()
        self.interrupt_idle_blade(fade=False)
        # 先完整生成，再一次切换；保留位置、大小、动画状态和窗口焦点。
        frames, durations, native = build_frames(self.height(), identifier)
        self.image_id, self.frames, self.durations = identifier, frames, durations
        self.native_animation, self.frame = native, 0
        self._live2d_requested = not bool(identifier)
        self._load_idle_blade_frames()
        self._shown_frame = None
        if self._live2d_requested and self._live2d_ready:
            self.makeCurrent()
            try:
                self._ensure_live2d()
            finally:
                self.doneCurrent()
        self._live2d_active = self._live2d_requested and self._live2d_model is not None
        self._set_render_mode()
        self._frame_mask()

    def set_mouth_level(self, level):
        """接收当前语音包络值；跨线程信号会由 Qt 自动排入界面线程。"""
        self._mouth_target = min(1.0, max(0.0, float(level)))

    @property
    def available_motions(self):
        """仅向模型公布当前默认 Live2D 中已验证的原生动作。"""
        if not self._live2d_active or self._live2d_model is None:
            return ()
        actions = []
        if {"ParamEyeLOpen", "ParamEyeROpen"}.issubset(self._live2d_parameter_ids):
            actions.append("blink")
        if ARM_RAISE_BINDING_VERIFIED and "ParamArmRA" in self._live2d_parameter_ids:
            actions.append("raise_hand")
        return tuple(actions)

    def play_motion(self, motion):
        """在现有 Live2D 绘制帧上启动一次白名单动作。"""
        if motion not in self.available_motions:
            LOG.warning("忽略未绑定的玄司动作 action=%s", motion)
            return False
        self.cancel_motion()
        self._motion_name = motion
        self._motion_started = time.monotonic()
        if motion == "blink":
            self._live2d_model.SetAutoBlinkEnable(False)
        LOG.info("玄司动作开始 action=%s", motion)
        self.update()
        return True

    def cancel_motion(self):
        """取消动作并把参数恢复到中立值；休眠时继续保持闭眼。"""
        motion, self._motion_name = self._motion_name, None
        self._motion_started = None
        if motion is None:
            return False
        model = self._live2d_model
        if model is not None:
            if motion == "blink":
                if self.animation != "sleep":
                    model.SetParameterValue("ParamEyeLOpen", 1.0)
                    model.SetParameterValue("ParamEyeROpen", 1.0)
                model.SetAutoBlinkEnable(self.animation != "sleep")
            elif motion == "raise_hand" and "ParamArmRA" in self._live2d_parameter_ids:
                model.SetParameterValue("ParamArmRA", 0.0)
        LOG.info("玄司动作已中断 action=%s", motion)
        self.update()
        return True

    def _motion_parameter_values(self, now):
        """按单调时钟推进一次性动作；返回值由本帧 Live2D 参数写入。"""
        if self._motion_name is None or self._motion_started is None:
            return {}
        elapsed = max(0.0, now - self._motion_started)
        if self._motion_name == "blink":
            close_end = BLINK_CLOSE_SECONDS
            hold_end = close_end + BLINK_HOLD_SECONDS
            finish = hold_end + BLINK_OPEN_SECONDS
            if elapsed >= finish:
                self._motion_name = None
                self._motion_started = None
                self._live2d_model.SetAutoBlinkEnable(self.animation != "sleep")
                LOG.info("玄司动作结束 action=blink")
                eye_open = 1.0
            elif elapsed < close_end:
                eye_open = 1.0 - _smoothstep(elapsed / close_end)
            elif elapsed < hold_end:
                eye_open = 0.0
            else:
                eye_open = _smoothstep((elapsed - hold_end) / BLINK_OPEN_SECONDS)
            return {"ParamEyeLOpen": eye_open, "ParamEyeROpen": eye_open}

        if self._motion_name == "raise_hand":
            lower_start = ARM_RAISE_SECONDS + ARM_HOLD_SECONDS
            finish = lower_start + ARM_RAISE_SECONDS
            if elapsed >= finish:
                self._motion_name = None
                self._motion_started = None
                LOG.info("玄司动作结束 action=raise_hand")
                arm_value = 0.0
            elif elapsed < ARM_RAISE_SECONDS:
                arm_value = ARM_RAISE_VALUE * _smoothstep(elapsed / ARM_RAISE_SECONDS)
            elif elapsed < lower_start:
                arm_value = ARM_RAISE_VALUE
            else:
                arm_value = ARM_RAISE_VALUE * (
                    1.0 - _smoothstep((elapsed - lower_start) / ARM_RAISE_SECONDS)
                )
            return {"ParamArmRA": arm_value}
        return {}

    def initializeGL(self):
        self._live2d_ready = True
        if self._live2d_requested:
            self._ensure_live2d()
        self._live2d_active = self._live2d_requested and self._live2d_model is not None
        self._set_render_mode()
        if self.context() is not None:
            self.context().aboutToBeDestroyed.connect(self._release_live2d)

    def _ensure_live2d(self):
        if self._live2d_model is not None or self._live2d_failed:
            return
        try:
            if not LIVE2D_MODEL.is_file():
                raise FileNotFoundError(LIVE2D_MODEL)
            LOG.info("玄司 Live2D 渲染器初始化开始")
            import live2d.v3 as live2d

            SESSION.acquire(self, live2d)
            self._live2d_module = live2d
            model = self._live2d_model = live2d.LAppModel()
            LOG.info("Live2D 模型加载开始 file=%s", LIVE2D_MODEL.name)
            model.LoadModelJson(str(LIVE2D_MODEL))
            LOG.info("Live2D 模型文件已读取")
            parameter_ids = set(model.GetParamIds())
            missing = set(LIVE2D_PARAMETERS) - parameter_ids
            if missing:
                raise ValueError(f"模型缺少绑定参数：{', '.join(sorted(missing))}")
            model.SetAutoBlinkEnable(True)
            model.SetAutoBreathEnable(False)
            if self.animation == "sleep":
                model.SetAutoBlinkEnable(False)
                model.SetParameterValue("ParamEyeLOpen", 0.0)
                model.SetParameterValue("ParamEyeROpen", 0.0)
            self._live2d_module = live2d
            self._live2d_model = model
            self._live2d_parameter_ids = frozenset(parameter_ids)
            self._last_render = time.monotonic()
            LOG.info("玄司 Live2D 模型已加载 parameters=%s", len(parameter_ids))
            LOG.info("Live2D 视线跟随已启用：按桌宠所在屏幕范围平滑映射")
            LOG.info(
                "玄司发丝与衣摆独立摆动已启用 hair_period=%.1fs cloth_period=%.1fs integration_hz=60",
                HAIR_SWAY_PERIOD_SECONDS,
                CLOTH_SWAY_PERIOD_SECONDS,
            )
            padding = max(2, round(self.height() * LIVE2D_MASK_PADDING_RATIO))
            LOG.info("Live2D 发丝窗口边界缓冲已启用 padding=%dpx", padding)
        except Exception:
            self._live2d_failed = True
            self._release_live2d()
            LOG.exception("玄司 Live2D 加载失败，继续使用原 PNG 形象")

    def _set_render_mode(self):
        self._live2d_active = self._live2d_requested and self._live2d_model is not None
        if self._live2d_active:
            # 小幅扩展系统窗口点击蒙版，避免裁切摆动后移出原图轮廓的发丝。
            self.setMask(self._live2d_window_mask())
            if self.isVisible():
                self.render_clock.start()
        else:
            self.render_clock.stop()
            self._shown_frame = None
            self._frame_mask()
        self._refresh_motion_capabilities()
        self.update()
        LOG.info("桌宠绘制模式已同步 mode=%s", "Live2D" if self._live2d_active else "图片")

    def _refresh_motion_capabilities(self):
        actions = self.available_motions
        if actions == self._motion_capabilities:
            return
        self._motion_capabilities = actions
        self.motion_capabilities_changed.emit(actions)
        LOG.info("玄司原生动作能力已更新 actions=%s", ",".join(actions) or "无")

    def _live2d_window_mask(self):
        """按窗口高度扩展原图点击轮廓，避免高 DPI 或改尺寸后缓冲失衡。"""
        padding = max(2, round(self.height() * LIVE2D_MASK_PADDING_RATIO))
        return _expand_mask_region(self.frames["idle"][0][1], padding)

    def resizeGL(self, width, height):
        if self._live2d_model is not None:
            scale = self.devicePixelRatioF()
            self._live2d_model.Resize(round(width * scale), round(height * scale))

    def paintGL(self):
        if self._live2d_active and self._live2d_model is not None:
            live2d = self._live2d_module
            now = time.monotonic()
            elapsed = max(0.0, min(0.1, now - self._last_render))
            self._last_render = now
            overlay = self._idle_blade_visual(now)
            if overlay is not None:
                # 拔刀图包含完整角色；该帧只显示姿态图，避免底层模型透出形成重影。
                live2d.clearBuffer(0.0, 0.0, 0.0, 0.0)
                self._present_idle_blade(overlay)
                return
            self._update_gaze(elapsed)
            self._mouth_level += (self._mouth_target - self._mouth_level) * min(1.0, elapsed * 14.0)
            model = self._live2d_model
            if self.animation == "sleep":
                model.SetParameterValue("ParamEyeLOpen", 0.0)
                model.SetParameterValue("ParamEyeROpen", 0.0)
                model.SetParameterValue("ParamMouthOpenY", 0.0)
            else:
                model.SetParameterValue("ParamEyeBallX", self._gaze_x)
                model.SetParameterValue("ParamEyeBallY", self._gaze_y)
                model.SetParameterValue("ParamMouthOpenY", self._mouth_level)
            self._update_sway(elapsed)
            for parameter, value in self._motion_parameter_values(now).items():
                model.SetParameterValue(parameter, value)
            # 先设置当帧参数，再由 Cubism 计算网格变形并绘制。
            live2d.clearBuffer(0.0, 0.0, 0.0, 0.0)
            model.Update()
            model.Draw()
            self._present_idle_blade(None)
            return
        # Live2D 与 PNG 回退都由 QOpenGLWidget 的绘制流程显示。
        # Qt 不会替重写的 paintGL 清空缓冲；透明图片和透明动图帧必须先清除旧像素。
        functions = self.context().functions()
        functions.glClearColor(0.0, 0.0, 0.0, 0.0)
        functions.glClear(0x00004000)  # GL_COLOR_BUFFER_BIT，仅清当前窗口的颜色缓冲。
        painter = QPainter(self)
        painter.drawPixmap(0, 0, self._pixmap())

    @property
    def supports_idle_blade(self):
        """只有默认 Live2D 模型和完整透明动作帧才允许播放。"""
        return bool(self._live2d_active and self._live2d_model is not None and self._idle_blade_frames)

    def _load_idle_blade_frames(self):
        """按当前桌宠尺寸预缩放动作帧，避免空闲动画中途读盘或解码。"""
        if not self._live2d_requested:
            self._idle_blade_frames = ()
            self._idle_blade_mask = QRegion()
            return
        try:
            self._idle_blade_frames, self._idle_blade_mask = load_idle_blade_frames(self.width(), self.height())
            padding = max(2, round(self.height() * 0.01))
            self._idle_blade_mask = _expand_mask_region(self._idle_blade_mask, padding)
        except (OSError, ValueError):
            self._idle_blade_frames = ()
            self._idle_blade_mask = QRegion()
            LOG.exception("玄司久置拔刀素材不可用，已禁用该待机动作")

    def start_idle_blade(self):
        """进入一次透明关键帧演出；姿态显示期间暂停 Live2D 绘制。"""
        if not self.supports_idle_blade or self._idle_blade_started is not None:
            return False
        self._idle_blade_fade_out = None
        self._idle_blade_started = time.monotonic()
        self.setMask(self._idle_blade_mask)
        self.update()
        LOG.info("玄司久置待机拔刀动作开始")
        return True

    def interrupt_idle_blade(self, fade=True):
        """中断拔刀动作；用户仍在操作时短暂淡回实时 Live2D。"""
        if self._idle_blade_started is None:
            if not fade and self._idle_blade_fade_out is not None:
                self._idle_blade_fade_out = None
                if self._live2d_active:
                    self.setMask(self._live2d_window_mask())
                self._present_idle_blade(None)
            return

        now = time.monotonic()
        elapsed = now - self._idle_blade_started
        pose = idle_blade_pose(elapsed)
        opacity = idle_blade_opacity(elapsed)
        self._idle_blade_started = None
        if fade and pose is not None and opacity > 0.0:
            self._idle_blade_fade_out = (pose, opacity, now)
        else:
            self._idle_blade_fade_out = None
            if self._live2d_active:
                self.setMask(self._live2d_window_mask())
            self._present_idle_blade(None)
        LOG.info("玄司久置待机拔刀动作已中断")
        self.update()

    def _idle_blade_visual(self, now):
        """返回当前预缓存姿态和透明度；每帧不访问磁盘或输出日志。"""
        pose, opacity = None, 0.0
        if self._idle_blade_started is not None:
            elapsed = now - self._idle_blade_started
            pose = idle_blade_pose(elapsed)
            opacity = idle_blade_opacity(elapsed)
            if pose is None:
                self._idle_blade_started = None
                if self._live2d_active:
                    self.setMask(self._live2d_window_mask())
                LOG.info("玄司久置待机拔刀动作结束，Live2D 绘制已恢复")
        elif self._idle_blade_fade_out is not None:
            pose, initial_opacity, started = self._idle_blade_fade_out
            opacity = initial_opacity * max(0.0, 1.0 - (now - started) / IDLE_BLADE_FADE_SECONDS)
            if opacity <= 0.0:
                self._idle_blade_fade_out = None
                self.setMask(self._live2d_window_mask())
                return None

        if pose is None or opacity <= 0.0:
            return None
        return pose, opacity

    def _present_idle_blade(self, visual):
        """用透明子控件覆盖 GL 帧缓冲，避免在 Cubism 绘制后混用 OpenGL 状态。"""
        if visual is None:
            if not self._idle_blade_overlay.isHidden():
                self._idle_blade_overlay.hide()
            self._idle_blade_visible_pose = None
            self._idle_blade_visible_opacity = -1.0
            return

        pose, opacity = visual
        if pose != self._idle_blade_visible_pose:
            self._idle_blade_overlay.setPixmap(self._idle_blade_frames[pose])
            self._idle_blade_visible_pose = pose
        if abs(opacity - self._idle_blade_visible_opacity) >= 0.01:
            self._idle_blade_effect.setOpacity(opacity)
            self._idle_blade_visible_opacity = opacity
        if not self._idle_blade_overlay.isVisible():
            self._idle_blade_overlay.show()
            self._idle_blade_overlay.raise_()

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

    def _release_live2d(self):
        if self._live2d_module is None:
            return
        self.makeCurrent()
        try:
            if self._live2d_model is not None:
                self._live2d_model.DestroyRenderer()
            # 原生模型析构也会访问 Cubism，必须先在当前上下文中清掉模型引用。
            self._live2d_model = None
            SESSION.release(self)
            LOG.info("玄司 Live2D 渲染资源已释放")
        except Exception:
            LOG.exception("玄司 Live2D 渲染资源释放失败")
        finally:
            self.doneCurrent()
            self._live2d_model = None
            self._live2d_module = None
            self._live2d_active = False
            self._live2d_parameter_ids = frozenset()
            self._refresh_motion_capabilities()

    def _pixmap(self):
        frames = self.frames[self.animation]
        return frames[self.frame % len(frames)][0]

    def _frame_mask(self):
        # 原生窗口形状只覆盖非透明像素，外围矩形不会挡住下面的程序。
        if self._live2d_active:
            return
        key = "idle" if self.native_animation else self.animation, self.frame % len(self.durations)
        if key == self._shown_frame:
            return
        self._shown_frame = key
        region = self.frames[key[0]][key[1]][1]
        # 空区域在 Qt 表示“清除蒙版”；透明帧应使用窗外区域，不能挡住下层应用。
        self.setMask(region if not region.isEmpty() else QRegion(-1, -1, 1, 1))
        if hasattr(self, "clock"):
            self.clock.setInterval(self.durations[key[1]])
        self.update()

    def _tick(self):
        if not self.isVisible():
            return
        now = time.monotonic()
        if (
            self.follow
            and not self.paused
            and self.drag_start is None
            and now - self.last_follow_step >= 0.18
        ):
            self.last_follow_step = now
            target = QCursor.pos() + QPoint(70, 50)
            delta = target - self.pos()
            distance = math.hypot(delta.x(), delta.y())
            if distance > 130:
                screen = QGuiApplication.screenAt(QCursor.pos()) or self.screen()
                bounds = screen.availableGeometry()
                x = int(self.x() + delta.x() / distance * 18)
                y = int(self.y() + delta.y() / distance * 18)
                self.move(
                    max(bounds.left(), min(x, bounds.right() - self.width() + 1)),
                    max(bounds.top(), min(y, bounds.bottom() - self.height() + 1)),
                )
                self.animation = "walk_right" if delta.x() > 0 else "walk_left"
            elif self.animation.startswith("walk"):
                self.animation = "idle"
        if self._live2d_active:
            return
        self.frame += 1
        self._frame_mask()

    def showEvent(self, event):
        self.clock.start(self.durations[self.frame % len(self.durations)])
        if self._live2d_active:
            self.render_clock.start()
        super().showEvent(event)

    def hideEvent(self, event):
        self.interrupt_idle_blade(fade=False)
        self.cancel_motion()
        self.clock.stop()
        self.render_clock.stop()
        super().hideEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_start = event.globalPosition().toPoint()
            self.move_start = self.pos()

    def mouseMoveEvent(self, event):
        if self.drag_start is not None:
            self.move(self.move_start + event.globalPosition().toPoint() - self.drag_start)

    def mouseReleaseEvent(self, event):
        if self.drag_start is not None:
            moved = (event.globalPosition().toPoint() - self.drag_start).manhattanLength()
            self.drag_start = None
            if moved < 6:
                self.open_requested.emit()

    def contextMenuEvent(self, event):
        self.open_requested.emit()
