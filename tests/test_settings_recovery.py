"""配置恢复只回退无效字段，后续保存不能丢失原始配置。"""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from pet.config import Settings, load_settings, save_settings


@pytest.mark.parametrize("invalid", [{"interval": 0}, {"speed": "wrong"}, {"ai": {"policy": "wrong"}}])
def test_invalid_field_preserves_other_user_preferences(tmp_path, invalid):
    path = tmp_path / "settings.json"
    raw = {"name": "保留名字", "persona": "保留人设", "model_path": "E:/custom/model.gguf", **invalid}
    original = json.dumps(raw, ensure_ascii=False).encode("utf-8")
    path.write_bytes(original)

    loaded = load_settings(path)

    assert loaded.name == raw["name"]
    assert loaded.persona == raw["persona"]
    assert loaded.model_path == raw["model_path"]
    assert loaded.validate() == loaded
    assert path.read_bytes() == original


def test_recovery_report_explains_fields_without_exposing_values(tmp_path):
    from pet.config import load_settings_result

    path = tmp_path / "settings.json"
    path.write_text('{"name":"保留名字","interval":0}', encoding="utf-8")
    result = load_settings_result(path)
    assert result.settings.name == "保留名字"
    assert "interval" in result.warning
    assert "保留名字" not in result.warning


def test_saving_recovered_settings_keeps_original_bytes_in_backup(tmp_path):
    path = tmp_path / "settings.json"
    original = b'{"name":"custom","interval":0}'
    path.write_bytes(original)
    loaded = load_settings(path)

    save_settings(replace(loaded, audio_avoidance=False), path)

    assert load_settings(path).name == "custom"
    assert not load_settings(path).audio_avoidance
    backups = list(tmp_path.glob("settings.json.*.bak"))
    assert len(backups) == 1
    assert backups[0].read_bytes() == original
    # 恢复后的正常保存不重复创建备份。
    save_settings(replace(load_settings(path), observe=False), path)
    assert list(tmp_path.glob("settings.json.*.bak")) == backups


@pytest.mark.parametrize("original", [b"{broken", b"null", b"[]", b"\xff\xfe"])
def test_unreadable_settings_cannot_be_overwritten_by_defaults(tmp_path, original):
    path = tmp_path / "settings.json"
    path.write_bytes(original)
    loaded = load_settings(path)

    with pytest.raises(ValueError, match="原配置|修复"):
        save_settings(replace(loaded, name="new name"), path)

    assert path.read_bytes() == original


def test_future_ai_schema_preserves_other_fields_and_cannot_be_downgraded(tmp_path):
    path = tmp_path / "settings.json"
    original = b'{"name":"custom","ai":{"schema_version":999,"policy":"online_first"}}'
    path.write_bytes(original)
    loaded = load_settings(path)
    assert loaded.name == "custom"
    assert loaded.ai.policy == "local_only"

    with pytest.raises(ValueError, match="版本|升级"):
        save_settings(replace(loaded, audio_avoidance=False), path)

    assert path.read_bytes() == original


def test_backup_failure_leaves_configuration_unchanged(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    original = b'{"name":"custom","interval":0}'
    path.write_bytes(original)
    original_open = Path.open

    def fail_backup(self, *args, **kwargs):
        if self.suffix == ".bak":
            raise PermissionError("模拟无法备份")
        return original_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fail_backup)
    with pytest.raises(OSError):
        save_settings(replace(load_settings(path), audio_avoidance=False), path)
    assert path.read_bytes() == original


def test_voice_fields_are_recovered_with_engine_constraints(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text('{"tts_engine":"natural","speaker":17,"interval":0}', encoding="utf-8")
    loaded = load_settings(path)
    assert loaded.tts_engine == "natural" and loaded.speaker == 17
    assert loaded.interval == Settings().interval


def test_panel_displays_configuration_warning_until_successful_save(monkeypatch):
    from PySide6.QtWidgets import QApplication

    from pet.panel import Panel

    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    panel = Panel(Settings(), settings_warning="interval 无效，原文件已保留")
    try:
        assert "原文件已保留" in panel.form.hint.text()
        panel.persona.name.setText("修改名字")
        assert "原文件已保留" in panel.form.hint.text()
        panel.form.complete("模拟写盘失败")
        panel.form.refresh()
        assert "原文件已保留" in panel.form.hint.text()
        panel.settings = panel.form.read()
        panel.form.complete("")
        assert "原文件已保留" not in panel.form.hint.text()
    finally:
        panel.deleteLater()
        app.processEvents()
