"""首次配置只在内存选择；设备与在线验证均使用离线替身。"""

import threading
import time
from dataclasses import asdict, replace
from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt, QThreadPool, QTimer
from PySide6.QtWidgets import QApplication, QDialog

from pet.ai.device import DeviceReport
from pet.ai.settings import ModelProfile
from pet.store_setup_form import StoreSetupDialog


@pytest.fixture
def form(monkeypatch, tmp_path):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    jobs = []
    monkeypatch.setattr("pet.store_setup_form.QThreadPool", SimpleNamespace(
        globalInstance=lambda: SimpleNamespace(start=jobs.append)))
    report = DeviceReport(system="Windows", architecture="AMD64", os_build=26200,
                          avx2=True, memory_available=64 * 2**30,
                          app_free=200 * 2**30, model_free=200 * 2**30,
                          app_volume="test", model_volume="test")
    monkeypatch.setattr("pet.store_setup_form.probe_device", lambda *args: report)
    dialog = StoreSetupDialog(tmp_path / "工作区", tmp_path / "模型")
    yield dialog, jobs, tmp_path, app
    dialog.reject()
    dialog.deleteLater()
    app.processEvents()


def choose(widget, value):
    widget.setCurrentIndex(widget.findData(value))


def test_first_run_dialog_follows_system_theme(form):
    dialog, _jobs, _tmp, app = form
    hints = app.styleHints()
    try:
        hints.colorSchemeChanged.emit(Qt.ColorScheme.Dark)
        assert "#202622" in dialog.styleSheet()
        hints.colorSchemeChanged.emit(Qt.ColorScheme.Light)
        assert "#fcfbf7" in dialog.styleSheet()
    finally:
        hints.colorSchemeChanged.emit(hints.colorScheme())


def online_profile(dialog):
    choose(dialog.ai.policy, "online_first")
    dialog.ai.set_profile(ModelProfile(endpoint="https://example.invalid/v1", model="synthetic",
                                      capabilities=("text", "image", "tools", "stream", "cancel")))
    dialog.ai.key.setText("in-memory-secret")
    profile = dialog.ai.profile()
    dialog.ai._validation = SimpleNamespace(request_id="test", profile=profile)
    verified = replace(profile, verified_at="test", verified_capabilities=profile.capabilities,
                       verification_fingerprint=profile.fingerprint())
    dialog.ai.validation_complete("test", verified, "")
    return verified


def test_local_confirmation_uses_background_probe_and_keeps_files_untouched(form):
    dialog, jobs, root, _ = form
    dialog.confirm_selection()
    assert dialog.selection is None and len(jobs) == 1
    assert not list(root.iterdir())
    jobs[0].run()
    assert dialog.result() != QDialog.DialogCode.Accepted
    assert dialog.selection is None
    dialog.confirm_selection()
    assert dialog.result() == QDialog.DialogCode.Accepted
    selection = dialog.selection
    assert selection.plan.mode == "local" and selection.plan.backend == "cpu"
    assert selection.plan.voice_components == ()
    assert selection.profile is None and selection.key is None
    assert not list(root.iterdir())


def test_voice_backup_and_summary_match_actual_plan_resources(form):
    dialog, jobs, _, _ = form
    dialog.backup.setChecked(True)
    dialog.voice["tts"].setChecked(True)
    dialog.confirm_selection()
    jobs[0].run()
    dialog.confirm_selection()
    plan = dialog.selection.plan
    assert plan.backup_model_ids == ("qwen3.5-4b",)
    assert plan.voice_components == ("tts",)
    assert "MiB" in dialog.summary.text()
    assert f"{plan.download_bytes / 2**20:.1f}" in dialog.summary.text()
    assert "9B" in dialog.summary.text() and "4B" in dialog.summary.text()
    assert "Melo" in dialog.summary.text()


def test_primary_light_model_does_not_download_itself_as_backup(form):
    dialog, jobs, _, _ = form
    dialog.backup.setChecked(True)
    choose(dialog.ai.local_model, "qwen3.5-4b")
    assert not dialog.backup.isEnabled()
    dialog.confirm_selection()
    jobs[0].run()
    dialog.confirm_selection()
    assert dialog.selection.plan.primary_model_id == "qwen3.5-4b"
    assert dialog.selection.plan.backup_model_ids == ()


def test_online_confirmation_requires_complete_validation_before_probe(form):
    dialog, jobs, _, _ = form
    choose(dialog.ai.policy, "online_first")
    dialog.ai.set_profile(ModelProfile(endpoint="https://example.invalid/v1", model="synthetic"))
    dialog.confirm_selection()
    assert not jobs and dialog.selection is None
    assert "验证" in dialog.status.text()


def test_verified_api_selection_keeps_key_in_memory_and_excludes_local_downloads(form, caplog):
    dialog, jobs, root, _ = form
    profile = online_profile(dialog)
    dialog.confirm_selection()
    jobs[0].run()
    dialog.confirm_selection()
    selection = dialog.selection
    assert selection.plan.mode == "api" and selection.plan.download_bytes == 0
    assert selection.profile == profile and selection.key == "in-memory-secret"
    assert selection.plan.credential_ref == profile.credential_ref
    assert "in-memory-secret" not in repr(selection)
    assert "in-memory-secret" not in str(asdict(selection.plan))
    assert "in-memory-secret" not in str(asdict(selection.profile))
    assert "in-memory-secret" not in caplog.text
    assert not list(root.iterdir())


