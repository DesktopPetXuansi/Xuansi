"""用户主动唤出的右下角对话窗口；Esc 隐藏，共享主面板对话。"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCursor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class QuickChat(QWidget):
    send_requested = Signal(str, bool)
    voice_requested = Signal(bool)
    stop_requested = Signal()
    speech_requested = Signal(bool)

    def __init__(self, settings, style):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowTitle(f"{settings.name} · 快捷对话")
        self.setStyleSheet(style)
        self.resize(410, 400)
        layout = QVBoxLayout(self)
        self.status = QLabel("随时聊两句 · Esc 收起")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.live_transcript = QLabel("")
        self.live_transcript.setTextFormat(Qt.TextFormat.PlainText)
        self.live_transcript.setWordWrap(True)
        self.live_transcript.setObjectName("hint")
        layout.addWidget(self.live_transcript)
        self.chat = QPlainTextEdit()
        self.chat.setReadOnly(True)
        self.chat.setMaximumBlockCount(150)
        self.chat.setPlaceholderText("和主面板共用人设、对话和本地记忆。")
        layout.addWidget(self.chat)
        self.with_screen = QCheckBox("附上屏幕画面")
        layout.addWidget(self.with_screen)
        row = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText("直接输入，回车发送…")
        self.input.setMaxLength(2000)
        self.input.returnPressed.connect(self.send)
        row.addWidget(self.input)
        button = QPushButton("发送")
        button.setObjectName("primary")
        button.clicked.connect(self.send)
        row.addWidget(button)
        layout.addLayout(row)
        self.voice = QPushButton("开启连续对话")
        self.voice.setCheckable(True)
        self.voice.toggled.connect(self.voice_requested)
        controls = QHBoxLayout()
        controls.addWidget(self.voice)
        self.stop_button = QPushButton("停止回复")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop_requested)
        controls.addWidget(self.stop_button)
        layout.addLayout(controls)
        self.audio_status = QLabel("声音回避已开启")
        self.audio_status.setObjectName("hint")
        self.audio_status.setWordWrap(True)
        audio_row = QHBoxLayout()
        audio_row.addWidget(self.audio_status, 1)
        self.speech_button = QPushButton("朗读开启")
        self.speech_button.setCheckable(True)
        self.speech_button.setToolTip("直接开启或关闭朗读，不改变麦克风状态。")
        self.speech_button.toggled.connect(self.speech_requested)
        audio_row.addWidget(self.speech_button)
        layout.addLayout(audio_row)
        self.escape = QShortcut(QKeySequence("Esc"), self)
        self.escape.activated.connect(self.hide)

    def append(self, speaker, text):
        self.chat.appendPlainText(f"{speaker}\n{text}\n")
        bar = self.chat.verticalScrollBar()
        bar.setValue(bar.maximum())

    def send(self):
        text = self.input.text().strip()
        if text:
            self.input.clear()
            self.send_requested.emit(text, self.with_screen.isChecked())

    def voice_state(self, enabled, paused=False):
        self.voice.blockSignals(True)
        self.voice.setChecked(enabled)
        self.voice.setText(
            "连续对话已暂停" if enabled and paused else "关闭连续对话" if enabled else "开启连续对话"
        )
        self.voice.setToolTip("休眠期间暂停收音，唤醒后恢复；点击可取消恢复。" if enabled and paused else "")
        self.voice.blockSignals(False)

    def toggle(self):
        if self.isVisible() and self.isActiveWindow():
            self.hide()
            return
        screen = QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
        self.show()
        # 使用可用工作区与窗口外框，适配任务栏、多显示器及不同 DPI。
        area = screen.availableGeometry()
        frame = self.frameGeometry()
        self.move(
            max(area.left(), area.right() - frame.width() - 15),
            max(area.top(), area.bottom() - frame.height() - 15),
        )
        self.raise_()
        self.activateWindow()
        self.input.setFocus()

    def closeEvent(self, event):
        self.hide()
        event.ignore()
