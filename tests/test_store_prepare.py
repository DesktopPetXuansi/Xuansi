"""商店资源准备使用临时目录和网络替身，不读取真实凭据或下载模型。"""

import json
import os
import shutil
import subprocess
import sys
from dataclasses import asdict, replace
from pathlib import Path
from unittest.mock import Mock

import pytest

from pet.ai.install_plan import InstallPlan, save_plan
from pet.ai.settings import ModelProfile
from scripts import store_prepare

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def inputs(monkeypatch, tmp_path):
    root = tmp_path / "商店工作区 with spaces"
    monkeypatch.setenv("XUANSI_WRITABLE_ROOT", str(root))
    plan = InstallPlan(mode="api", policy="online_first", app_dir=str(root),
                       model_dir=str(tmp_path / "模型"))
    plan_path = tmp_path / "plan.json"
    save_plan(plan, plan_path)
    profile = ModelProfile(endpoint="https://example.invalid/v1", model="synthetic",
                           capabilities=("text", "image", "tools", "stream", "cancel"))
    profile = replace(profile, verified_capabilities=profile.capabilities, verified_at="2026-10-28",
                      verification_fingerprint=profile.fingerprint())
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(json.dumps(asdict(profile)), encoding="utf-8")
    return root, plan_path, profile_path


def test_empty_api_plan_saves_settings_without_network_or_extra_resources(inputs, monkeypatch):
    root, plan_path, profile_path = inputs
    network = Mock(side_effect=AssertionError("unexpected network"))
    monkeypatch.setattr("urllib.request.urlopen", network)

    store_prepare.prepare_install(plan_path, profile_path)

    saved = json.loads((root / "data/settings.json").read_text(encoding="utf-8"))
    assert saved["ai"]["policy"] == "online_first"
    assert saved["model_path"] == saved["projector_path"] == ""
    assert saved["speak_replies"] is False
    assert not (root / "runtime").exists()
    assert sorted(path.name for path in (root / "data").iterdir()) == ["install-plan.json", "settings.json"]
    network.assert_not_called()


@pytest.mark.parametrize("override", [None, "", "relative/path", "C:relative", "different"])
def test_invalid_destination_fails_before_writes_or_deployment(inputs, monkeypatch, tmp_path, override):
    root, plan_path, profile_path = inputs
    if override is None:
        monkeypatch.delenv("XUANSI_WRITABLE_ROOT")
    else:
        monkeypatch.setenv("XUANSI_WRITABLE_ROOT", str(tmp_path / override) if override == "different" else override)
    deploy = Mock(side_effect=AssertionError("unexpected deployment"))
    monkeypatch.setattr(store_prepare, "deploy_plan", deploy)

    with pytest.raises(ValueError):
        store_prepare.prepare_install(plan_path, profile_path)

    deploy.assert_not_called()
    assert not root.exists()
    assert not (tmp_path / "different").exists()


@pytest.mark.parametrize("change", ["unverified", "empty-endpoint", "secret", "plan-mismatch"])
def test_invalid_profile_fails_before_writes_or_deployment(inputs, monkeypatch, change):
    root, plan_path, profile_path = inputs
    raw = json.loads(profile_path.read_text(encoding="utf-8"))
    if change == "unverified":
        raw["verified_capabilities"] = []
    elif change == "empty-endpoint":
        raw["endpoint"] = ""
    elif change == "secret":
        raw["api_key"] = "must-never-persist"
    else:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        plan["provider_profile_id"] = "different-profile"
        plan_path.write_text(json.dumps(plan), encoding="utf-8")
    profile_path.write_text(json.dumps(raw), encoding="utf-8")
    deploy = Mock(side_effect=AssertionError("unexpected deployment"))
    monkeypatch.setattr(store_prepare, "deploy_plan", deploy)

    with pytest.raises(ValueError):
        store_prepare.prepare_install(plan_path, profile_path)

    deploy.assert_not_called()
    assert not root.exists()


def test_download_failure_keeps_existing_settings_and_can_retry(inputs, monkeypatch):
    root, plan_path, profile_path = inputs
    settings_path = root / "data/settings.json"
    settings_path.parent.mkdir(parents=True)
    previous = b'{"name":"old companion","persona":"keep me","ai":{}}'
    settings_path.write_bytes(previous)
    deploy = Mock(side_effect=RuntimeError("synthetic download failure"))
    monkeypatch.setattr(store_prepare, "deploy_plan", deploy)

    with pytest.raises(RuntimeError):
        store_prepare.prepare_install(plan_path, profile_path)

    assert settings_path.read_bytes() == previous
    assert list(settings_path.parent.iterdir()) == [settings_path]
    deploy.side_effect = None
    store_prepare.prepare_install(plan_path, profile_path)
    saved = json.loads(settings_path.read_text(encoding="utf-8"))
    assert saved["name"] == "old companion"
    assert saved["persona"] == "keep me"
    assert saved["ai"]["policy"] == "online_first"
    backups = list(settings_path.parent.glob("settings.before-install-*.json"))
    assert len(backups) == 1
    assert json.loads(backups[0].read_text(encoding="utf-8")) == json.loads(previous)
    assert not list(settings_path.parent.glob(".store-*"))


