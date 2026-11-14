"""商店版首次配置：明确选择后后台检测，结果与密钥草稿只保留在内存。"""

import logging
from dataclasses import dataclass, field, replace
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal
from PySide6.QtWidgets import QDialogButtonBox, QLabel, QScrollArea, QVBoxLayout, QWidget

from .ai.device import probe_device
from .ai.install_plan import InstallPlan, prepare_plan, resources_for
from .ai.settings import AISettings, ModelProfile
from .ai_page import AIPage
from .store_setup_widgets import first_run_hints, resource_summary, resource_widgets
from .theme import ThemedDialog

LOG = logging.getLogger(__name__)
REQUIRED = ("text", "image", "tools", "stream", "cancel")


@dataclass(frozen=True)
class SetupSelection:
    """仅 plan/profile 可以序列化；key 交给启动协调器后应及时释放。"""

    plan: InstallPlan
    profile: ModelProfile | None
    key: str | None = field(repr=False)


class _ProbeSignals(QObject):
    complete = Signal(int, object, str)


class _Probe(QRunnable):
    def __init__(self, signals, generation, app_dir, model_dir):
        super().__init__()
        self.signals, self.generation = signals, generation
        self.app_dir, self.model_dir = app_dir, model_dir

    def run(self):
        try:
            report = probe_device(self.app_dir, self.model_dir)
            self.signals.complete.emit(self.generation, report, "")
        except Exception:
            LOG.warning("首次配置环境检测未完成")
            self.signals.complete.emit(self.generation, None, "环境检测未完成，请检查目录后重试。")


