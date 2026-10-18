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

    load_finished = Signal(bool, str)

    def __init__(self, parent, *, size=224):
        self.prepared_model = None
        super().__init__(size, parent=parent)
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
        if self.prepared_model is not None:
            # Qt 重建上下文时也保持候选，不能经父类误载默认模型。
            self._live2d_requested = False
        super().initializeGL()
        if self.prepared_model is not None:
            self._load_preview_target()
        else:
            self._report_loaded()
        self.motion_capabilities_changed.emit(self.available_motions)

    def _load_preview_target(self):
        """GL 就绪事件或重新显示触发一次试载，不轮询、不把图片回退当模型成功。"""
        if not self._live2d_ready:
            return
        if self.prepared_model is not None:
            try:
                version = self.prepared_model[0]["resourceVersionId"]
                if not self._live2d_active or self._platform_model_version != version:
                    self.select_platform_model(version, self.prepared_model)
            except Exception as exc:
                self._live2d_requested = False
                self._live2d_failed = True
                LOG.warning("形象模型预览失败 type=%s", type(exc).__name__)
                self.load_finished.emit(False, "模型预览失败，请检查模型是否完整、格式是否兼容")
                return
        elif not self._live2d_active:
            self._live2d_failed = False
            self.makeCurrent()
            try:
                self._live2d_requested = True
                self._ensure_live2d()
                self._set_render_mode()
            finally:
                self.doneCurrent()
        self._report_loaded()

    def _report_loaded(self):
        success = self._live2d_active
        self.load_finished.emit(success, "形象预览已就绪" if success else "默认形象动态预览不可用，请重新打开后重试")

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
        if ready:
            self._load_preview_target()
            self.motion_capabilities_changed.emit(self.available_motions)


class AppearancePreview(QWidget):
    motion_capabilities_changed = Signal(object)
    load_finished = Signal(bool, str)

    def __init__(self, parent=None, *, size=224):
        super().__init__(parent)
        self.preview_size = size
        self.setFixedHeight(size + 14)
        self.identifier = ""
        self.image_failed = False
        # 在顶层窗口显示前加入 GL 子控件，避免 Qt 重建原生窗口引起 showEvent 重入。
        self.renderer = PreviewAvatar(self, size=size)
        self.renderer.hide()
        self.frames = self.renderer.frames
        self.durations, self.native = self.renderer.durations, self.renderer.native_animation
        self.index = 0
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.timeout.connect(self.advance)
        self.renderer.motion_capabilities_changed.connect(self.motion_capabilities_changed.emit)
        self.renderer.load_finished.connect(self.load_finished.emit)

    def set_image(self, identifier):
        self.stop()
        self.renderer.prepared_model = None
        self.renderer._live2d_requested = False
        self.renderer._live2d_failed = False
        self.renderer._platform_model_version = ""
        self.renderer._platform_expression = False
        self.renderer._platform_parameters = {}
        self.image_failed = False
        self.identifier = identifier
        if identifier:
            try:
                # 与明确应用共用严格解码，既不接受默认回退，也不重复读取同一张图片。
                self.frames, self.durations, self.native = build_frames(self.preview_size, identifier, strict=True)
            except (ValueError, OSError, RuntimeError):
                self.identifier = ""
                self.image_failed = True
                LOG.warning("形象图片预览失败")
                self.load_finished.emit(False, "图片预览失败，请重新导入图片或动图")
                return
            self.load_finished.emit(True, "形象预览已就绪")
        else:
            # 同样的空 image_id 也可能正在显示平台模型，必须强制解除该选择。
            self.renderer.set_image("", force=True)
            self.frames = self.renderer.frames
            self.durations, self.native = self.renderer.durations, self.renderer.native_animation
        self.index = 0
        self.update()
        self.timer.setInterval(self.durations[0])
        if self.isVisible():
            self.start()

    def set_model(self, prepared):
        """只改变独立预览器的候选，等待真正的 GL 试载成功后才通知宿主。"""
        self.stop()
        self.identifier = ""
        self.image_failed = False
        self.renderer.prepared_model = prepared
        self.renderer._live2d_requested = False
        self.renderer._live2d_failed = False
        self.update()
        if self.isVisible():
            self.start()

    @property
    def available_motions(self):
        return self.renderer.available_motions

    def play_motion(self, motion):
        """按钮只驱动当前预览的模型，不向桌宠发送动作或写入任何配置。"""
        return self.renderer.play_motion(motion)

    def start(self):
        if self.image_failed:
            return
        if self.identifier:
            self.timer.start()
            return
        self.renderer.move((self.width() - self.renderer.width()) // 2, 7)
        self.renderer.resume()
        LOG.info("桌宠形象动态预览已打开 custom=%s", self.renderer.prepared_model is not None)

    def stop(self):
        """隐藏时停止绘制并在有效 GL 上下文中释放模型，保留控件供窗口重开。"""
        self.timer.stop()
        if not self.renderer.isHidden() or self.renderer._live2d_module is not None:
            self.renderer.hide()
            self.renderer._release_live2d()
            LOG.info("桌宠形象动态预览已关闭")
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
