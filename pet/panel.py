"""同页控制中心：分区展开、统一保存，只因用户明确操作而显示。"""

import logging

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLayout,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .config import Settings
from .control_section import ControlSection
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
        self.sections = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        self.title = QLabel(settings.name)
        self.title.setObjectName("title")
        layout.addWidget(self.title)
        self.status = QLabel("已就绪 · 麦克风关闭")
        self.status.setObjectName("status")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        layout.addLayout(common_controls(self))
        self.live_transcript = QLabel("")
        self.live_transcript.setTextFormat(Qt.TextFormat.PlainText)
        self.live_transcript.setWordWrap(True)
        self.live_transcript.setObjectName("hint")
        layout.addWidget(self.live_transcript)
        self.audio_status = QLabel("声音回避已开启")
        self.audio_status.setObjectName("hint")
        self.audio_status.setWordWrap(True)
        layout.addWidget(self.audio_status)
        navigation = QHBoxLayout()
        navigation.addWidget(QLabel("定位分区"))
        self.navigation = QComboBox()
        for key, title in SECTIONS:
            self.navigation.addItem(title, key)
        self.navigation.activated.connect(lambda index: self.open_section(self.navigation.itemData(index)))
        navigation.addWidget(self.navigation, 1)
        layout.addLayout(navigation)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        body = QWidget()
        content = QVBoxLayout(body)
        content.setContentsMargins(0, 0, 10, 0)
        content.setSpacing(10)
        content.setSizeConstraint(QLayout.SizeConstraint.SetMinAndMaxSize)
        for key, title in SECTIONS:
            section = ControlSection(key, title)
            section.opening.connect(lambda key=key: self._prepare(key))
            self.sections[key] = section
            content.addWidget(section)
        content.addStretch()
        self.scroll.setWidget(body)
        layout.addWidget(self.scroll, 1)
        populate_sections(self)
        self.form = PanelSettings(self)
        layout.addWidget(self.form.hint)
        actions = QHBoxLayout()
        self.save_button = QPushButton("保存全部设置")
        self.save_button.setObjectName("primary")
        self.save_button.clicked.connect(self._save)
        actions.addWidget(self.save_button)
        close = QPushButton("收起控制中心")
        close.clicked.connect(self.close)
        actions.addWidget(close)
        layout.addLayout(actions)
        self.footer = QLabel("仅本机处理 · 快捷键和托盘均打开此控制中心")
        self.footer.setObjectName("hint")
        self.footer.setWordWrap(True)
        layout.addWidget(self.footer)
        self.escape = QShortcut(QKeySequence("Esc"), self)
        self.escape.activated.connect(self.close)
        self.sections["chat"].set_expanded(True)

    def mount_section(self, key, widget, on_open=None):
        self._opening_callbacks[key] = on_open
        self.sections[key].set_widget(widget)

    def _prepare(self, key):
        callback = self._opening_callbacks.get(key)
        if callback is not None:
            callback()

    def open_section(self, key):
        self.show()
        self.sections[key].set_expanded(True)
        self.navigation.setCurrentIndex(self.navigation.findData(key))
        self.raise_()
        self.activateWindow()
        # 等布局完成后定位标题；展开多个分区也不会切走或重建原表单。
        QTimer.singleShot(0, lambda: self.sections[key].scroll_into_view(self.scroll))
        LOG.info("控制中心定位分区 key=%s", key)

    def collapse_section(self, key):
        self.sections[key].set_expanded(False)

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
        for key, section in self.sections.items():
            if section.expanded:
                self._prepare(key)

    def closeEvent(self, event):
        event.ignore()
        self.form.close()
