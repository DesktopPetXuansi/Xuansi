"""默认形象复用桌宠 Live2D，导入图片使用缓存帧；关闭时释放预览模型。"""

import logging

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QRegion
from PySide6.QtWidgets import QWidget

from .avatar import Avatar
from .character_frames import build_frames

LOG = logging.getLogger(__name__)
LIGHT_BACKGROUND = QColor("#efeee8")
DARK_BACKGROUND = QColor("#35413d")


class PreviewAvatar(Avatar):
    """只复用绘制和已绑定动作，预览不拖动、不显示气泡、不执行久置拔刀。"""

    def __init__(self, parent):
        super().__init__(224, parent=parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def _load_idle_blade_frames(self):
        self._idle_blade_frames = ()
        self._idle_blade_mask = QRegion()

    def _live2d_window_mask(self):
        return QRegion(self.rect())

    def _frame_mask(self):
        super()._frame_mask()
        self.clearMask()  # 预览使用完整矩形，摆动发丝不受桌面透明点击蒙版限制。

    def initializeGL(self):
        super().initializeGL()
        # 加载失败也通知按钮状态；不把 PNG 回退声称为可执行 Live2D 动作。
        self.motion_capabilities_changed.emit(self.available_motions)

    def paintGL(self):
        super().paintGL()
        painter = QPainter(self)
        # 在透明角色后补背景，保持导入图片与 Live2D 的透明度预览一致。
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationOver)
        painter.fillRect(0, 0, self.width() // 2, self.height(), LIGHT_BACKGROUND)
        painter.fillRect(self.width() // 2, 0, self.width(), self.height(), DARK_BACKGROUND)
        painter.end()

    def resume(self):
        """窗口重开时只重建自身模型，保留已经创建的 Qt GL 控件。"""
        ready = self._live2d_ready
        self.show()
        if ready and not self._live2d_active:
            self._live2d_failed = False
            self.makeCurrent()
            try:
                self._ensure_live2d()
                self._set_render_mode()
            finally:
                self.doneCurrent()
            self.motion_capabilities_changed.emit(self.available_motions)


class AppearancePreview(QWidget):
    motion_capabilities_changed = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(238)
        self.identifier = ""
        # 在顶层窗口显示前加入 GL 子控件，避免 Qt 重建原生窗口引起 showEvent 重入。
        self.renderer = PreviewAvatar(self)
        self.renderer.hide()
        self.frames = self.renderer.frames
        self.durations, self.native = self.renderer.durations, self.renderer.native_animation
        self.index = 0
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.timeout.connect(self.advance)
        self.renderer.motion_capabilities_changed.connect(self.motion_capabilities_changed.emit)

    def set_image(self, identifier):
        self.stop()
        self.identifier = identifier
        if identifier:
            self.frames, self.durations, self.native = build_frames(224, identifier)
        else:
            self.frames = self.renderer.frames
            self.durations, self.native = self.renderer.durations, self.renderer.native_animation
        self.index = 0
        self.update()
        self.timer.setInterval(self.durations[0])
        if self.isVisible():
            self.start()

    @property
    def available_motions(self):
        return self.renderer.available_motions

    def play_motion(self, motion):
        """按钮只驱动当前预览的模型，不向桌宠发送动作或写入任何配置。"""
        return self.renderer.play_motion(motion)

    def start(self):
        if self.identifier:
            self.timer.start()
            return
        self.renderer.move((self.width() - self.renderer.width()) // 2, 7)
        self.renderer.resume()
        LOG.info("默认玄司动态预览已打开")

    def stop(self):
        """隐藏时停止绘制并在有效 GL 上下文中释放模型，保留控件供窗口重开。"""
        self.timer.stop()
        if not self.renderer.isHidden() or self.renderer._live2d_module is not None:
            self.renderer.hide()
            self.renderer._release_live2d()
            LOG.info("默认玄司动态预览已关闭")
        self.motion_capabilities_changed.emit(())

    def advance(self):
        self.index = (self.index + 1) % len(self.durations)
        self.timer.setInterval(self.durations[self.index])
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        # 浅、深两块底色方便辨认透明区域，底色不会写入图片。
        painter.fillRect(0, 0, self.width() // 2, self.height(), LIGHT_BACKGROUND)
        painter.fillRect(self.width() // 2, 0, self.width(), self.height(), DARK_BACKGROUND)
        if self.identifier:
            frame = self.frames["idle"][self.index][0]
            painter.drawPixmap((self.width() - frame.width()) // 2, 7, frame)

    def resizeEvent(self, event):
        self.renderer.move((self.width() - self.renderer.width()) // 2, 7)
        super().resizeEvent(event)

    def showEvent(self, event):
        self.start()
        super().showEvent(event)

    def hideEvent(self, event):
        self.stop()
        super().hideEvent(event)
