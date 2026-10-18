"""基础/API 预检只使用合成事实与临时目录，不触碰用户配置。"""

from dataclasses import replace
from types import SimpleNamespace

import pytest

from pet.ai.assessment import assess_base
from pet.ai.device import DeviceReport
from scripts import preflight


def base_device(**changes):
    return replace(DeviceReport(
        system="Windows", architecture="AMD64", os_build=26100,
        memory_available=2 * 2**30, app_free=4 * 2**30,
    ), **changes)


@pytest.mark.parametrize("missing", [
    {"system": ""}, {"architecture": ""}, {"os_build": None},
    {"memory_available": None}, {"app_free": None},
    {"memory_available": None, "app_free": None,
     "unknown_reasons": ("内存探测失败", "应用磁盘探测失败")},
])
def test_missing_required_base_fact_stays_unknown_and_selectable(missing):
    result = assess_base(base_device(**missing))
    assert result.status == "unknown"
    assert result.selectable
    assert "重新检测" in "；".join(result.reasons)
    assert "预检通过" not in "；".join(result.reasons)


@pytest.mark.parametrize(("changes", "status"), [
    ({"system": "Linux", "memory_available": None}, "incompatible"),
    ({"architecture": "ARM64", "app_free": None}, "incompatible"),
    ({"os_build": 17134, "memory_available": None}, "incompatible"),
    ({"memory_available": 512 * 2**20 - 1, "app_free": None}, "insufficient"),
    ({"memory_available": None, "app_free": 2 * 2**30 - 1}, "insufficient"),
])
def test_known_base_blocker_has_priority_over_unknown_fact(changes, status):
    result = assess_base(base_device(**changes))
    assert result.status == status
    assert not result.selectable


@pytest.mark.parametrize("avx2", [None, False])
def test_api_base_does_not_require_local_model_or_gpu_facts(avx2):
    result = assess_base(base_device(
        memory_available=512 * 2**20, app_free=2 * 2**30,
        avx2=avx2, model_free=None, gpus=(),
        unknown_reasons=("NVIDIA 显存或驱动探测失败", "模型磁盘探测失败"),
    ))
    assert result.status == "estimated"
    assert result.selectable


def test_preflight_probe_serializes_unknown_base_status(tmp_path, monkeypatch):
    # 只替换硬件边界；实际执行报告生成，所有输出均留在 pytest 临时目录。
    monkeypatch.setattr(preflight, "probe_device", lambda *_: base_device(
        memory_available=None, app_free=None,
        unknown_reasons=("内存探测失败", "应用磁盘探测失败"),
    ))
    output = tmp_path / "report"
    assert preflight.probe(SimpleNamespace(
        app_dir=tmp_path / "app", model_dir=tmp_path / "models", output=output,
    )) == 0
    base = preflight.read_ini(output / "device.ini")["base"]
    assert base["status"] == "unknown"
    assert base["selectable"] == "1"
    assert "预检通过" not in base["reason"]
