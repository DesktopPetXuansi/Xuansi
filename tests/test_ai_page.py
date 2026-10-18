"""在线配置界面的秘密草稿与快照事务；不请求真实服务商。"""

import asyncio
import threading
from dataclasses import replace
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication, QLineEdit

from pet.ai.credentials import new_ref
from pet.ai.settings import AISettings, ModelProfile
from pet.ai_page import AIPage
from pet.ai_tasks import AIResults, ValidateProfile
from pet.config import MODELS, Settings
from pet.panel import Panel
from pet.preferences import PreferencesPage


@pytest.fixture
def page(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    widget = AIPage(AISettings())
    yield widget
    widget.hide()
    widget.deleteLater()
    app.processEvents()


def test_key_is_password_only_draft_and_rotation_invalidates_evidence(page):
    original = ModelProfile(endpoint="https://example.test/v1", model="model", credential_ref="old")
    page.set_profile(replace(original, verified_at="today", verified_capabilities=("text",),
                             verification_fingerprint=original.fingerprint()))
    page.key.setText("test-key")
    profile, key = page.credential_draft()
    assert page.key.echoMode() == QLineEdit.EchoMode.Password
    assert key == "test-key" and profile.credential_ref != "old"
    assert not profile.is_verified("text")
    assert "test-key" not in str(page.apply(AISettings()).to_dict())


def test_success_only_clears_matching_key_snapshot(page):
    page.key.setText("first")
    snapshot = page.credential_draft()
    page.key.setText("second")
    page.credentials_saved(snapshot)
    assert page.key.text() == "second"
    snapshot = page.credential_draft()
    page.credentials_saved(snapshot)
    assert page.key.text() == "" and not page.credential_changed()
    assert page.profile().credential_ref == snapshot[0].credential_ref


def test_late_validation_cannot_overwrite_new_profile(page):
    page.set_profile(ModelProfile(endpoint="https://example.test/v1", model="first"))
    candidate = page.profile()
    page.model.setText("second")
    page.validation_complete(candidate.fingerprint(), replace(candidate, verified_at="today",
                             verification_fingerprint=candidate.fingerprint()), "")
    assert page.profile().model == "second"
    assert not page.profile().verified_at


def test_cloud_permissions_default_off_and_are_independent(page):
    assert not page.cloud_memory.isChecked() and not page.cloud_observation.isChecked()
    page.cloud_memory.setChecked(True)
    settings = page.apply(AISettings())
    assert settings.cloud_memory and not settings.cloud_observation


def test_key_only_edit_is_unsaved_in_panel(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    panel = Panel(Settings())
    assert not panel.form.changed()
    panel.model_page.ai_page.key.setText("draft")
    assert panel.form.changed()
    assert "未保存" in panel.form.hint.text()
    panel.hide()
    panel.deleteLater()
    app.processEvents()


def test_local_choice_updates_paired_paths_without_overwriting_initial_custom_path(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    panel = Panel(replace(Settings(), model_path="custom/model.gguf", projector_path="custom/vision.gguf"))
    page = panel.model_page
    assert page.model.text() == "custom/model.gguf"
    page.ai_page.model_dir.setText("E:/models")
    page.ai_page.local_model.setCurrentIndex(page.ai_page.local_model.findData("qwen3.5-4b"))
    assert page.model.text().replace("\\", "/") == "E:/models/qwen3.5-4b/Qwen3.5-4B-Q4_K_M.gguf"
    assert page.projector.text().replace("\\", "/") == "E:/models/qwen3.5-4b/mmproj-F16.gguf"
    page.ai_page.backend.setCurrentIndex(page.ai_page.backend.findData("cpu"))
    assert page.apply(panel.settings).ai.local_backend == "cpu"
    panel.hide()
    panel.deleteLater()
    app.processEvents()


def test_endpoint_change_does_not_reuse_saved_credential(page):
    page.set_profile(ModelProfile(endpoint="https://first.test/v1", credential_ref="saved"))
    page.endpoint.setText("https://second.test/v1")
    assert not page.profile().credential_ref
    page.key.setText("new")
    first_ref = page.profile().credential_ref
    page.endpoint.setText("https://third.test/v1")
    assert page.profile().credential_ref and page.profile().credential_ref != first_ref


def test_same_profile_late_result_after_cancel_is_ignored(page):
    candidate = page.profile()
    cancelled = []
    page._validation = SimpleNamespace(request_id="old", profile=candidate, cancel=lambda: cancelled.append(True))
    page.cancel_validation()
    page.validation_complete("old", replace(candidate, verified_at="today",
                             verification_fingerprint=candidate.fingerprint()), "")
    assert cancelled and not page.profile().verified_at


def test_successful_validation_updates_evidence_and_keeps_key(page):
    page.endpoint.setText("https://example.test/v1")
    page.key.setText("draft")
    candidate = page.profile()
    page._validation = SimpleNamespace(request_id="current", profile=candidate)
    verified = replace(candidate, verified_at="today", verified_capabilities=("text",),
                       verification_fingerprint=candidate.fingerprint())
    page.validation_complete("current", verified, "")
    assert page.profile().is_verified("text") and page.key.text() == "draft"


def test_uninstalled_voice_is_disabled_without_rewriting_preferences(page):
    settings = replace(Settings(), ai=replace(AISettings(), voice_components=()))
    preferences = PreferencesPage(settings)
    assert not preferences.speak.isEnabled() and not preferences.device.isEnabled()
    assert preferences.apply(settings) == settings
    preferences.deleteLater()


def test_background_validation_cancel_closes_coroutine_and_releases_key(page, monkeypatch):
    started, closed = threading.Event(), threading.Event()

    async def validate(profile, key):
        started.set()
        try:
            await asyncio.sleep(30)
        finally:
            closed.set()

    monkeypatch.setattr("pet.ai.validation.validate_profile", validate)
    worker = ValidateProfile(AIResults(), ModelProfile(), "in-memory-only", "request")
    thread = threading.Thread(target=worker.run)
    thread.start()
    assert started.wait(2), "验证必须在后台启动"
    worker.cancel()
    thread.join(2)
    assert not thread.is_alive() and closed.is_set()
    assert worker.key is None


@pytest.fixture
def saved_page(page):
    endpoint = "https://example.test/v1"
    profile = ModelProfile(endpoint=endpoint, model="original", credential_ref=new_ref(endpoint))
    widget = AIPage(AISettings(profile=profile))
    yield widget, profile
    widget.deleteLater()


def test_clearing_validated_key_restores_saved_reference(saved_page):
    widget, original = saved_page
    widget.key.setText("new-key-draft")
    candidate = widget.profile()
    widget._validation = SimpleNamespace(request_id="validation", profile=candidate)
    verified = replace(candidate, verified_at="today", verified_capabilities=("text",),
                       verification_fingerprint=candidate.fingerprint())
    widget.validation_complete("validation", verified, "")
    assert widget.profile().is_verified("text")
    widget.key.clear()
    assert widget.credential_draft() is None
    assert widget.profile().credential_ref == original.credential_ref
    assert not widget.profile().is_verified("text")
    widget.endpoint.setText("https://different.test/v1")
    assert not widget.profile().credential_ref


def test_model_edit_during_key_save_can_be_saved_again(saved_page):
    widget, _ = saved_page
    widget.key.setText("new-key-draft")
    snapshot = widget.credential_draft()
    widget.model.setText("edited-during-save")
    widget.credentials_saved(snapshot)
    next_snapshot = widget.credential_draft()
    assert next_snapshot[0].model == "edited-during-save"
    assert next_snapshot[1] == snapshot[1]
    assert next_snapshot[0].credential_ref != snapshot[0].credential_ref
    widget.credentials_saved(next_snapshot)
    assert not widget.credential_changed()
    assert widget.profile() == next_snapshot[0]


def test_successful_snapshot_becomes_baseline_even_after_user_changes_key(saved_page):
    widget, _ = saved_page
    widget.key.setText("first")
    snapshot = widget.credential_draft()
    widget.key.setText("second")
    widget.credentials_saved(snapshot)
    assert widget.key.text() == "second"
    widget.key.clear()
    assert widget.profile().credential_ref == snapshot[0].credential_ref


def test_default_device_probe_uses_actual_model_root(page, monkeypatch):
    tasks = []
    monkeypatch.setattr("pet.ai_page.QThreadPool", SimpleNamespace(
        globalInstance=lambda: SimpleNamespace(start=tasks.append)))
    page.probe()
    assert tasks[0].model_dir == MODELS
