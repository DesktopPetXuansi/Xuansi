"""共享计划规则只接收合成事实，不探测设备或访问用户文件。"""

from dataclasses import FrozenInstanceError, replace

import pytest

from pet.ai.device import DeviceReport, GpuReport
from pet.ai.install_plan import InstallPlan, prepare_plan, resources_for
from pet.ai.settings import ModelProfile


@pytest.fixture
def report():
    return DeviceReport(system="Windows", architecture="AMD64", os_build=22631,
                        memory_available=32 * 2**30, avx2=True,
                        gpus=(GpuReport("合成显卡", 16 * 2**30, 16 * 2**30, "555.0"),),
                        app_free=64 * 2**30, model_free=64 * 2**30,
                        app_volume="合成应用卷", model_volume="合成模型卷")


@pytest.mark.parametrize("gpus,backend", [((), "cpu"), (
    (GpuReport("合成显卡", 16 * 2**30, 16 * 2**30, "555.0"),), "cuda")])
def test_auto_backend_returns_new_immutable_plan(report, gpus, backend):
    original = InstallPlan()
    prepared = prepare_plan(original, replace(report, gpus=gpus))
    assert prepared is not original
    assert original.backend == "auto"
    assert prepared.backend == backend
    with pytest.raises(FrozenInstanceError):
        prepared.backend = "auto"


def test_api_draft_requires_only_base_resources_without_profile(report):
    facts = replace(report, memory_available=2**30, avx2=False, gpus=(),
                    app_free=2 * 2**30, model_free=0, model_volume=report.app_volume)
    prepared = prepare_plan(InstallPlan(mode="api", policy="online_first"), facts)
    assert resources_for(prepared) == ()
    assert prepared.provider_profile_id == prepared.credential_ref == ""
    with pytest.raises(ValueError, match="Windows"):
        prepare_plan(prepared, replace(facts, system="Linux"))


def test_each_selected_local_model_is_assessed(report):
    facts = replace(report, model_free=4 * 2**30)
    primary = InstallPlan(primary_model_id="qwen3.5-4b")
    prepare_plan(primary, facts)
    with pytest.raises(ValueError, match="模型盘当前"):
        prepare_plan(replace(primary, backup_model_ids=("qwen3.5-9b",)), facts)
    with pytest.raises(ValueError, match="AVX2"):
        prepare_plan(primary, replace(report, avx2=False))


def verified_profile():
    """证明仅绑定合成端点和凭据引用，不读取实际凭据。"""
    profile = ModelProfile(endpoint="https://example.invalid/v1", model="合成模型",
                           credential_ref="synthetic-reference",
                           capabilities=("text", "image", "tools", "stream", "cancel"))
    return replace(profile, verified_capabilities=profile.capabilities, verified_at="2026-10-18",
                   verification_fingerprint=profile.fingerprint())


def test_verified_profile_binds_identity_without_mutating_input(report):
    original = InstallPlan(mode="api")
    profile = verified_profile()
    prepared = prepare_plan(original, report, profile)
    assert prepared.provider_profile_id == profile.fingerprint()
    assert prepared.credential_ref == profile.credential_ref
    assert original.provider_profile_id == original.credential_ref == ""


@pytest.mark.parametrize("missing", ["text", "image", "tools", "stream", "cancel"])
def test_profile_requires_all_five_capabilities(report, missing):
    profile = verified_profile()
    profile = replace(profile, verified_capabilities=tuple(
        item for item in profile.verified_capabilities if item != missing))
    with pytest.raises(ValueError, match="能力验证"):
        prepare_plan(InstallPlan(mode="api"), report, profile)


def test_profile_proof_must_match_current_identity(report):
    with pytest.raises(ValueError, match="能力验证"):
        prepare_plan(InstallPlan(mode="api"), report,
                     replace(verified_profile(), credential_ref="changed-reference"))


@pytest.mark.parametrize("app_free,model_free,fails", [
    (7 * 2**30, 16 * 2**30, True), (16 * 2**30, 7 * 2**30, True),
    (None, 7 * 2**30, True), (7 * 2**30, None, True),
    (None, None, False), (16 * 2**30, 16 * 2**30, False),
])
def test_shared_volume_uses_minimum_known_available_space(report, app_free, model_free, fails):
    facts = replace(report, app_free=app_free, model_free=model_free, model_volume=report.app_volume)
    if fails:
        with pytest.raises(ValueError, match="同一卷"):
            prepare_plan(InstallPlan(), facts)
    else:
        prepare_plan(InstallPlan(), facts)


def test_unknown_volume_warns_and_keeps_individual_space_checks(report, caplog):
    facts = replace(report, app_volume=None, app_free=7 * 2**30, model_free=7 * 2**30)
    prepare_plan(InstallPlan(), facts)
    assert "卷身份未知" in caplog.text
    with pytest.raises(ValueError, match="模型盘空间不足"):
        prepare_plan(InstallPlan(mode="api", voice_components=("tts",)),
                     replace(facts, model_free=0))


def test_voice_archives_keep_download_and_extraction_reserve(report):
    plan = InstallPlan(mode="api", voice_components=("tts",))
    resources = resources_for(plan)
    reserve = sum(item.bytes * (3 if item.archive else 1) for item in resources)
    assert any(item.archive for item in resources)
    prepare_plan(plan, replace(report, model_free=reserve))
    with pytest.raises(ValueError, match="模型盘空间不足"):
        prepare_plan(plan, replace(report, model_free=reserve - 1))
