"""对话页内可收起的使用检查；沿用桌面主题，不另建设置或聊天入口。"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QToolButton, QVBoxLayout, QWidget


class FirstChatCard(QFrame):
    action_requested = Signal(str)
    example_requested = Signal()

    def __init__(self):
        super().__init__()
        self.completed = False
        self.setObjectName('firstChatCard')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 4, 10, 8)
        layout.setSpacing(4)
        self.toggle = QToolButton()
        self.toggle.setObjectName('advancedSettings')
        self.toggle.setText('开始使用 · 先聊上第一句')
        self.toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle.setCheckable(True)
        self.toggle.setAccessibleName('展开或收起使用检查')
        header = QHBoxLayout()
        header.setSpacing(6)
        header.addWidget(self.toggle)
        self.body = QWidget()
        self.body.setObjectName('firstChatBody')
        body = QVBoxLayout(self.body)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(6)
        self.note = QLabel()
        self.note.setTextFormat(Qt.TextFormat.PlainText)
        self.note.setWordWrap(True)
        self.note.setObjectName('hint')
        self.note.setMinimumWidth(0)
        body.addWidget(self.note)
        self.action = QPushButton('模型设置')
        self.action_key = 'model'
        self.action.clicked.connect(lambda: self.action_requested.emit(self.action_key))
        self.example = QPushButton('填入一句问候')
        self.example.setToolTip('仅填入输入框，点击发送后才会请求模型；保留已有草稿。')
        self.example.clicked.connect(self.example_requested)
        header.addStretch()
        header.addWidget(self.action)
        header.addWidget(self.example)
        layout.addLayout(header)
        layout.addWidget(self.body)
        self.toggle.toggled.connect(self._expanded)
        self._expanded(False)
        self.hide()  # 后台完成首次状态读取后才展示，不阻塞主窗口创建。

    def _expanded(self, expanded):
        # 展开时短标题为恢复操作留宽度；完成后收起仍明确展示结果。
        title = ('使用检查' if self.completed else '先聊上第一句') if expanded else (
            '文字对话已完成 · 使用检查' if self.completed else '开始使用 · 先聊上第一句'
        )
        self.toggle.setText(title)
        self.body.setVisible(expanded)
        self.action.setVisible(expanded)
        self.example.setVisible(expanded)
        self.toggle.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)

    def set_note(self, text, *, action='model', label='模型设置'):
        self.note.setText(text)
        # 长错误最多预览三行；完整说明留在提示与辅助描述，发送区保持可见。
        self.note.setMaximumHeight(self.note.fontMetrics().lineSpacing() * 3)
        self.note.setToolTip(text)
        self.note.setAccessibleDescription(text)
        self.action_key = action
        self.action.setText(label)

    def complete(self):
        self.completed = True
        self.set_note('已经成功收到文字回复。语音、形象和高级参数可以按需稍后设置。')
        self.toggle.setChecked(False)
        self._expanded(False)
