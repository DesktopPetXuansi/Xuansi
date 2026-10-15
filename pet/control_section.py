"""同一滚动页内的可展开分区；隐藏内容复用现有控件与业务状态。"""

import logging

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtWidgets import QFrame, QSizePolicy, QToolButton, QVBoxLayout, QWidget

LOG = logging.getLogger(__name__)


class ControlSection(QFrame):
    opening = Signal()

    def __init__(self, key: str, title: str):
        super().__init__()
        self.key = key
        self.expanded = False
        self.setObjectName("controlSection")
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.heading = QToolButton()
        self.heading.setText(title)
        self.heading.setObjectName("sectionHeader")
        self.heading.setCheckable(True)
        self.heading.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.heading.setArrowType(Qt.ArrowType.RightArrow)
        self.heading.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.heading.toggled.connect(self.set_expanded)
        layout.addWidget(self.heading)
        self.body = QWidget()
        self.content = QVBoxLayout(self.body)
        self.content.setContentsMargins(14, 4, 14, 14)
        self.body.hide()
        layout.addWidget(self.body)

    def set_widget(self, widget):
        while item := self.content.takeAt(0):
            previous = item.widget()
            if previous is not None and previous is not widget:
                previous.hide()
                previous.deleteLater()
        # QDialog 即使有 parent 仍可能是窗口，明确清除其窗口属性。
        widget.setParent(self.body, Qt.WindowType.Widget)
        self.content.addWidget(widget)
        widget.show()

    def set_expanded(self, expanded):
        if expanded == self.expanded:
            return
        self.expanded = expanded
        self.heading.blockSignals(True)
        self.heading.setChecked(expanded)
        self.heading.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
        self.heading.blockSignals(False)
        if expanded:
            # 预览等控件先恢复内容，再收到由分区展开传播的 showEvent。
            self.opening.emit()
        self.body.setVisible(expanded)
        LOG.debug("控制中心分区 key=%s expanded=%s", self.key, expanded)

    def scroll_into_view(self, scroll):
        # 直接对齐分区顶部；只保证标题可见会把表单留在视口之外。
        top = self.heading.mapTo(scroll.widget(), QPoint()).y()
        scroll.verticalScrollBar().setValue(top)
