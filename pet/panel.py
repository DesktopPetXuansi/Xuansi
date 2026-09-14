"""原生控制面板：聊天、人设、长期记忆、偏好；只因明确点击而显示。"""

from PySide6.QtCore import Signal
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenuBar,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .config import Settings
from .log_viewer import LogViewer
from .model_page import ModelPage
from .preferences import PersonaPage, PreferencesPage
from .theme import configure_fonts

STYLE = """
QWidget { background: #f7f8f3; color: #293d33; font: 10pt "Microsoft YaHei UI"; }
QLabel#title { font-size: 20pt; font-weight: 600; }
QLabel#hint { color: #68766c; font-size: 9pt; }
QLabel#status { background: #e7efe5; padding: 9px; border-radius: 6px; }
QTabWidget::pane { border: 0; padding-top: 10px; }
QTabBar::tab { padding: 9px 17px; background: transparent; border-bottom: 2px solid transparent; }
QTabBar::tab:selected { border-bottom: 2px solid #497758; color: #32543d; }
QPushButton { background: #e8ede3; border: 1px solid #c7d3c3; border-radius: 5px; padding: 8px 12px; }
QPushButton:hover { background: #dae6d6; }
QPushButton:checked, QPushButton#primary { background: #496e54; color: white; border-color: #496e54; }
QLineEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox { background: #ffffff; border: 1px solid #cbd5c8; border-radius: 4px; padding: 6px; selection-background-color: #709078; }
QLineEdit:focus, QPlainTextEdit:focus { border-color: #577b61; }
QCheckBox { spacing: 8px; padding: 4px 0; }
QCheckBox::indicator { width: 14px; height: 14px; border: 1px solid #8eaa93; border-radius: 3px; background: white; }
QCheckBox::indicator:checked { background: #497758; border: 2px solid #2f543a; }
QScrollArea { border: 0; }
"""


