"""标签内容的独立滚动容器；切换页面时保留表单实例与滚动位置。"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QScrollArea, QVBoxLayout, QWidget


class ControlSection(QScrollArea):

    def __init__(self, key: str, title: str):
        super().__init__()
        self.key = key
        self.setWidgetResizable(key != "chat")
        self.setFrameShape(QScrollArea.Shape.NoFrame)
        fill = key in ("chat", "persona", "memory", "logs")
        if key == "chat":
            # 输入区随页面布局保留，记录自己滚动；不滚动整个对话页。
            self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.body = QWidget()
        layout = QVBoxLayout(self.body)
        layout.setContentsMargins(20, 12, 20, 16)
        layout.setSpacing(12)
        heading = QLabel(title)
        heading.setObjectName("sectionTitle")
        layout.addWidget(heading)
        self.content = QVBoxLayout()
        layout.addLayout(self.content, 1 if fill else 0)
        if not fill:
            layout.addStretch()
        self.setWidget(self.body)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.key == "chat":
            # QScrollArea 会把含换行标签的建议高度当作下限；对话需固定到视口，
            # 由内部记录区伸缩，避免输入随整页滚到窗口之外。
            self.body.resize(self.viewport().size())

    @property
    def active(self):
        # Stack 只显式隐藏非当前页；主窗口收起不改变当前标签。
        return not self.isHidden()

    def set_widget(self, widget):
        while item := self.content.takeAt(0):
            previous = item.widget()
            if previous is not None and previous is not widget:
                previous.hide()
                previous.deleteLater()
        # QDialog 有 parent 仍可能是窗口，明确设置普通子控件标志。
        widget.setParent(self.body, Qt.WindowType.Widget)
        self.content.addWidget(widget)
        widget.show()
