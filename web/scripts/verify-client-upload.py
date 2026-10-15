"""真实 Qt 上传验收；浏览器由父进程处理，令牌仅驻留本次内存。"""

import asyncio
import json
import logging
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from pet.platform_api import PlatformClient  # noqa: E402
from pet.platform_auth import website_url  # noqa: E402
from pet.platform_resources import read_installed  # noqa: E402


class MemoryStore:
    def __init__(self):
        self.tokens = None

    def read(self):
        return self.tokens

    def save(self, tokens):
        self.tokens = tokens

    def delete(self):
        self.tokens = None


def verify(payload):
    from PySide6.QtCore import QObject, Signal
    from PySide6.QtWidgets import QApplication, QWidget

    from pet.config import Settings
    from pet.platform_dialog import PlatformDialog

    class Runtime(QObject):
        platform_settings_saved = Signal(object, str)

    origin = website_url(payload["origin"])
    store = MemoryStore()
    application = QApplication.instance() or QApplication([])
    panel = QWidget()
    owner = SimpleNamespace(panel=panel, settings=Settings(platform_url=origin), runtime=Runtime())
    dialog = PlatformDialog(owner)

    def browser(url):
        # IPC 行由父进程消费后打开隔离浏览器；不写报告，也不转发到用户输出。
        print(f"__QA_AUTHORIZE__{url}", flush=True)
        return True

    def wait_finished(timeout=90):
        deadline = time.monotonic() + timeout
        while dialog.worker is not None and time.monotonic() < deadline:
            application.processEvents()
            time.sleep(0.01)
        application.processEvents()
        assert dialog.worker is None, "客户端后台任务未及时完成"

    try:
        with patch("pet.platform_upload_dialog.PlatformClient", lambda base: PlatformClient(base, store)), \
                patch("pet.platform_auth.webbrowser.open", browser):
            dialog.open_upload()
            wait_finished()
            window = dialog.upload_dialog
            assert window.connected and window.author.text() == payload["author"]
            print("客户端上传验收：真实 Qt 连接、浏览器上传同意和 PKCE 回环通过", flush=True)
            source = ROOT / "assets/xuansi/rigging/xuansi.model3.json"
            with patch("pet.platform_upload_dialog.QFileDialog.getOpenFileName", return_value=(str(source), "")):
                window.file_button.click()
            assert window.source.text() == str(source) and window.name.text() == "xuansi"
            assert window.version.text() == "1.0.0"
            window.submit_button.click()
            wait_finished()
            assert window.resource_id and window.progress.value() == 100
            assert "上传完成" in window.status.text() and window.view_button.isVisible()
            resource_id = window.resource_id
            print("客户端上传验收：真实模型自动整理、流式上传、worker校验和自动入库通过", flush=True)

            with tempfile.TemporaryDirectory(prefix="pet-client-upload-check-") as directory:
                original_request = window.client.request

                async def isolated_request(method, route, data=None, *, headers=None):
                    result = await original_request(method, route, data, headers=headers)
                    if route.endswith("/download-authorizations"):
                        # Go 使用站点地址生成下载票据。测试 API 独立运行，只将本次
                        # 本地下载能力路由回隔离 API，避免交给主站的开发数据库。
                        target = urlsplit(result["url"])
                        website = urlsplit(website_url(payload["websiteOrigin"]))
                        assert (target.scheme, target.netloc) == (website.scheme, website.netloc)
                        assert target.path.startswith("/api/v1/downloads/") and not target.fragment
                        local = urlsplit(origin)
                        result = {**result, "url": urlunsplit((local.scheme, local.netloc,
                                                               target.path, target.query, ""))}
                    return result

                window.client.request = isolated_request

                async def download():
                    library = await window.client.request("GET", "/me/library")
                    item = next(item for item in library if item["resource"]["id"] == resource_id)
                    version_id = item["pinnedVersionId"]
                    manifest = await window.client.install(resource_id, version_id, Path(directory))
                    assert len(manifest["files"]) == 4
                    assert not any(file["path"].endswith(".cmo3") for file in manifest["files"])
                    return version_id

                version_id = asyncio.run(download())
                window.client.request = original_request
                manifest, installed = read_installed(version_id, Path(directory))
                assert installed.read_bytes() == source.read_bytes()
                for file in manifest["files"]:
                    assert (installed.parent / file["path"]).read_bytes() == (source.parent / file["path"]).read_bytes()
                print("客户端上传验收：同一模型真实下载、摘要验证、原文件逐项一致与离线读取通过", flush=True)
            asyncio.run(window.client.logout())
            assert store.read() is None
    finally:
        dialog.shutdown()
        if dialog.worker:
            dialog.worker.wait(5000)
            application.processEvents()
        dialog.deleteLater()
        panel.deleteLater()
        application.processEvents()


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    try:
        verify(json.load(sys.stdin))
    except Exception as exc:
        # 固定错误类型，避免异常 URL、令牌和请求正文进入父进程日志。
        print(f"客户端上传验收失败：{type(exc).__name__}", file=sys.stderr)
        raise SystemExit(1)
