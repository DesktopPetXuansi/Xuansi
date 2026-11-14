"""Update reminders persist without blocking a user's manual check."""

import time
from pathlib import Path

from PySide6.QtWidgets import QApplication

from pet import update_page


def test_reminder_and_skip_keep_manual_check_available(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    version_root = tmp_path / "versions" / "0.9.1"
    version_root.mkdir(parents=True)
    (version_root / "VERSION").write_text("0.9.1", encoding="utf-8")
    (tmp_path / "Xuansi.exe").write_bytes(b"fixture")
    (tmp_path / "update").mkdir()
    (tmp_path / "update" / "update-state.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(update_page, "ROOT", version_root)
    monkeypatch.setattr(update_page, "DATA", tmp_path / "data")
    page = update_page.UpdatePage()
    page.candidate = {"version": "0.9.2", "sha256": "a" * 64, "bytes": 100}
    page.downloaded = True
    page.remind_later()
    assert not page.downloaded
    assert update_page.read_preferences(page.preferences_path)["remindAfter"] > time.time()
    calls = []
    monkeypatch.setattr(page, "_run", lambda operation, automatic=False: calls.append((operation, automatic)))
    page._automatic_check()
    assert calls == []
    page.check()
    assert calls == [("check", False)]
    page.skip_version()
    assert update_page.read_preferences(page.preferences_path)["skipVersion"] == "0.9.2"
    page.periodic.stop()
    page.deleteLater()
    app.processEvents()


def test_old_preferences_gain_reminder_defaults(tmp_path):
    path = Path(tmp_path) / "prefs.json"
    path.write_text('{"autoCheck":true,"autoDownload":false,"installOnExit":false}', encoding="utf-8")
    preferences = update_page.read_preferences(path)
    assert preferences["skipVersion"] == "" and preferences["remindAfter"] == 0


def test_completed_bundle_is_available_after_reopening_update_page(tmp_path):
    launcher = tmp_path / "Xuansi.exe"
    candidate = {"sha256": "b" * 64, "bytes": 3}
    cache = tmp_path / "update/downloads"
    cache.mkdir(parents=True)
    archive = cache / (candidate["sha256"] + ".zip")
    assert not update_page.cached_bundle(launcher, candidate)
    archive.write_bytes(b"zip")
    assert update_page.cached_bundle(launcher, candidate)
    archive.write_bytes(b"incomplete")
    assert not update_page.cached_bundle(launcher, candidate)
