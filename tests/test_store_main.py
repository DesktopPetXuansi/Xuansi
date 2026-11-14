"""商店首次配置完成后复用同一 Qt 应用和已取得的实例锁。"""

import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pet.__main__ as entry


def test_desktop_main_reuses_the_application_and_locked_instance(monkeypatch, tmp_path):
    application = SimpleNamespace(setQuitOnLastWindowClosed=Mock(), setApplicationName=Mock(),
                                  setWindowIcon=Mock(), exec=Mock(return_value=0))
    lock = SimpleNamespace(tryLock=Mock(side_effect=AssertionError("must not lock twice")), unlock=Mock())
    server = SimpleNamespace(close=Mock())
    loop = SimpleNamespace(call_soon_threadsafe=Mock(), stop=Mock())
    thread = SimpleNamespace(join=Mock())
    pet = SimpleNamespace(open_panel=Mock(), quit=Mock(), runtime=SimpleNamespace(loop=loop, thread=thread))
    monkeypatch.setattr(entry, "DATA", tmp_path / "data")
    monkeypatch.setattr(entry, "QApplication", Mock(side_effect=AssertionError("must not create another app")))
    monkeypatch.setattr(entry, "QIcon", Mock(return_value=object()))
    monkeypatch.setattr(entry, "configure_opengl_sharing", Mock(side_effect=AssertionError("already configured")))
    monkeypatch.setattr(entry.psutil, "Process", Mock(return_value=SimpleNamespace(nice=Mock())))
    monkeypatch.setattr(entry.ctypes, "windll", SimpleNamespace(user32=SimpleNamespace(
        SetProcessDpiAwarenessContext=Mock())))
    monkeypatch.setitem(sys.modules, "pet.app", SimpleNamespace(DesktopPet=Mock(return_value=pet)))
    monkeypatch.setitem(sys.modules, "pet.theme", SimpleNamespace(configure_fonts=Mock()))
    monkeypatch.setitem(sys.modules, "pet.instance", SimpleNamespace(
        listen_for_launch=Mock(return_value=server), show_existing=Mock()))
    monkeypatch.setattr(sys, "argv", ["pet"])

    entry.main(application=application, instance_lock=lock)

    lock.tryLock.assert_not_called()
    lock.unlock.assert_called_once()
    server.close.assert_called_once()
    application.exec.assert_called_once()
    loop.call_soon_threadsafe.assert_called_once_with(loop.stop)
