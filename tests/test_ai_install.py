"""资源计划只执行明确选择，测试不连接网络或读取真实模型。"""

from dataclasses import replace
from pathlib import Path

import pytest

from pet.ai.install_plan import InstallPlan, load_plan, resources_for, save_plan


def test_api_without_voice_has_no_local_resources(tmp_path):
    plan = InstallPlan(mode="api", app_dir=str(tmp_path), model_dir=str(tmp_path / "models"))
    assert resources_for(plan) == ()
    assert plan.download_bytes == 0


def test_light_model_never_downloads_standard_weights(tmp_path):
    plan = InstallPlan(primary_model_id="qwen3.5-4b", backend="cpu", app_dir=str(tmp_path))
    assets = resources_for(plan)
    assert {asset.kind for asset in assets} == {"model", "projector", "engine"}
    assert all("9B" not in asset.url and "cuda" not in asset.url for asset in assets)
    assert sum(asset.kind == "model" for asset in assets) == 1
    backup = resources_for(replace(plan, backup_model_ids=("qwen3.5-9b",)))
    assert sum(asset.kind == "model" for asset in backup) == 2
    assert sum(asset.kind == "engine" for asset in backup) == 1


def test_voice_components_are_independent(tmp_path):
    plan = InstallPlan(mode="api", voice_components=("realtime",), app_dir=str(tmp_path))
    assets = resources_for(plan)
    assert len(assets) == 3
    assert {asset.kind for asset in assets} == {"realtime"}


def test_plan_roundtrip_and_rejects_unknown_secret_fields(tmp_path):
    path = tmp_path / "plan.json"
    plan = InstallPlan(mode="api", credential_ref="xuansi.ai/profile-1", app_dir=str(tmp_path))
    save_plan(plan, path)
    assert load_plan(path) == plan
    path.write_text('{"mode":"api", "api_key":"secret"}', encoding="utf-8")
    with pytest.raises(ValueError, match="字段"):
        load_plan(path)


@pytest.mark.parametrize("changes", [
    {"primary_model_id": "untrusted"}, {"backend": "vulkan"},
    {"voice_components": ("unknown",)}, {"policy": "loop"},
    {"schema_version": 2}, {"model_dir": "relative/path"},
])
def test_invalid_plan_is_rejected(changes):
    with pytest.raises(ValueError):
        InstallPlan(**changes).validate()


def test_api_deployment_never_opens_network_or_creates_model_directory(tmp_path, monkeypatch):
    from scripts import download_assets

    def unexpected_fetch(_asset):
        pytest.fail("API-only 不应下载任何本地资源")

    monkeypatch.setattr(download_assets, "fetch", unexpected_fetch)
    model_dir = tmp_path / "must-not-exist"
    download_assets.deploy_plan(InstallPlan(mode="api", app_dir=str(tmp_path), model_dir=str(model_dir)))
    assert not model_dir.exists()
    assert not (tmp_path / "runtime/llama").exists()


def test_cpu_archive_is_isolated_and_traversal_is_rejected(tmp_path):
    import zipfile

    from scripts import download_assets

    archive = tmp_path / "llama-cpu.zip"
    with zipfile.ZipFile(archive, "w") as stream:
        stream.writestr("llama-server.exe", b"synthetic executable")
    selected = [("https://invalid.example/synthetic", archive, "unused")]
    download_assets.extract(selected, tmp_path / "models", tmp_path / "runtime", tmp_path / "manifest.json")
    assert (tmp_path / "runtime/llama/cpu/llama-server.exe").is_file()
    assert not (tmp_path / "runtime/llama/cuda").exists()
    with zipfile.ZipFile(archive, "w") as stream:
        stream.writestr("../../../outside.exe", b"bad")
    with pytest.raises(ValueError, match="越界"):
        download_assets.extract(selected, tmp_path / "models", tmp_path / "runtime", tmp_path / "manifest.json")


def test_apply_preserves_custom_settings_and_selects_only_voice_components(tmp_path):
    import argparse
    import json

    from scripts.preflight import apply_settings

    settings_path = tmp_path / "data/settings.json"
    settings_path.parent.mkdir()
    settings_path.write_text(json.dumps({"name": "原名字", "interval": 90, "ai": {"cloud_memory": True}}),
                             encoding="utf-8")
    plan = InstallPlan(app_dir=str(tmp_path), model_dir=str(tmp_path / "chosen"),
                       primary_model_id="qwen3.5-4b", backend="cpu", voice_components=("asr",))
    plan_path = tmp_path / "plan.json"
    save_plan(plan, plan_path)
    assert apply_settings(argparse.Namespace(plan=plan_path, profile=None)) == 0
    saved = json.loads(settings_path.read_text(encoding="utf-8"))
    assert saved["name"] == "原名字" and saved["interval"] == 90
    assert saved["ai"]["cloud_memory"] is True
    assert saved["ai"]["voice_components"] == ["asr"]
    assert saved["gpu_layers"] == 0
    assert saved["speak_replies"] is False and saved["realtime_voice"] is False
    assert saved["model_path"] == str(tmp_path / "chosen/qwen3.5-4b/Qwen3.5-4B-Q4_K_M.gguf")


