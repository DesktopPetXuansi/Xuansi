"""久置拔刀动作的纯时序计算及低分辨率透明姿态缓存。"""

import logging
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter, QPixmap, QRegion

LOG = logging.getLogger(__name__)
IDLE_BLADE_ASSET_DIR = Path(__file__).resolve().parents[1] / "assets/xuansi/idle-blade"
IDLE_BLADE_FRAME_FILES = ("reach.png", "grip.png", "draw-half.png", "drawn.png")
IDLE_BLADE_SEQUENCE = (0, 1, 2, 3, 3, 2, 1, 0)
IDLE_BLADE_FRAME_DURATIONS = (0.28, 0.30, 0.35, 0.18, 0.88, 0.35, 0.30, 0.28)
IDLE_BLADE_TOTAL_SECONDS = sum(IDLE_BLADE_FRAME_DURATIONS)
IDLE_BLADE_FADE_SECONDS = 0.18
IDLE_BLADE_SCALE = 0.92


def idle_blade_pose(elapsed):
    """返回当前时刻应显示的姿态编号；动作区间外返回空值。"""
    elapsed = float(elapsed)
    if elapsed < 0.0 or elapsed >= IDLE_BLADE_TOTAL_SECONDS:
        return None

    boundary = 0.0
    for pose, duration in zip(IDLE_BLADE_SEQUENCE, IDLE_BLADE_FRAME_DURATIONS, strict=True):
        boundary += duration
        if elapsed < boundary:
            return pose
    return None


def idle_blade_opacity(elapsed):
    """两端在短时间内渐隐，避免拔刀动作突然盖住或切回模型。"""
    elapsed = float(elapsed)
    if elapsed <= 0.0 or elapsed >= IDLE_BLADE_TOTAL_SECONDS:
        return 0.0
    return min(
        1.0,
        elapsed / IDLE_BLADE_FADE_SECONDS,
        (IDLE_BLADE_TOTAL_SECONDS - elapsed) / IDLE_BLADE_FADE_SECONDS,
    )


def load_idle_blade_frames(width, height):
    """启动时把四张高分辨率图缩小缓存，绘制循环只读内存中的桌宠尺寸帧。"""
    frames = []
    mask = QRegion()
    target_width = max(1, round(width * IDLE_BLADE_SCALE))
    target_height = max(1, round(height * IDLE_BLADE_SCALE))

    for filename in IDLE_BLADE_FRAME_FILES:
        path = IDLE_BLADE_ASSET_DIR / filename
        source = QPixmap(str(path))
        if source.isNull():
            raise OSError(f"待机拔刀姿态无法读取：{path.name}")

        sprite = source.scaled(
            target_width,
            target_height,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        canvas = QPixmap(width, height)
        canvas.fill(Qt.GlobalColor.transparent)
        painter = QPainter(canvas)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawPixmap((width - sprite.width()) // 2, (height - sprite.height()) // 2, sprite)
        painter.end()
        frames.append(canvas)
        mask = mask.united(QRegion(canvas.mask()))

    if len(frames) != len(IDLE_BLADE_FRAME_FILES) or mask.isEmpty():
        raise ValueError("待机拔刀姿态素材不完整或没有可见像素")

    LOG.info("久置拔刀姿态已缓存 frames=%d size=%dx%d", len(frames), width, height)
    return tuple(frames), mask
