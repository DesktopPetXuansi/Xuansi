"""把本机已导入的 APNG 预生成窗口帧，播放时不解码、不读盘。"""

import logging

from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter, QPixmap, QRegion

from .animation_import import MAX_FRAMES, MAX_TOTAL_PIXELS
from .appearance import image_path

LOG = logging.getLogger(__name__)


def load_animation(identifier, width, height):
    frames, durations = [], []
    try:
        with Image.open(image_path(identifier), formats=("PNG",)) as source:
            count = getattr(source, "n_frames", 1)
            if count > MAX_FRAMES or source.width * source.height * count > MAX_TOTAL_PIXELS:
                raise ValueError("动图副本超出范围")
            for index in range(count):
                source.seek(index)
                pixels = source.convert("RGBA")
                data = pixels.tobytes()
                image = QImage(data, pixels.width, pixels.height, QImage.Format.Format_RGBA8888)
                sprite = QPixmap.fromImage(image).scaled(
                    width - 12,
                    height - 12,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                canvas = QPixmap(width, height)
                canvas.fill(Qt.GlobalColor.transparent)
                painter = QPainter(canvas)
                painter.drawPixmap((width - sprite.width()) // 2, (height - sprite.height()) // 2, sprite)
                painter.end()
                frames.append((canvas, QRegion(canvas.mask())))
                durations.append(max(20, min(10000, round(source.info.get("duration", 100) or 100))))
        if not any(not region.isEmpty() for _, region in frames):
            raise ValueError("动图副本没有可见内容")
        LOG.info("动图帧缓存完成 frames=%s size=%sx%s", len(frames), width, height)
        return frames, durations
    except (OSError, ValueError, Image.DecompressionBombError) as exc:
        LOG.warning("动图副本不可用，回退玄司 type=%s", type(exc).__name__)
        return None
