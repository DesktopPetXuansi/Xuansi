"""桌宠入口，文件日志只记录运行状态；不自动打开麦克风。"""

import ctypes
import json
import logging
import os
import sys
from logging.handlers import RotatingFileHandler

import psutil
from PySide6.QtCore import QLockFile, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from .config import DATA, ROOT
from .live2d_session import configure_opengl_sharing


def update_health_check():
    """Read-only first launch probe, before logging or runtime construction."""
    nonce = os.environ.get("XUANSI_UPDATE_TRIAL_NONCE", "")
    if len(nonce) < 32 or not nonce.isascii():
        raise ValueError("缺少升级试运行凭据")
    from .config import load_settings_result

    loaded = load_settings_result()
    loaded.settings.validate()
    from . import app as _app  # noqa: F401 - verify key UI/runtime imports
    from .panel import Panel

    configure_opengl_sharing()
    application = QApplication([sys.argv[0]])
    panel = Panel(loaded.settings)
    panel.setEnabled(False)
    panel.show()

    def complete():
        panel.close()
        print(json.dumps({"nonce": nonce, "version": (ROOT / "VERSION").read_text(encoding="utf-8").strip()}), flush=True)
        application.quit()

    QTimer.singleShot(0, complete)
    return application.exec()


def configure_logging():
    DATA.mkdir(parents=True, exist_ok=True)
    if not logging.getLogger().handlers:
        handler = RotatingFileHandler(DATA / "pet.log", maxBytes=512 * 1024, backupCount=2, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        logging.basicConfig(level=logging.INFO, handlers=[handler])
    logging.getLogger("httpx").setLevel(logging.WARNING)


def main(*, application=None, instance_lock=None):
    configure_logging()
    psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
    # Windows / Qt / 全局鼠标钩子使用一致的每显示器 DPI 感知。
    ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    if application is None:
        configure_opengl_sharing()
        application = QApplication(sys.argv)
    app = application
    from .instance import listen_for_launch, show_existing

    # 商店首次配置可能已经持有锁；沿用该锁直到桌宠退出，避免重复启动。
    lock = instance_lock
    if lock is None:
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
    if "--update-health-check" in sys.argv:
        raise SystemExit(update_health_check())
    main()
