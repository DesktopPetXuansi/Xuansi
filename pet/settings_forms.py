"""设置页共用的原生表单；参数折叠保留控件和草稿，窄窗标签可换行。"""

import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFormLayout, QGroupBox, QLabel, QToolButton, QVBoxLayout, QWidget

LOG = logging.getLogger(__name__)


class AdvancedSettings(QWidget):
    """仅隐藏参数子容器，不触发整个模型页的隐藏与取消逻辑。"""

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.toggle = QToolButton()
        self.toggle.setText("高级设置")
        self.toggle.setObjectName("advancedSettings")
        self.toggle.setCheckable(True)
        self.toggle.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.toggle.setAccessibleDescription("展开模型参数；已有设置会保留。")
        layout.addWidget(self.toggle, alignment=Qt.AlignmentFlag.AlignLeft)
        self.content = QWidget()
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(12)
        self.content.hide()
        layout.addWidget(self.content)
        self.toggle.toggled.connect(self._expand)

    def _expand(self, expanded):
        self.content.setVisible(expanded)
        self.toggle.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
        self.toggle.setAccessibleDescription("收起模型参数；已有设置会保留。" if expanded
                                            else "展开模型参数；已有设置会保留。")
        LOG.debug("高级设置显示已切换 expanded=%s", expanded)


def form_group(layout: QVBoxLayout, title: str):
    group = QGroupBox(title)
    form = QFormLayout(group)
    # 允许较长标签与字段换行，避免小窗口出现整页横向滚动。
    form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
    form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
    form.setFormAlignment(Qt.AlignmentFlag.AlignTop)
    form.setContentsMargins(12, 12, 12, 8)
    form.setHorizontalSpacing(12)
    form.setVerticalSpacing(8)
    layout.addWidget(group)
    return form


def field_row(form: QFormLayout, title: str, field: QWidget):
    label = QLabel(title)
    label.setBuddy(field)
    field.setAccessibleName(title)
    form.addRow(label, field)


def form_hint(form: QFormLayout, text: str):
    label = QLabel(text)
    label.setWordWrap(True)
    label.setObjectName("hint")
    form.addRow(label)
    return label
