"""控制中心的紧凑公共区；保留原信号，聊天操作由对话页就近摆放。"""

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QAction, QPainter
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QToolButton, QVBoxLayout


class LiveTranscript(QLabel):
    """空转写不占空间，现有运行时仍可直接调用 setText 更新。"""

    def setText(self, text):
        super().setText(text)
        # 长转写最多预览三行，全文可悬停查看，避免把发送区挤出小窗口。
        self.setMaximumHeight(self.fontMetrics().lineSpacing() * 3)
        self.setToolTip(text)
        self.setAccessibleDescription(text)
        self.setVisible(bool(text))

    def clear(self):
        # 运行时关闭麦克风和休眠会调用 clear；同时移除全文提示与辅助描述。
        self.setText("")


class ProductName(QLabel):
    """保留完整名称与辅助名称，只在绘制时省略过长标题。"""

    def __init__(self, name):
        super().__init__(name)
        self.setMaximumWidth(120)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.setToolTip(name)

    def minimumSizeHint(self):
        return QSize(0, super().minimumSizeHint().height())

    def setText(self, text):
        super().setText(text)
        self.setToolTip(text)
        self.setAccessibleName(text)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setPen(self.palette().color(self.foregroundRole()))
        text = self.fontMetrics().elidedText(self.text(), Qt.TextElideMode.ElideRight, self.width())
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)


class ResourceStatus(QLabel):
    """共享一行展示后台操作，操作结束后恢复持续更新的本机资源信息。"""

    def __init__(self, text):
        super().__init__(text)
        self._resources = text
        self._activity = ""
        self._provider = ""

    def setText(self, text):
        self._resources = text
        self._refresh()

    def set_activity(self, message):
        self._activity = message
        self._refresh()

    def set_provider(self, message):
        # 推理位置与模型持续可见，上传进度和资源轮询都不能覆盖它。
        self._provider = message
        self._refresh()

    def _refresh(self):
        super().setText(' · '.join(part for part in (self._provider, self._activity or self._resources) if part))
        self.setToolTip("\n".join(part for part in (self._provider, self._activity, self._resources) if part))


def create_header(panel):
    header = QFrame()
    header.setObjectName("panelHeader")
    row = QHBoxLayout(header)
    row.setContentsMargins(12, 8, 12, 8)
    row.setSpacing(8)
    panel.title = ProductName(panel.settings.name)
    panel.title.setObjectName("productName")
    row.addWidget(panel.title)
    panel.status = QLabel("已就绪 · 麦克风关闭")
    panel.status.setObjectName("status")
    panel.status.setTextFormat(Qt.TextFormat.PlainText)
    panel.status.setWordWrap(True)
    panel.status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    panel.status.setMinimumWidth(96)
    panel.status.setAccessibleName("桌宠运行状态")
    row.addWidget(panel.status, 1)
    panel.voice_button = QPushButton("开启连续对话")
    panel.voice_button.setCheckable(True)
    panel.voice_button.toggled.connect(panel.voice_requested)
    row.addWidget(panel.voice_button)
    panel.sleep_button = QPushButton("休眠")
    panel.sleep_button.clicked.connect(panel.sleep_requested)
    row.addWidget(panel.sleep_button)

    panel.speech_button = QPushButton("朗读开启")
    panel.speech_button.setCheckable(True)
    panel.speech_button.setToolTip("临时开启或关闭回复朗读，不影响麦克风。保存设置或重启后，恢复语音与行为中的默认偏好。")
    panel.speech_button.toggled.connect(panel.speech_requested)
    panel.look_button = QPushButton("看一眼屏幕")
    panel.look_button.clicked.connect(panel.look_requested)
    panel.stop_button = QPushButton("停止回复")
    panel.stop_button.setEnabled(False)
    panel.stop_button.setToolTip("停止本轮生成和播放，已开启的麦克风会继续聆听。")
    panel.stop_button.clicked.connect(panel.stop_requested)
    panel.audio_avoidance_action = QAction("有其他声音时暂停朗读", panel)
    panel.audio_avoidance_action.setCheckable(True)
    panel.audio_avoidance_action.setChecked(panel.settings.audio_avoidance)
    panel.audio_avoidance_action.setToolTip("勾选后，其他软件发声时停止朗读，只显示文字；安静后不补播旧回复。此开关自动保存并立即生效，不影响麦克风。")
    panel.audio_avoidance_button = QToolButton()
    panel.audio_avoidance_button.setObjectName("avoidance")
    panel.audio_avoidance_button.setDefaultAction(panel.audio_avoidance_action)
    panel.live_transcript = LiveTranscript()
    panel.live_transcript.setTextFormat(Qt.TextFormat.PlainText)
    panel.live_transcript.setWordWrap(True)
    panel.live_transcript.setObjectName("hint")
    panel.live_transcript.setAccessibleName("实时语音转写")
    panel.live_transcript.hide()
    panel.audio_status = QLabel(
        "已开启：其他软件发声时暂停朗读" if panel.settings.audio_avoidance
        else "已关闭：朗读可与其他软件同时播放"
    )
    panel.audio_status.setObjectName("hint")
    panel.audio_status.setWordWrap(True)
    for label in (panel.live_transcript, panel.audio_status):
        label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    return header


def create_footer(panel):
    footer = QFrame()
    footer.setObjectName("panelFooter")
    row = QHBoxLayout(footer)
    row.setContentsMargins(12, 6, 12, 6)
    row.setSpacing(8)
    panel.form.hint.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    panel.form.hint.setToolTip(
        "保存设置会结束当前回复并关闭麦克风，朗读恢复默认偏好。记忆需单独保存，形象需单独应用。"
    )
    state = QVBoxLayout()
    state.setSpacing(2)
    state.addWidget(panel.form.hint)
    # 资源定时回调沿用这个控件更新可用内存及收音状态，不能在精简布局时删除。
    panel.footer = ResourceStatus("资源待检测 · 麦克风关闭")
    panel.footer.setObjectName("hint")
    panel.footer.setWordWrap(True)
    panel.footer.setTextFormat(Qt.TextFormat.PlainText)
    panel.footer.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    panel.footer.setAccessibleName("本机资源与麦克风状态")
    state.addWidget(panel.footer)
    row.addLayout(state, 1)
    panel.save_button = QPushButton("保存设置")
    panel.save_button.setToolTip("保存人设、语音与行为、模型与快捷键；结束当前回复并关闭麦克风，朗读恢复默认偏好。")
    panel.save_button.clicked.connect(panel._save)
    row.addWidget(panel.save_button)
    panel.collapse_button = QPushButton("收起")
    panel.collapse_button.setObjectName("quiet")
    panel.collapse_button.setToolTip(
        "有设置修改时先保存，结束回复并关闭麦克风；无修改时直接收起。\n"
        "后台上传继续。Ctrl+Tab 切换标签，Esc 或全局快捷键也可收起。"
    )
    panel.collapse_button.clicked.connect(panel.close)
    row.addWidget(panel.collapse_button)
    return footer
