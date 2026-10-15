"""直接上传窗口在真实 Qt 事件循环中工作，不启动推理或写用户凭据。"""

import asyncio
import threading
import time
from types import SimpleNamespace
from uuid import uuid4

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication, QWidget

from pet.config import Settings
from pet.platform_dialog import PlatformDialog


class UploadRuntime(QObject):
    platform_settings_saved = Signal(object, str)


def pump_until(application, condition):
    deadline = time.monotonic() + 5
    while not condition() and time.monotonic() < deadline:
        application.processEvents()
        time.sleep(0.005)
    assert condition(), "Qt 上传任务未及时退出"


@pytest.mark.parametrize("fails", [False, True])
def test_direct_upload_connects_once_and_keeps_qt_responsive(monkeypatch, fails):
    application = QApplication.instance() or QApplication([])
    panel = QWidget()
    owner = SimpleNamespace(panel=panel, settings=Settings(), runtime=UploadRuntime())
    dialog = PlatformDialog(owner)
    ui_thread, calls, authorization_calls = threading.get_ident(), [], []
    tokens = {}

    class Store:
        def read(self):
            return dict(tokens) if tokens else None

        def save(self, values):
            tokens.update(values)

    class Client:
        base_url = "http://localhost:3000"
        store = Store()

        def __init__(self, _base):
            pass

        async def request(self, _method, _path):
            assert threading.get_ident() != ui_thread
            return {"displayName": "当前账号作者", "emailVerified": True}

        async def upload_model(self, source, metadata, progress):
            assert threading.get_ident() != ui_thread
            calls.append((source, metadata))
            progress("正在上传模型", 50)
            await asyncio.sleep(0.02)
            if fails:
                from pet.platform_upload import UploadError

                raise UploadError("模型引用文件不存在：texture.png")
            return {"resourceId": str(uuid4()), "resourceVersionId": str(uuid4()), "name": metadata["name"]}

    async def authorize(_base, *, upload):
        assert upload and threading.get_ident() != ui_thread
        authorization_calls.append(True)
        return {"access_token": "test-access", "refresh_token": "test-refresh", "scope": "resources:read resources:write"}

    monkeypatch.setattr("pet.platform_upload_dialog.PlatformClient", Client)
    monkeypatch.setattr("pet.platform_upload_dialog.authorize", authorize)
    try:
        dialog.open_upload()
        pump_until(application, lambda: dialog.worker is None)
        window = dialog.upload_dialog
        assert window.author.text() == "当前账号作者" and window.submit_button.isEnabled()
        window.name.setText("本地模型")
        window.submit_button.click()
        assert dialog.worker is not None and not window.source.isEnabled()
        pump_until(application, lambda: dialog.worker is None)
        assert calls[0][1]["name"] == "本地模型"
        assert calls[0][1]["version"] == "1.0.0"
        if fails:
            assert "texture.png" in window.status.text()
            assert not window.view_button.isVisible()
        else:
            assert "上传完成" in window.status.text()
            assert window.progress.value() == 100 and window.view_button.isVisible()
        window.close()
        dialog.open_upload()
        pump_until(application, lambda: dialog.worker is None)
        assert len(authorization_calls) == 1, "已有上传授权仍反复打开浏览器"
    finally:
        dialog.shutdown()
        if dialog.worker:
            dialog.worker.wait(5000)
            application.processEvents()
        dialog.deleteLater()
        panel.deleteLater()
        application.processEvents()
