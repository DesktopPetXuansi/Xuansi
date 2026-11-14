"""首次聊天的无秘密状态：文件存在仅代表资源线索，真实成功由对话运行时确认。"""

import json
import logging
import tempfile
from pathlib import Path

LOG = logging.getLogger(__name__)


def read_completed(path: Path):
    try:
        if path.stat().st_size > 1024:
            return False
        value = json.loads(path.read_text(encoding='utf-8'))
        return (isinstance(value, dict) and type(value.get('version')) is int
                and value['version'] == 1 and value.get('completed') is True)
    except FileNotFoundError:
        return False
    except (OSError, ValueError):
        LOG.warning('首次聊天标记无法读取，保留原文件并显示使用提示')
        return False


def save_completed(path: Path):
    """只保存成功布尔值；原子替换，不能混入配置、正文或凭据。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         prefix='.first-chat-', suffix='.tmp', delete=False) as output:
            temporary = Path(output.name)
            json.dump({'version': 1, 'completed': True}, output)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    LOG.info('首次文字聊天完成标记已保存')


def check_setup(settings):
    """仅在后台检查已保存配置，不加载模型、读密钥或调用收费接口。"""
    if settings.ai.policy == 'online_first':
        profile = settings.ai.profile
        if not all((profile.endpoint, profile.model, profile.credential_ref)):
            return '在线配置尚未填完整。到模型设置填写服务、模型和 API Key，保存后回来聊天。'
        return '在线配置已保存，连接待对话确认。发送的文字会交给所选服务，可能产生 API 费用。'
    found = all(Path(path).is_file() for path in (settings.model_path, settings.projector_path))
    hint = ('本地模型文件已找到，实际运行待对话确认。可直接在下方发送一句话。' if found
            else '本地模型或配套组件未找到。到模型设置确认资源和路径，保存后回来聊天。')
    if settings.ai.policy == 'local_first':
        hint += ' 已选本地优先；若转用已配置的在线服务，会传输文字且可能产生费用。'
    return hint
