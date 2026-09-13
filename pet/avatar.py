"""复用 NekoAI 动画定义的原生桌宠；自动展示永不取得输入焦点。"""

import json
import logging
import math

from PySide6.QtCore import QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QGuiApplication, QPainter, QPixmap
from PySide6.QtWidgets import QLabel, QWidget

from .config import ROOT

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

    def __init__(self, size=96):
        super().__init__(None, PASSIVE)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.definition = json.loads((ROOT / "assets/neko/pet.json").read_text(encoding="utf-8"))
        self.sprites = {
            path.name: QPixmap(str(path)) for path in (ROOT / "assets/neko/sprites").glob("*.png")
        }
        self.animation = "idle"
        self.frame = 0
        self.follow = False
        self.paused = False
        self.drag_start = None
        self.move_start = None
        self.status_color = QColor("#73937c")
        self.set_size(size)
        bounds = QGuiApplication.primaryScreen().availableGeometry()
        self.move(bounds.right() - size - 32, bounds.bottom() - size - 24)
        self.clock = QTimer(self)
        self.clock.setInterval(180)
        self.clock.timeout.connect(self._tick)
        self.clock.start()
        self.bubble = Bubble()
        self.setToolTip("点击打开对话 · 拖动调整位置")

    def set_size(self, size):
        self.setFixedSize(size, size)
        self._frame_mask()

    def set_animation(self, name):
        if name in self.definition["animations"] and name != self.animation:
            self.animation, self.frame = name, 0
        self._frame_mask()

    def _pixmap(self):
        frames = self.definition["animations"][self.animation]["files"]
        original = self.sprites.get(frames[self.frame % len(frames)], self.sprites["awake.png"])
        return original.scaled(
            self.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.FastTransformation
        )

    def _frame_mask(self):
        # 原生窗口形状只覆盖非透明像素，外围矩形不会挡住下面的程序。
        self.setMask(self._pixmap().mask())
        self.update()

    def _tick(self):
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
