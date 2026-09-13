"""玄司原生桌宠；自动展示永不取得输入焦点。"""

import logging
import math

from PySide6.QtCore import QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QCursor, QGuiApplication, QPainter
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

    def __init__(self, size=160):
        super().__init__(None, PASSIVE)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.frames = {}
        self.animation = "idle"
        self.frame = 0
        self.follow = False
        self.paused = False
        self.drag_start = None
        self.move_start = None
        self.set_size(size)
        bounds = QGuiApplication.primaryScreen().availableGeometry()
        self.move(bounds.right() - self.width() - 32, bounds.bottom() - self.height() - 24)
        self.clock = QTimer(self)
        self.clock.setInterval(180)
        self.clock.timeout.connect(self._tick)
        self.clock.start()
        self.bubble = Bubble()
        self.setToolTip("点击打开对话 · 拖动调整位置")

    def set_size(self, size):
        if self.frames and self.height() == size:
            return
        self.frames = build_frames(size)
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
            self.animation, self.frame = name, 0
        self._frame_mask()

    def _pixmap(self):
        frames = self.frames[self.animation]
        return frames[self.frame % len(frames)][0]

    def _frame_mask(self):
        # 原生窗口形状只覆盖非透明像素，外围矩形不会挡住下面的程序。
        key = self.animation, self.frame % len(self.frames[self.animation])
        if key == self._shown_frame:
            return
        self._shown_frame = key
        self.setMask(self.frames[key[0]][key[1]][1])
        self.update()

    def _tick(self):
        if not self.isVisible():
            return
        self.frame += 1
        if self.follow and not self.paused and self.drag_start is None:
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
