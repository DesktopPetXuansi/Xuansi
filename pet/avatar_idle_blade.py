"""久置拔刀缓存帧遮罩层、播放状态与透明度淡出。"""

import logging
import time

from PySide6.QtCore import Qt
from PySide6.QtGui import QRegion
from PySide6.QtWidgets import QGraphicsOpacityEffect, QLabel

from .avatar_mask import _expand_mask_region
from .idle_blade_animation import (
    IDLE_BLADE_FADE_SECONDS,
    idle_blade_opacity,
    idle_blade_pose,
    load_idle_blade_frames,
)

# 保留原 pet.avatar 日志来源；每帧计算保持无日志和无磁盘访问。
LOG = logging.getLogger("pet.avatar")


class AvatarIdleBlade:
    """久置拔刀缓存帧遮罩层、播放状态与透明度淡出。"""

    def _init_idle_blade_state(self):
        """构造透明遮罩层，随后仍由 set_size 同步几何与缓存帧。"""
        self._idle_blade_frames = ()
        self._idle_blade_mask = QRegion()
        self._idle_blade_started = None
        self._idle_blade_fade_out = None
        self._idle_blade_visible_pose = None
        self._idle_blade_visible_opacity = -1.0
        self._idle_blade_overlay = QLabel(self)
        self._idle_blade_overlay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._idle_blade_overlay.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._idle_blade_overlay.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._idle_blade_overlay.setStyleSheet("background: transparent; border: none;")
        self._idle_blade_effect = QGraphicsOpacityEffect(self._idle_blade_overlay)
        self._idle_blade_effect.setOpacity(0.0)
        self._idle_blade_overlay.setGraphicsEffect(self._idle_blade_effect)
        self._idle_blade_overlay.hide()

    @property
    def supports_idle_blade(self):
        """只有默认 Live2D 模型和完整透明动作帧才允许播放。"""
        return bool(self._live2d_active and self._live2d_model is not None and self._idle_blade_frames)

    def _load_idle_blade_frames(self):
        """按当前桌宠尺寸预缩放动作帧，避免空闲动画中途读盘或解码。"""
        if not self._live2d_requested:
            self._idle_blade_frames = ()
            self._idle_blade_mask = QRegion()
            return
        try:
            self._idle_blade_frames, self._idle_blade_mask = load_idle_blade_frames(
                self.width(), self.height()
            )
            padding = max(2, round(self.height() * 0.01))
            self._idle_blade_mask = _expand_mask_region(self._idle_blade_mask, padding)
        except (OSError, ValueError):
            self._idle_blade_frames = ()
            self._idle_blade_mask = QRegion()
            LOG.exception("玄司久置拔刀素材不可用，已禁用该待机动作")

    def start_idle_blade(self):
        """进入一次透明关键帧演出；姿态显示期间暂停 Live2D 绘制。"""
        if not self.supports_idle_blade or self._idle_blade_started is not None:
            return False
        self._idle_blade_fade_out = None
        self._idle_blade_started = time.monotonic()
        self.setMask(self._idle_blade_mask)
        self.update()
        LOG.info("玄司久置待机拔刀动作开始")
        return True

    def interrupt_idle_blade(self, fade=True):
        """中断拔刀动作；用户仍在操作时短暂淡回实时 Live2D。"""
        if self._idle_blade_started is None:
            if not fade and self._idle_blade_fade_out is not None:
                self._idle_blade_fade_out = None
                if self._live2d_active:
                    self.setMask(self._live2d_window_mask())
                self._present_idle_blade(None)
            return

        now = time.monotonic()
        elapsed = now - self._idle_blade_started
        pose = idle_blade_pose(elapsed)
        opacity = idle_blade_opacity(elapsed)
        self._idle_blade_started = None
        if fade and pose is not None and opacity > 0.0:
            self._idle_blade_fade_out = (pose, opacity, now)
        else:
            self._idle_blade_fade_out = None
            if self._live2d_active:
                self.setMask(self._live2d_window_mask())
            self._present_idle_blade(None)
        LOG.info("玄司久置待机拔刀动作已中断")
        self.update()

    def _idle_blade_visual(self, now):
        """返回当前预缓存姿态和透明度；每帧不访问磁盘或输出日志。"""
        pose, opacity = None, 0.0
        if self._idle_blade_started is not None:
            elapsed = now - self._idle_blade_started
            pose = idle_blade_pose(elapsed)
            opacity = idle_blade_opacity(elapsed)
            if pose is None:
                self._idle_blade_started = None
                if self._live2d_active:
                    self.setMask(self._live2d_window_mask())
                LOG.info("玄司久置待机拔刀动作结束，Live2D 绘制已恢复")
        elif self._idle_blade_fade_out is not None:
            pose, initial_opacity, started = self._idle_blade_fade_out
            opacity = initial_opacity * max(0.0, 1.0 - (now - started) / IDLE_BLADE_FADE_SECONDS)
            if opacity <= 0.0:
                self._idle_blade_fade_out = None
                self.setMask(self._live2d_window_mask())
                return None

        if pose is None or opacity <= 0.0:
            return None
        return pose, opacity

    def _present_idle_blade(self, visual):
        """用透明子控件覆盖 GL 帧缓冲，避免在 Cubism 绘制后混用 OpenGL 状态。"""
        if visual is None:
            if not self._idle_blade_overlay.isHidden():
                self._idle_blade_overlay.hide()
            self._idle_blade_visible_pose = None
            self._idle_blade_visible_opacity = -1.0
            return

        pose, opacity = visual
        if pose != self._idle_blade_visible_pose:
            self._idle_blade_overlay.setPixmap(self._idle_blade_frames[pose])
            self._idle_blade_visible_pose = pose
        if abs(opacity - self._idle_blade_visible_opacity) >= 0.01:
            self._idle_blade_effect.setOpacity(opacity)
            self._idle_blade_visible_opacity = opacity
        if not self._idle_blade_overlay.isVisible():
            self._idle_blade_overlay.show()
            self._idle_blade_overlay.raise_()
