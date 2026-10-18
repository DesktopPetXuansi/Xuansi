"""桌宠产品的推理依赖装配；运行时与验收入口共享同一默认配置。"""

import logging
from functools import partial

from ..config import MODELS
from ..inference import LocalEngine
from .local_candidates import prepared_local_candidates
from .providers import create_provider
from .selection import InferenceRouter

LOG = logging.getLogger(__name__)


def create_inference_router(*, on_event=None):
    """只装配依赖，实际模型加载与凭据读取仍在异步 start 阶段。"""
    router = InferenceRouter(local=LocalEngine(),
                             local_candidates=partial(prepared_local_candidates, model_root=MODELS),
                             provider_factory=create_provider, on_event=on_event)
    LOG.debug('产品推理路由已装配，尚未启动提供方')
    return router
