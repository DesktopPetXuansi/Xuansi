"""原生模型策略表单；API Key 仅在密码框与保存事务快照的内存中存在。"""

import logging
from contextlib import ExitStack
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QSignalBlocker, Qt, QThreadPool, Signal
from PySide6.QtWidgets import QWidget

from .ai.settings import CAPABILITIES
from .ai_setup_form import KEY_LINKS, SERVICE_NAMES, create_setup_form
from .ai_tasks import AIResults, ProbeDevice, ValidateProfile
from .panel_style import COLORS

LOG = logging.getLogger(__name__)


class AIPage(QWidget):
    changed = Signal()

    def __init__(self, settings):
        super().__init__()
        self._profile = settings.profile
        # 验证成功只是草稿；只有配置保存回执可以更新已持久化凭据基准。
        self._saved_profile = settings.profile
        self._credential_ref = settings.profile.credential_ref
        self._key_endpoint = ""
        self._validation = None
        self._generation = 0
        # 工作任务持有信号对象直到完成，窗口销毁时 Qt 自动断开接收者。
        self.results = AIResults()
        self.results.validation.connect(self.validation_complete)
        self.results.device.connect(self._device_complete)
        create_setup_form(self, settings)
        # 后台返回的错误和自定义模型名只按文字显示，不能被解释为链接或富文本。
        for label in (self.validation_status, self.device_status, self.device_details):
            label.setTextFormat(Qt.TextFormat.PlainText)
        self.set_profile(settings.profile)
        self.presets.activated.connect(self._preset_changed)
        self.policy.currentIndexChanged.connect(self._policy_changed)
        self._policy_changed()
        self.key.textChanged.connect(self._key_changed)
        for field in (self.provider, self.region, self.endpoint, self.model, self.mode):
            field.textChanged.connect(self._profile_changed)
        self.context_tokens.valueChanged.connect(self._profile_changed)
        for box in self.capabilities.values():
            box.toggled.connect(self._profile_changed)
        LOG.debug("模型策略与在线设置表单已就绪")

    def set_profile(self, profile):
        self.cancel_validation()
        self._profile = profile
        # 整批回填只刷新一次，避免中间字段组合清除验证或分配错误的凭据引用。
        fields = [getattr(self, name) for name in ("provider", "region", "endpoint", "model", "mode")]
        with ExitStack() as stack:
            for field in (*fields, self.context_tokens, *self.capabilities.values()):
                stack.enter_context(QSignalBlocker(field))
            for name in ("provider", "region", "endpoint", "model", "mode"):
                getattr(self, name).setText(getattr(profile, name))
            self.context_tokens.setValue(profile.context_tokens)
            for name, box in self.capabilities.items():
                box.setChecked(name in profile.capabilities)
        if not self.key.text():
            self._credential_ref = self._saved_reference()
        self._profile_changed()
        if self.key.text():
            # 完整预设一次确定地址，不受手动首次逐字输入地址的宽限影响。
            self._key_endpoint = profile.endpoint

    @staticmethod
    def _same_configuration(first, second):
        return (all(getattr(first, name) == getattr(second, name) for name in
                    ("provider", "region", "endpoint", "model", "mode", "context_tokens"))
                and set(first.capabilities) == set(second.capabilities))

    def _preset_changed(self, index):
        profile = self.presets.itemData(index)
        if profile is None:
            self.advanced.toggle.setChecked(True)
            self.endpoint.setFocus()
            return
        current = self.profile()
        if self._same_configuration(current, profile):
            return  # 同一预设再次点选，不清空密钥、验证证据或正在进行的测试。
        self.set_profile(profile)
        LOG.info("在线服务预设已更新")

    def _policy_changed(self, *_):
        policy = self.policy.currentData()
        self.local_group.setVisible(policy != "online_first")
        self.online_group.setVisible(policy != "local_only")
        self.privacy_group.setVisible(policy != "local_only")
        hints = {
            "local_only": "对话在本机运行，无在线对话费用；需要已安装的本机模型。",
            "local_first": "先使用本机模型，资源不足时尝试已通过测试的在线服务；在线请求会发送资料并由服务商计费。",
            "online_first": "优先使用在线服务，资源不足时尝试已安装并验证的本机模型；在线请求会发送资料并由服务商计费。",
        }
        self.policy_hint.setText(hints[policy])
        if policy == "local_only":
            self.cancel_validation()
        self.changed.emit()

    def _refresh_online_summary(self):
        profile = self.profile()
        matched = next((index for index in range(1, self.presets.count())
                        if self._same_configuration(profile, self.presets.itemData(index))), 0)
        with QSignalBlocker(self.presets):
            self.presets.setCurrentIndex(matched)
        service = SERVICE_NAMES.get(profile.provider, "自定义服务")
        self.online_model.setText(f"当前模型：{service} · {profile.model}" if profile.model
                                  else "选择服务商后会自动填写模型；也可在高级设置中自定义。")
        link = KEY_LINKS.get(profile.provider)
        # 链接只能来自仓库固定白名单，不能使用端点或其他可编辑文本拼成 HTML。
        help_text = (f'<a style="color: {COLORS["accent"]}" href="{link}">获取 API 密钥（官方）</a>。' if link
                     else "请从所用服务的官方控制台获取 API 密钥。")
        if profile.provider == "bailian":
            help_text += "密钥需与所选地区一致。"
        self.key_help.setText(help_text + "保存后存入本机系统凭据管理器。")

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

        # 填写密钥时绑定已有地址；地址尚空时允许用户继续逐字填写首个地址。
        self._key_endpoint = self.endpoint.text().strip() if self.key.text() else ""
        try:
            self._credential_ref = new_ref(self.endpoint.text()) if self.key.text() else self._saved_reference()
        except ValueError:
            self._credential_ref = ""  # 未填写端点时仍允许保留密码草稿。
        self._profile_changed()

    def _saved_reference(self):
        return (self._saved_profile.credential_ref
                if self.endpoint.text().strip() == self._saved_profile.endpoint else "")

    def _profile_changed(self, *_):
        from .ai.credentials import new_ref, ref_matches_endpoint

        endpoint = self.endpoint.text().strip()
        cleared = bool(self.key.text() and self._key_endpoint and endpoint != self._key_endpoint)
        if cleared:
            # 手动改地址与选择其他服务遵守同一边界，旧密钥不能改换引用后继续发送。
            with QSignalBlocker(self.key):
                self.key.clear()
            self._key_endpoint = ""
            LOG.info("在线服务地址已更改，已清除原密钥草稿")
        if self.key.text() and not ref_matches_endpoint(self._credential_ref, endpoint):
            try:
                self._credential_ref = new_ref(endpoint)
            except ValueError:
                self._credential_ref = ""
        elif not self.key.text():
            # 新端点必须重新输入 Key，不向其发送已保存凭据。
            self._credential_ref = self._saved_reference()
        self.cancel_validation()
        self._update_validation_status()
        self._refresh_online_summary()
        if cleared:
            self.validation_status.setText("服务地址已更改，请重新填写对应服务的 API 密钥。\n"
                                           + self.validation_status.text())
        self.changed.emit()

    def _update_validation_status(self):
        profile = self.profile()
        names = {"text": "文字聊天", "image": "看图", "tools": "使用工具", "stream": "逐步显示回复",
                 "cancel": "取消请求", "json": "JSON 结构化输出"}
        passed = [title for name, title in names.items() if name in profile.capabilities and profile.is_verified(name)]
        pending = [title for name, title in names.items() if name in profile.capabilities and not profile.is_verified(name)]
        lines = []
        if passed:
            lines.append("已通过：" + "、".join(passed))
        if pending:
            lines.append("未验证：" + "、".join(pending))
        lines.append("测试通过只说明对应能力可用，不能保证所有桌宠操作都能正确完成。")
        self.validation_status.setText("\n".join(lines))

    def credential_changed(self):
        return bool(self.key.text())

    def credential_draft(self):
        if self.key.text():
            # 保存快照从此绑定实际地址，后续改地址必须重新输入密钥。
            self._key_endpoint = self.endpoint.text().strip()
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

    def restore_configuration(self, settings):
        """历史引用仅用于原服务；历史验证证据已清空，不能绕过重新验证。"""
        self.cancel_validation()
        self.key.clear()
        self._saved_profile = settings.profile
        self.set_profile(settings.profile)
        for widget, value in ((self.policy, settings.policy), (self.local_model, settings.local_model),
                              (self.backend, settings.local_backend)):
            index = widget.findData(value)
            if index < 0:
                widget.addItem(value, value)
                index = widget.count() - 1
            widget.setCurrentIndex(index)
        self.model_dir.setText(settings.model_dir)
        self.backup_model.setText(settings.backup_model_path)
        self.backup_projector.setText(settings.backup_projector_path)
        self.cloud_memory.setChecked(settings.cloud_memory)
        self.cloud_observation.setChecked(settings.cloud_observation)
        self.changed.emit()

    def start_validation(self):
        self.cancel_validation()
        try:
            profile = self.profile().validate()
            if not profile.endpoint or not profile.model:
                raise ValueError("请先选择服务商，或在高级设置中填写 API 地址和模型名称。")
        except ValueError as exc:
            self.validation_status.setText(str(exc))
            return
        if self.key.text():
            self._key_endpoint = profile.endpoint
        self._validation = ValidateProfile(self.results, profile, self.key.text() or None, uuid4().hex)
        self.validate_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.validation_status.setText("正在测试连接和所选能力，可取消；使用示例资料，可能产生少量费用。")
        QThreadPool.globalInstance().start(self._validation)

    def cancel_validation(self):
        if self._validation is not None:
            self._validation.cancel()
            self._validation = None
            self.validation_status.setText("测试已取消，配置和密钥草稿仍保留；已产生的费用可能仍会结算。")
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
            if self.key.text():
                self._key_endpoint = profile.endpoint
            self._update_validation_status()
            self.changed.emit()

    def probe(self):
        from .config import MODELS

        self._generation += 1
        self.device_status.setText("正在检测电脑配置，不会更改你的设置…")
        self.detect.setEnabled(False)
        QThreadPool.globalInstance().start(ProbeDevice(self.results, self._generation,
                                                     Path(self.model_dir.text().strip() or MODELS)))

    def _device_complete(self, generation, report, error):
        if generation != self._generation:
            return
        self.detect.setEnabled(True)
        if error:
            self.device_status.setText("无法确认电脑是否适合本机运行，请重新检测；尚未实测。")
            self.device_details.setText(error)
            return
        from .ai.assessment import assess
        from .ai.catalog import MODELS

        descriptions, recommendations, statuses = [], [], []
        for index in range(self.local_model.count()):
            model_id = self.local_model.itemData(index)
            if model_id not in MODELS:
                continue
            result = assess(report, model_id, self.backend.currentData())
            self.local_model.model().item(index).setEnabled(result.selectable)
            descriptions.append(MODELS[model_id].name + "：" + "；".join(result.reasons))
            statuses.append(result.status)
            if MODELS[model_id].verification == "verified" and result.status in ("estimated", "slow"):
                suffix = "（可能需要较长等待）" if result.status == "slow" else ""
                recommendations.append(MODELS[model_id].name + suffix)
        self.device_details.setText("\n".join(descriptions))
        if recommendations:
            message = "推荐：" + "、".join(recommendations) + "。资源估算可运行，回复速度未实测。"
        elif "unknown" in statuses or not statuses:
            message = "无法确认电脑是否适合本机运行，请重新检测；回复速度未实测。"
        elif all(status in ("insufficient", "incompatible") for status in statuses):
            message = "当前电脑资源或系统不满足本机模型要求，可查看高级设置中的原因；未实测。"
        else:
            message = "当前没有已验证适配的推荐方案，可查看高级设置中的原因；回复速度未实测。"
        self.device_status.setText(message)
        LOG.info("电脑配置检测完成，已展示建议；保留用户配置")

    def hideEvent(self, event):
        self.cancel_validation()
        self._generation += 1
        self.detect.setEnabled(True)
        super().hideEvent(event)
