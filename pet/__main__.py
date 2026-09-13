"""桌宠入口，文件日志只记录运行状态；不自动打开麦克风。"""

import ctypes
import logging
import sys
from logging.handlers import RotatingFileHandler

import psutil
from PySide6.QtCore import QLockFile, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from .config import DATA, ROOT


def main():
    DATA.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(DATA / "pet.log", maxBytes=512 * 1024, backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler])
    logging.getLogger("httpx").setLevel(logging.WARNING)
    psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
    # Windows / Qt / 全局鼠标钩子使用一致的每显示器 DPI 感知。
    ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    app = QApplication(sys.argv)
    from .instance import listen_for_launch, show_existing

    lock = QLockFile(str(DATA / "app.lock"))
    if not lock.tryLock(0):
        show_existing()
        return
    from .theme import configure_fonts

    configure_fonts(app)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("Xuansi Local Companion")
    app.setWindowIcon(QIcon(str(ROOT / "assets/xuansi/icon.ico")))
    from .app import DesktopPet

    # 冒烟验收只验证生命周期，不观察用户正在工作的画面。
    from .config import Settings

    pet = DesktopPet(app, Settings(observe=False) if "--smoke" in sys.argv else None)
    server = listen_for_launch(app, pet.open_panel)
    if "--panel" in sys.argv:
        pet.open_panel()
    if "--smoke" in sys.argv:
        QTimer.singleShot(5000, pet.quit)
    try:
        app.exec()
    finally:
        server.close()
        pet.runtime.loop.call_soon_threadsafe(pet.runtime.loop.stop)
        pet.runtime.thread.join(timeout=2)
        lock.unlock()


if __name__ == "__main__":
    main()
