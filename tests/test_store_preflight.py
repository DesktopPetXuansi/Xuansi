"""隔离预检载荷与可写目录；使用无资源 API 计划，不联网或读取真实用户数据。"""

import json
import os
import shutil
import subprocess
import sys
from dataclasses import asdict, replace
from pathlib import Path

import pytest

from pet.ai.install_plan import InstallPlan, save_plan
from pet.ai.settings import ModelProfile

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def payload(tmp_path):
    target = tmp_path / "只读载荷 with spaces"
    (target / "scripts").mkdir(parents=True)
    (target / "pet").mkdir()
    shutil.copy2(ROOT / "pet/__init__.py", target / "pet/__init__.py")
    shutil.copytree(ROOT / "pet/ai", target / "pet/ai", ignore=shutil.ignore_patterns("__pycache__"))
    for name in ("preflight.py", "download_assets.py"):
        shutil.copy2(ROOT / "scripts" / name, target / "scripts" / name)
    return target


def run_preflight(payload, arguments, writable_root=None):
    environment = dict(os.environ, PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1")
    environment.pop("XUANSI_WRITABLE_ROOT", None)
    if writable_root is not None:
        environment["XUANSI_WRITABLE_ROOT"] = str(writable_root)
    return subprocess.run(
        [sys.executable, str(payload / "scripts/preflight.py"), *arguments], cwd=payload,
        env=environment, capture_output=True, text=True, encoding="utf-8", timeout=20,
    )


@pytest.mark.parametrize("external", [False, True])
def test_default_validation_stays_bound_to_payload_root(payload, tmp_path, external):
    destination = tmp_path / "其他目录" if external else payload
    plan = tmp_path / "plan.json"
    save_plan(InstallPlan(app_dir=str(destination)), plan)
    result = run_preflight(payload, ["validate", "--plan", str(plan)])
    assert (result.returncode == 0) is (not external), result.stdout + result.stderr
    if external:
        assert not destination.exists()


@pytest.mark.parametrize("alias", [False, True])
def test_explicit_writable_root_accepts_only_its_resolved_plan(payload, tmp_path, alias):
    writable = tmp_path / "商店数据 with spaces"
    requested = writable / "child/.." if alias else writable
    plan = tmp_path / "plan.json"
    save_plan(InstallPlan(app_dir=str(requested)), plan)
    result = run_preflight(payload, ["validate", "--plan", str(plan)], writable)
    assert result.returncode == 0, result.stdout + result.stderr
    assert not writable.exists()


@pytest.mark.parametrize("override", ["", "relative/path", "C:relative"])
def test_invalid_override_cannot_fall_back_to_payload(payload, tmp_path, override):
    plan = tmp_path / "plan.json"
    save_plan(InstallPlan(app_dir=str(payload)), plan)
    result = run_preflight(payload, ["validate", "--plan", str(plan)], override)
    assert result.returncode != 0
    assert not (payload / "relative").exists()


def test_explicit_root_rejects_another_plan_destination(payload, tmp_path):
    writable, other = tmp_path / "商店数据", tmp_path / "未授权目录"
    plan = tmp_path / "plan.json"
    save_plan(InstallPlan(app_dir=str(other)), plan)
    result = run_preflight(payload, ["validate", "--plan", str(plan)], writable)
    assert result.returncode != 0
    assert not writable.exists()
    assert not other.exists()


def test_empty_resource_plan_applies_settings_outside_payload(payload, tmp_path):
    writable = tmp_path / "商店数据 with spaces"
    plan_path = tmp_path / "plan.json"
    plan = InstallPlan(mode="api", policy="online_first", app_dir=str(writable),
                       model_dir=str(tmp_path / "模型"), voice_components=())
    save_plan(plan, plan_path)
    profile = ModelProfile(endpoint="https://example.invalid/v1", model="合成模型",
                           capabilities=("text", "image", "tools", "stream", "cancel"))
    profile = replace(profile, verified_capabilities=profile.capabilities,
                      verified_at="2026-10-28", verification_fingerprint=profile.fingerprint())
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(json.dumps(asdict(profile)), encoding="utf-8")
    before = {path.relative_to(payload): path.read_bytes() for path in payload.rglob("*") if path.is_file()}
    result = run_preflight(payload, ["validate", "--plan", str(plan_path)], writable)
    assert result.returncode == 0, result.stdout + result.stderr
    # 真正执行空资源部署；若错误触发联网，替身会立即失败，而非访问外部服务。
    deployment = subprocess.run(
        [sys.executable, "-c", """
import sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path.cwd() / 'scripts'))
from download_assets import deploy_plan
from pet.ai.install_plan import load_plan
with patch('urllib.request.urlopen', side_effect=AssertionError('unexpected network')):
    deploy_plan(load_plan(Path(sys.argv[1])))
""", str(plan_path)], cwd=payload,
        env=dict(os.environ, PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1", XUANSI_WRITABLE_ROOT=str(writable)),
        capture_output=True, text=True, encoding="utf-8", timeout=20,
    )
    assert deployment.returncode == 0, deployment.stdout + deployment.stderr
    result = run_preflight(payload, ["apply", "--plan", str(plan_path), "--profile", str(profile_path)], writable)
    assert result.returncode == 0, result.stdout + result.stderr
    saved = json.loads((writable / "data/settings.json").read_text(encoding="utf-8"))
    assert saved["ai"]["policy"] == "online_first"
    assert saved["model_path"] == saved["projector_path"] == ""
    assert saved["speak_replies"] is False
    assert (writable / "data/install-plan.json").is_file()
    after = {path.relative_to(payload): path.read_bytes() for path in payload.rglob("*") if path.is_file()}
    assert after == before
    assert not (payload / "data").exists()
