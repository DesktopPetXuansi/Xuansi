"""识别本机已准备的模型配对，保留用户配置优先级。"""

from __future__ import annotations

import logging
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from .catalog import MODELS, RESOURCES
from .install_plan import LEGACY_MODEL_DIR, user_model_dir
from .selection import Candidate

if TYPE_CHECKING:
    from ..config import Settings

LOG = logging.getLogger(__name__)


def resource_present(path: Path, size: int):
    try:
        return path.is_file() and path.stat().st_size == size
    except OSError:
        return False


def find_local_model(settings: Settings, *, model_root: Path):
    """先用完整的显式配对，再检查已选档位的固定目录。"""
    model = MODELS.get(settings.ai.local_model)
    resources = resources_for_model(model) if model is not None else ()
    paths = (Path(settings.model_path), Path(settings.projector_path))
    if all(path.is_file() for path in paths):
        if model is None:
            return settings
        configured = (model.model_path, model.projector_path)
        if all(not ('/' + path.as_posix().casefold()).endswith('/' + name.casefold())
               or resource_present(path, resource.bytes)
               for path, name, resource in zip(paths, configured, resources, strict=True)):
            return settings
    if model is None:
        return None
    if settings.ai.policy == 'online_first':
        return None  # 在线优先仅允许原配置明确安装并通过验收的本机回退。
    roots = [Path(settings.ai.model_dir)] if settings.ai.model_dir else []
    roots.extend((model_root, user_model_dir(), LEGACY_MODEL_DIR))
    for root in dict.fromkeys(roots):
        weights, projector = (root / model.model_path, root / model.projector_path)
        if all(resource_present(path, resource.bytes)
               for path, resource in zip((weights, projector), resources, strict=True)):
            return replace(settings, model_path=str(weights), projector_path=str(projector))
    return None


def resources_for_model(model):
    return tuple(RESOURCES[key] for key in model.resources)


def uses_catalog_paths(settings: Settings, model_root: Path):
    model = MODELS.get(settings.ai.local_model)
    if model is None:
        return False
    root = Path(settings.ai.model_dir) if settings.ai.model_dir else model_root
    return (Path(settings.model_path) == root / model.model_path
            and Path(settings.projector_path) == root / model.projector_path)


def _presentation_verified(model_id: str, model_path: str, projector_path: str, root: Path):
    """仅对已做合成协议探针的固定 9B 资源开放可选表情输出。"""
    model = MODELS.get(model_id)
    if model_id != 'qwen3.5-9b' or model is None or model.verification != 'verified':
        return False
    pairs = (
        (Path(model_path), root / model.model_path, RESOURCES['9b-weights'].bytes),
        (Path(projector_path), root / model.projector_path, RESOURCES['9b-projector'].bytes),
    )
    try:
        return all(actual.is_file() and actual.resolve() == expected.resolve() and actual.stat().st_size == size
                   for actual, expected, size in pairs)
    except OSError:
        return False


def _verified_local(settings: Settings, model_id: str, model_path: str, projector_path: str, root: Path):
    model = MODELS.get(model_id)
    if (model is None or model.verification != 'verified' or settings.ai.local_backend != 'cuda'
            or settings.gpu_layers == 0):
        return False
    # 自定义文件可手动选择；自动链只接纳固定目录已验收的模型和后端组合。
    pairs = ((Path(model_path), root / model.model_path), (Path(projector_path), root / model.projector_path))
    return all(resource_present(actual, resource.bytes) and actual.resolve() == expected.resolve()
               for (actual, expected), resource in zip(pairs, resources_for_model(model), strict=True))


def prepared_local_candidates(settings: Settings, *, model_root: Path):
    """默认根目录由产品入口提供；配置中的显式目录继续优先。"""
    ai = settings.ai
    root = Path(ai.model_dir) if ai.model_dir else model_root
    candidates = []
    primary = find_local_model(settings, model_root=model_root)
    if primary is not None:
        model_path, projector_path = primary.model_path, primary.projector_path
        catalog = MODELS.get(ai.local_model)
        primary_root = root
        if catalog is not None and (model_path, projector_path) != (settings.model_path, settings.projector_path):
            primary_root = Path(model_path).parents[len(Path(catalog.model_path).parts) - 1]
        candidates.append(Candidate(
            ai.local_model, primary, display_name=Path(model_path).stem,
            verified_fallback=_verified_local(primary, ai.local_model, model_path, projector_path, primary_root),
            presentation_verified=_presentation_verified(ai.local_model, model_path, projector_path, primary_root)))
    # 备用仍受当前 4B 语义验收记录约束，存在文件不等于允许隐式回退。
    if (ai.backup_model_path and ai.backup_projector_path
            and _verified_local(settings, 'qwen3.5-4b', ai.backup_model_path, ai.backup_projector_path, root)):
        backup = replace(settings, model_path=ai.backup_model_path, projector_path=ai.backup_projector_path)
        candidates.append(Candidate('qwen3.5-4b', backup, display_name=Path(backup.model_path).stem,
                                    verified_fallback=True))
    LOG.debug('本地候选准备完成 count=%d', len(candidates))
    return tuple(candidates)
