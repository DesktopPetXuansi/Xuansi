"""标签内容的独立滚动容器；切换页面时保留表单实例与滚动位置。"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QScrollArea, QVBoxLayout, QWidget


class ControlSection(QScrollArea):

    def __init__(self, key: str, title: str):
        super().__init__()
        self.key = key
        self.setWidgetResizable(True)
        self.body = QWidget()
        layout = QVBoxLayout(self.body)
        layout.setContentsMargins(20, 12, 20, 20)
        heading = QLabel(title)
        heading.setObjectName("sectionTitle")
        layout.addWidget(heading)
        self.content = QVBoxLayout()
        layout.addLayout(self.content)
        layout.addStretch()
        self.setWidget(self.body)

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
