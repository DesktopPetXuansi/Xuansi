"""识别产品已准备的本地候选；不加载引擎，不下载资源或改变用户首选。"""

from __future__ import annotations

import logging
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from .catalog import MODELS
from .selection import Candidate

if TYPE_CHECKING:
    from ..config import Settings

LOG = logging.getLogger(__name__)


def _verified_local(settings: Settings, model_id: str, model_path: str, projector_path: str, root: Path):
    model = MODELS.get(model_id)
    if (model is None or model.verification != 'verified' or settings.ai.local_backend != 'cuda'
            or settings.gpu_layers == 0):
        return False
    # 自定义文件可手动选择；自动链只接纳固定目录已验收的模型和后端组合。
    pairs = ((Path(model_path), root / model.model_path), (Path(projector_path), root / model.projector_path))
    return all(actual.is_file() and actual.resolve() == expected.resolve() for actual, expected in pairs)


def prepared_local_candidates(settings: Settings, *, model_root: Path):
    """默认根目录由产品入口提供；配置中的显式目录继续优先。"""
    ai = settings.ai
    root = Path(ai.model_dir) if ai.model_dir else model_root
    candidates = []
    if settings.model_path and settings.projector_path:
        candidates.append(Candidate(
            ai.local_model, settings, display_name=Path(settings.model_path).stem,
            verified_fallback=_verified_local(settings, ai.local_model, settings.model_path,
                                              settings.projector_path, root)))
    # 备用仍受当前 4B 语义验收记录约束，存在文件不等于允许隐式回退。
    if (ai.backup_model_path and ai.backup_projector_path
            and _verified_local(settings, 'qwen3.5-4b', ai.backup_model_path, ai.backup_projector_path, root)):
        backup = replace(settings, model_path=ai.backup_model_path, projector_path=ai.backup_projector_path)
        candidates.append(Candidate('qwen3.5-4b', backup, display_name=Path(backup.model_path).stem,
                                    verified_fallback=True))
    LOG.debug('本地候选准备完成 count=%d', len(candidates))
    return tuple(candidates)
