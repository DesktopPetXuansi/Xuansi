"""玄司原生桌宠；自动展示永不取得输入焦点。"""

import logging
import math
import time

from PySide6.QtCore import QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QCursor, QGuiApplication, QPainter, QRegion
from PySide6.QtWidgets import QLabel, QWidget

from .character_frames import build_frames

LOG = logging.getLogger(__name__)
PASSIVE = (
    Qt.WindowType.Tool
    | Qt.WindowType.FramelessWindowHint
    | Qt.WindowType.WindowStaysOnTopHint
    | Qt.WindowType.WindowDoesNotAcceptFocus
)


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


class Avatar(QWidget):
    open_requested = Signal()

    def __init__(self, size=160, image_id=""):
        super().__init__(None, PASSIVE)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.frames = {}
        self.image_id = image_id
        self.animation = "idle"
        self.frame = 0
        self.follow = False
        self.paused = False
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
        self.bubble = Bubble()
        self.setToolTip("点击打开对话 · 拖动调整位置")

    def set_size(self, size):
        if self.frames and self.height() == size:
            return
        self.frames, self.durations, self.native_animation = build_frames(size, self.image_id)
        self.setFixedSize(self.frames["idle"][0][0].size())
        self._shown_frame = None
        self._frame_mask()
        # 增大形象后仍完整留在当前工作区，不伸进任务栏或屏幕外。
        bounds = self.screen().availableGeometry()
        self.move(
            max(bounds.left(), min(self.x(), bounds.right() - self.width() + 1)),
            max(bounds.top(), min(self.y(), bounds.bottom() - self.height() + 1)),
        )

    def set_animation(self, name):
        if name in self.frames and name != self.animation:
            self.animation = name
            if not self.native_animation:
                self.frame = 0
        self._frame_mask()

    def set_image(self, identifier, force=False):
        if identifier == self.image_id and not force:
            return
        # 先完整生成，再一次切换；保留位置、大小、动画状态和窗口焦点。
        frames, durations, native = build_frames(self.height(), identifier)
        self.image_id, self.frames, self.durations = identifier, frames, durations
        self.native_animation, self.frame = native, 0
        self._shown_frame = None
        self._frame_mask()

    def _pixmap(self):
        frames = self.frames[self.animation]
        return frames[self.frame % len(frames)][0]

    def _frame_mask(self):
        # 原生窗口形状只覆盖非透明像素，外围矩形不会挡住下面的程序。
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
        self.frame += 1
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
        self._frame_mask()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.drawPixmap(0, 0, self._pixmap())

    def showEvent(self, event):
        self.clock.start(self.durations[self.frame % len(self.durations)])
        super().showEvent(event)

    def hideEvent(self, event):
        self.clock.stop()
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