@pytest.mark.parametrize('components,previous,expected', [
    (('realtime',), False, True), (('asr',), True, False),
    (('asr', 'realtime'), False, False), (('asr', 'realtime'), True, True),
])
def test_install_voice_mode_matches_selected_recognition_components(tmp_path, components, previous, expected):
    """安装单识别组件时修正旧模式；同时安装两种时保留用户偏好。"""
    import argparse
    import json

    from scripts.preflight import apply_settings

    settings_path = tmp_path / 'data/settings.json'
    settings_path.parent.mkdir()
    settings_path.write_text(json.dumps({'realtime_voice': previous}), encoding='utf-8')
    plan_path = tmp_path / 'plan.json'
    save_plan(InstallPlan(app_dir=str(tmp_path), voice_components=components), plan_path)
    apply_settings(argparse.Namespace(plan=plan_path, profile=None))
    saved = json.loads(settings_path.read_text(encoding='utf-8'))
    assert saved['realtime_voice'] is expected


def test_explicit_install_choice_keeps_recoverable_custom_model_configuration(tmp_path):
    import argparse
    import json

    from scripts.preflight import apply_settings

    path = tmp_path / 'data/settings.json'
    path.parent.mkdir()
    original = {'name': '原设置', 'model_path': 'C:/Custom/chosen.gguf',
                'projector_path': 'C:/Custom/projector.gguf'}
    path.write_text(json.dumps(original, ensure_ascii=False), encoding='utf-8')
    plan_path = tmp_path / 'plan.json'
    save_plan(InstallPlan(app_dir=str(tmp_path), model_dir=str(tmp_path / 'models')), plan_path)
    apply_settings(argparse.Namespace(plan=plan_path, profile=None))
    backups = list(path.parent.glob('settings.before-install-*.json'))
    assert len(backups) == 1
    assert json.loads(backups[0].read_text(encoding='utf-8')) == original


@pytest.mark.parametrize('existing_settings', [False, True])
def test_plan_write_failure_does_not_commit_new_api_credential_reference(tmp_path, monkeypatch, existing_settings):
    """安装计划落盘失败后可清理新凭据，原配置不能指向该引用。"""
    import argparse
    import json
    from dataclasses import asdict

    from pet.ai.settings import ModelProfile
    from scripts import preflight

    path = tmp_path / 'data/settings.json'
    path.parent.mkdir()
    original = b'{"ai":{"profile":{"credential_ref":"synthetic-old-reference"}}}'
    if existing_settings:
        path.write_bytes(original)
    profile = ModelProfile(endpoint='https://example.invalid/v1', model='synthetic-model',
                           credential_ref='synthetic-new-reference',
                           capabilities=('text', 'image', 'tools', 'stream', 'cancel'))
    profile = replace(profile, verified_capabilities=profile.capabilities, verified_at='2026-10-18',
                      verification_fingerprint=profile.fingerprint())
    profile_path = tmp_path / 'profile.json'
    profile_path.write_text(json.dumps(asdict(profile)), encoding='utf-8')
    plan_path = tmp_path / 'plan.json'
    save_plan(InstallPlan(mode='api', policy='online_first', app_dir=str(tmp_path),
                          credential_ref=profile.credential_ref), plan_path)

    def fail_plan_write(*_):
        raise OSError('synthetic install-plan write failure')

    monkeypatch.setattr(preflight, 'save_plan', fail_plan_write)
    with pytest.raises(OSError, match='install-plan write failure'):
        preflight.apply_settings(argparse.Namespace(plan=plan_path, profile=profile_path))
    if existing_settings:
        assert path.read_bytes() == original
    else:
        assert not path.exists()


def test_preflight_runner_kills_hung_child(tmp_path):
    import subprocess
    import sys
    import time

    from scripts import preflight_runner

    child = tmp_path / "blocked.py"
    child.write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
    started = time.monotonic()
    result = subprocess.run([sys.executable, str(Path(preflight_runner.__file__)), "--timeout", "0.1", str(child)],
                            timeout=10, capture_output=True)
    assert result.returncode == 124
    assert time.monotonic() - started < 5


def test_profile_cli_preserves_mode_and_context_budget(tmp_path, monkeypatch):
    import json
    import sys

    from scripts import preflight

    choices = tmp_path / "profile.ini"
    output = tmp_path / "profile.json"
    preflight.write_ini(choices, {"profile": {
        "provider": "custom", "region": "test", "endpoint": "https://example.invalid/v1",
        "model": "synthetic", "mode": "explicit-mode", "context_tokens": "65536",
    }})
    monkeypatch.setattr(sys, "argv", ["preflight.py", "profile", "--choices", str(choices), "--output", str(output)])
    assert preflight.main() == 0
    profile = json.loads(output.read_text(encoding="utf-8"))
    assert profile["mode"] == "explicit-mode"
    assert profile["context_tokens"] == 65536
    assert "key" not in profile


