"""不抢焦点的桌面气泡与桌面窗口样式，保留原显示时长和布局。"""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QLabel

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
