"""商店版启动：先完成首次配置，再沿用桌宠的应用和实例锁。"""

import ctypes
import logging
import sys

from PySide6.QtCore import QLockFile
from PySide6.QtWidgets import QApplication, QDialog

from .__main__ import configure_logging
from .__main__ import main as desktop_main
from .config import DATA, WRITABLE_ROOT
from .instance import listen_for_launch, show_existing
from .live2d_session import configure_opengl_sharing
from .store_progress import StoreProgressDialog
from .store_setup_form import StoreSetupDialog
from .theme import configure_fonts

LOG = logging.getLogger(__name__)


def configure_dpi():
    # 与桌宠入口一致，先设置 DPI 再创建任何 Qt 窗口。
    ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))


class _Activation:
    def __init__(self):
        self.window = None

    def show(self):
        if self.window is not None:
            self.window.showNormal()
            self.window.raise_()
            self.window.activateWindow()


def _close_server(server):
    if server is not None:
        server.close()
        server.newConnection.disconnect()
        server.deleteLater()


def main():
    configure_dpi()
    configure_opengl_sharing()
    application = QApplication(sys.argv)
    application.setQuitOnLastWindowClosed(False)
    DATA.mkdir(parents=True, exist_ok=True)
    lock = QLockFile(str(DATA / "app.lock"))
    if not lock.tryLock(0):
        show_existing()
        return 0
    server = None
    try:
        configure_logging()
        configure_fonts(application)
        if not (DATA / "settings.json").exists():
            activation = _Activation()
            server = listen_for_launch(application, activation.show)
            setup = StoreSetupDialog(WRITABLE_ROOT, WRITABLE_ROOT / "models")
            activation.window = setup
            if setup.exec() != QDialog.DialogCode.Accepted:
                LOG.info("首次配置已取消")
                return 0
            selection = setup.selection
            # 提取内存快照后清空密码框，不将密钥交给子进程或写入普通文件。
            setup.ai.key.clear()
            progress = StoreProgressDialog(WRITABLE_ROOT, selection)
            activation.window = progress
            result = progress.exec()
            # 窗口关闭后不让密码快照陪同桌宠进程长期驻留内存。
            selection = None
            setup.selection = None
            if result != QDialog.DialogCode.Accepted:
                LOG.info("首次资源准备未完成")
                return 0
            _close_server(server)
            server = None
        LOG.info("商店版进入桌宠")
        desktop_main(application=application, instance_lock=lock)
        return 0
    finally:
        _close_server(server)
        if lock.isLocked():
            lock.unlock()