class StoreSetupDialog(ThemedDialog):
    def __init__(self, app_dir: Path, model_dir: Path, settings: AISettings | None = None, parent=None):
        super().__init__(parent)
        self.app_dir = Path(app_dir)
        if not self.app_dir.is_absolute() or not Path(model_dir).is_absolute():
            raise ValueError("首次配置需要绝对工作目录和模型目录")
        self.selection = None
        self._pending = None
        self._ready = None
        self._generation = 0
        self._signals = _ProbeSignals()
        self._signals.complete.connect(self._probed)
        initial = replace(settings or AISettings(voice_components=()), model_dir=str(model_dir))
        self.setWindowTitle("准备玄司")
        self.resize(800, 740)
        self.setMinimumSize(600, 480)
        layout = QVBoxLayout(self)
        title = QLabel("选择适合你的聊天方式")
        title.setObjectName("title")
        layout.addWidget(title)
        intro = QLabel("先选择模型、保存位置和语音组件；检测与确认都不会下载资源。\n"
                       "商店版会在用户文件夹保存设置，不会自动导入官网旧版的数据。")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.body = QWidget()
        content = QVBoxLayout(self.body)
        self.ai = AIPage(initial)
        # 安装选择不接受旧资源的任意文件路径，也不在首次配置开放后台资料授权。
        self.ai.model_dir.parentWidget().hide()
        content.addWidget(self.ai)
        resource_widgets(self, content, model_dir, initial.voice_components)
        scroll.setWidget(self.body)
        layout.addWidget(scroll, 1)
        self.status = QLabel()
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.confirm = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.confirm.setObjectName("primary")
        self.confirm.setText("检查并预览资源")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("暂不配置")
        buttons.accepted.connect(self.confirm_selection)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.ai.detect.clicked.disconnect()
        self.ai.detect.clicked.connect(self.detect_environment)
        self.ai.changed.connect(self._changed)
        self.ai.local_model.currentIndexChanged.connect(self._changed)
        self.model_directory.textChanged.connect(self.ai.model_dir.setText)
        self.ai.model_dir.textChanged.connect(self.model_directory.setText)
        self.model_directory.textChanged.connect(self._changed)
        self.backend.currentIndexChanged.connect(self._changed)
        self.backup.toggled.connect(self._changed)
        for box in self.voice.values():
            box.toggled.connect(self._changed)
        self._changed()

    def _draft_plan(self):
        if not self.model_directory.text().strip() or not Path(self.model_directory.text().strip()).is_absolute():
            raise ValueError("请选择模型和语音资源的绝对保存目录。")
        policy = self.ai.policy.currentData()
        local = policy != "online_first"
        return InstallPlan(mode="local" if local else "api", policy=policy,
                           primary_model_id=self.ai.local_model.currentData(),
                           backup_model_ids=("qwen3.5-4b",) if local and self.backup.isEnabled()
                           and self.backup.isChecked() else (), backend=self.backend.currentData(),
                           app_dir=str(self.app_dir), model_dir=self.model_directory.text().strip(),
                           voice_components=tuple(name for name, box in self.voice.items() if box.isChecked())).validate()

    def _changed(self, *_):
        self._generation += 1
        self._pending = None
        self._ready = None
        self.selection = None
        self.confirm.setEnabled(True)
        self.confirm.setText("检查并预览资源")
        self.ai.detect.setEnabled(True)
        self.ai.privacy_group.hide()
        first_run_hints(self.ai)
        self.ai.backend.setCurrentIndex(self.ai.backend.findData(self.backend.currentData()))
        local = self.ai.policy.currentData() != "online_first"
        self.backend.setEnabled(local)
        self.backup.setEnabled(local and self.ai.local_model.currentData() != "qwen3.5-4b")
        try:
            plan = self._draft_plan()
            self.summary.setText(resource_summary(plan))
        except ValueError:
            self.summary.setText("请填写有效的绝对模型目录，再确认下载量。")

    def _start_probe(self):
        self._generation += 1
        self.confirm.setEnabled(False)
        self.ai.detect.setEnabled(False)
        self.status.setText("正在检查电脑和所选目录，可关闭窗口取消本次配置…")
        QThreadPool.globalInstance().start(_Probe(self._signals, self._generation, self.app_dir,
                                                 Path(self.model_directory.text().strip())))

    def detect_environment(self):
        self._pending = None
        self._ready = None
        self.selection = None
        try:
            self._draft_plan()
        except ValueError as exc:
            self.status.setText(str(exc))
            return
        self._start_probe()

    def confirm_selection(self):
        if self._ready is not None:
            self.selection = self._ready
            self._ready = None
            LOG.info("首次配置选择已确认，模式=%s，资源数=%d", self.selection.plan.mode,
                     len(resources_for(self.selection.plan)))
            super().accept()
            return
        self.selection = None
        try:
            plan = self._draft_plan()
            profile = self.ai.profile().validate() if plan.policy != "local_only" else None
            if profile is not None and (not profile.endpoint or not profile.model or not profile.is_verified(*REQUIRED)):
                raise ValueError("请先点击在线服务的测试按钮，通过文字、图片、工具、流式和取消验证。")
            self._pending = (plan, profile, self.ai.key.text() or None if profile else None)
        except ValueError as exc:
            self.status.setText(str(exc))
            return
        self._start_probe()

    def _probed(self, generation, report, error):
        if generation != self._generation:
            return
        self.confirm.setEnabled(True)
        self.ai.detect.setEnabled(True)
        if error:
            self._pending = None
            self.status.setText(error)
            return
        if self._pending is None:
            self.ai._device_complete(self.ai._generation, report, "")
            self.status.setText("电脑检测已完成，请确认选择后继续。")
            return
        plan, profile, key = self._pending
        self._pending = None
        try:
            prepared = prepare_plan(plan, report, profile)
        except ValueError as exc:
            self.status.setText(str(exc))
            return
        # 自动后端可能改变下载量；展示定稿后再次确认，不能沿用检测前的估算。
        self._ready = SetupSelection(prepared, profile, key)
        self.summary.setText(resource_summary(prepared, prepared=True))
        self.status.setText("检查完成，请再次确认上方资源和下载量；下一步才会开始准备。")
        self.confirm.setText("确认选择并继续")

    def reject(self):
        self._generation += 1
        self._pending = None
        self._ready = None
        self.selection = None
        self.ai.cancel_validation()
        self.ai.key.clear()
        LOG.info("首次配置选择已取消")
        super().reject()
