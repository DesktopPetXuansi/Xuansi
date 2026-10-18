"""桌宠直接上传窗口：一次账号连接，选择本地运行模型即可上传。"""

import asyncio
import logging
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QPushButton,
)

from .platform_api import PlatformClient
from .platform_auth import authorize, website_url
from .platform_layout import upload_layout
from .platform_resources import read_installed
from .platform_upload import UploadError

LOG = logging.getLogger(__name__)


class ModelUploadDialog(QDialog):
    def __init__(self, platform, *, embedded=False):
        super().__init__(platform)
        self.embedded = embedded
        if embedded:
            self.setParent(platform, Qt.WindowType.Widget)
        self.platform = platform
        self.client = None
        self.connected = False
        self.busy = False
        self.resource_id = None
        self.setWindowTitle("上传 Live2D 模型 · 玄司")
        self.setWindowModality(Qt.WindowModality.NonModal if embedded else Qt.WindowModality.WindowModal)
        self.resize(600, 460)
        upload_layout(self)
        LOG.debug("模型上传页分组布局已构建")
        if embedded:
            for button in self.findChildren(QPushButton):
                button.setAutoDefault(False)
                button.setDefault(False)
        self.set_busy(False)

    def set_busy(self, busy):
        self.busy = busy
        pending = getattr(self.client, "pending_model_upload", None)
        for widget in (self.source, self.file_button, self.folder_button, self.name, self.author,
                       self.version, self.license):
            widget.setEnabled(not busy and not pending)
        self.connect_button.setEnabled(not busy)
        self.view_button.setEnabled(not busy)
        if pending:
            self.resource_id = pending["resourceId"]
            self.view_button.show()
        self.submit_button.setEnabled(not busy and self.connected)
        self.submit_button.setText("完成加入资源库" if pending else "上传模型")
        self.cancel_button.setText("取消操作" if busy else "返回对话" if self.embedded else "关闭")

    def connect_account(self):
        requested_url = self.platform.url.text().strip()
        saved_version = self.platform.owner.settings.platform_model_version

        async def operation():
            base_url = website_url(requested_url)
            client = self.client if self.client and self.client.base_url == base_url else PlatformClient(base_url)
            tokens = await asyncio.to_thread(client.store.read)
            if not tokens or "resources:write" not in str(tokens.get("scope", "")).split():
                tokens = await authorize(base_url, upload=True)
                if "resources:write" not in str(tokens.get("scope", "")).split():
                    raise UploadError("官网尚未授予上传权限，请允许上传模型后重试")
                await asyncio.to_thread(client.store.save, tokens)
            profile = await client.request("GET", "/me")
            if not profile.get("emailVerified"):
                raise UploadError("请先在官网验证邮箱，再连接并上传模型")
            selected = None
            if saved_version:
                try:
                    _, selected = await asyncio.to_thread(read_installed, saved_version)
                except (ValueError, OSError):
                    LOG.info("当前本机模型不可读取，上传窗口等待手动选择")
            return client, profile, selected

        self.platform.start("upload-connect", operation)

    def browse_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择 Live2D 模型入口", self.source.text(),
                                             "Live2D 模型 (*.model3.json)")
        if path:
            self.source.setText(path)
            self.name.setText(Path(path).name.removesuffix(".model3.json"))

    def browse_folder(self):
        path = QFileDialog.getExistingDirectory(self, "选择包含 Live2D 运行文件的文件夹")
        if path:
            self.source.setText(path)
            self.name.setText(Path(path).name)

    def submit(self):
        if not self.client or not self.source.text():
            self.status.setText("请先连接官网并选择本地模型。")
            return
        try:
            requested_url = website_url(self.platform.url.text().strip())
        except ValueError as exc:
            self.status.setText(str(exc))
            return
        if requested_url != self.client.base_url:
            # 同页可直接回到旧表单；提交时再次核对站点，原入库回执保留到切回原站点。
            self.status.setText("官网地址已更改，请先点击“连接官网”再上传；原站点的未完成记录已保留。")
            LOG.info("上传前官网地址已变更，等待重新连接")
            return
        metadata = {"name": self.name.text().strip(), "author": self.author.text().strip(),
                    "version": self.version.text().strip(), "license": self.license.text().strip()}
        if not all(metadata.values()):
            self.status.setText("请填写模型名称、原作者、版本号与使用许可。")
            return
        source = self.source.text()
        self.view_button.hide()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)

        async def operation():
            return await self.client.upload_model(
                source, metadata, lambda message, percent: self.platform.worker.progress.emit(message, percent))

        self.platform.start("upload-model", operation)

    def show_progress(self, message, percent):
        self.status.setText(message)
        self.progress.setRange(0, 0 if "校验" in message else 100)
        self.progress.setValue(percent)

    def completed(self, command, result):
        if command == "upload-connect":
            self.client, profile, selected = result
            self.connected = True
            if not self.author.text():
                self.author.setText(profile["displayName"])
            if selected:
                self.source.setText(str(selected))
                self.name.setText(selected.name.removesuffix(".model3.json"))
            self.connection.setText(f"已连接官网账号：{profile['displayName']}")
            self.status.setText("选择模型后点击上传；文件整理、官网校验和加入资源库会自动完成。")
        elif command == "upload-model":
            self.resource_id = result["resourceId"]
            self.show_progress("上传完成，模型已加入官网资源库。", 100)
            self.view_button.show()
            self.platform.status.setText("上传完成；点击刷新官网资源即可下载使用。")

    def view_resource(self):
        if self.resource_id and self.client:
            QDesktopServices.openUrl(QUrl(f"{self.client.base_url}/resources/{self.resource_id}"))

    def cancel_or_close(self):
        if self.busy:
            self.platform.cancel()
            self.status.setText("正在取消操作并清理上传…")
        else:
            if self.embedded:
                self.platform.owner.panel.collapse_section("upload")
                LOG.info("从上传标签返回对话，保留上传表单与回执")
            else:
                self.close()

    def closeEvent(self, event):
        if self.embedded:
            self.cancel_or_close()
            event.ignore()
            return
        if self.busy:
            self.platform.cancel()
        super().closeEvent(event)

    def accept(self):
        if not self.embedded:
            super().accept()

    def reject(self):
        if not self.embedded:
            super().reject()

    def keyPressEvent(self, event):
        # 嵌入表单不采用 QDialog 的默认 Enter 提交与 Esc 关闭语义。
        if self.embedded and event.key() in (Qt.Key.Key_Escape, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            event.ignore()
            return
        super().keyPressEvent(event)
