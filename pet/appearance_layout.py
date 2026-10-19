"""形象页按选择、预览、使用组织；次要资源与分享操作保留在页内。"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMenu,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .panel_chrome import ProductName


def button(text, action):
    widget = QPushButton(text)
    widget.clicked.connect(action)
    return widget


def build_layout(view):
    layout = QVBoxLayout(view)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(6)
    identity = QHBoxLayout()
    # 复用带省略号与完整提示的标签，长模型名不挤掉预览和主操作。
    for name, text in (('current_label', '当前使用：默认玄司'), ('candidate_label', '预览：默认玄司')):
        label = ProductName(text)
        label.setMaximumWidth(16777215)
        label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        setattr(view, name, label)
        identity.addWidget(label, 1)
    layout.addLayout(identity)
    sources = QHBoxLayout()
    view.local_button = button('本地导入', view.browse)
    menu = QMenu(view.local_button)
    menu.addAction('选择图片、动图或模型文件', view.browse)
    menu.addAction('选择模型文件夹', view.browse_folder)
    view.folder_button = QToolButton()
    view.folder_button.setText('文件夹')
    view.folder_button.setToolTip('导入包含模型运行文件的文件夹')
    view.folder_button.setMenu(menu)
    view.folder_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
    view.online_button = button('在线挑选', view.online_requested)
    view.mine_button = button('我的形象', view.mine_requested)
    view.history_button = button('使用历史', view.history_requested)
    for widget in (view.local_button, view.folder_button, view.online_button, view.mine_button, view.history_button):
        sources.addWidget(widget)
    sources.addStretch()
    layout.addLayout(sources)
    view.stack = QStackedWidget()
    preview_page = QWidget()
    preview_layout = QVBoxLayout(preview_page)
    preview_layout.setContentsMargins(0, 0, 0, 0)
    preview_layout.setSpacing(4)
    # 低频动作预览放在画面旁，不增加竖向操作栏或影响“使用”的可见性。
    preview_row = QHBoxLayout()
    preview_row.addWidget(view.preview, 1)
    view.motion_button = button('预览眨眼', lambda: view.preview.play_motion('blink'))
    view.motion_button.setObjectName('quiet')
    view.motion_button.setToolTip('只播放当前预览的动作，不改变桌面形象')
    view.motion_button.setEnabled(False)
    preview_row.addWidget(view.motion_button, 0, Qt.AlignmentFlag.AlignTop)
    preview_layout.addLayout(preview_row)
    view.stack.addWidget(preview_page)
    choices_page = QWidget()
    choices_layout = QVBoxLayout(choices_page)
    choices_layout.setContentsMargins(0, 0, 0, 0)
    choices_layout.setSpacing(4)
    view.choices_title = QLabel()
    choices_layout.addWidget(view.choices_title)
    view.choices = QListWidget()
    view.choices.setAccessibleName('可选择的桌宠形象')
    view.choices.setMinimumHeight(64)
    view.choices.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Ignored)
    view.choices.currentRowChanged.connect(view.refresh_buttons)
    choices_layout.addWidget(view.choices, 1)
    row = QHBoxLayout()
    view.choice_button = button('预览所选形象', view.choose_item)
    view.login_button = button('登录官网', view.login_requested)
    view.back_button = button('返回预览', lambda: view.stack.setCurrentIndex(0))
    for widget in (view.choice_button, view.login_button, view.back_button):
        row.addWidget(widget)
    choices_layout.addLayout(row)
    view.stack.addWidget(choices_page)
    layout.addWidget(view.stack, 1)
    view.status = QLabel('先选择一个形象，预览满意后点击“使用这个形象”，程序会自动保存。')
    view.status.setWordWrap(True)
    view.status.setTextFormat(Qt.TextFormat.PlainText)
    view.status.setObjectName('hint')
    view.status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    view.status.setAccessibleName('形象更换进度与结果')
    layout.addWidget(view.status)
    row = QHBoxLayout()
    view.default_button = button('恢复默认', view.default_requested)
    view.share_button = button('上传分享', view.share_requested)
    view.more_button = button('更多资源', view.more_requested)
    for widget in (view.default_button, view.share_button, view.more_button):
        widget.setObjectName('quiet')
        row.addWidget(widget)
    row.addStretch()
    view.cancel_button = button('取消操作', view.cancel_requested)
    view.cancel_button.hide()
    row.addWidget(view.cancel_button)
    view.apply_button = button('使用这个形象', view.use_candidate)
    view.apply_button.setObjectName('primary')
    row.addWidget(view.apply_button)
    layout.addLayout(row)