@pytest.mark.parametrize("previous", ["not-json", "[]", '{"ai":[]}'])
def test_corrupt_existing_settings_stop_before_deployment(inputs, monkeypatch, previous):
    root, plan_path, profile_path = inputs
    settings_path = root / "data/settings.json"
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text(previous, encoding="utf-8")
    deploy = Mock(side_effect=AssertionError("unexpected deployment"))
    monkeypatch.setattr(store_prepare, "deploy_plan", deploy)

    with pytest.raises(ValueError):
        store_prepare.prepare_install(plan_path, profile_path)

    deploy.assert_not_called()
    assert settings_path.read_text(encoding="utf-8") == previous
    assert list(settings_path.parent.iterdir()) == [settings_path]


def test_download_cannot_change_the_validated_plan_or_profile(inputs, monkeypatch):
    root, plan_path, profile_path = inputs

    def replace_inputs(_):
        plan_path.write_text('{"api_key":"unexpected-secret"}', encoding="utf-8")
        profile_path.write_text('{"endpoint":"https://changed.invalid"}', encoding="utf-8")

    monkeypatch.setattr(store_prepare, "deploy_plan", replace_inputs)
    store_prepare.prepare_install(plan_path, profile_path)

    saved = json.loads((root / "data/settings.json").read_text(encoding="utf-8"))
    assert saved["ai"]["profile"]["endpoint"] == "https://example.invalid/v1"
    assert saved["ai"]["profile"]["model"] == "synthetic"
    assert "unexpected-secret" not in (root / "data/install-plan.json").read_text(encoding="utf-8")


def test_missing_profile_stops_api_preparation_before_writes(inputs, monkeypatch):
    root, plan_path, _ = inputs
    deploy = Mock(side_effect=AssertionError("unexpected deployment"))
    monkeypatch.setattr(store_prepare, "deploy_plan", deploy)

    with pytest.raises(ValueError):
        store_prepare.prepare_install(plan_path)

    deploy.assert_not_called()
    assert not root.exists()


def test_cli_failure_is_nonzero_and_does_not_log_private_exception_text(inputs, monkeypatch, caplog):
    root, plan_path, profile_path = inputs
    monkeypatch.setattr(store_prepare, "deploy_plan", Mock(side_effect=RuntimeError("private-secret-content")))

    assert store_prepare.main(["--plan", str(plan_path), "--profile", str(profile_path)]) == 1

    assert "private-secret-content" not in caplog.text
    assert "RuntimeError" in caplog.text
    assert not (root / "data/settings.json").exists()


def test_local_plan_uses_selected_resources_then_applies_settings(inputs, monkeypatch):
    root, plan_path, _ = inputs
    plan = InstallPlan(app_dir=str(root), model_dir=str(root / "models"), backend="cpu")
    save_plan(plan, plan_path)

    def deployment(selected):
        assert selected == plan
        assert not (root / "data/settings.json").exists()
        (root / "runtime").mkdir(parents=True)
        (root / "runtime/verified-resource").write_text("synthetic", encoding="utf-8")

    monkeypatch.setattr(store_prepare, "deploy_plan", deployment)
    assert store_prepare.main(["--plan", str(plan_path)]) == 0

    saved = json.loads((root / "data/settings.json").read_text(encoding="utf-8"))
    assert saved["ai"]["policy"] == "local_only"
    assert saved["ai"]["local_backend"] == "cpu"
    assert saved["gpu_layers"] == 0
    assert saved["model_path"].startswith(str(root / "models"))
    assert (root / "runtime/verified-resource").read_text(encoding="utf-8") == "synthetic"


def test_existing_verified_profile_can_be_reused_without_a_new_profile_file(inputs):
    root, plan_path, profile_path = inputs
    settings_path = root / "data/settings.json"
    settings_path.parent.mkdir(parents=True)
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    settings_path.write_text(json.dumps({"ai": {"profile": profile}}), encoding="utf-8")

    store_prepare.prepare_install(plan_path)

    saved = json.loads(settings_path.read_text(encoding="utf-8"))
    assert saved["ai"]["profile"] == profile
    assert saved["ai"]["policy"] == "online_first"


def test_worker_cli_uses_its_payload_with_a_different_working_directory(inputs, tmp_path):
    """首次运行由后台进程触发，工作目录不保证是商店包目录。"""
    root, plan_path, profile_path = inputs
    payload = tmp_path / "模拟商店载荷"
    (payload / "scripts").mkdir(parents=True)
    (payload / "pet").mkdir()
    shutil.copy2(ROOT / "pet/__init__.py", payload / "pet/__init__.py")
    shutil.copytree(ROOT / "pet/ai", payload / "pet/ai", ignore=shutil.ignore_patterns("__pycache__"))
    for name in ("store_prepare.py", "preflight.py", "download_assets.py"):
        shutil.copy2(ROOT / "scripts" / name, payload / "scripts" / name)
    before = {path.relative_to(payload) for path in payload.rglob("*") if path.is_file()}
    environment = dict(os.environ, XUANSI_WRITABLE_ROOT=str(root), PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1")

    result = subprocess.run(
        [sys.executable, str(payload / "scripts/store_prepare.py"), "--plan", str(plan_path),
         "--profile", str(profile_path)],
        cwd=tmp_path, env=environment, capture_output=True, text=True, encoding="utf-8", timeout=30,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert (root / "data/settings.json").is_file()
    assert {path.relative_to(payload) for path in payload.rglob("*") if path.is_file()} == before
