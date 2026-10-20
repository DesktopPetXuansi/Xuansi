"""轻量反馈窗口：明确提交、可选版本预览、关闭或失败保留草稿。"""

import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .feedback import CATEGORIES, FeedbackDraft, diagnostic_text
from .panel_style import STYLE

LOG = logging.getLogger(__name__)


def add_field(layout, title, field):
    label = QLabel(title)
    label.setBuddy(field)
    field.setAccessibleName(title)
    layout.addWidget(label)
    layout.addWidget(field)


class FeedbackDialog(QDialog):
    submit_requested = Signal(object)
    diagnostics_requested = Signal()
    copy_requested = Signal(str)
    connection_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("反馈中心")
        self.setModal(False)
        self.setMinimumSize(440, 480)
        self.resize(520, 580)
        self.setStyleSheet(STYLE)
        self._diagnostics = None
        self._diagnostic_pending = False
        self._busy = False
        self._received = False
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.scroll = QScrollArea()
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setWidgetResizable(True)
        content = QWidget()
        form = QVBoxLayout(content)
        form.setContentsMargins(16, 14, 16, 10)
        form.setSpacing(6)
        intro = QLabel("无需 GitHub 账户，即可在这里反馈。提交后，标题、具体说明及你勾选的版本和系统信息"
                       "会公开至 GitHub 的 DesktopPetXuansi/Xuansi，任何人都能查看。"
                       "联系方式仅私有保存，不会公开。请勿在标题和说明中填写个人信息、密码或 API 密钥。")
        intro.setWordWrap(True)
        form.addWidget(intro)
        self.category = QComboBox()
        for key, label in CATEGORIES.items():
            self.category.addItem(label, key)
        add_field(form, "反馈类型", self.category)
        self.title_input = QLineEdit()
        self.title_input.setMaxLength(80)
        self.title_input.setPlaceholderText("用一句话概括")
        add_field(form, "标题", self.title_input)
        self.description = QPlainTextEdit()
        self.description.setMinimumHeight(120)
        self.description.setPlaceholderText("刚才做了什么？遇到了什么问题？\n如果是建议，说说你希望怎样使用。\n请勿填写密码或 API 密钥。")
        add_field(form, "具体说明", self.description)
        self.contact = QLineEdit()
        self.contact.setMaxLength(160)
        self.contact.setPlaceholderText("邮箱或其他联系方式，方便进一步了解问题")
        add_field(form, "联系方式（选填）", self.contact)
        diagnostic_row = QHBoxLayout()
        self.include_diagnostics = QCheckBox("附上版本和系统信息")
        self.include_diagnostics.toggled.connect(self._include_changed)
        diagnostic_row.addWidget(self.include_diagnostics)
        self.preview_button = QToolButton()
        self.preview_button.setText("查看")
        self.preview_button.setCheckable(True)
        self.preview_button.toggled.connect(self._preview_changed)
        diagnostic_row.addWidget(self.preview_button)
        diagnostic_row.addStretch()
        form.addLayout(diagnostic_row)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setAccessibleName("将附带的版本和系统信息")
        self.preview.setFixedHeight(100)
        form.addWidget(self.preview)
        # 许可不预选；较长公开范围由可换行说明承载，保证小窗口可读。
        self.public_consent = QCheckBox("我同意公开这条反馈")
        self.public_consent.setAccessibleName("我同意将这条反馈公开至 GitHub")
        form.addWidget(self.public_consent)
        consent_hint = QLabel("公开内容：标题、具体说明及勾选的版本和系统信息。联系方式不公开。")
        consent_hint.setWordWrap(True)
        consent_hint.setObjectName("hint")
        form.addWidget(consent_hint)
        self.destination = QLabel()
        self.destination.setTextFormat(Qt.TextFormat.PlainText)
        self.destination.setWordWrap(True)
        self.destination.setObjectName("hint")
        form.addWidget(self.destination)
        self.status = QLabel()
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        self.status.setAccessibleName("反馈提交结果")
        self.status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        form.addWidget(self.status)
        self.connection_button = QPushButton("检查官网连接")
        self.connection_button.clicked.connect(self.connection_requested)
        self.connection_button.hide()
        form.addWidget(self.connection_button)
        self.scroll.setWidget(content)
        outer.addWidget(self.scroll, 1)
        footer = QHBoxLayout()
        footer.setContentsMargins(16, 8, 16, 12)
        self.copy_button = QPushButton("复制内容")
        self.copy_button.clicked.connect(self._copy)
        footer.addWidget(self.copy_button)
        footer.addStretch()
        close = QPushButton("关闭")
        close.clicked.connect(self.close)
        footer.addWidget(close)
        self.submit_button = QPushButton("提交反馈")
        self.submit_button.setObjectName("primary")
        self.submit_button.clicked.connect(self._submit)
        footer.addWidget(self.submit_button)
        outer.addLayout(footer)
        # 输入回车不会意外发出反馈；文本框可正常换行，提交始终是明确操作。
        for button in self.findChildren(QPushButton):
            button.setAutoDefault(False)
        self._refresh()

    def draft(self):
        return FeedbackDraft(self.category.currentData(), self.title_input.text(), self.description.toPlainText(),
                             self.contact.text(), self._diagnostics if self.include_diagnostics.isChecked() else None,
                             public_consent=self.public_consent.isChecked())

    def _submit(self):
        if self._busy:
            return
        if self._received:
            self._received = False
            self.title_input.clear()
            self.description.clear()
            self.contact.clear()
            self.include_diagnostics.setChecked(False)
            self.public_consent.setChecked(False)
            self.status.clear()
            self._refresh()
            self.title_input.setFocus()
            return
        try:
            draft = self.draft()
            draft.payload()
        except ValueError as exc:
            self.failed(str(exc))
            return
        if not draft.public_consent:
            self.status.setText("请先勾选“我同意公开这条反馈”，确认后再提交。")
            self.connection_button.hide()
            self.public_consent.setFocus()
            LOG.info("反馈尚未提交：用户未确认公开范围")
            return
        self.status.clear()
        self.connection_button.hide()
        self.set_busy(True)
        self.submit_requested.emit(draft)

    def _copy(self):
        try:
            self.copy_requested.emit(self.draft().copy_text())
        except ValueError as exc:
            self.status.setText(str(exc))

    def _include_changed(self, checked):
        if checked and self._diagnostics is None and not self._diagnostic_pending:
            self._diagnostic_pending = True
            self.diagnostics_requested.emit()
        if not checked:
            self.preview_button.setChecked(False)
        self._refresh()

    def _preview_changed(self, checked):
        self.preview.setVisible(checked and self.include_diagnostics.isChecked())

    def set_diagnostics(self, values):
        self._diagnostic_pending = False
        self._diagnostics = dict(values)
        self.preview.setPlainText(diagnostic_text(values))
        self._refresh()

    def diagnostics_failed(self):
        self._diagnostic_pending = False
        self.status.setText("暂时无法整理版本信息，可取消勾选后提交。")
        self._refresh()

    def set_busy(self, enabled):
        self._busy = enabled
        self._refresh()

    def failed(self, message):
        self.status.setText(message)
        self.set_busy(False)
        self.connection_button.show()

    def received(self, receipt):
        self._received = True
        self.status.setText(f"已收到你的反馈。编号：{receipt.id}\n内容已保留供你复制；需要时可以再写一条。")
        self.set_busy(False)
        self.connection_button.hide()
        LOG.info("反馈窗口已显示服务端收据")

    def _refresh(self):
        editable = not self._busy and not self._received
        for field in (self.category, self.title_input, self.description, self.contact,
                      self.include_diagnostics, self.public_consent):
            field.setEnabled(editable)
        opted_in = self.include_diagnostics.isChecked()
        self.preview_button.setVisible(opted_in)
        self.preview_button.setEnabled(self._diagnostics is not None)
        self.preview.setVisible(opted_in and self.preview_button.isChecked())
        self.submit_button.setEnabled(not self._busy and (self._received or not opted_in or self._diagnostics is not None))
        self.submit_button.setText("正在提交…" if self._busy else "再写一条" if self._received else "提交反馈")
        self.copy_button.setEnabled(not self._busy)
