"""探测未知与资源不足不可混淆，评估只使用合成设备事实。"""

from dataclasses import replace

import pytest

from pet.ai.assessment import assess, assess_base
from pet.ai.device import DeviceReport, GpuReport, probe_device


def device(**changes):
    return replace(DeviceReport(
        system="Windows", architecture="AMD64", os_build=22631,
        memory_total=32 * 2**30, memory_available=20 * 2**30,
        avx2=True, gpus=(), app_free=40 * 2**30, model_free=40 * 2**30,
    ), **changes)


def test_cpu_route_remains_selectable_and_unverified():
    result = assess(device(), "qwen3.5-4b", backend="cpu")
    assert result.selectable
    assert result.status == "unverified"
    assert result.estimated


def test_probe_failure_is_unknown_instead_of_incompatible():
    result = assess(device(memory_available=None, avx2=None), "qwen3.5-9b", backend="cpu")
    assert result.status == "unknown"
    assert result.selectable


def test_known_resource_shortage_and_os_incompatibility_disable_choice():
    assert not assess(device(memory_available=100), "qwen3.5-9b").selectable
    assert assess(device(os_build=17134), "qwen3.5-4b").status == "incompatible"
    assert assess(device(model_free=100), "qwen3.5-4b").status == "insufficient"


def test_cuda_absence_and_low_vram_are_different():
    assert assess(device(), "qwen3.5-4b", backend="cuda").status == "incompatible"
    gpu = GpuReport(name="synthetic", memory_total=8 * 2**30, memory_free=2**30, driver="555.0")
    result = assess(device(gpus=(gpu,)), "qwen3.5-9b", backend="cuda")
    assert result.selectable  # GPU 层可分担到 CPU，不将低显存直接判为不兼容。


def test_probe_completes_without_optional_dependencies(tmp_path):
    result = probe_device(tmp_path, tmp_path, timeout=0.1)
    assert result.architecture
    assert result.app_free is not None
    assert result.model_free is not None


def test_api_base_accepts_windows_10_without_avx2_or_nvidia():
    assert assess_base(device(os_build=19045, avx2=False)).selectable
    assert not assess_base(device(memory_available=20)).selectable


def test_unknown_cuda_probe_is_not_incompatible():
    report = device(unknown_reasons=("NVIDIA 显存或驱动探测失败",))
    assert assess(report, "qwen3.5-4b", backend="cuda").selectable


def test_cuda_driver_compatibility_does_not_disable_cpu_or_api():
    from pet.ai.assessment import preferred_backend

    old = device(gpus=(GpuReport("synthetic", 8 * 2**30, 8 * 2**30, "527.00"),))
    assert assess(old, "qwen3.5-9b", backend="cuda").status == "incompatible"
    assert preferred_backend(old) == "cpu"
    assert assess(old, "qwen3.5-4b", backend="cpu").selectable
    assert assess_base(old).selectable
    unknown = replace(old, gpus=(replace(old.gpus[0], driver="unknown"),))
    assert assess(unknown, "qwen3.5-9b", backend="cuda").status == "unverified"
    minor = replace(old, gpus=(replace(old.gpus[0], driver="530.00"),))
    assert assess(minor, "qwen3.5-9b", backend="cuda").status == "unverified"


def test_volume_identity_handles_uncreated_directories_without_writing(tmp_path):
    from pet.ai.device import volume_identity

    missing = tmp_path / "not-created" / "models"
    assert volume_identity(missing) == volume_identity(tmp_path)
    assert not missing.parent.exists()


@pytest.mark.parametrize("shared", [True, False])
def test_windows_volume_identity_uses_guid_for_mounts_and_aliases(tmp_path, monkeypatch, shared):
    """同盘符下的挂载卷可不同；不同挂载路径也可以指向同一卷。"""
    from types import SimpleNamespace

    from pet.ai import device as module

    def mount_path(path, buffer, _size):
        buffer.value = "X:\\mounted\\" if path.endswith("alias") else "X:\\"
        return 1

    def volume_name(mount, buffer, _size):
        buffer.value = "synthetic-volume-a" if shared or mount == "X:\\" else "synthetic-volume-b"
        return 1

    kernel = SimpleNamespace(GetVolumePathNameW=mount_path, GetVolumeNameForVolumeMountPointW=volume_name)
    # 替换系统边界，不创建/修改真实系统挂载点。
    monkeypatch.setattr(module.ctypes, "windll", SimpleNamespace(kernel32=kernel), raising=False)
    monkeypatch.setattr(module.sys, "platform", "win32")
    (tmp_path / "alias").mkdir()
    assert (module.volume_identity(tmp_path) == module.volume_identity(tmp_path / "alias")) is shared


@pytest.mark.parametrize("failed_api", ["GetVolumePathNameW", "GetVolumeNameForVolumeMountPointW"])
def test_windows_volume_api_failure_remains_unknown(tmp_path, monkeypatch, failed_api):
    from types import SimpleNamespace

    from pet.ai import device as module

    def mount_path(_path, buffer, _size):
        buffer.value = "X:\\"
        return int(failed_api != "GetVolumePathNameW")

    def volume_name(_mount, _buffer, _size):
        return 0

    kernel = SimpleNamespace(GetVolumePathNameW=mount_path, GetVolumeNameForVolumeMountPointW=volume_name)
    monkeypatch.setattr(module.ctypes, "windll", SimpleNamespace(kernel32=kernel), raising=False)
    monkeypatch.setattr(module.ctypes, "WinError", lambda: OSError("synthetic volume probe error"), raising=False)
    monkeypatch.setattr(module.sys, "platform", "win32")
    with pytest.raises(OSError, match="synthetic volume probe error"):
        module.volume_identity(tmp_path)


def test_probe_records_unknown_volume_without_losing_known_free_space(tmp_path, monkeypatch):
    from pet.ai import device as module

    def unavailable_volume(_path):
        raise OSError("synthetic volume unavailable")

    monkeypatch.setattr(module, "volume_identity", unavailable_volume)
    monkeypatch.setattr(module.shutil, "which", lambda *_: None)
    report = module.probe_device(tmp_path, tmp_path)
    assert report.app_volume is None and report.model_volume is None
    assert report.app_free is not None and report.model_free is not None
    assert "应用卷身份探测失败" in report.unknown_reasons
    assert "模型卷身份探测失败" in report.unknown_reasons


def test_volume_permission_failure_does_not_fall_back_to_parent(tmp_path, monkeypatch):
    from pathlib import Path

    from pet.ai.device import volume_identity

    def denied(_path):
        raise PermissionError("synthetic access denied")

    monkeypatch.setattr(Path, "resolve", denied)
    with pytest.raises(PermissionError):
        volume_identity(tmp_path / "models")
