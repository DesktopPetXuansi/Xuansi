"""设置易懂化的交互回归；用合成配置检查草稿、折叠和模式切换。"""

import logging
from dataclasses import replace
from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from pet.ai.device import DeviceReport, GpuReport
from pet.ai.settings import AISettings, ModelProfile
from pet.config import Settings
from pet.panel import Panel

LOG = logging.getLogger(__name__)


@pytest.fixture
def make_panel(monkeypatch, tmp_path):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    windows = []

    def create(settings=Settings()):
        panel = Panel(settings)
        panel.logs.path = tmp_path / "usability.log"
        windows.append(panel)
        panel.open_section("model")
        panel.resize(880, 760)
        app.processEvents()
        return panel

    yield create
    for panel in windows:
        panel.hide()
        panel.deleteLater()
    app.processEvents()


def test_advanced_settings_are_hidden_and_keyboard_toggle_keeps_configuration(make_panel):
    settings = replace(Settings(), temperature=0.3, gpu_layers=12, model_path="custom/model.gguf")
    panel = make_panel(settings)
    page = panel.model_page
    assert not page.temperature.isVisible() and not page.ai_page.backend.isVisible()
    assert not panel.form.changed(), "初始化应保留已有手动参数，不产生未保存修改"
    toggle = page.ai_page.advanced.toggle
    toggle.setFocus()
    QTest.keyClick(toggle, Qt.Key.Key_Space)
    assert page.temperature.isVisible() and page.ai_page.backend.isVisible()
    assert page.apply(settings) == settings
    assert not panel.form.changed(), "展开高级设置只改变显示"
    QTest.keyClick(toggle, Qt.Key.Key_Space)
    assert not page.temperature.isVisible()
    assert page.apply(settings) == settings


@pytest.mark.parametrize("policy,local,online", [
    ("local_only", True, False), ("local_first", True, True), ("online_first", False, True),
])
def test_run_mode_shows_needed_fields_and_preserves_other_drafts(make_panel, policy, local, online):
    panel = make_panel()
    page = panel.model_page.ai_page
    page.endpoint.setText("https://example.test/v1")
    page.model.setText("custom-model")
    page.key.setText("test-only-draft")
    page.cloud_memory.setChecked(True)
    page.policy.setCurrentIndex(page.policy.findData(policy))
    QApplication.instance().processEvents()
    assert page.local_model.isVisible() == local
    assert page.presets.isVisible() == online
    assert page.key.isVisible() == online
    assert page.cloud_memory.isVisible() == online
    assert page.profile().model == "custom-model" and page.key.text() == "test-only-draft"
    assert page.cloud_memory.isChecked() and not page.cloud_observation.isChecked()


def test_folding_parameters_keeps_unsaved_values_and_running_validation(make_panel):
    panel = make_panel()
    page = panel.model_page
    page.temperature.setValue(0.4)
    snapshot = panel.form.read()
    cancelled = []
    page.ai_page._validation = SimpleNamespace(cancel=lambda: cancelled.append(True))
    try:
        page.ai_page.advanced.toggle.click()
        page.ai_page.advanced.toggle.click()
        assert panel.form.read() == snapshot and panel.form.changed()
        assert not cancelled, "折叠参数不能触发整个模型页的隐藏取消逻辑"
    finally:
        page.ai_page._validation = None


def test_preset_selection_fills_technical_fields_without_clearing_key_or_privacy(make_panel):
    page = make_panel().model_page.ai_page
    page.policy.setCurrentIndex(page.policy.findData("online_first"))
    page.key.setText("test-only-draft")
    index = next(i for i in range(page.presets.count())
                 if page.presets.itemData(i) and page.presets.itemData(i).provider == "deepseek")
    page.presets.setCurrentIndex(index)
    page.presets.activated.emit(index)
    profile = page.profile()
    assert profile.provider == "deepseek" and profile.endpoint and profile.model
    assert "tools" in profile.capabilities
    assert page.key.text() == "test-only-draft"
    assert not page.cloud_memory.isChecked() and not page.cloud_observation.isChecked()
    assert not page.endpoint.isVisible(), "选择服务商后无需先理解 API 地址与能力声明"
    assert "https://" in page.key_help.text(), "提供所选服务商的官方密钥入口"


def test_result_names_verified_and_unverified_capabilities_separately(make_panel):
    profile = ModelProfile(endpoint="https://example.test/v1", model="demo",
                           capabilities=("text", "image", "tools"))
    profile = replace(profile, verified_at="today", verified_capabilities=("text",),
                      verification_fingerprint=profile.fingerprint())
    page = make_panel(replace(Settings(), ai=AISettings(policy="online_first", profile=profile)))
    status = page.model_page.ai_page.validation_status.text()
    assert "已通过：文字聊天" in status
    assert "未验证：看图、使用工具" in status


def test_resource_recommendation_preserves_manual_choices_and_unknown_is_explicit(make_panel):
    page = make_panel().model_page.ai_page
    report = DeviceReport(system="Windows", architecture="AMD64", os_build=22631,
                          memory_total=32 * 2**30, memory_available=20 * 2**30, avx2=True,
                          gpus=(GpuReport("合成显卡", 16 * 2**30, 16 * 2**30, "555.0"),),
                          app_free=40 * 2**30, model_free=40 * 2**30)
    original = page.apply(AISettings())
    page._device_complete(page._generation, report, "")
    assert "推荐" in page.device_status.text() and "未实测" in page.device_status.text()
    assert page.apply(AISettings()) == original, "检测提供建议，用户选择前不能覆盖配置"
    page._device_complete(page._generation, DeviceReport(), "")
    assert "无法确认" in page.device_status.text()
    LOG.info("本机推荐检查通过，未知环境未被标记为已验证推荐")
