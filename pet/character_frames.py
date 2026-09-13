"""玄司的轻量全身动作；缩放、旋转和透明点击区域只在尺寸变化时生成。"""

import logging
import math
import time

from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter, QPixmap, QRegion

from .config import ROOT

LOG = logging.getLogger(__name__)
STATES = ("idle", "thinking", "happy", "sleep", "walk_left", "walk_right")


def build_frames(height):
    started = time.perf_counter()
    width = round(height * 0.75)
    original = QPixmap(str(ROOT / "assets/xuansi/front.png"))
    if original.isNull():
        raise RuntimeError("玄司形象素材缺失，请检查 assets/xuansi/front.png")
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
    LOG.info("玄司形象已加载 height=%s frames=%s elapsed=%.3fs", height, 48, time.perf_counter() - started)
    return animations
