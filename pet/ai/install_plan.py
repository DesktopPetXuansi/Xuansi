"""无秘密安装计划与资源集合，部署入口不重新决定模型和用户策略。"""

import json
import logging
import os
from dataclasses import asdict, dataclass, fields, replace
from pathlib import Path
from typing import TYPE_CHECKING

from .assessment import assess, assess_base, preferred_backend
from .catalog import MODELS, RESOURCES
from .device import DeviceReport

if TYPE_CHECKING:
    from .settings import ModelProfile

LOG = logging.getLogger(__name__)


def default_model_dir():
    """识别已有旧模型目录；新安装使用当前用户目录，不要求 D 盘。"""
    legacy = Path("D:/AI/Models/desktop-pet")
    if legacy.is_dir():
        return str(legacy)
    return str(Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Xuansi" / "models")


@dataclass(frozen=True)
class InstallPlan:
    schema_version: int = 1
    mode: str = "local"
    primary_model_id: str = "qwen3.5-9b"
    backup_model_ids: tuple[str, ...] = ()
    backend: str = "auto"
    app_dir: str = ""
    model_dir: str = ""
    voice_components: tuple[str, ...] = ()
    policy: str = "local_only"
    provider_profile_id: str = ""
    credential_ref: str = ""

    def validate(self):
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValueError("不支持的安装计划版本")
        if self.mode not in ("local", "api") or self.backend not in ("auto", "cuda", "cpu"):
            raise ValueError("安装模式或后端无效")
        if self.policy not in ("local_only", "local_first", "online_first"):
            raise ValueError("回退策略无效")
        if self.primary_model_id not in MODELS or any(item not in MODELS for item in self.backup_model_ids):
            raise ValueError("模型不在固定目录中")
        if any(item not in ("asr", "tts", "realtime") for item in self.voice_components):
            raise ValueError("语音组件无效")
        for value in (self.app_dir, self.model_dir):
            if not isinstance(value, str) or (value and (not Path(value).is_absolute() or '"' in value)):
                raise ValueError("安装和模型目录必须为不含引号的绝对路径")
        for value in (self.provider_profile_id, self.credential_ref):
            if not isinstance(value, str) or any(ord(char) < 32 for char in value):
                raise ValueError("提供方引用无效")
        return self

    @property
    def download_bytes(self):
        return sum(resource.bytes for resource in resources_for(self))


def resources_for(plan: InstallPlan):
    plan.validate()
    selected = []
    if plan.mode == "local":
        for model_id in (plan.primary_model_id, *plan.backup_model_ids):
            selected.extend(MODELS[model_id].resources)
        # auto 的选择在前置检测阶段固定为具体后端，未检测时保守使用 CPU。
        selected.extend(("llama-cuda", "cudart") if plan.backend == "cuda" else ("llama-cpu",))
    for component in plan.voice_components:
        selected.extend({"asr": ("sensevoice",), "tts": ("melo", "kokoro"),
                         "realtime": ("realtime-encoder", "realtime-decoder", "realtime-tokens")}[component])
    return tuple(RESOURCES[item] for item in dict.fromkeys(selected))


def prepare_plan(plan: InstallPlan, report: DeviceReport, profile: "ModelProfile | None" = None):
    """按已提供的设备事实定稿新计划；探测、档案读取和保存由调用方负责。"""
    plan.validate()
    base = assess_base(report)
    if not base.selectable:
        raise ValueError("；".join(base.reasons))
    plan = replace(plan, backend=preferred_backend(report) if plan.backend == "auto" else plan.backend)
    if profile is not None:
        if not profile.is_verified("text", "image", "tools", "stream", "cancel"):
            raise ValueError("API 配置尚未完成能力验证")
        plan = replace(plan, provider_profile_id=profile.fingerprint(), credential_ref=profile.credential_ref)
    if plan.mode == "local":
        for selected in (plan.primary_model_id, *plan.backup_model_ids):
            result = assess(report, selected, plan.backend)
            if not result.selectable:
                raise ValueError("；".join(result.reasons))
    _validate_space(plan, report)
    LOG.info("安装计划已定稿，模式=%s，后端=%s", plan.mode, plan.backend)
    return plan


def _validate_space(plan: InstallPlan, report: DeviceReport):
    """同时保留下载、运行依赖与解压暂存预算，不重复使用同卷容量。"""
    # 确认页同时核算主模型、备用、语音与暂存余量，不对安装中的资源变化作保证。
    resources = resources_for(plan)
    model_bytes = sum(item.bytes for item in resources if item.location == "models")
    runtime_bytes = sum(item.bytes for item in resources if item.location == "runtime")
    archive_bytes = sum(item.bytes for item in resources if item.location == "models" and item.archive)
    model_reserve = model_bytes + archive_bytes * 2
    app_reserve = runtime_bytes * 3 + 2 * 2**30
    app_volume, model_volume = getattr(report, "app_volume", None), getattr(report, "model_volume", None)
    if model_bytes and app_volume is not None and app_volume == model_volume:
        # 两次采样可能不同或部分未知；同卷必须共用最小已知可用量，不能重复花费。
        available = [value for value in (report.app_free, report.model_free) if value is not None]
        if available and min(available) < app_reserve + model_reserve:
            raise ValueError("应用与模型目录位于同一卷，空间不足以保留所选资源、运行依赖与解压暂存余量")
    elif model_bytes and (app_volume is None or model_volume is None):
        LOG.warning("卷身份未知，无法确认共用空间预算；保留各目录已知空间检查")
    if model_bytes and report.model_free is not None and report.model_free < model_reserve:
        raise ValueError("模型盘空间不足以保留所选资源与归档解压暂存余量")
    if report.app_free is not None and report.app_free < app_reserve:
        raise ValueError("应用盘空间不足以部署运行依赖与所选引擎")


def save_plan(plan: InstallPlan, path: Path):
    plan.validate()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(asdict(plan), ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)
    LOG.info("安装计划已保存，模式=%s，资源数=%d", plan.mode, len(resources_for(plan)))


def load_plan(path: Path):
    raw = json.loads(path.read_text(encoding="utf-8-sig"))
    allowed = {field.name for field in fields(InstallPlan)}
    if not isinstance(raw, dict) or raw.keys() - allowed:
        raise ValueError("安装计划包含未知字段，拒绝保存秘密或任意资源")
    for name in ("backup_model_ids", "voice_components"):
        if name in raw:
            if not isinstance(raw[name], list) or any(not isinstance(item, str) for item in raw[name]):
                raise ValueError("安装计划列表字段无效")
            raw[name] = tuple(raw[name])
    return InstallPlan(**raw).validate()
