"""设置页共用的原生表单分组；窄窗换行，标签始终关联输入控件。"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFormLayout, QGroupBox, QLabel, QVBoxLayout, QWidget


def form_group(layout: QVBoxLayout, title: str):
    group = QGroupBox(title)
    form = QFormLayout(group)
    # 允许较长标签与字段换行，避免小窗口出现整页横向滚动。
    form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
    form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
    form.setFormAlignment(Qt.AlignmentFlag.AlignTop)
    form.setContentsMargins(12, 16, 12, 12)
    form.setHorizontalSpacing(16)
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
