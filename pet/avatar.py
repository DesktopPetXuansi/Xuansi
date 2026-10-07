"""玄司原生桌宠的窗口交互与模块组合；自动展示永不取得输入焦点。"""

import math
import time

from PySide6.QtCore import QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QCursor, QGuiApplication, QSurfaceFormat
from PySide6.QtOpenGLWidgets import QOpenGLWidget

# 兼容既有模块导入；常量与算法只在对应职责模块定义一次。
from .avatar_bubble import PASSIVE as PASSIVE
from .avatar_bubble import Bubble as Bubble
from .avatar_dynamics import CLOTH_SWAY_PERIOD_SECONDS as CLOTH_SWAY_PERIOD_SECONDS
from .avatar_dynamics import CLOTH_SWAY_PHASE_OFFSET as CLOTH_SWAY_PHASE_OFFSET
from .avatar_dynamics import HAIR_SWAY_PARAMETER_IDS as HAIR_SWAY_PARAMETER_IDS
from .avatar_dynamics import HAIR_SWAY_PERIOD_SECONDS as HAIR_SWAY_PERIOD_SECONDS
from .avatar_dynamics import MAX_SWAY_FRAME_SECONDS as MAX_SWAY_FRAME_SECONDS
from .avatar_dynamics import SWAY_INTEGRATION_STEP_SECONDS as SWAY_INTEGRATION_STEP_SECONDS
from .avatar_dynamics import AvatarDynamics
from .avatar_dynamics import HairSwayState as HairSwayState
from .avatar_dynamics import _advance_hair_sway as _advance_hair_sway
from .avatar_dynamics import _advance_spring_component as _advance_spring_component
from .avatar_dynamics import _advance_sway_phase as _advance_sway_phase
from .avatar_dynamics import _cloth_sway_parameter as _cloth_sway_parameter
from .avatar_dynamics import _gaze_axis as _gaze_axis
from .avatar_dynamics import _hair_wind_force as _hair_wind_force
from .avatar_idle_blade import AvatarIdleBlade
from .avatar_live2d import LIVE2D_MODEL as LIVE2D_MODEL
from .avatar_live2d import LIVE2D_PARAMETERS as LIVE2D_PARAMETERS
from .avatar_live2d import LOG as LOG
from .avatar_live2d import AvatarLive2D
from .avatar_mask import LIVE2D_MASK_PADDING_RATIO as LIVE2D_MASK_PADDING_RATIO
from .avatar_mask import AvatarMask
from .avatar_mask import _expand_mask_region as _expand_mask_region
from .avatar_motion import ARM_HOLD_SECONDS as ARM_HOLD_SECONDS
from .avatar_motion import ARM_RAISE_BINDING_VERIFIED as ARM_RAISE_BINDING_VERIFIED
from .avatar_motion import ARM_RAISE_SECONDS as ARM_RAISE_SECONDS
from .avatar_motion import ARM_RAISE_VALUE as ARM_RAISE_VALUE
from .avatar_motion import BLINK_CLOSE_SECONDS as BLINK_CLOSE_SECONDS
from .avatar_motion import BLINK_HOLD_SECONDS as BLINK_HOLD_SECONDS
from .avatar_motion import BLINK_OPEN_SECONDS as BLINK_OPEN_SECONDS
from .avatar_motion import AvatarMotion
from .avatar_motion import _smoothstep as _smoothstep
from .character_frames import build_frames
from .idle_blade_animation import IDLE_BLADE_FADE_SECONDS as IDLE_BLADE_FADE_SECONDS
from .idle_blade_animation import idle_blade_opacity as idle_blade_opacity
from .idle_blade_animation import idle_blade_pose as idle_blade_pose
from .idle_blade_animation import load_idle_blade_frames as load_idle_blade_frames
from .live2d_session import SESSION as SESSION


class Avatar(AvatarLive2D, AvatarIdleBlade, AvatarMotion, AvatarMask, AvatarDynamics, QOpenGLWidget):
    open_requested = Signal()
    motion_capabilities_changed = Signal(object)

    def __init__(self, size=160, image_id="", *, parent=None):
        super().__init__(parent, PASSIVE if parent is None else Qt.WindowType.Widget)
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
        self._init_live2d_state(image_id)
        self._init_motion_state()
        self._init_parameter_state()
        self._init_idle_blade_state()
        self._last_render = time.monotonic()
        self.drag_start = None
        self.move_start = None
        self.last_follow_step = 0.0
        self.set_size(size)
        if parent is None:
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
        self.bubble = Bubble() if parent is None else None
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
        if self.isWindow():
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

    def initializeGL(self):
        """保留 Qt 虚函数与 PreviewAvatar 的继承覆写入口。"""
        super().initializeGL()

    def resizeGL(self, width, height):
        super().resizeGL(width, height)

    def paintGL(self):
        """绘制由 Live2D 模块推进，预览仍可在 super() 后补背景。"""
        super().paintGL()
