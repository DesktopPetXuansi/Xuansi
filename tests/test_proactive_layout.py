"""小窗口中主动问候开关仍可访问并作为独立设置保存。"""

from PySide6.QtCore import QPoint, QRect
from PySide6.QtWidgets import QApplication

from pet.config import Settings
from pet.panel import Panel


def test_proactive_checkbox_is_reachable_in_small_control_center(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    panel = Panel(Settings())
    try:
        panel.resize(520, 480)
        panel.show()
        panel.open_section("preferences")
        app.processEvents()
        section = panel.sections["preferences"]
        checkbox = panel.preferences.proactive_chat
        section.ensureWidgetVisible(checkbox)
        app.processEvents()
        rectangle = QRect(checkbox.mapTo(section.viewport(), QPoint()), checkbox.size())
        assert section.horizontalScrollBar().maximum() == 0
        assert section.viewport().rect().contains(rectangle)
        checkbox.click()
        draft = panel.form.read()
        assert draft.proactive_chat and not draft.speak_observations
    finally:
        panel.hide()
        panel.deleteLater()
        app.processEvents()
