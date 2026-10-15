"""控制中心的对话、记忆和常用操作布局；行为通过原有信号交给运行时。"""

from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QCheckBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .log_viewer import LogViewer
from .model_page import ModelPage
from .panel_style import STYLE
from .preferences import PersonaPage, PreferencesPage


def common_controls(panel):
    grid = QGridLayout()
    panel.voice_button = QPushButton("开启连续对话")
    panel.voice_button.setCheckable(True)
    panel.voice_button.toggled.connect(panel.voice_requested)
    panel.speech_button = QPushButton("朗读开启")
    panel.speech_button.setCheckable(True)
    panel.speech_button.setToolTip("直接开启或关闭朗读，不改变麦克风状态。")
    panel.speech_button.toggled.connect(panel.speech_requested)
    look = QPushButton("看一眼屏幕")
    look.clicked.connect(panel.look_requested)
    panel.sleep_button = QPushButton("休眠")
    panel.sleep_button.clicked.connect(panel.sleep_requested)
    panel.stop_button = QPushButton("停止回复")
    panel.stop_button.setEnabled(False)
    panel.stop_button.setToolTip("停止本轮生成和播放，已开启的麦克风会继续聆听。")
    panel.stop_button.clicked.connect(panel.stop_requested)
    panel.audio_avoidance_action = QAction("声音回避", panel)
    panel.audio_avoidance_action.setCheckable(True)
    panel.audio_avoidance_action.setChecked(panel.settings.audio_avoidance)
    panel.audio_avoidance_action.setToolTip("其他软件发声时暂停朗读；自动保存并立即生效。")
    panel.audio_avoidance_button = QToolButton()
    panel.audio_avoidance_button.setObjectName("avoidance")
    panel.audio_avoidance_button.setDefaultAction(panel.audio_avoidance_action)
    buttons = (panel.voice_button, panel.speech_button, look, panel.sleep_button,
               panel.stop_button, panel.audio_avoidance_button)
    for index, button in enumerate(buttons):
        grid.addWidget(button, index // 3, index % 3)
    for column in range(3):
        grid.setColumnStretch(column, 1)
    return grid


def chat_content(panel):
    page = QWidget()
    layout = QVBoxLayout(page)
    layout.setContentsMargins(0, 0, 0, 0)
    panel.chat = QPlainTextEdit()
    panel.chat.setReadOnly(True)
    panel.chat.setMinimumHeight(200)
    panel.chat.setMaximumHeight(340)
    panel.chat.setMaximumBlockCount(250)
    panel.chat.setPlaceholderText("聊点什么，或者开启连续对话。\n想让我长期记住什么，可以明确告诉我。")
    layout.addWidget(panel.chat)
    panel.with_screen = QCheckBox("这次对话附上屏幕画面")
    layout.addWidget(panel.with_screen)
    row = QHBoxLayout()
    panel.input = QLineEdit()
    panel.input.setMaxLength(2000)
    panel.input.setPlaceholderText("和我说句话，回车发送…")
    panel.input.returnPressed.connect(panel._send)
    row.addWidget(panel.input)
    send = QPushButton("发送")
    send.setObjectName("primary")
    send.clicked.connect(panel._send)
    row.addWidget(send)
    layout.addLayout(row)
    return page


def memory_content(panel):
    page = QWidget()
    layout = QVBoxLayout(page)
    layout.setContentsMargins(0, 0, 0, 0)
    explanation = QLabel("长期记忆保存在本机，重启后仍在。明确要求才会保存；也可在下面手动编辑。")
    explanation.setWordWrap(True)
    layout.addWidget(explanation)
    panel.memory = QPlainTextEdit()
    panel.memory.setMinimumHeight(150)
    panel.memory.setMaximumHeight(240)
    panel.memory.setPlaceholderText("称呼、偏好、重要事项…\n不要填写密码、密钥和证件信息。")
    layout.addWidget(panel.memory)
    row = QHBoxLayout()
    save = QPushButton("保存记忆")
    save.clicked.connect(lambda: panel.memory_requested.emit(panel.memory.toPlainText()))
    row.addWidget(save)
    clear = QPushButton("清空记忆")
    clear.clicked.connect(panel._clear_memory)
    row.addWidget(clear)
    layout.addLayout(row)
    return page


def populate_sections(panel):
    """组装既有表单；配置只保留统一保存入口，校验和数据草稿沿用原组件。"""
    panel.mount_section("chat", chat_content(panel))
    panel.persona = PersonaPage(panel.settings)
    for field in (panel.persona.persona, panel.persona.prompt):
        field.setMinimumHeight(90)
        field.setMaximumHeight(140)
    panel.preferences = PreferencesPage(panel.settings)
    panel.preferences.preview_requested.connect(panel._preview)
    panel.model_page = ModelPage(panel.settings)
    for key, widget in (("persona", panel.persona), ("preferences", panel.preferences), ("model", panel.model_page)):
        widget.save_requested.connect(panel._save)
        widget.save_button.hide()
        panel.mount_section(key, widget)
    panel.mount_section("memory", memory_content(panel))
    panel.logs = LogViewer(STYLE)
    panel.logs.content.setMinimumHeight(220)
    panel.logs.content.setMaximumHeight(340)
    panel.mount_section("logs", panel.logs)
    for key in ("appearance", "resources"):
        note = QLabel("本地形象与官网资源将在此分区管理。")
        note.setWordWrap(True)
        panel.mount_section(key, note)
    upload = QWidget()
    layout = QVBoxLayout(upload)
    note = QLabel("选择本地模型，在本页完成官网连接、上传和入库。")
    note.setWordWrap(True)
    layout.addWidget(note)
    button = QPushButton("选择并上传本地模型")
    button.clicked.connect(panel.upload_requested)
    layout.addWidget(button)
    panel.mount_section("upload", upload)
