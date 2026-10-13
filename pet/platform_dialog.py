"""官网资源库窗口：所有网络与磁盘工作后台运行，SDK 只在 Qt 主线程使用。"""

import asyncio
import logging
import threading
from dataclasses import replace

import httpx
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from .platform_api import PlatformClient
from .platform_auth import authorize, website_url
from .platform_resources import installed_resources, read_installed

LOG = logging.getLogger(__name__)


class PlatformTask(QThread):
    completed = Signal(str, object)
    failed = Signal(str)

    def __init__(self, command, operation, parent):
        super().__init__(parent)
        self.command = command
        self.operation = operation
        self.loop = None
        self.task = None
        self.cancel_requested = threading.Event()

    def run(self):
        async def execute():
            self.loop = asyncio.get_running_loop()
            self.task = asyncio.current_task()
            if self.cancel_requested.is_set():
                raise asyncio.CancelledError
            return await self.operation()

        try:
            self.completed.emit(self.command, asyncio.run(execute()))
        except asyncio.CancelledError:
            self.failed.emit("资源操作已取消")
        except httpx.HTTPStatusError as exc:
            # HTTP 异常正文或 URL 可能包含令牌；界面和日志仅显示状态码。
            self.failed.emit(f"官网请求失败（HTTP {exc.response.status_code}），请检查账号权限或稍后重试")
        except (ValueError, KeyError, TypeError, OSError, httpx.RequestError, asyncio.TimeoutError):
            LOG.warning("官网资源操作失败 command=%s", self.command)
            self.failed.emit("资源操作失败：请检查官网地址、授权、资源完整性及兼容版本")
        except Exception as exc:
            LOG.warning("官网资源工作线程异常 command=%s type=%s", self.command, type(exc).__name__)
            self.failed.emit("资源服务暂时不可用，请稍后重试")

    def cancel(self):
        self.cancel_requested.set()
        if self.loop and self.task and not self.loop.is_closed():
            try:
                self.loop.call_soon_threadsafe(self.task.cancel)
            except RuntimeError:
                # 运行循环可能已同时结束；finished 信号仍负责完整退场。
                pass


