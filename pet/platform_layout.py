"""资源与上传页的原生布局；账号、线程与保存事务由原窗口负责。"""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QListWidget,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
)

from .avatar_live2d import LIVE2D_MODEL
from .platform_upload import DEFAULT_LICENSE


def hint(text):
    label = QLabel(text)
    label.setObjectName("hint")
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    return label


def group(layout, title, *, stretch=0):
    box = QGroupBox(title)
    content = QVBoxLayout(box)
    content.setSpacing(8)
    layout.addWidget(box, stretch)
    return content


def action_grid(actions):
    """两列操作保留自然阅读顺序，让窄窗不被一整排按钮撑宽。"""
    grid = QGridLayout()
    grid.setColumnStretch(0, 1)
    grid.setColumnStretch(1, 1)
    for index, button in enumerate(actions):
        button.setProperty("secondary", True)
        grid.addWidget(button, index // 2, index % 2)
    return grid


def resource_layout(dialog):
    layout = QVBoxLayout(dialog)
    layout.setSpacing(12)
    connection = group(layout, "官网连接")
    connection.addWidget(hint("官网账号仅用于资源；聊天、录音与推理仍留在本机。"))
    dialog.url = QLineEdit(dialog.owner.settings.platform_url)
    dialog.url.setAccessibleName("官网地址")
    fields = QFormLayout()
    fields.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
    fields.addRow("官网地址", dialog.url)
    connection.addLayout(fields)
    dialog.controls = []
    buttons = []
    for label, slot in [("浏览器登录", dialog.login), ("退出官网账号", dialog.logout)]:
        button = QPushButton(label)
        button.clicked.connect(slot)
        dialog.controls.append(button)
        buttons.append(button)
    connection.addLayout(action_grid(buttons))

    remote = group(layout, "官网可下载资源", stretch=1)
    dialog.remote_state = hint("尚未加载，点击“刷新官网资源”查看。")
    remote.addWidget(dialog.remote_state)
    dialog.remote = QListWidget()
    # 未加载和空列表用说明呈现，保留实际资源列表的自然伸展。
    dialog.remote.hide()
    dialog.remote.setAccessibleName("官网可下载资源")
    dialog.remote.setMinimumHeight(92)
    dialog.remote.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    dialog.remote.currentRowChanged.connect(dialog.load_versions)
    remote.addWidget(dialog.remote, 1)
    dialog.versions = QComboBox()
    dialog.versions.setAccessibleName("可下载版本")
    dialog.versions.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    dialog.versions.setMinimumContentsLength(8)
    fields = QFormLayout()
    fields.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
    fields.addRow("可下载版本", dialog.versions)
    remote.addLayout(fields)
    buttons = []
    for label, slot in [("刷新官网资源", dialog.refresh_remote), ("下载安装所选版本", dialog.download),
                        ("上传本地 Live2D 模型", dialog.open_upload)]:
        button = QPushButton(label)
        button.clicked.connect(slot)
        dialog.controls.append(button)
        buttons.append(button)
    remote.addLayout(action_grid(buttons))

    local = group(layout, "本机已安装资源", stretch=1)
    dialog.local_state = hint("无需登录，断网也可使用；尚未加载本机列表。")
    local.addWidget(dialog.local_state)
    dialog.local = QListWidget()
    dialog.local.hide()
    dialog.local.setAccessibleName("本机已安装资源")
    dialog.local.setMinimumHeight(92)
    dialog.local.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    local.addWidget(dialog.local, 1)
    buttons = []
    for label, slot in [("刷新本机资源", dialog.refresh_local), ("应用模型 / 动作 / 表情", dialog.apply_selected),
                        ("恢复默认玄司", dialog.restore_default), ("结束当前表情", dialog.reset_expression)]:
        button = QPushButton(label)
        button.clicked.connect(slot)
        if slot == dialog.reset_expression:
            button.setToolTip("结束当前表情，恢复视线和口型")
        dialog.controls.append(button)
        buttons.append(button)
    local.addLayout(action_grid(buttons))
    dialog.status = hint("使用浏览器登录，或直接使用本机资源。")
    dialog.status.setAccessibleName("资源操作状态")
    layout.addWidget(dialog.status)
    cancel = QPushButton("取消操作")
    cancel.setProperty("secondary", True)
    cancel.clicked.connect(dialog.cancel)
    layout.addWidget(cancel, alignment=Qt.AlignmentFlag.AlignRight)


def upload_layout(dialog):
    layout = QVBoxLayout(dialog)
    layout.setSpacing(12)
    selection = group(layout, "选择本地模型")
    selection.addWidget(hint("选择模型入口或文件夹，客户端会自动整理运行文件。"))
    initial = "" if dialog.platform.owner.settings.avatar_image else str(LIVE2D_MODEL)
    dialog.source = QLineEdit(initial)
    dialog.source.setReadOnly(True)
    dialog.source.setAccessibleName("本地模型文件或文件夹")
    # 完整路径仅在悬停时显示，不进入运行日志。
    dialog.source.setToolTip(initial)
    dialog.source.textChanged.connect(dialog.source.setToolTip)
    selection.addWidget(dialog.source)
    dialog.file_button = QPushButton("选择模型文件")
    dialog.folder_button = QPushButton("选择模型文件夹")
    dialog.file_button.clicked.connect(dialog.browse_file)
    dialog.folder_button.clicked.connect(dialog.browse_folder)
    selection.addLayout(action_grid([dialog.file_button, dialog.folder_button]))

    metadata = group(layout, "基本信息")
    fields = QFormLayout()
    fields.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
    dialog.name = QLineEdit(Path(initial).name.removesuffix(".model3.json") if initial else "")
    dialog.author = QLineEdit()
    dialog.version = QLineEdit("1.0.0")
    dialog.license = QLineEdit(DEFAULT_LICENSE)
    dialog.name.setMaxLength(120)
    for label, field in [("模型名称", dialog.name), ("模型作者", dialog.author),
                         ("版本号", dialog.version), ("使用许可", dialog.license)]:
        field.setAccessibleName(label)
        fields.addRow(label, field)
    metadata.addLayout(fields)

    transfer = group(layout, "上传与入库")
    dialog.connection = hint("首次连接需要在浏览器中登录并允许上传模型。")
    transfer.addWidget(dialog.connection)
    dialog.progress = QProgressBar()
    dialog.progress.setAccessibleName("模型上传进度")
    dialog.progress.setRange(0, 100)
    dialog.progress.setValue(0)
    transfer.addWidget(dialog.progress)
    dialog.status = hint("正在连接官网账号…")
    dialog.status.setAccessibleName("上传操作状态")
    transfer.addWidget(dialog.status)
    dialog.submit_button = QPushButton("上传模型")
    dialog.connect_button = QPushButton("连接官网")
    dialog.cancel_button = QPushButton("关闭")
    dialog.view_button = QPushButton("在官网查看")
    dialog.submit_button.clicked.connect(dialog.submit)
    dialog.connect_button.clicked.connect(dialog.connect_account)
    dialog.cancel_button.clicked.connect(dialog.cancel_or_close)
    dialog.view_button.clicked.connect(dialog.view_resource)
    dialog.view_button.hide()
    transfer.addLayout(action_grid([dialog.submit_button, dialog.connect_button,
                                    dialog.view_button, dialog.cancel_button]))
    dialog.submit_button.setProperty("secondary", False)
    dialog.submit_button.setProperty("primary", True)
    layout.addStretch()
