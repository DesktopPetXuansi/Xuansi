"""同页控制中心使用离屏 Qt，验证导航、草稿和组件显隐，不启动模型。"""

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QMenuBar, QTabWidget

from pet.config import Settings
from pet.panel import Panel


@pytest.fixture
def panel(monkeypatch, tmp_path):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    application = QApplication.instance() or QApplication([])
    application.setQuitOnLastWindowClosed(False)
    window = Panel(Settings())
    window.logs.path = tmp_path / "control-center.log"
    window.show()
    application.processEvents()
    yield window
    window.hide()
    window.logs.hide()
    window.deleteLater()
    application.processEvents()


def test_controls_share_one_scroll_page_without_tab_or_menu_windows(panel):
    assert not panel.findChildren(QTabWidget), "控制项应直接在同一页展开"
    assert not panel.findChildren(QMenuBar), "控制中心不再依赖多层菜单"
    for key in ("chat", "persona", "memory", "preferences", "model", "logs"):
        panel.open_section(key)
    for widget in (panel.chat, panel.persona, panel.memory, panel.preferences, panel.model_page, panel.logs):
        assert widget.isVisible() and widget.window() is panel
    assert panel.sections["chat"].expanded and panel.sections["model"].expanded


def test_navigation_keeps_unsaved_draft_and_focuses_the_existing_page(panel):
    panel.persona.name.setText("同页草稿")
    panel.open_configuration()
    panel.open_logs()
    assert panel.persona.name.text() == "同页草稿"
    assert "未保存" in panel.form.hint.text()
    assert panel.logs.window() is panel and not panel.logs.isWindow()
    assert panel.isVisible()


def test_mount_and_collapse_reuse_the_same_widget_and_stop_hidden_work(panel):
    calls = []
    content = QLabel("同一份表单")
    panel.mount_section("upload", content, on_open=lambda: calls.append("打开"))
    panel.open_section("upload")
    panel.open_section("upload")
    assert calls == ["打开"]
    assert content.window() is panel and content.isVisible()
    panel.collapse_section("upload")
    assert not content.isVisible()
    panel.open_section("upload")
    assert calls == ["打开", "打开"] and content.text() == "同一份表单"
    panel.open_logs()
    assert panel.logs.timer.isActive()
    panel.collapse_section("logs")
    assert not panel.logs.timer.isActive()


def test_unified_save_and_escape_preserve_the_existing_close_transaction(panel):
    pending = []
    panel.settings_requested.connect(pending.append)
    panel.persona.name.setText("统一保存")
    panel.save_button.click()
    assert len(pending) == 1 and pending[0].name == "统一保存"
    panel.settings = pending[0]
    panel.form.complete("")
    QTest.keyClick(panel.input, Qt.Key.Key_Escape)
    assert not panel.isVisible()


def test_navigation_places_the_requested_form_at_the_top_of_the_viewport(panel):
    for key in ("persona", "memory", "preferences", "model"):
        panel.open_section(key)
    QTest.qWait(30)
    point = panel.sections["model"].heading.mapTo(panel.scroll.viewport(), QPoint())
    assert 0 <= point.y() <= 24, "定位后应直接看到目标表单，而不是仅在页面底部露出标题"
