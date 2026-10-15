"""统一控制中心：浏览器式标签导航，复用表单并沿用配置保存事务。"""

import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .config import Settings
from .control_navigation import ControlNavigation
from .panel_content import common_controls, populate_sections
from .panel_settings import PanelSettings
from .panel_style import STYLE
from .theme import configure_fonts

LOG = logging.getLogger(__name__)
SECTIONS = (
    ("chat", "对话"), ("persona", "人设与提示词"), ("memory", "长期记忆"),
    ("preferences", "语音与行为"), ("model", "模型与快捷键"), ("appearance", "桌宠形象"),
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

    def __init__(self, settings: Settings):
        super().__init__()
        configure_fonts(QApplication.instance())
        self.settings = settings
        self.setWindowTitle(f"{settings.name} · 控制中心")
        self.resize(880, 760)
        self.setMinimumSize(520, 480)
        self.setStyleSheet(STYLE)
        self._opening_callbacks = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.navigation = ControlNavigation(SECTIONS, self)
        self.sections = self.navigation.pages
        self.navigation.opening.connect(self._prepare)
        layout.addWidget(self.navigation.header)
        toolbar_widget = QWidget()
        toolbar = QVBoxLayout(toolbar_widget)
        toolbar.setContentsMargins(20, 12, 20, 8)
        brand = QHBoxLayout()
        self.title = QLabel(settings.name)
        self.title.setObjectName("productName")
        brand.addWidget(self.title)
        self.status = QLabel("已就绪 · 麦克风关闭")
        self.status.setObjectName("status")
        self.status.setWordWrap(True)
        brand.addWidget(self.status, 1)
        toolbar.addLayout(brand)
        toolbar.addLayout(common_controls(self))
        self.live_transcript = QLabel("")
        self.live_transcript.setTextFormat(Qt.TextFormat.PlainText)
        self.live_transcript.setWordWrap(True)
        self.live_transcript.setObjectName("hint")
        toolbar.addWidget(self.live_transcript)
        self.audio_status = QLabel("声音回避已开启")
        self.audio_status.setObjectName("hint")
        self.audio_status.setWordWrap(True)
        toolbar.addWidget(self.audio_status)
        layout.addWidget(toolbar_widget)
        layout.addWidget(self.navigation.stack, 1)
        populate_sections(self)
        self.form = PanelSettings(self)
        footer_widget = QWidget()
        footer = QVBoxLayout(footer_widget)
        footer.setContentsMargins(20, 8, 20, 12)
        footer.addWidget(self.form.hint)
        actions = QHBoxLayout()
        self.save_button = QPushButton("保存全部设置")
        self.save_button.setObjectName("primary")
        self.save_button.clicked.connect(self._save)
        actions.addWidget(self.save_button)
        close = QPushButton("收起控制中心")
        close.clicked.connect(self.close)
        actions.addWidget(close)
        footer.addLayout(actions)
        self.footer = QLabel("Ctrl+Tab 切换标签 · 快捷键和托盘均打开此控制中心")
        self.footer.setObjectName("hint")
        self.footer.setWordWrap(True)
        footer.addWidget(self.footer)
        layout.addWidget(footer_widget)
        self.escape = QShortcut(QKeySequence("Esc"), self)
        self.escape.activated.connect(self.close)

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
            self.navigation.select("chat")

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
