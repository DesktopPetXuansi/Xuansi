"""显式注册本机中文字体，使原生及无屏幕渲染使用相同字体。"""

from pathlib import Path

from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication, QDialog

from .form_wheel import install_form_wheel_filter
from .panel_style import style_for


def configure_fonts(app):
    install_form_wheel_filter(app)
    for name in ("msyh.ttc", "msyhbd.ttc", "msyhl.ttc"):
        path = Path("C:/Windows/Fonts") / name
        if path.exists():
            QFontDatabase.addApplicationFont(str(path))
    font = QFont("Microsoft YaHei")
    font.setPointSizeF(10.5)
    app.setFont(font)


class ThemedDialog(QDialog):
    """Standalone windows use the same live system palette as the control center."""

    def __init__(self, parent=None, *, embedded=False):
        super().__init__(parent)
        install_form_wheel_filter(QApplication.instance())
        if not embedded:
            hints = QApplication.styleHints()
            hints.colorSchemeChanged.connect(self._apply_color_scheme)
            self._apply_color_scheme(hints.colorScheme())

    def _apply_color_scheme(self, scheme):
        self.setStyleSheet(style_for(scheme))
