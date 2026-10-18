"""纯评估逻辑；资源估算与业务实测严格区分，不制造跨设备性能保证。"""

from dataclasses import dataclass

from .catalog import MODELS, RESOURCES
from .device import DeviceReport

# NVIDIA CUDA 12.4 官方 release notes Table 2/3：Windows minor compatibility 528.33，
# 完整 toolkit 路线 551.61；较旧但仍在 minor 范围的驱动需要额外实测。
CUDA_MIN_DRIVER = (528, 33)
CUDA_TOOLKIT_DRIVER = (551, 61)


def cuda_driver_status(driver: str):
    try:
        parts = driver.strip().split(".")
        version = tuple(int(item) for item in parts[:2])
        if len(version) != 2:
            return "unknown"
    except ValueError:
        return "unknown"
    if version < CUDA_MIN_DRIVER:
        return "incompatible"
    return "supported" if version >= CUDA_TOOLKIT_DRIVER else "minor"


def preferred_backend(report: DeviceReport):
    return "cuda" if any(cuda_driver_status(gpu.driver) == "supported" for gpu in report.gpus) else "cpu"


@dataclass(frozen=True)
class Assessment:
    model_id: str
    status: str
    reasons: tuple[str, ...]
    estimated: bool = True
    schema_version: int = 1

    @property
    def selectable(self):
        return self.status not in ("incompatible", "insufficient")


def assess(report: DeviceReport, model_id: str, backend: str = "auto"):
    backend = preferred_backend(report) if backend == "auto" else backend
    model = MODELS[model_id]
    weights = sum(RESOURCES[item].bytes for item in model.resources)
    base = assess_base(report)
    if not base.selectable:
        return Assessment(model_id, base.status, base.reasons)
    if report.avx2 is False:
        return Assessment(model_id, "incompatible", ("当前固定本地引擎要求 AVX2 指令支持",))
    if backend == "cuda" and not report.gpus and not any("NVIDIA" in reason for reason in report.unknown_reasons):
        return Assessment(model_id, "incompatible", ("未检测到可用 NVIDIA CUDA 设备，可选择 CPU 路线",))
    drivers = tuple(cuda_driver_status(gpu.driver) for gpu in report.gpus)
    if backend == "cuda" and drivers and all(status == "incompatible" for status in drivers):
        return Assessment(model_id, "incompatible", ("固定 CUDA 12.4 引擎要求 Windows 驱动至少 528.33，请更新驱动或选择 CPU",))
    # 下载与临时文件并存；解压后的引擎、运行依赖另计，不冒充精确峰值。
    if report.model_free is not None and report.model_free < weights + 256 * 2**20:
        return Assessment(model_id, "insufficient", ("模型盘当前可用空间不足，请释放空间或更改目录后重试",))
    if report.app_free is not None and report.app_free < 2 * 2**30:
        return Assessment(model_id, "insufficient", ("应用盘当前空间不足以部署依赖和引擎",))
    # 系统内存与 GPU 可用显存共同承载权重，保留基础桌宠余量；不依赖显卡名称。
    gpu_free = max((gpu.memory_free for gpu in report.gpus), default=0) if backend != "cpu" else 0
    if report.memory_available is not None and report.memory_available + gpu_free < weights + 2 * 2**30:
        return Assessment(model_id, "insufficient", ("当前可用内存及显存不足以容纳权重与基础桌宠余量",))
    unknown = (report.os_build is None or report.avx2 is None or report.memory_available is None
               or report.model_free is None or report.app_free is None)
    if unknown:
        return Assessment(model_id, "unknown", ("部分环境探测未知，可重新检测；未知不等于不兼容",))
    if backend == "cuda" and (not drivers or not any(status == "supported" for status in drivers)):
        return Assessment(model_id, "unverified", ("驱动未知或只满足 CUDA minor compatibility，当前固定引擎仍需验证",))
    if model.verification == "failed":
        return Assessment(model_id, "unverified", ("实验模型：完整语义验收未通过，仍可手动选择，不能作为完整自动备用",))
    if model.verification != "verified" or backend == "cpu" or not report.gpus:
        return Assessment(model_id, "unverified", ("当前模型或后端尚未完成本项目完整业务验收，可能较慢",))
    if gpu_free < weights:
        return Assessment(model_id, "slow", ("部分权重需由系统内存承载，预计等待增加，仍可选择",))
    return Assessment(model_id, "estimated", ("当前资源预计可承载；尚未加载测量实际响应速度",))


def assess_base(report: DeviceReport):
    """API-only 的基础桌宠检查不要求 AVX2、显卡或本地模型盘。"""
    if report.system and report.system != "Windows":
        return Assessment("base", "incompatible", ("当前桌面安装包仅支持 Windows",))
    if report.architecture and report.architecture.lower() not in ("amd64", "x86_64"):
        return Assessment("base", "incompatible", ("当前桌面安装包仅支持 x64",))
    if report.os_build is not None and report.os_build < 17763:
        return Assessment("base", "incompatible", ("当前 Qt 运行时需要 Windows 10 1809 或更新系统",))
    if report.memory_available is not None and report.memory_available < 512 * 2**20:
        return Assessment("base", "insufficient", ("当前可用内存不足基础桌宠的预留量（512 MiB）",))
    if report.app_free is not None and report.app_free < 2 * 2**30:
        return Assessment("base", "insufficient", ("应用盘空间不足运行环境预计预留量（2 GiB）",))
    # 先保留明确阻止结论；基础事实缺失时允许重试，不能误报预检通过。
    if (not report.system or not report.architecture or report.os_build is None
            or report.memory_available is None or report.app_free is None):
        return Assessment("base", "unknown", ("基础环境探测未知，可重新检测；未知不等于不兼容",))
    return Assessment("base", "estimated", ("基础资源预检通过，实际界面和语音负载仍需运行验证",))