class PlatformDialog(QDialog):
    shutdown_done = Signal()

    def __init__(self, owner):
        super().__init__(owner.panel)
        self.owner = owner
        self.worker = None
        self.client = None
        self.pending_settings = None
        self.shutting_down = False
        self.shutdown_emitted = False
        self.resources = []
        self.request_url = owner.settings.platform_url
        owner.runtime.platform_settings_saved.connect(self.platform_saved)
        self.setWindowTitle("官网资源库 · 玄司")
        self.resize(620, 540)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("官网账号仅用于资源；聊天、录音、推理仍留在本机。"))
        self.url = QLineEdit(owner.settings.platform_url)
        layout.addWidget(self.url)
        row = QHBoxLayout()
        self.controls = []
        for label, slot in [("浏览器登录", self.login), ("刷新官网资源", self.refresh_remote),
                            ("退出官网账号", self.logout), ("取消操作", self.cancel)]:
            button = QPushButton(label)
            button.clicked.connect(slot)
            row.addWidget(button)
            if label != "取消操作":
                self.controls.append(button)
        layout.addLayout(row)
        reset_expression = QPushButton("结束当前表情，恢复视线和口型")
        reset_expression.clicked.connect(self.reset_expression)
        self.controls.append(reset_expression)
        layout.addWidget(reset_expression)
        self.remote = QListWidget()
        self.remote.currentRowChanged.connect(self.load_versions)
        layout.addWidget(self.remote)
        self.versions = QComboBox()
        layout.addWidget(self.versions)
        button = QPushButton("下载安装所选版本")
        button.clicked.connect(self.download)
        self.controls.append(button)
        layout.addWidget(button)
        layout.addWidget(QLabel("本机已安装资源（无需登录，断网也可使用）"))
        self.local = QListWidget()
        layout.addWidget(self.local)
        row = QHBoxLayout()
        for label, slot in [("刷新本机资源", self.refresh_local), ("应用模型 / 动作 / 表情", self.apply_selected),
                            ("恢复默认玄司", self.restore_default)]:
            button = QPushButton(label)
            button.clicked.connect(slot)
            self.controls.append(button)
            row.addWidget(button)
        layout.addLayout(row)
        self.status = QLabel("使用浏览器登录，或直接使用本机资源。")
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

    def present(self):
        self.show()
        self.raise_()
        self.activateWindow()
        self.refresh_local()

    def set_busy(self, busy):
        self.url.setEnabled(not busy)
        self.remote.setEnabled(not busy)
        self.local.setEnabled(not busy)
        self.versions.setEnabled(not busy)
        for control in self.controls:
            control.setEnabled(not busy)

    def start(self, command, operation):
        if self.shutting_down:
            return
        if self.worker is not None and self.worker.isRunning():
            return
        self.set_busy(True)
        self.request_url = self.url.text().strip()
        self.status.setText("正在处理…浏览器授权最多等待五分钟，可取消。")
        self.worker = PlatformTask(command, operation, self)
        self.worker.completed.connect(self.completed)
        self.worker.failed.connect(self.task_failed)
        self.worker.finished.connect(self.task_finished)
        self.worker.start()

    def task_failed(self, message):
        if self.worker and self.worker.command == "save":
            self.pending_settings = None
            message = "资源已在本次运行中应用，但配置保存失败；重启将恢复上次选择。"
        self.status.setText(message)

    def task_finished(self):
        self.set_busy(self.pending_settings is not None or self.shutting_down)
        if self.worker:
            self.worker.deleteLater()
            self.worker = None
        if self.shutting_down:
            self.finish_shutdown()

    def api(self):
        self.client = PlatformClient(website_url(self.request_url))
        return self.client

    def login(self):
        async def operation():
            client = self.api()
            tokens = await authorize(client.base_url)
            await asyncio.to_thread(client.store.save, tokens)
            return client.base_url
        self.start("login", operation)

    def refresh_remote(self):
        async def operation():
            client = self.api()
            own = await client.request("GET", "/me/library")
            public = await client.request("GET", "/resources?limit=100")
            resources = {item["resource"]["id"]: item["resource"] for item in own}
            resources.update({item["id"]: item for item in public})
            return list(resources.values())
        self.start("remote", operation)

    def load_versions(self, row):
        self.versions.clear()
        if not 0 <= row < len(self.resources):
            return
        resource = self.resources[row]
        async def operation():
            return await self.api().request("GET", f"/resources/{resource['id']}/versions")
        self.start("versions", operation)

    def download(self):
        row = self.remote.currentRow()
        version = self.versions.currentData()
        if row < 0 or version is None:
            self.status.setText("请选择官网资源及已通过校验的版本")
            return
        resource_id = self.resources[row]["id"]
        async def operation():
            await self.api().install(resource_id, version)
            return await asyncio.to_thread(installed_resources)
        self.start("local", operation)

    def refresh_local(self):
        async def operation():
            return await asyncio.to_thread(installed_resources)
        self.start("local", operation)

    def apply_selected(self):
        item = self.local.currentItem()
        if not item:
            self.status.setText("请先选择本机已安装资源")
            return
        version = item.data(Qt.ItemDataRole.UserRole)
        async def operation():
            prepared = await asyncio.to_thread(read_installed, version)
            if prepared[0]["kind"] in {"IMAGE", "ANIMATION"}:
                from .appearance import import_image

                imported = await asyncio.to_thread(import_image, prepared[1])
                return prepared, imported.identifier
            return prepared, None
        self.start("apply", operation)

    def restore_saved(self):
        version = self.owner.settings.platform_model_version
        if not version or self.owner.settings.avatar_image:
            return
        async def operation():
            model = await asyncio.to_thread(read_installed, version)
            expression_id = self.owner.settings.platform_expression_version
            expression = await asyncio.to_thread(read_installed, expression_id) if expression_id else None
            return model, expression
        self.start("restore", operation)

    def restore_default(self):
        avatar = self.owner.avatar
        avatar._release_live2d()
        avatar._platform_model_version = ""
        avatar._platform_expression = False
        avatar.set_image("", force=True)
        self.persist_selection(replace(self.owner.settings, avatar_image="", platform_model_version="",
                                       platform_expression_version=""))

    def reset_expression(self):
        self.owner.avatar.reset_platform_expression()
        self.persist_selection(replace(self.owner.settings, platform_expression_version=""))

    def persist_selection(self, settings):
        changes = {name: getattr(settings, name) for name in (
            "platform_url", "platform_model_version", "platform_expression_version", "avatar_image")
                   if getattr(settings, name) != getattr(self.owner.settings, name)}
        self.persist_fields(changes)

    def persist_fields(self, changes):
        self.pending_settings = changes
        self.set_busy(True)
        self.owner.runtime.persist_platform(changes)

    def platform_saved(self, settings, error):
        if self.pending_settings is None:
            return
        self.pending_settings = None
        if not error:
            self.owner.settings = self.owner.panel.settings = settings
            self.status.setText("选择已保存；重启继续使用。")
        else:
            self.status.setText("本次选择未能保存；重启将恢复上次配置。")
        self.set_busy(bool(self.worker and self.worker.isRunning()) or self.shutting_down)

    def logout(self):
        async def operation():
            await self.api().logout()
        self.start("logout", operation)

    def cancel(self):
        if self.worker:
            self.worker.cancel()

    def completed(self, command, result):
        if self.shutting_down:
            return
        try:
            if command == "login":
                self.persist_fields({"platform_url": result})
                self.status.setText("官网授权已保存至 Windows 凭据管理器，正在保存官网地址。")
            elif command == "remote":
                self.resources = result
                self.remote.blockSignals(True)
                self.remote.clear()
                for resource in result:
                    self.remote.addItem(f"{resource['name']} · {resource['kind']}")
                self.remote.blockSignals(False)
                self.status.setText("选择资源查看可用版本；动作和表情须匹配当前模型。")
            elif command == "versions":
                for version in result:
                    if version["validationStatus"] == "READY":
                        self.versions.addItem(version["version"], version["id"])
                self.status.setText("版本列表已更新。")
            elif command == "local":
                self.local.clear()
                for manifest in result:
                    item = QListWidgetItem(f"{manifest['entrypoint']} · {manifest['kind']} · {manifest['version']}")
                    item.setData(Qt.ItemDataRole.UserRole, manifest["resourceVersionId"])
                    self.local.addItem(item)
                self.status.setText("本机资源已更新。下载后请选择并应用。")
            elif command in {"apply", "restore"}:
                prepared, expression = result
                manifest, path = prepared
                kind, version = manifest["kind"], manifest["resourceVersionId"]
                settings = self.owner.settings
                if kind == "MODEL":
                    self.owner.avatar.select_platform_model(version, prepared)
                    settings = replace(settings, avatar_image="", platform_model_version=version,
                                       platform_expression_version="")
                    if expression:
                        self.owner.avatar.apply_platform_action(expression[0]["resourceVersionId"], expression)
                        settings = replace(settings, platform_expression_version=expression[0]["resourceVersionId"])
                elif kind in {"MOTION", "EXPRESSION"}:
                    self.owner.avatar.apply_platform_action(version, prepared)
                    if kind == "EXPRESSION":
                        settings = replace(settings, platform_expression_version=version)
                else:
                    self.owner.avatar.set_image(expression, force=True)
                    settings = replace(settings, avatar_image=expression, platform_model_version="",
                                       platform_expression_version="")
                self.persist_selection(settings)
                self.status.setText("资源已成功试载并应用，正在保存选择…")
            elif command == "logout":
                self.status.setText("官网账号已退出；本机已安装资源和本地推理继续可用。")
        except (ValueError, OSError, RuntimeError, KeyError):
            LOG.warning("平台资源界面操作失败 command=%s", command)
            self.status.setText("模型或资源应用失败，原有模型保持可用；请检查兼容性。")

    def closeEvent(self, event):
        # 隐藏窗口不销毁后台工作；退出应用时由协调层取消并等待线程。
        self.hide()
        event.ignore()

    def shutdown(self):
        self.shutting_down = True
        self.set_busy(True)
        self.cancel()
        self.hide()
        if self.worker is None:
            self.finish_shutdown()

    def finish_shutdown(self):
        if not self.shutdown_emitted:
            self.shutdown_emitted = True
            self.shutdown_done.emit()
