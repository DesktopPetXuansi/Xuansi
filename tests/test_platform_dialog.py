"""真实 Qt 界面和 Windows 保管接口回归，不启动推理或浏览器。"""

import asyncio
import sys
import threading
import time
from types import SimpleNamespace
from uuid import uuid4

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication, QWidget

from pet.config import Settings
from pet.platform_auth import CredentialStore
from pet.platform_dialog import PlatformDialog


class SettingsRuntime(QObject):
    platform_settings_saved = Signal(object, str)


def test_resource_dialog_refresh_runs_in_background(monkeypatch):
    application = QApplication.instance() or QApplication([])
    panel = QWidget()
    owner = SimpleNamespace(panel=panel, settings=Settings(), runtime=SettingsRuntime())
    dialog = PlatformDialog(owner)
    version = str(uuid4())
    manifest = {"resourceVersionId": version, "entrypoint": "pet.model3.json", "version": "1", "kind": "MODEL"}
    monkeypatch.setattr("pet.platform_dialog.installed_resources", lambda: [manifest])
    dialog.refresh_local()
    deadline = time.monotonic() + 3
    while dialog.worker is not None and time.monotonic() < deadline:
        application.processEvents()
        time.sleep(0.01)
    assert dialog.worker is None
    assert dialog.local.count() == 1
    assert dialog.local.item(0).text().startswith("pet.model3.json")
    assert dialog.remote.isEnabled()
    dialog.shutdown()
    dialog.deleteLater()
    panel.deleteLater()
    application.processEvents()


@pytest.mark.skipif(sys.platform != "win32", reason="凭据管理器仅供 Windows 客户端")
def test_windows_credentials_read_write_delete():
    store = CredentialStore(f"https://{uuid4()}.example.invalid")
    try:
        assert store.read() is None
        store.save({"access_token": "test-access-only", "refresh_token": "test-refresh-only"})
        assert store.read()["refresh_token"] == "test-refresh-only"
        store.delete()
        assert store.read() is None
    finally:
        store.delete()


def test_shutdown_waits_for_blocked_disk_without_blocking_qt():
    """Event 模拟无限慢磁盘：取消不能误报线程结束，Qt 事件循环仍然响应。"""
    from pet.app import DesktopPet

    application = QApplication.instance() or QApplication([])
    panel = QWidget()
    dialog = PlatformDialog(SimpleNamespace(panel=panel, settings=Settings(), runtime=SettingsRuntime()))
    started, release = threading.Event(), threading.Event()
    quit_calls = []
    root = SimpleNamespace(_quitting=True, _runtime_shutdown_complete=False,
                           _platform_shutdown_complete=False,
                           application=SimpleNamespace(quit=lambda: quit_calls.append(True)))
    root._finish_shutdown = lambda: DesktopPet._finish_shutdown(root)
    dialog.shutdown_done.connect(lambda: DesktopPet._platform_shutdown_finished(root))

    def blocked_disk():
        started.set()
        assert release.wait(10)

    async def operation():
        await asyncio.to_thread(blocked_disk)

    dialog.start("blocked-test", operation)
    try:
        assert started.wait(2)
        before = time.monotonic()
        dialog.shutdown()
        assert time.monotonic() - before < 0.2
        DesktopPet._runtime_shutdown_finished(root)
        for _ in range(10):
            application.processEvents()
        assert dialog.worker.isRunning() and not quit_calls
        assert not root._platform_shutdown_complete
        release.set()
        deadline = time.monotonic() + 3
        while dialog.worker is not None and time.monotonic() < deadline:
            application.processEvents()
            time.sleep(0.01)
        assert dialog.worker is None
        assert quit_calls == [True]
    finally:
        release.set()
        if dialog.worker:
            dialog.worker.wait(3000)
            application.processEvents()
        dialog.deleteLater()
        panel.deleteLater()
        application.processEvents()
