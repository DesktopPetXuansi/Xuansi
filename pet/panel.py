"""统一控制中心：浏览器式标签导航，复用表单并沿用配置保存事务。"""

import logging
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QVBoxLayout,
    QWidget,
)

from .config import Settings
from .control_navigation import ControlNavigation
from .panel_chrome import create_footer, create_header
from .panel_content import populate_sections
from .panel_settings import PanelSettings
from .panel_style import STYLE
from .panel_window import restore_size, save_size
from .theme import configure_fonts

LOG = logging.getLogger(__name__)
SECTIONS = (
    ("chat", "对话"), ("persona", "人设与提示词"), ("memory", "长期记忆"),
    ("preferences", "语音与行为"), ("model", "模型与快捷键"), ("appearance", "更换形象"),
    ("resources", "官网资源"), ("upload", "上传本地 Live2D"), ("logs", "运行日志"),
)


class Panel(QWidget):
    send_requested = Signal(str, bool)
    voice_requested = Signal(bool)
    look_requested = Signal()
    sleep_requested = Signal()
    settings_requested = Signal(object)
    memory_requested = Signal(str)
    preview_requested = Signal(object)
    upload_requested = Signal()
    stop_requested = Signal()
    speech_requested = Signal(bool)
    feedback_requested = Signal()

    def __init__(self, settings: Settings, *, window_state_path: Path | None = None):
        super().__init__()
        configure_fonts(QApplication.instance())
        self.settings = settings
        self.setWindowTitle(f"{settings.name} · 控制中心")
        self.window_state_path = window_state_path
        self.setMinimumSize(520, 480)
        restore_size(self, window_state_path)
        self.setStyleSheet(STYLE)
        self._opening_callbacks = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.navigation = ControlNavigation(SECTIONS, self)
        self.sections = self.navigation.pages
        self.navigation.opening.connect(self._prepare)
        layout.addWidget(self.navigation.header)
        layout.addWidget(create_header(self))
        layout.addWidget(self.navigation.stack, 1)
        populate_sections(self)
        self.form = PanelSettings(self)
        layout.addWidget(create_footer(self))
        self.escape = QShortcut(QKeySequence("Esc"), self)
        self.escape.activated.connect(self.close)
        LOG.info("控制中心布局已就绪，七个主标签与九个固定页面沿用原保存事务")

    def mount_section(self, key, widget, on_open=None):
        self._opening_callbacks[key] = on_open
        self.sections[key].set_widget(widget)

    def _prepare(self, key):
        callback = self._opening_callbacks.get(key)
        if self.isVisible() and callback is not None:
            callback()

    def open_section(self, key):
        self.navigation.select(key)
        self.show()
        self.raise_()
        self.activateWindow()
        LOG.info("打开控制中心标签 key=%s", key)

    def collapse_section(self, key):
        # 内嵌表单的返回/关闭只离开当前标签，退出时不能重新显示主窗口。
        if self.navigation.current_key == key and key != "chat":
            self.navigation.select('appearance' if key in ('resources', 'upload') else 'chat')

    def open_configuration(self):
        self.open_section("model")

    def open_logs(self):
        self.open_section("logs")

    def toggle(self):
        if self.isVisible() and self.isActiveWindow():
            self.close()
        else:
            self.open_section("chat")
            self.input.setFocus(Qt.FocusReason.ShortcutFocusReason)

    def _clear_memory(self):
        self.memory.clear()
        self.memory_requested.emit("")

    def _send(self):
        text = self.input.text().strip()
        if text:
            self.input.clear()
            self.send_requested.emit(text, self.with_screen.isChecked())

    def append(self, speaker: str, text: str):
        self.chat.appendPlainText(f"{speaker}\n{text}\n")
        self.chat.moveCursor(QTextCursor.MoveOperation.End)

    def voice_state(self, enabled, paused=False):
        self.voice_button.blockSignals(True)
        self.voice_button.setChecked(enabled)
        self.voice_button.setText("连续对话已暂停" if enabled and paused else "关闭连续对话" if enabled else "开启连续对话")
        self.voice_button.setToolTip("休眠期间暂停收音，唤醒后恢复；点击可取消恢复。" if enabled and paused else "")
        self.voice_button.blockSignals(False)

    def _save(self):
        self.form.request()

    def _preview(self):
        try:
            self.preview_requested.emit(self.preferences.apply(self.persona.apply(self.settings)).validate())
        except ValueError as exc:
            self.status.setText(str(exc))

    def saving(self, enabled):
        self.form.saving = enabled
        self.form.refresh()
        for button in (self.save_button, self.persona.save_button, self.preferences.save_button, self.model_page.save_button):
            button.setEnabled(not enabled)

    def showEvent(self, event):
        super().showEvent(event)
        self._prepare(self.navigation.current_key)

    def closeEvent(self, event):
        event.ignore()
        self.form.close()

    def hideEvent(self, event):
        super().hideEvent(event)
        # 配置保存完成、直接收起和退出统一走这里；忽略系统最小化的临时隐藏。
        if not event.spontaneous():
            save_size(self, self.window_state_path)
