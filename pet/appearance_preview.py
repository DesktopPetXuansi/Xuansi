"""形象选择器内的播放预览；与桌宠共用帧生成，隐藏即停止。"""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget

from .character_frames import build_frames


class AppearancePreview(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(238)
        self.frames, self.durations, self.native = build_frames(224)
        self.index = 0
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.timeout.connect(self.advance)

    def set_image(self, identifier):
        self.frames, self.durations, self.native = build_frames(224, identifier)
        self.index = 0
        self.update()
        self.timer.setInterval(self.durations[0])
        if self.isVisible():
            self.timer.start()

    def advance(self):
        self.index = (self.index + 1) % len(self.durations)
        self.timer.setInterval(self.durations[self.index])
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        # 浅、深两块底色方便辨认透明区域，底色不会写入图片。
        painter.fillRect(0, 0, self.width() // 2, self.height(), QColor("#efeee8"))
        painter.fillRect(self.width() // 2, 0, self.width(), self.height(), QColor("#35413d"))
        frame = self.frames["idle"][self.index][0]
        painter.drawPixmap((self.width() - frame.width()) // 2, 7, frame)

    def showEvent(self, event):
        self.timer.start(self.durations[self.index])
        super().showEvent(event)

    def hideEvent(self, event):
        self.timer.stop()
        super().hideEvent(event)
