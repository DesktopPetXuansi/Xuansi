"""控制中心的对话、记忆和常用操作布局；行为通过原有信号交给运行时。"""

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .first_chat_card import FirstChatCard
from .log_viewer import LogViewer
from .model_page import ModelPage
from .preferences import PersonaPage, PreferencesPage
from .update_page import UpdatePage


def chat_content(panel):
    page = QWidget()
    layout = QVBoxLayout(page)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(7)
    panel.first_chat = FirstChatCard()
    layout.addWidget(panel.first_chat)
    panel.chat = QPlainTextEdit()
    panel.chat.setObjectName("conversationHistory")
    panel.chat.setReadOnly(True)
    panel.chat.setMinimumHeight(64)
    panel.chat.setAccessibleName("对话记录")
    panel.chat.setMaximumBlockCount(250)
    panel.chat.setPlaceholderText("先发一句话，语音和形象可以稍后设置。\n想让我长期记住什么，可以明确告诉我。")
    # 只让记录区滚动并使用剩余高度，输入不会随外层内容移出视口。
    layout.addWidget(panel.chat, 1)
    layout.addWidget(panel.live_transcript)
    sharing = QHBoxLayout()
    panel.screen_enabled = QCheckBox("允许按轮分享屏幕")
    panel.screen_enabled.setChecked(panel.settings.screen_mode == "manual")
    panel.screen_enabled.toggled.connect(
        lambda enabled: panel.screen_mode_requested.emit("manual" if enabled else "off")
    )
    panel.with_screen = QCheckBox("给下一条文字或语音附图")
    sharing.addWidget(panel.screen_enabled)
    sharing.addWidget(panel.with_screen)
    sharing.addStretch()
    layout.addLayout(sharing)
    panel.automatic_observation = QCheckBox("本次运行允许本机自动观察")
    panel.automatic_observation.setToolTip("鼠标活动时按需观察，仅使用本机视觉模型。重启后关闭。")
    panel.automatic_observation.toggled.connect(panel.automatic_observation_requested)
    automatic = QHBoxLayout()
    automatic.addWidget(panel.automatic_observation)
    automatic.addStretch()
    automatic.setContentsMargins(0, 0, 0, 0)
    layout.addLayout(automatic)
    panel.screen_status = QLabel()
    panel.screen_status.setWordWrap(True)
    panel.screen_status.hide()
    panel.screen_warning = QLabel()
    panel.screen_warning.setWordWrap(True)
    panel.screen_warning.hide()
    layout.addWidget(panel.screen_status)
    layout.addWidget(panel.screen_warning)
    panel.screen_mode(panel.settings.screen_mode)
    controls = QHBoxLayout()
    controls.setSpacing(8)
    for button in (panel.look_button, panel.speech_button, panel.audio_avoidance_button):
        controls.addWidget(button)
    controls.addStretch()
    controls.addWidget(panel.stop_button)
    layout.addLayout(controls)
    quiet = QPushButton("主动消息静默")
    menu = QMenu(quiet)
    menu.addAction("这次先安静（1 小时）", lambda: panel.quiet_requested.emit(False))
    menu.addAction("今天安静", lambda: panel.quiet_requested.emit(True))
    quiet.setMenu(menu)
    quiet.setMaximumHeight(28)
    automatic.addWidget(quiet)
    layout.addWidget(panel.audio_status)
    row = QHBoxLayout()
    panel.input = QLineEdit()
    panel.input.setObjectName("messageComposer")
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
    tab_order = (panel.chat, panel.screen_enabled, panel.with_screen, panel.automatic_observation, quiet,
                 panel.look_button, panel.speech_button,
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
    panel.memory_entries = panel._memory_draft_base = ()
    panel._submitted_memory = None
    panel.memory_items = QComboBox()
    panel.memory_items.addItem("选择要更正的记忆", None)
    panel.memory_items.setAccessibleName("选择记忆条目")
    panel.memory_items.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    layout.addWidget(panel.memory_items)
    panel.memory_correction = QLineEdit()
    panel.memory_correction.setPlaceholderText("输入所选条目的新内容")
    panel.memory_correction.setAccessibleName("记忆更正内容")
    panel.memory_items.currentIndexChanged.connect(panel.memory_correction.clear)
    layout.addWidget(panel.memory_correction)
    actions = QHBoxLayout()
    for action, label in (("edit", "更正"), ("undo", "撤销更正"), ("forget", "彻底遗忘")):
        button = QPushButton(label)
        button.clicked.connect(lambda _checked, action=action: panel._memory_action(action))
        actions.addWidget(button)
    layout.addLayout(actions)
    panel.memory = QPlainTextEdit()
    panel.memory.setMinimumHeight(150)
    panel.memory.setAccessibleName("长期记忆内容")
    panel.memory.setPlaceholderText("称呼、偏好、重要事项…\n不要填写密码、密钥和证件信息。")
    layout.addWidget(panel.memory, 1)
    row = QHBoxLayout()
    save = QPushButton("保存记忆")
    save.clicked.connect(panel._save_memory_draft)
    row.addWidget(save)
    reload = QPushButton("重载已保存记忆")
    reload.clicked.connect(panel._reload_memory_draft)
    row.addWidget(reload)
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
    panel.update_page = UpdatePage(panel)
    panel.mount_section("updates", panel.update_page)
    panel.logs = LogViewer("")
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