def test_corrupt_settings_are_preserved_and_install_fails(tmp_path):
    import argparse

    from scripts.preflight import apply_settings

    path = tmp_path / "data/settings.json"
    path.parent.mkdir()
    path.write_text("not json", encoding="utf-8")
    plan = tmp_path / "plan.json"
    save_plan(InstallPlan(app_dir=str(tmp_path)), plan)
    with pytest.raises(ValueError):
        apply_settings(argparse.Namespace(plan=plan, profile=None))
    assert path.read_text(encoding="utf-8") == "not json"


@pytest.mark.parametrize(("same_volume", "app_free", "model_free", "fails"), [
    (True, 7 * 2**30, 7 * 2**30, True),
    (True, 16 * 2**30, 16 * 2**30, False),
    (True, 16 * 2**30, 7 * 2**30, True),
    (True, None, 7 * 2**30, True),
    (True, None, None, False),
    (False, 7 * 2**30, 7 * 2**30, False),
    (None, 7 * 2**30, 7 * 2**30, False),
])
def test_preflight_reserves_combined_space_only_for_known_shared_volume(
        tmp_path, monkeypatch, same_volume, app_free, model_free, fails):
    """9B CUDA 的单项都能装入 7 GiB，但同卷总预算超过该容量。"""
    import argparse
    from types import SimpleNamespace

    from pet.ai.device import DeviceReport, GpuReport
    from scripts import preflight

    report = DeviceReport(system="Windows", architecture="AMD64", os_build=22631,
                          memory_available=32 * 2**30, avx2=True,
                          gpus=(GpuReport("synthetic", 16 * 2**30, 16 * 2**30, "555.0"),),
                          app_free=app_free, model_free=model_free)
    # 旧探测报告没有卷字段；未知不能被当成明确的同卷或空间不足。
    facts = vars(report).copy()
    facts.pop("app_volume", None)
    facts.pop("model_volume", None)
    if same_volume is not None:
        facts.update(app_volume="synthetic-volume-a",
                     model_volume="synthetic-volume-a" if same_volume else "synthetic-volume-b")
    monkeypatch.setattr(preflight, "probe_device", lambda *_: SimpleNamespace(**facts))
    choices, output = tmp_path / "choices.ini", tmp_path / "plan.json"
    preflight.write_ini(choices, {"choices": {
        "mode": "local", "model": "qwen3.5-9b", "backend": "cuda",
        "app_dir": str(tmp_path / "app"), "model_dir": str(tmp_path / "models"),
    }})
    args = argparse.Namespace(choices=choices, output=output, profile=None)
    if fails:
        with pytest.raises(ValueError, match="同一卷"):
            preflight.create_plan(args)
        assert not output.exists()
    else:
        assert preflight.create_plan(args) == 0
        assert output.exists()


def test_api_only_shared_volume_reserves_no_gguf_space(tmp_path, monkeypatch):
    """API-only 同卷只保留基础运行空间，不附带 9B 模型预算。"""
    import argparse
    from types import SimpleNamespace

    from pet.ai.device import DeviceReport
    from scripts import preflight

    facts = vars(DeviceReport(system="Windows", architecture="AMD64", os_build=22631,
                              memory_available=2**30, app_free=2 * 2**30,
                              model_free=None)).copy()
    facts.update(app_volume="synthetic-volume", model_volume="synthetic-volume")
    monkeypatch.setattr(preflight, "probe_device", lambda *_: SimpleNamespace(**facts))
    choices, output = tmp_path / "choices.ini", tmp_path / "plan.json"
    preflight.write_ini(choices, {"choices": {
        "mode": "api", "app_dir": str(tmp_path / "app"), "model_dir": str(tmp_path / "models"),
    }})
    assert preflight.create_plan(argparse.Namespace(choices=choices, output=output, profile=None)) == 0
    assert resources_for(load_plan(output)) == ()
    assert not (tmp_path / "models").exists()
    with pytest.raises(ValueError, match="完整能力验证"):
        preflight.apply_settings(argparse.Namespace(plan=output, profile=None))
    assert not (tmp_path / "app/data/settings.json").exists()


def test_preflight_summary_uses_prepared_backend(tmp_path, monkeypatch):
    """自动后端定稿后，确认摘要与保存的计划必须一致。"""
    import argparse

    from pet.ai.device import DeviceReport
    from scripts import preflight

    report = DeviceReport(system="Windows", architecture="AMD64", os_build=22631,
                          memory_available=32 * 2**30, avx2=True,
                          app_free=64 * 2**30, model_free=64 * 2**30,
                          app_volume="合成应用卷", model_volume="合成模型卷")
    monkeypatch.setattr(preflight, "probe_device", lambda *_: report)
    choices, output = tmp_path / "choices.ini", tmp_path / "plan.json"
    preflight.write_ini(choices, {"choices": {
        "backend": "auto", "app_dir": str(tmp_path / "app"), "model_dir": str(tmp_path / "models"),
    }})
    assert preflight.create_plan(argparse.Namespace(choices=choices, output=output, profile=None)) == 0
    assert load_plan(output).backend == "cpu"
    assert "后端：cpu" in output.with_suffix(".txt").read_text(encoding="utf-8")
