"""控制中心的浏览器式标签使用离屏 Qt，不启动模型或读取用户数据。"""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QMenuBar, QTabBar

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


def test_horizontal_tabs_switch_content_inside_one_control_window(panel):
    assert panel.findChildren(QTabBar) == [panel.navigation.bar]
    assert not panel.findChildren(QMenuBar), "控制中心不再依赖多层菜单"
    assert panel.navigation.bar.count() == len(panel.sections) == 9
    for key in ("chat", "persona", "memory", "preferences", "model", "logs"):
        panel.open_section(key)
        assert panel.navigation.current_key == key
        assert [name for name, page in panel.sections.items() if page.active] == [key]
    for widget in (panel.chat, panel.persona, panel.memory, panel.preferences, panel.model_page, panel.logs):
        assert widget.window() is panel
    assert panel.logs.isVisible() and not panel.persona.isVisible()


def test_navigation_keeps_unsaved_draft_and_focuses_the_existing_page(panel):
    panel.persona.name.setText("同页草稿")
    panel.open_configuration()
    panel.open_logs()
    assert panel.persona.name.text() == "同页草稿"
    assert "未保存" in panel.form.hint.text()
    assert panel.logs.window() is panel and not panel.logs.isWindow()
    assert panel.isVisible()


def test_tab_switching_reuses_widgets_and_stops_hidden_work(panel):
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
    panel.open_section("chat")
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


def test_clicking_a_tab_and_the_list_menu_use_the_same_navigation(panel):
    bar = panel.navigation.bar
    QTest.mouseClick(bar, Qt.MouseButton.LeftButton, pos=bar.tabRect(1).center())
    assert panel.navigation.current_key == "persona" and panel.persona.isVisible()
    for action in panel.navigation.menu.actions():
        action.trigger()
        assert panel.navigation.current_key == action.data()
        assert panel.navigation.stack.currentWidget() is panel.sections[action.data()]
        action.trigger()  # 重复选择当前标签也必须保留唯一的勾选项。
        assert [item.data() for item in panel.navigation.menu.actions() if item.isChecked()] == [action.data()]
    assert {action.data() for action in panel.navigation.menu.actions()} == set(panel.sections)


def test_browser_keyboard_shortcuts_switch_tabs_without_sending_messages(panel):
    sent = []
    panel.send_requested.connect(lambda *values: sent.append(values))
    panel.input.setText("未发送的草稿")
    panel.input.setFocus()
    QTest.keyClick(panel.input, Qt.Key.Key_Tab, Qt.KeyboardModifier.ControlModifier)
    assert panel.navigation.current_key == "persona"
    QTest.keyClick(panel.persona.name, Qt.Key.Key_Tab,
                   Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
    assert panel.navigation.current_key == "chat"
    assert panel.input.text() == "未发送的草稿" and not sent


def test_each_tab_keeps_its_scroll_position_when_switching(panel):
    content = QLabel("长表单")
    content.setMinimumHeight(1600)
    panel.mount_section("upload", content)
    panel.open_section("upload")
    QTest.qWait(20)
    scroll = panel.sections["upload"].verticalScrollBar()
    assert scroll.maximum() > 120
    scroll.setValue(120)
    panel.open_section("chat")
    panel.open_section("upload")
    QTest.qWait(20)
    assert scroll.value() == 120 and content.window() is panel


def test_leaving_an_embedded_tab_never_reopens_a_hidden_center(panel):
    panel.open_section("upload")
    panel.hide()
    panel.collapse_section("upload")
    assert panel.navigation.current_key == "chat"
    assert not panel.isVisible()
