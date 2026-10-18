"""控制中心的对话、记忆和常用操作布局；行为通过原有信号交给运行时。"""

from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .log_viewer import LogViewer
from .model_page import ModelPage
from .panel_style import STYLE
from .preferences import PersonaPage, PreferencesPage


def chat_content(panel):
    page = QWidget()
    layout = QVBoxLayout(page)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)
    panel.chat = QPlainTextEdit()
    panel.chat.setReadOnly(True)
    panel.chat.setMinimumHeight(64)
    panel.chat.setAccessibleName("对话记录")
    panel.chat.setMaximumBlockCount(250)
    panel.chat.setPlaceholderText("聊点什么，或者开启连续对话。\n想让我长期记住什么，可以明确告诉我。")
    # 只让记录区滚动并使用剩余高度，输入不会随外层内容移出视口。
    layout.addWidget(panel.chat, 1)
    layout.addWidget(panel.live_transcript)
    panel.with_screen = QCheckBox("这次对话附上屏幕画面")
    layout.addWidget(panel.with_screen)
    controls = QHBoxLayout()
    controls.setSpacing(8)
    for button in (panel.look_button, panel.speech_button, panel.audio_avoidance_button):
        controls.addWidget(button)
    controls.addStretch()
    controls.addWidget(panel.stop_button)
    layout.addLayout(controls)
    layout.addWidget(panel.audio_status)
    row = QHBoxLayout()
    panel.input = QLineEdit()
    panel.input.setMaxLength(2000)
    panel.input.setAccessibleName("对话输入")
    panel.input.setPlaceholderText("和我说句话，回车发送…")
    panel.input.returnPressed.connect(panel._send)
    row.addWidget(panel.input, 1)
    send = QPushButton("发送")
    send.setObjectName("primary")
    send.clicked.connect(panel._send)
    row.addWidget(send)
    layout.addLayout(row)
    tab_order = (panel.chat, panel.with_screen, panel.look_button, panel.speech_button,
                 panel.audio_avoidance_button, panel.stop_button, panel.input, send)
    for previous, following in zip(tab_order, tab_order[1:]):
        QWidget.setTabOrder(previous, following)
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
    panel.memory.setAccessibleName("长期记忆内容")
    panel.memory.setPlaceholderText("称呼、偏好、重要事项…\n不要填写密码、密钥和证件信息。")
    layout.addWidget(panel.memory, 1)
    row = QHBoxLayout()
    save = QPushButton("保存记忆")
    save.clicked.connect(lambda: panel.memory_requested.emit(panel.memory.toPlainText()))
    row.addWidget(save)
    clear = QPushButton("清空记忆")
    clear.setObjectName("danger")
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
        field.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
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
