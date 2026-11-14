"""主动问候的默认设置、本机限频和不含正文的持久状态。"""

import json
from datetime import datetime, timedelta

import pytest
from PySide6.QtWidgets import QApplication

from pet.config import Settings, load_settings, save_settings
from pet.preferences import PreferencesPage
from pet.proactive_chat import ProactiveGate, ProactiveLimiter


def test_old_settings_keep_proactive_chat_disabled(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text('{"speak_observations": true}', encoding="utf-8")
    settings = load_settings(path)
    assert not settings.proactive_chat
    assert settings.speak_observations


def test_proactive_setting_survives_restart_without_changing_observation_speech(tmp_path):
    path = tmp_path / "settings.json"
    save_settings(Settings(proactive_chat=True, speak_observations=False), path)
    loaded = load_settings(path)
    assert loaded.proactive_chat and not loaded.speak_observations


def test_proactive_checkbox_is_independent_of_observation_speech(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    page = PreferencesPage(Settings(speak_observations=True))
    try:
        assert not page.proactive_chat.isChecked()
        page.proactive_chat.setChecked(True)
        saved = page.apply(Settings(speak_observations=True)).validate()
        assert saved.proactive_chat and saved.speak_observations
        assert page.proactive_chat.accessibleName()
    finally:
        page.deleteLater()
        app.processEvents()


def test_gate_waits_an_hour_and_requires_recent_real_activity():
    gate = ProactiveGate(100)
    gate.record_activity(3699)
    assert not gate.can_attempt(3699, eligible=True)
    assert gate.can_attempt(3700, eligible=True)
    assert not gate.can_attempt(3700, eligible=False)
    assert not gate.can_attempt(3820, eligible=True)


def test_attempt_backoff_prevents_polling_retries():
    gate = ProactiveGate(0)
    gate.record_activity(3600)
    assert gate.can_attempt(3600, eligible=True)
    gate.record_attempt(3600)
    gate.record_activity(3899)
    assert not gate.can_attempt(3899, eligible=True)
    assert gate.can_attempt(3900, eligible=True)


def test_limiter_survives_restart_and_daily_boundary(tmp_path):
    path = tmp_path / "proactive.json"
    now = datetime(2026, 10, 31, 10).timestamp()
    limiter = ProactiveLimiter(path)
    first = limiter.reserve(now)
    assert first
    assert ProactiveLimiter(path).reserve(now + 3599) is None
    second = ProactiveLimiter(path).reserve(now + 3600)
    assert second and second != first
    assert ProactiveLimiter(path).reserve(now + 7200) is None
    tomorrow = (datetime.fromtimestamp(now) + timedelta(days=1)).timestamp()
    assert ProactiveLimiter(path).reserve(tomorrow)
    state = json.loads(path.read_text(encoding="utf-8"))
    assert {"day", "last_at", "count"} <= set(state)
    assert state["count"] == 1
    assert first not in path.read_text(encoding="utf-8")


def test_shared_quota_and_quiet_today_survive_restart(tmp_path):
    path = tmp_path / "proactive.json"
    now = datetime(2026, 10, 31, 10).timestamp()
    limiter = ProactiveLimiter(path)
    first = limiter.reserve(now)
    limiter.mark_shown(first, now)
    assert not limiter.reserve_observation(now + 5)
    assert limiter.reserve_observation(now + 3600)
    assert limiter.reserve(now + 7200) is None
    limiter.quiet_today(now)
    assert not ProactiveLimiter(path).available(now + 10800)
    assert ProactiveLimiter(path).available(now + 86400)


def test_clock_rollback_and_corrupt_state_fail_closed(tmp_path, caplog):
    path = tmp_path / "proactive.json"
    now = datetime(2026, 10, 31, 10).timestamp()
    limiter = ProactiveLimiter(path)
    assert limiter.reserve(now)
    assert limiter.reserve(now - 86400) is None
    path.write_text("损坏记录", encoding="utf-8")
    assert limiter.reserve(now + 86400) is None
    assert path.read_text(encoding="utf-8") == "损坏记录"
    assert "损坏记录" not in caplog.text


@pytest.mark.parametrize("state", [
    {"day": "2026-10-31", "last_at": True, "count": 1},
    {"day": "2026-10-31", "last_at": 1, "count": True},
    {"day": "2026-10-31", "last_at": float("nan"), "count": 1},
])
def test_invalid_limiter_types_do_not_reset_the_quota(tmp_path, state):
    path = tmp_path / "proactive.json"
    path.write_text(json.dumps(state), encoding="utf-8")
    assert ProactiveLimiter(path).reserve(datetime(2026, 10, 31, 12).timestamp()) is None