def test_local_first_preserves_online_profile_and_selected_resources(form):
    dialog, jobs, _, _ = form
    profile = online_profile(dialog)
    choose(dialog.ai.policy, "local_first")
    dialog.confirm_selection()
    jobs[0].run()
    dialog.confirm_selection()
    assert dialog.selection.plan.mode == "local"
    assert dialog.selection.plan.policy == "local_first"
    assert dialog.selection.profile == profile
    assert dialog.selection.plan.download_bytes > 0


def test_rejected_relative_model_directory_preserves_user_choices(form):
    dialog, jobs, root, _ = form
    dialog.model_directory.setText("relative/models")
    dialog.voice["realtime"].setChecked(True)
    dialog.confirm_selection()
    assert not jobs and dialog.selection is None
    assert dialog.voice["realtime"].isChecked()
    assert dialog.model_directory.text() == "relative/models"
    assert not list(root.iterdir())


def test_cancel_ignores_late_probe_and_clears_key(form):
    dialog, jobs, root, _ = form
    online_profile(dialog)
    dialog.confirm_selection()
    dialog.reject()
    jobs[0].run()
    assert dialog.selection is None and not dialog.ai.key.text()
    assert dialog.result() == QDialog.DialogCode.Rejected
    assert not list(root.iterdir())


def test_device_failure_keeps_selections_and_allows_retry(form, monkeypatch):
    dialog, jobs, _, _ = form
    monkeypatch.setattr("pet.store_setup_form.probe_device", lambda *args: (_ for _ in ()).throw(OSError()))
    dialog.backup.setChecked(True)
    dialog.confirm_selection()
    jobs[0].run()
    assert dialog.selection is None and dialog.confirm.isEnabled()
    assert dialog.backup.isChecked() and "检测" in dialog.status.text()


def test_explicit_device_check_only_queues_work_and_never_accepts(form):
    dialog, jobs, root, _ = form
    dialog.detect_environment()
    assert len(jobs) == 1 and dialog.selection is None
    jobs[0].run()
    assert dialog.selection is None and dialog.result() != QDialog.DialogCode.Accepted
    assert not list(root.iterdir())


def test_empty_model_directory_is_rejected_without_probe(form):
    dialog, jobs, root, _ = form
    dialog.model_directory.clear()
    dialog.confirm_selection()
    assert not jobs and dialog.selection is None
    assert not list(root.iterdir())


def test_edit_during_probe_invalidates_old_result_and_allows_detection(form):
    dialog, jobs, _, _ = form
    dialog.confirm_selection()
    dialog.voice["tts"].setChecked(True)
    jobs[0].run()
    assert dialog.selection is None and dialog.ai.detect.isEnabled()
    dialog.confirm_selection()
    assert len(jobs) == 2


def test_prepared_download_budget_is_shown_before_final_confirmation(form):
    dialog, jobs, _, _ = form
    dialog.confirm_selection()
    jobs[0].run()
    assert dialog.selection is None
    assert "再次确认" in dialog.status.text()
    dialog.backup.setChecked(True)
    dialog.confirm_selection()
    assert len(jobs) == 2 and dialog.selection is None


def test_real_worker_does_not_block_qt_event_loop(form, monkeypatch):
    dialog, _, _, app = form
    started, release = threading.Event(), threading.Event()
    monkeypatch.setattr("pet.store_setup_form.QThreadPool", QThreadPool)

    def slow_probe(*args):
        started.set()
        assert release.wait(2)
        return DeviceReport()

    monkeypatch.setattr("pet.store_setup_form.probe_device", slow_probe)
    dialog.confirm_selection()
    try:
        assert started.wait(1)
        ticks = []
        QTimer.singleShot(0, lambda: ticks.append(True))
        app.processEvents()
        assert ticks and dialog.selection is None
    finally:
        release.set()
    deadline = time.monotonic() + 2
    while dialog._ready is None and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.001)
    assert dialog._ready is not None


def test_known_insufficient_resources_stop_confirmation_without_clearing_choices(form, monkeypatch):
    dialog, jobs, _, _ = form
    monkeypatch.setattr("pet.store_setup_form.probe_device", lambda *args: DeviceReport(memory_available=1))
    dialog.voice["asr"].setChecked(True)
    dialog.confirm_selection()
    jobs[0].run()
    assert dialog._ready is None and dialog.selection is None
    assert "不足" in dialog.status.text() and dialog.voice["asr"].isChecked()


def test_edit_after_returning_to_accepted_dialog_clears_old_selection(form):
    dialog, jobs, _, _ = form
    dialog.confirm_selection()
    jobs[0].run()
    dialog.confirm_selection()
    assert dialog.selection is not None
    dialog.voice["tts"].setChecked(True)
    assert dialog.selection is None
    assert dialog.voice["tts"].isChecked()
