"""商店启动顺序在隔离目录中验证，不注册或安装应用。"""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtWidgets import QDialog

import pet.store_bootstrap as bootstrap


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    root = tmp_path / "商店数据"
    application = SimpleNamespace(setQuitOnLastWindowClosed=Mock())
    lock = SimpleNamespace(tryLock=Mock(return_value=True), isLocked=Mock(return_value=True), unlock=Mock())
    server = SimpleNamespace(close=Mock(), deleteLater=Mock(), newConnection=SimpleNamespace(disconnect=Mock()))
    selection = SimpleNamespace(plan=object(), profile=None, key=None)
    setup = SimpleNamespace(exec=Mock(return_value=QDialog.DialogCode.Accepted), selection=selection,
                            ai=SimpleNamespace(key=SimpleNamespace(clear=Mock())))
    progress = SimpleNamespace(exec=Mock(return_value=QDialog.DialogCode.Accepted))
    monkeypatch.setattr(bootstrap, "DATA", root / "data")
    monkeypatch.setattr(bootstrap, "WRITABLE_ROOT", root)
    monkeypatch.setattr(bootstrap, "QApplication", Mock(return_value=application))
    monkeypatch.setattr(bootstrap, "QLockFile", Mock(return_value=lock))
    monkeypatch.setattr(bootstrap, "configure_opengl_sharing", Mock())
    monkeypatch.setattr(bootstrap, "configure_fonts", Mock())
    monkeypatch.setattr(bootstrap, "configure_dpi", Mock())
    monkeypatch.setattr(bootstrap, "configure_logging", Mock())
    monkeypatch.setattr(bootstrap, "listen_for_launch", Mock(return_value=server))
    monkeypatch.setattr(bootstrap, "show_existing", Mock())
    monkeypatch.setattr(bootstrap, "StoreSetupDialog", Mock(return_value=setup))
    monkeypatch.setattr(bootstrap, "StoreProgressDialog", Mock(return_value=progress))
    monkeypatch.setattr(bootstrap, "desktop_main", Mock())
    return root, application, lock, server, setup, progress, selection


def test_new_install_runs_configuration_before_desktop(isolated):
    root, application, lock, server, setup, progress, selection = isolated
    assert bootstrap.main() == 0
    bootstrap.StoreSetupDialog.assert_called_once_with(root, root / "models")
    bootstrap.StoreProgressDialog.assert_called_once_with(root, selection)
    bootstrap.desktop_main.assert_called_once_with(application=application, instance_lock=lock)
    setup.ai.key.clear.assert_called_once()
    server.close.assert_called_once()
    lock.unlock.assert_called_once()


@pytest.mark.parametrize("phase", ["setup", "progress"])
def test_cancel_closes_without_starting_desktop_and_releases_lock(isolated, phase):
    _, _, lock, server, setup, progress, _ = isolated
    (setup if phase == "setup" else progress).exec.return_value = QDialog.DialogCode.Rejected
    assert bootstrap.main() == 0
    bootstrap.desktop_main.assert_not_called()
    server.close.assert_called_once()
    lock.unlock.assert_called_once()


def test_existing_settings_skip_new_install_flow(isolated):
    root, application, lock, _, _, _, _ = isolated
    (root / "data").mkdir(parents=True)
    (root / "data/settings.json").write_text("{}", encoding="utf-8")
    assert bootstrap.main() == 0
    bootstrap.StoreSetupDialog.assert_not_called()
    bootstrap.StoreProgressDialog.assert_not_called()
    bootstrap.desktop_main.assert_called_once_with(application=application, instance_lock=lock)


def test_second_start_notifies_existing_instance_without_opening_wizard(isolated):
    _, _, lock, _, _, _, _ = isolated
    lock.tryLock.return_value = False
    assert bootstrap.main() == 0
    bootstrap.show_existing.assert_called_once()
    bootstrap.StoreSetupDialog.assert_not_called()
    bootstrap.desktop_main.assert_not_called()
    lock.unlock.assert_not_called()
