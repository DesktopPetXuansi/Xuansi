"""显式注册本机中文字体，使原生及无屏幕渲染使用相同字体。"""

from pathlib import Path

from PySide6.QtGui import QFont, QFontDatabase


def configure_fonts(app):
    for name in ("msyh.ttc", "msyhbd.ttc", "msyhl.ttc"):
        path = Path("C:/Windows/Fonts") / name
        if path.exists():
            QFontDatabase.addApplicationFont(str(path))
    app.setFont(QFont("Microsoft YaHei", 10))
