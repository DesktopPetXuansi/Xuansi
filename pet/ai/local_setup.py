"""Prepare the selected catalog model in the user's model directory."""

import shutil
from dataclasses import dataclass
from pathlib import Path

from .catalog import MODELS, Resource
from .install_plan import user_model_dir
from .local_candidates import find_local_model, resource_present, resources_for_model
from .resource_download import fetch_resource


@dataclass(frozen=True)
class ModelDownload:
    model_id: str
    name: str
    root: Path
    resources: tuple[Resource, ...]

    @property
    def size(self):
        return sum(resource.bytes for resource in self.resources)


def inspect_local_setup(settings, model_root):
    if settings.ai.policy == "online_first":
        return False, None
    if find_local_model(settings, model_root=model_root) is not None:
        return True, None
    model = MODELS.get(settings.ai.local_model)
    if model is None:
        return False, None
    # An inferred legacy location is a lookup hint. New downloads default to a per-user location.
    root = Path(settings.ai.model_dir).expanduser().absolute() if settings.ai.model_dir else user_model_dir()
    missing = tuple(resource for resource in resources_for_model(model)
                    if not resource_present(root / resource.path, resource.bytes))
    return False, ModelDownload(settings.ai.local_model, model.name, root, missing)


def download_model(plan, stop, report):
    from PySide6.QtCore import QLockFile

    plan.root.mkdir(parents=True, exist_ok=True)
    lock = QLockFile(str(plan.root / '.xuansi-model-download.lock'))
    lock.setStaleLockTime(0)
    if not lock.tryLock(0):
        raise ValueError('已有玄司正在准备此目录里的模型。请稍后重新检查。')
    try:
        free = shutil.disk_usage(plan.root).free
        if free < plan.size:
            # A paused download already occupies disk space, so budget only for what remains.
            remaining = plan.size
            for resource in plan.resources:
                path = plan.root / (resource.path + '.xuansi.part')
                if path.is_file():
                    remaining -= min(resource.bytes, path.stat().st_size)
            if free < remaining:
                raise ValueError('模型目录所在磁盘空间不足。请释放空间或在模型设置更换目录。')
        done = 0
        for resource in plan.resources:
            path = plan.root / resource.path
            urls = (resource.url,)
            if resource.id in ('9b-weights', '9b-projector'):
                urls += ('https://modelscope.cn/models/unsloth/Qwen3.5-9B-GGUF/resolve/master/' + path.name,)
            fetch_resource(urls, path, resource.sha256, size=resource.bytes, stop=stop,
                           partial_suffix='.xuansi.part',
                           report=lambda phase, amount: report(phase, done + amount, plan.size))
            done += resource.bytes
    finally:
        lock.unlock()
