"""管理页配置草稿与关闭保存；保存完成前保留可恢复的表单。"""

import logging
from dataclasses import replace

from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QKeySequenceEdit,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QSpinBox,
)

LOG = logging.getLogger(__name__)


class PanelSettings:
    def __init__(self, panel):
        self.panel = panel
        self.saving = False
        self.closing = False
        self.hint = QLabel()
        self.hint.setObjectName("hint")
        self.hint.setWordWrap(True)
        changes = (
            (QLineEdit, "textChanged"), (QPlainTextEdit, "textChanged"),
            (QCheckBox, "toggled"), (QComboBox, "currentIndexChanged"),
            (QSpinBox, "valueChanged"), (QDoubleSpinBox, "valueChanged"),
            (QKeySequenceEdit, "keySequenceChanged"),
        )
        for page in (panel.persona, panel.preferences, panel.model_page):
            for widget_type, signal in changes:
                for widget in page.findChildren(widget_type):
                    getattr(widget, signal).connect(self.refresh)
        self.refresh()

    def read(self):
        return self.panel.model_page.apply(
            self.panel.preferences.apply(self.panel.persona.apply(self.panel.settings))
        ).validate()

    def changed(self):
        # Qt 会规范化快捷键修饰键顺序；等价组合不应被当成未保存修改。
        saved = replace(
            self.panel.settings,
            chat_hotkey=QKeySequence(self.panel.settings.chat_hotkey).toString(
                QKeySequence.SequenceFormat.PortableText
            ),
        )
        return self.read() != saved

    def refresh(self, *_):
        if self.saving:
            self.hint.setText("正在保存配置…")
            return
        try:
            changed = self.changed()
        except ValueError:
            changed = True
        self.hint.setText(
            "有未保存的配置修改 · 关闭时保存，并结束对话、关闭麦克风"
            if changed else "配置已保存 · 关闭窗口时自动保存修改"
        )

    def request(self):
        if self.saving:
            return
        try:
            settings = self.read()
        except ValueError as exc:
            self.complete(str(exc))
            return
        self.panel.settings_requested.emit(settings)

    def complete(self, error):
        closing, self.closing = self.closing, False
        self.saving = False
        if error:
            self.hint.setText("配置未保存：" + error)
            self.panel.status.setText(error)
            LOG.warning("管理页配置保存未完成，保留草稿")
            return
        self.refresh()
        if closing:
            try:
                if not self.changed():
                    self.panel.hide()
                    LOG.info("管理页配置保存完成，窗口已收起")
            except ValueError:
                pass  # 保存期间继续编辑的无效草稿留在窗口中。

    def close(self):
        self.closing = True
        if self.saving:
            return
        try:
            if not self.changed():
                self.closing = False
                self.panel.hide()
                LOG.info("管理页已收起，配置无变化")
                return
        except ValueError as exc:
            self.complete(str(exc))
            return
        LOG.info("管理页关闭前保存配置")
        self.request()
