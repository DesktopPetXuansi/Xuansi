"""独立记忆普通窗口宽高；只在明确收起时短写入，不进入业务配置事务。"""

import json
import logging
from pathlib import Path

from PySide6.QtWidgets import QStyle

LOG = logging.getLogger(__name__)
DEFAULT_SIZE = (720, 560)


def restore_size(window, path: Path | None):
    width, height = DEFAULT_SIZE
    if path is not None:
        try:
            saved = json.loads(path.read_text(encoding='utf-8'))
            candidate = (saved['width'], saved['height'])
            if any(type(value) is not int or value <= 0 for value in candidate):
                raise ValueError('窗口大小需要正整数')
            width, height = candidate
        except FileNotFoundError:
            pass
        except (OSError, ValueError, KeyError, TypeError):
            LOG.warning('窗口大小记录无法读取，使用默认尺寸')
    # QWidget 和 QScreen 均使用逻辑像素；预留原生标题栏与边框，不再乘 DPR。
    available = window.screen().availableGeometry()
    style = window.style()
    frame = style.pixelMetric(QStyle.PixelMetric.PM_DefaultFrameWidth)
    title = style.pixelMetric(QStyle.PixelMetric.PM_TitleBarHeight)
    width = max(window.minimumWidth(), min(width, available.width() - 2 * frame))
    height = max(window.minimumHeight(), min(height, available.height() - title - 2 * frame))
    window.resize(width, height)
    LOG.info('控制中心窗口大小已恢复 width=%s height=%s', width, height)


def save_size(window, path: Path | None):
    if path is None:
        return
    # 最大化、全屏及最小化都只记恢复后的普通尺寸，不记整个屏幕大小。
    size = (window.normalGeometry().size()
            if window.isMaximized() or window.isFullScreen() or window.isMinimized() else window.size())
    if size.isEmpty():
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps({'width': size.width(), 'height': size.height()}), encoding='utf-8')
        temporary.replace(path)
        LOG.debug('控制中心窗口大小已保存 width=%s height=%s', size.width(), size.height())
    except OSError:
        # 窗口偏好保存失败不阻塞收起，也不能触发业务设置或改变运行状态。
        LOG.warning('无法保存控制中心窗口大小，本次仍正常收起')
