"""真实 Qt 表单的关闭保存；只写临时配置，不接触用户数据。"""

from dataclasses import replace

import pytest
from PySide6.QtWidgets import QApplication

from pet.config import Settings, load_settings, save_settings
from pet.panel import Panel
from pet.preferences import PreferencesPage


@pytest.fixture
def panel(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    window = Panel(Settings())
    window.show()
    app.processEvents()
    yield window
    window.hide()
    window.logs.hide()
    window.deleteLater()
    app.processEvents()


def test_close_persists_edits_and_reopened_panel_keeps_them(panel, tmp_path):
    path = tmp_path / "settings.json"

    def save(settings):
        panel.saving(True)
        save_settings(settings, path)
        panel.settings = settings
        panel.saving(False)
        panel.form.complete("")

    panel.settings_requested.connect(save)
    panel.persona.name.setText("关闭保存测试")
    panel.preferences.interval.setValue(37)
    panel.model_page.temperature.setValue(0.3)
    panel.close()
    assert path.exists(), "关闭时应保存修改，而不是只隐藏表单"
    assert not panel.isVisible()
    reloaded = load_settings(path)
    assert reloaded.name == "关闭保存测试"
    assert reloaded.interval == 37 and reloaded.temperature == 0.3
    panel.show()
    assert panel.persona.name.text() == reloaded.name
    assert panel.preferences.interval.value() == reloaded.interval


def test_close_waits_for_async_save_and_keeps_draft_on_failure(panel):
    pending = []
    panel.settings_requested.connect(lambda settings: (pending.append(settings), panel.saving(True)))
    panel.persona.name.setText("保留草稿")
    panel.close()
    assert panel.isVisible(), "保存完成前保留面板，以便显示失败原因"
    assert len(pending) == 1
    panel.close()
    assert len(pending) == 1
    panel.saving(False)
    panel.form.complete("磁盘无法写入")
    assert panel.isVisible() and panel.persona.name.text() == "保留草稿"
    assert "磁盘无法写入" in panel.form.hint.text()
    assert panel.settings.name == Settings().name


def test_invalid_draft_stays_open_with_reason(panel):
    panel.persona.name.setText("")
    panel.close()
    assert panel.isVisible()
    assert "名字" in panel.status.text()


def test_close_without_edits_does_not_save_or_interrupt_conversation(panel):
    saved = []
    panel.settings_requested.connect(saved.append)
    panel.close()
    assert not panel.isVisible() and not saved


def test_edits_during_save_are_not_hidden_or_lost(panel):
    pending = []
    panel.settings_requested.connect(lambda settings: (pending.append(settings), panel.saving(True)))
    panel.persona.name.setText("第一版")
    panel.close()
    assert pending
    panel.persona.name.setText("第二版")
    panel.settings = pending[0]
    panel.saving(False)
    panel.form.complete("")
    assert panel.isVisible() and panel.persona.name.text() == "第二版"
    assert "未保存" in panel.form.hint.text()


def test_unavailable_microphone_selection_is_preserved(panel):
    """设备尚未枚举或临时断开，不能保存成系统默认设备。"""
    settings = replace(Settings(), input_device=99)
    preferences = PreferencesPage(settings)
    assert preferences.apply(settings).input_device == 99
    preferences.set_devices([], 99)
    assert preferences.apply(settings).input_device == 99
    preferences.deleteLater()


def test_device_enumeration_keeps_users_new_selection(panel):
    preferences = PreferencesPage(replace(Settings(), input_device=99))
    preferences.device.setCurrentIndex(0)
    preferences.set_devices([(99, "测试麦克风")], 99)
    assert preferences.device.currentData() == -1
    preferences.deleteLater()
