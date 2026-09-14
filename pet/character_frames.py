"""玄司的轻量全身动作；缩放、旋转和透明点击区域只在尺寸变化时生成。"""

import logging
import math
import time

from PySide6.QtCore import Qt
from PySide6.QtGui import QImageReader, QPainter, QPixmap, QRegion

from .appearance import DEFAULT_IMAGE, image_path

LOG = logging.getLogger(__name__)
STATES = ("idle", "thinking", "happy", "sleep", "walk_left", "walk_right")


def load_pixmap(identifier=""):
    path = image_path(identifier)
    reader = QImageReader(str(path))
    size = reader.size()
    # 自定义图片应为导入器生成的小 PNG；被删除或损坏时仍显示默认角色。
    original = QPixmap()
    if size.isValid() and max(size.width(), size.height()) <= 1536:
        original = QPixmap.fromImage(reader.read())
    fallback = original.isNull() or QRegion(original.mask()).isEmpty()
    if fallback:
        LOG.warning("形象副本不可用，回退默认玄司")
        original = QPixmap(str(DEFAULT_IMAGE))
    if original.isNull():
        raise RuntimeError("默认形象素材缺失，请检查 assets/xuansi/front.png")
    return original, fallback


def build_frames(height, identifier=""):
    started = time.perf_counter()
    width = round(height * 0.75)
    if identifier.endswith(".apng"):
        from .native_animation import load_animation

        loaded = load_animation(identifier, width, height)
        if loaded is not None:
            frames, durations = loaded
            # 动图沿用原帧序，状态切换复用同一缓存，不额外扭曲原有动作。
            return {state: frames for state in STATES}, durations, True
        identifier = ""
    original, _ = load_pixmap(identifier)
    sprite = original.scaled(
        width - 12,
        height - 12,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    animations = {}
    for state in STATES:
        frames = []
        for index in range(8):
            phase = math.sin(index * math.tau / 8)
            angle, lift, opacity = 0, max(0, phase), 1
            if state == "thinking":
                angle = phase * 2
            elif state == "happy":
                lift = abs(phase) * 3
            elif state == "sleep":
                angle, opacity = -3, 0.85
            elif state.startswith("walk"):
                angle, lift = phase * 2, abs(phase) * 2
            canvas = QPixmap(width, height)
            canvas.fill(Qt.GlobalColor.transparent)
            painter = QPainter(canvas)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            painter.setOpacity(opacity)
            painter.translate(width / 2, height / 2 - lift)
            painter.rotate(angle)
            if state == "walk_left":
                painter.scale(-1, 1)
            painter.drawPixmap(-sprite.width() // 2, -sprite.height() // 2, sprite)
            painter.end()
            # QPixmap.mask() 会扫描像素，提前缓存，定时器只取帧和切换窗口区域。
            frames.append((canvas, QRegion(canvas.mask())))
        animations[state] = frames
    LOG.info(
        "桌宠形象已加载 custom=%s height=%s frames=48 elapsed=%.3fs",
        bool(identifier),
        height,
        time.perf_counter() - started,
    )
    return animations, [180] * 8, False