class Panel(QWidget):
    send_requested = Signal(str, bool)
    voice_requested = Signal(bool)
    look_requested = Signal()
    sleep_requested = Signal()
    settings_requested = Signal(object)
    memory_requested = Signal(str)
    preview_requested = Signal(object)
    message_added = Signal(str, str)
    appearance_requested = Signal()

    def __init__(self, settings: Settings):
        super().__init__()
        from PySide6.QtWidgets import QApplication

        configure_fonts(QApplication.instance())
        self.settings = settings
        self.setWindowTitle(f"{settings.name} · 本地 AI 桌宠")
        self.resize(510, 670)
        self.setMinimumSize(460, 550)
        self.setStyleSheet(STYLE)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 18)
        bar = QMenuBar(self)
        configuration = bar.addMenu("配置")
        configuration.addAction("模型参数与快捷键", self.open_configuration)
        configuration.addAction("人设与系统提示词", lambda: self.tabs.setCurrentIndex(1))
        configuration.addAction("语音与行为", lambda: self.tabs.setCurrentIndex(3))
        configuration.addSeparator()
        self.audio_avoidance_action = configuration.addAction("声音回避（其他软件发声时静音）")
        self.audio_avoidance_action.setCheckable(True)
        self.audio_avoidance_action.setChecked(settings.audio_avoidance)
        self.audio_avoidance_action.setToolTip("开启时避让其他软件声音；关闭时允许同时播放。自动保存。")
        bar.addMenu("日志").addAction("运行日志", self.open_logs)
        bar.addMenu("形象").addAction("更换桌宠形象…", self.appearance_requested.emit)
        layout.setMenuBar(bar)
        self.title = QLabel(settings.name)
        self.title.setObjectName("title")
        layout.addWidget(self.title)
        subtitle = QLabel("在你身边，在这台电脑上。")
        subtitle.setObjectName("hint")
        layout.addWidget(subtitle)
        self.status = QLabel("已就绪 · 麦克风关闭")
        self.status.setObjectName("status")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        self._chat_page()
        self.persona = PersonaPage(settings)
        self.persona.save_requested.connect(self._save)
        self.tabs.addTab(self.persona, "人设")
        self._memory_page()
        self.preferences = PreferencesPage(settings)
        self.preferences.save_requested.connect(self._save)
        self.preferences.preview_requested.connect(self._preview)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.preferences)
        self.tabs.addTab(scroll, "偏好")
        self.model_page = ModelPage(settings)
        self.model_page.save_requested.connect(self._save)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.model_page)
        self.tabs.addTab(scroll, "配置")
        self.logs = LogViewer(STYLE)
        self.logs.setWindowTitle(f"{settings.name} · 运行日志")
        self.audio_status = QLabel("声音回避已开启")
        self.audio_status.setObjectName("hint")
        layout.addWidget(self.audio_status)
        self.footer = QLabel("仅本机处理 · 双击托盘也能打开面板")
        self.footer.setObjectName("hint")
        layout.addWidget(self.footer)

    def _chat_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 4, 0, 0)
        self.chat = QPlainTextEdit()
        self.chat.setReadOnly(True)
        self.chat.setPlaceholderText(
            "聊点什么，或者开启连续对话。\n\n想让我长期记住什么，可以说：\n“记住，我喜欢简短的回答。”"
        )
        self.chat.setMaximumBlockCount(250)
        layout.addWidget(self.chat)
        self.with_screen = QCheckBox("这次对话附上屏幕画面")
        layout.addWidget(self.with_screen)
        row = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setMaxLength(2000)
        self.input.setPlaceholderText("和我说句话…")
        self.input.returnPressed.connect(self._send)
        row.addWidget(self.input)
        send = QPushButton("发送")
        send.setObjectName("primary")
        send.clicked.connect(self._send)
        row.addWidget(send)
        layout.addLayout(row)
        row = QHBoxLayout()
        self.voice_button = QPushButton("开启连续对话")
        self.voice_button.setCheckable(True)
        self.voice_button.toggled.connect(self.voice_requested)
        row.addWidget(self.voice_button)
        look = QPushButton("看一眼")
        look.clicked.connect(self.look_requested)
        row.addWidget(look)
        self.sleep_button = QPushButton("休眠")
        self.sleep_button.clicked.connect(self.sleep_requested)
        row.addWidget(self.sleep_button)
        layout.addLayout(row)
        self.tabs.addTab(page, "聊天")

    def _memory_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        explanation = QLabel(
            "长期记忆保存在本机，重启后仍在。\n只记录你明确说“记住”的内容，或下面手动填写的事项。"
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        self.memory = QPlainTextEdit()
        self.memory.setPlaceholderText("称呼、偏好、重要事项…\n不要填写密码、密钥和证件信息。")
        layout.addWidget(self.memory)
        row = QHBoxLayout()
        save = QPushButton("保存记忆")
        save.clicked.connect(lambda: self.memory_requested.emit(self.memory.toPlainText()))
        row.addWidget(save)
        clear = QPushButton("清空记忆")
        clear.clicked.connect(self._clear_memory)
        row.addWidget(clear)
        layout.addLayout(row)
        self.tabs.addTab(page, "记忆")

    def _clear_memory(self):
        self.memory.clear()
        self.memory_requested.emit("")

    def _send(self):
        text = self.input.text().strip()
        if text:
            self.input.clear()
            self.send_requested.emit(text, self.with_screen.isChecked())

    def append(self, speaker: str, text: str):
        # 纯文本显示，模型不能把回复变成 HTML、链接动作或脚本。
        self.chat.appendPlainText(f"{speaker}\n{text}\n")
        self.chat.moveCursor(QTextCursor.MoveOperation.End)
        self.message_added.emit(speaker, text)

    def voice_state(self, enabled):
        self.voice_button.blockSignals(True)
        self.voice_button.setChecked(enabled)
        self.voice_button.setText("关闭连续对话" if enabled else "开启连续对话")
        self.voice_button.blockSignals(False)

    def _save(self):
        try:
            settings = self.model_page.apply(
                self.preferences.apply(self.persona.apply(self.settings))
            ).validate()
            self.settings_requested.emit(settings)
        except ValueError as exc:
            self.status.setText(str(exc))

    def _preview(self):
        try:
            settings = self.preferences.apply(self.persona.apply(self.settings)).validate()
            self.preview_requested.emit(settings)
        except ValueError as exc:
            self.status.setText(str(exc))

    def open_configuration(self):
        self.tabs.setCurrentIndex(4)
        self.show()
        self.raise_()
        self.activateWindow()

    def open_logs(self):
        self.logs.show()
        self.logs.raise_()
        self.logs.activateWindow()

    def saving(self, enabled):
        for button in (self.persona.save_button, self.preferences.save_button, self.model_page.save_button):
            button.setEnabled(not enabled)

    def closeEvent(self, event):
        self.hide()
        event.ignore()
