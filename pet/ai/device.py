"""安装前标准库探测；不访问用户内容，不加载模型，子进程有严格超时。"""

import csv
import ctypes
import logging
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class GpuReport:
    name: str
    memory_total: int
    memory_free: int
    driver: str = ""


@dataclass(frozen=True)
class DeviceReport:
    system: str = ""
    architecture: str = ""
    os_build: int | None = None
    memory_total: int | None = None
    memory_available: int | None = None
    avx2: bool | None = None
    gpus: tuple[GpuReport, ...] = ()
    app_free: int | None = None
    model_free: int | None = None
    unknown_reasons: tuple[str, ...] = ()
    measured_at: str = ""
    schema_version: int = 1
    # 追加字段保留旧报告和位置参数兼容；None 表示未确认卷身份。
    app_volume: str | None = None
    model_volume: str | None = None


def existing_parent(path: Path):
    """解析目录别名并寻找已有父目录；权限错误保留为未知，不回退到其他卷。"""
    path = path.resolve()
    while True:
        try:
            path.stat()
            return path
        except FileNotFoundError:
            if path.parent == path:
                raise
            path = path.parent


def free_space(path: Path):
    """尚未创建的目录使用最近存在父目录所在盘，不产生部署写入。"""
    return shutil.disk_usage(existing_parent(path)).free


def volume_identity(path: Path):
    """以真实卷身份核算共用空间，不能仅凭盘符判断挂载目录和路径别名。"""
    path = existing_parent(path)
    if sys.platform != "win32":
        return f"device:{path.stat().st_dev}"
    from ctypes import wintypes

    kernel = ctypes.windll.kernel32
    mount_path = ctypes.create_unicode_buffer(32768)
    volume = ctypes.create_unicode_buffer(50)
    # Win32 会沿 junction 链查找挂载点；卷 GUID 将多个挂载路径归一。
    for name in ("GetVolumePathNameW", "GetVolumeNameForVolumeMountPointW"):
        function = getattr(kernel, name)
        function.argtypes = (wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD)
        function.restype = wintypes.BOOL
    if not kernel.GetVolumePathNameW(str(path), mount_path, len(mount_path)):
        raise ctypes.WinError()
    if not kernel.GetVolumeNameForVolumeMountPointW(mount_path.value, volume, len(volume)):
        raise ctypes.WinError()
    return volume.value.casefold()


def probe_device(app_dir: Path, model_dir: Path, timeout: float = 5.0):
    reasons = []
    memory_total = memory_available = avx2 = None
    os_build = None
    if sys.platform == "win32":
        os_build = sys.getwindowsversion().build

        class MemoryStatus(ctypes.Structure):
            _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong),
                        *[(name, ctypes.c_ulonglong) for name in (
                            "total", "available", "page_total", "page_available", "virtual_total",
                            "virtual_available", "extended")]]

        status = MemoryStatus()
        status.length = ctypes.sizeof(status)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            memory_total, memory_available = status.total, status.available
        else:
            reasons.append("内存探测失败")
        # PF_AVX2_INSTRUCTIONS_AVAILABLE=40，由 OS 同时判断硬件与上下文支持。
        avx2 = bool(ctypes.windll.kernel32.IsProcessorFeaturePresent(40))
    else:
        reasons.append("Windows 之外的硬件探测尚未验证")
    gpus = ()
    tool = shutil.which("nvidia-smi")
    if tool:
        try:
            result = subprocess.run(
                [tool, "--query-gpu=name,memory.total,memory.free,driver_version", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=max(0.1, min(timeout, 8)),
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), check=True,
            )
            gpus = tuple(GpuReport(row[0].strip(), int(row[1]) * 2**20, int(row[2]) * 2**20,
                                   row[3].strip()) for row in csv.reader(result.stdout.splitlines()))
        except (OSError, ValueError, IndexError, subprocess.SubprocessError):
            reasons.append("NVIDIA 显存或驱动探测失败")
    disks, volumes = [], []
    for name, path in (("应用", app_dir), ("模型", model_dir)):
        try:
            disks.append(free_space(path))
        except OSError:
            disks.append(None)
            reasons.append(name + "磁盘探测失败")
        try:
            volumes.append(volume_identity(path))
        except (OSError, RuntimeError):
            volumes.append(None)
            reasons.append(name + "卷身份探测失败")
    report = DeviceReport(platform.system(), platform.machine(), os_build, memory_total,
                          memory_available, avx2, gpus, *disks, tuple(reasons), datetime.now(UTC).isoformat(),
                          app_volume=volumes[0], model_volume=volumes[1])
    LOG.info("环境探测完成，显卡数=%d，未知项=%d", len(gpus), len(reasons))
    return report
