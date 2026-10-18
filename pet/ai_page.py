"""原生模型策略表单；API Key 仅在密码框与保存事务快照的内存中存在。"""

import logging
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QThreadPool, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .ai.catalog import MODELS as LOCAL_MODELS
from .ai.settings import CAPABILITIES
from .ai_tasks import AIResults, ProbeDevice, ValidateProfile
from .settings_forms import field_row, form_group, form_hint

LOG = logging.getLogger(__name__)


class AIPage(QWidget):
    changed = Signal()

    def __init__(self, settings):
        super().__init__()
        self._profile = settings.profile
        # 验证成功只是草稿；只有配置保存回执可以更新已持久化凭据基准。
        self._saved_profile = settings.profile
        self._credential_ref = settings.profile.credential_ref
        self._validation = None
        self._generation = 0
        # 工作任务持有信号对象直到完成，窗口销毁时 Qt 自动断开接收者。
        self.results = AIResults()
        self.results.validation.connect(self.validation_complete)
        self.results.device.connect(self._device_complete)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        strategy = form_group(layout, "模型与回退策略")
        self.policy = QComboBox()
        for title, value in (("仅本地", "local_only"), ("本地优先 · 允许在线兜底", "local_first"),
                             ("优先在线", "online_first")):
            self.policy.addItem(title, value)
        self.policy.setCurrentIndex(self.policy.findData(settings.policy))
        field_row(strategy, "运行策略", self.policy)
        self.local_model = QComboBox()
        self.local_model.addItem("标准本地 · Qwen3.5 9B", "qwen3.5-9b")
        light_status = ('语义验收未通过' if LOCAL_MODELS['qwen3.5-4b'].verification == 'failed'
                        else '业务待验证')
        self.local_model.addItem(f'轻量本地 · Qwen3.5 4B（实验：{light_status}）', 'qwen3.5-4b')
        if self.local_model.findData(settings.local_model) < 0:
            self.local_model.addItem(settings.local_model, settings.local_model)
        self.local_model.setCurrentIndex(self.local_model.findData(settings.local_model))
        field_row(strategy, "本地主模型", self.local_model)
        self.backend = QComboBox()
        for title, value in (("自动分配", "auto"), ("NVIDIA CUDA", "cuda"), ("CPU（可能较慢）", "cpu")):
            self.backend.addItem(title, value)
        self.backend.setCurrentIndex(self.backend.findData(settings.local_backend))
        field_row(strategy, "本地计算后端", self.backend)
        self.model_dir = self._path(strategy, "模型根目录", settings.model_dir, directory=True)
        self.backup_model = self._path(strategy, "已安装备用模型 GGUF", settings.backup_model_path)
        self.backup_projector = self._path(strategy, "备用视觉组件 GGUF", settings.backup_projector_path)
        form_hint(strategy, "备用模型和视觉组件必须配套且已安装；运行中不会自动下载。选择本地档位后请检查下方主模型路径。")
        self.detect = QPushButton("重新检测设备")
        self.detect.clicked.connect(self.probe)
        strategy.addRow(self.detect)
        self.device_status = QLabel("设备适配待验证；重新检测仅预估资源，不代表实测响应速度。")
        self.device_status.setWordWrap(True)
        strategy.addRow(self.device_status)
        self._create_online(layout)
        privacy = form_group(layout, "在线资料发送范围")
        form_hint(privacy, "在线模型会接收对话文字、必要历史、工具结果及本轮明确附加的图片；费用由服务商直接结算。")
        self.cloud_memory = QCheckBox("允许云端检索长期记忆")
        self.cloud_memory.setChecked(settings.cloud_memory)
        privacy.addRow(self.cloud_memory)
        form_hint(privacy, "默认关闭。开启后可能按容量分批发送整个本地记忆库的候选内容，并非仅发送命中摘录；记忆文件仍保存在本机。")
        self.cloud_observation = QCheckBox("允许后台自动观察向在线模型发送截图")
        self.cloud_observation.setChecked(settings.cloud_observation)
        privacy.addRow(self.cloud_observation)
        form_hint(privacy, "默认关闭，与记忆检索和在线回退分别授权；录音保持本地识别，不随 API 开启而上传。")
        self.set_profile(settings.profile)
        self.key.textChanged.connect(self._key_changed)
        for field in (self.provider, self.region, self.endpoint, self.model, self.mode):
            field.textChanged.connect(self._profile_changed)
        self.context_tokens.valueChanged.connect(self._profile_changed)
        for box in self.capabilities.values():
            box.toggled.connect(self._profile_changed)
        LOG.debug("模型策略与在线设置表单已就绪")

    def _create_online(self, layout):
        online = form_group(layout, "在线 API · 自备 Key")
        from .ai.provider_catalog import preset_profiles

        self.presets = QComboBox()
        self.presets.addItem("选择服务商预设（未经过本机验证）", None)
        for profile in preset_profiles():
            self.presets.addItem(f"{profile.provider} / {profile.region} / {profile.model}", profile)
        self.presets.currentIndexChanged.connect(self._preset_changed)
        field_row(online, "服务商预设", self.presets)
        for name, title in (("provider", "服务商"), ("region", "地区"), ("endpoint", "HTTPS API 地址"),
                            ("model", "模型 ID"), ("mode", "工作模式")):
            field = QLineEdit()
            field.setMaxLength(2048)
            setattr(self, name, field)
            field_row(online, title, field)
        self.context_tokens = QSpinBox()
        self.context_tokens.setRange(1024, 2_000_000)
        field_row(online, "上下文预算 token", self.context_tokens)
        self.capabilities = {}
        for name, title in (("text", "文字"), ("image", "图片"), ("tools", "工具"),
                            ("stream", "流式"), ("cancel", "取消"), ("json", "结构化输出")):
            box = QCheckBox("声明支持：" + title)
            self.capabilities[name] = box
            online.addRow(box)
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.key.setMaxLength(4096)
        self.key.setPlaceholderText("留空保留已保存 Key；输入新 Key 将轮换凭据")
        field_row(online, "API Key（仅内存草稿）", self.key)
        form_hint(online, "自备 Key，由服务商直接计费。验证只发送合成文字、图片和无副作用工具用例，可能产生少量调用费用。官方声明不等于本项目验证。")
        self.validate_button = QPushButton("验证配置（可能产生少量费用）")
        self.validate_button.clicked.connect(self.start_validation)
        self.cancel_button = QPushButton("取消验证")
        self.cancel_button.clicked.connect(self.cancel_validation)
        self.cancel_button.setEnabled(False)
        online.addRow(self.validate_button, self.cancel_button)
        self.validation_status = QLabel()
        self.validation_status.setWordWrap(True)
        online.addRow(self.validation_status)

    def _path(self, form, title, value, directory=False):
        row = QHBoxLayout()
        field = QLineEdit(value)
        field.setMaxLength(2048)
        field.setAccessibleName(title)
        row.addWidget(field)
        button = QPushButton("选择")
        def choose():
            path = (QFileDialog.getExistingDirectory(self, title, field.text()) if directory else
                    QFileDialog.getOpenFileName(self, title, field.text(), "GGUF (*.gguf)")[0])
            if path:
                field.setText(path)
        button.clicked.connect(choose)
        row.addWidget(button)
        form.addRow(title, row)
        return field

    def set_profile(self, profile):
        self.cancel_validation()
        self._profile = profile
        if not self.key.text():
            self._credential_ref = profile.credential_ref
        for name in ("provider", "region", "endpoint", "model", "mode"):
            getattr(self, name).setText(getattr(profile, name))
        self.context_tokens.setValue(profile.context_tokens)
        for name, box in self.capabilities.items():
            box.setChecked(name in profile.capabilities)
        if not self.key.text():
            self._credential_ref = self._saved_reference()
        self._update_validation_status()

    def _preset_changed(self):
        profile = self.presets.currentData()
        if profile is not None:
            # 新端点不能复用旧服务商的凭据引用与验证证据。
            self.set_profile(profile)

    def profile(self):
        values = {name: getattr(self, name).text().strip() for name in
                  ("provider", "region", "endpoint", "model", "mode")}
        capabilities = tuple(name for name in sorted(CAPABILITIES) if self.capabilities[name].isChecked())
        if set(capabilities) == set(self._profile.capabilities):
            capabilities = self._profile.capabilities
        result = replace(self._profile, **values, context_tokens=self.context_tokens.value(),
                         credential_ref=self._credential_ref,
                         capabilities=capabilities)
        if result.fingerprint() != self._profile.fingerprint():
            result = replace(result, verified_capabilities=(), verified_at="", verification_fingerprint="")
        return result

    def _key_changed(self):
        from .ai.credentials import new_ref

        try:
            self._credential_ref = new_ref(self.endpoint.text()) if self.key.text() else self._saved_reference()
        except ValueError:
            self._credential_ref = ""  # 未填写端点时仍允许保留密码草稿。
        self._profile_changed()

    def _saved_reference(self):
        return (self._saved_profile.credential_ref
                if self.endpoint.text().strip() == self._saved_profile.endpoint else "")

    def _profile_changed(self, *_):
        if self.key.text() and self.endpoint.text().strip() != getattr(self, "_key_endpoint", ""):
            self._key_endpoint = self.endpoint.text().strip()
            from .ai.credentials import new_ref
            try:
                self._credential_ref = new_ref(self._key_endpoint)
            except ValueError:
                self._credential_ref = ""
        elif not self.key.text():
            # 新端点必须重新输入 Key，不向其发送已保存凭据。
            self._credential_ref = self._saved_reference()
        self.cancel_validation()
        self._update_validation_status()
        self.changed.emit()

    def _update_validation_status(self):
        self.validation_status.setText("当前配置已有匹配的验证证据。" if self.profile().is_verified("text")
                                       else "当前配置待验证；能力声明不代表完整桌宠可用。")

    def credential_changed(self):
        return bool(self.key.text())

    def credential_draft(self):
        return (self.profile(), self.key.text()) if self.key.text() else None

    def credentials_saved(self, snapshot):
        # 保存完成期间继续编辑时，只清理与成功快照完全一致的密码草稿。
        if snapshot is None:
            return
        unchanged = snapshot == self.credential_draft()
        self._saved_profile = snapshot[0]
        if unchanged:
            self._profile = snapshot[0]
            self.key.clear()
        elif self.key.text() and self._credential_ref == snapshot[0].credential_ref:
            # 原快照已提交，但新模型草稿仍需写 Key；分配新引用避免覆盖在用凭据。
            self._key_changed()
            LOG.info("凭据保存完成，保留继续编辑的草稿并更新引用")
        else:
            self._profile_changed()
        self.changed.emit()

    def apply(self, settings):
        return replace(settings, policy=self.policy.currentData(), local_model=self.local_model.currentData(),
                       local_backend=self.backend.currentData(),
                       model_dir=self.model_dir.text().strip(), backup_model_path=self.backup_model.text().strip(),
                       backup_projector_path=self.backup_projector.text().strip(), profile=self.profile(),
                       cloud_memory=self.cloud_memory.isChecked(), cloud_observation=self.cloud_observation.isChecked())

    def start_validation(self):
        self.cancel_validation()
        try:
            profile = self.profile().validate()
            if not profile.endpoint or not profile.model:
                raise ValueError("请填写 API 地址和模型 ID。")
        except ValueError as exc:
            self.validation_status.setText(str(exc))
            return
        self._validation = ValidateProfile(self.results, profile, self.key.text() or None, uuid4().hex)
        self.validate_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.validation_status.setText("正在验证合成用例，可取消；不读取屏幕、录音或记忆。")
        QThreadPool.globalInstance().start(self._validation)

    def cancel_validation(self):
        if self._validation is not None:
            self._validation.cancel()
            self._validation = None
            self.validation_status.setText("验证已取消，保留配置和 Key 草稿。")
        if hasattr(self, "validate_button"):
            self.validate_button.setEnabled(True)
            self.cancel_button.setEnabled(False)

    def validation_complete(self, request_id, profile, error):
        if (self._validation is None or request_id != self._validation.request_id
                or self._validation.profile.fingerprint() != self.profile().fingerprint()):
            return
        self._validation = None
        self.validate_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        if error:
            self.validation_status.setText(error)
        else:
            self._profile = profile
            self._update_validation_status()
            self.changed.emit()

    def probe(self):
        from .config import MODELS

        self._generation += 1
        self.device_status.setText("正在后台检测环境…")
        self.detect.setEnabled(False)
        QThreadPool.globalInstance().start(ProbeDevice(self.results, self._generation,
                                                     Path(self.model_dir.text().strip() or MODELS)))

    def _device_complete(self, generation, report, error):
        if generation != self._generation:
            return
        self.detect.setEnabled(True)
        if error:
            self.device_status.setText(error)
            return
        from .ai.assessment import assess
        from .ai.catalog import MODELS

        descriptions = []
        for index in range(self.local_model.count()):
            model_id = self.local_model.itemData(index)
            if model_id not in MODELS:
                continue
            result = assess(report, model_id, self.backend.currentData())
            self.local_model.model().item(index).setEnabled(result.selectable)
            descriptions.append(MODELS[model_id].name + "：" + "；".join(result.reasons))
        self.device_status.setText("\n".join(descriptions))

    def hideEvent(self, event):
        self.cancel_validation()
        self._generation += 1
        self.detect.setEnabled(True)
        super().hideEvent(event)
