"""Live2D 模型加载、当帧绘制与当前 OpenGL 上下文中的资源释放。"""

import logging
import time
from pathlib import Path

from PySide6.QtGui import QPainter

from .avatar_dynamics import CLOTH_SWAY_PERIOD_SECONDS, HAIR_SWAY_PARAMETER_IDS, HAIR_SWAY_PERIOD_SECONDS
from .avatar_mask import LIVE2D_MASK_PADDING_RATIO
from .live2d_session import SESSION

# 保留原 pet.avatar 日志来源和全部初始化、失败回退与释放信息。
LOG = logging.getLogger("pet.avatar")

LIVE2D_MODEL = Path(__file__).resolve().parents[1] / "assets/xuansi/rigging/xuansi.model3.json"


LIVE2D_PARAMETERS = (
    "ParamEyeBallX",
    "ParamEyeBallY",
    "ParamEyeLOpen",
    "ParamEyeROpen",
    "ParamMouthOpenY",
    *HAIR_SWAY_PARAMETER_IDS,
    "ParamBodyAngleX",
)


class AvatarLive2D:
    """Live2D 模型加载、当帧绘制与当前 OpenGL 上下文中的资源释放。"""

    def _init_live2d_state(self, image_id):
        """延迟创建原生资源，初始化继续发生在原来的 Qt GL 上下文。"""
        self._live2d_requested = not bool(image_id)
        self._live2d_active = False
        self._live2d_failed = False
        self._live2d_ready = False
        self._live2d_module = None
        self._live2d_model = None
        self._live2d_parameter_ids = frozenset()

    def initializeGL(self):
        self._live2d_ready = True
        if self._live2d_requested:
            self._ensure_live2d()
        self._live2d_active = self._live2d_requested and self._live2d_model is not None
        self._set_render_mode()
        if self.context() is not None:
            self.context().aboutToBeDestroyed.connect(self._release_live2d)

    def _ensure_live2d(self):
        if self._live2d_model is not None or self._live2d_failed:
            return
        try:
            if not LIVE2D_MODEL.is_file():
                raise FileNotFoundError(LIVE2D_MODEL)
            LOG.info("玄司 Live2D 渲染器初始化开始")
            import live2d.v3 as live2d

            SESSION.acquire(self, live2d)
            self._live2d_module = live2d
            model = self._live2d_model = live2d.LAppModel()
            LOG.info("Live2D 模型加载开始 file=%s", LIVE2D_MODEL.name)
            model.LoadModelJson(str(LIVE2D_MODEL))
            self.resizeGL(self.width(), self.height())
            LOG.info("Live2D 模型文件已读取")
            parameter_ids = set(model.GetParamIds())
            missing = set(LIVE2D_PARAMETERS) - parameter_ids
            if missing:
                raise ValueError(f"模型缺少绑定参数：{', '.join(sorted(missing))}")
            model.SetAutoBlinkEnable(True)
            model.SetAutoBreathEnable(False)
            if self.animation == "sleep":
                model.SetAutoBlinkEnable(False)
                model.SetParameterValue("ParamEyeLOpen", 0.0)
                model.SetParameterValue("ParamEyeROpen", 0.0)
            self._live2d_module = live2d
            self._live2d_model = model
            self._live2d_parameter_ids = frozenset(parameter_ids)
            self._last_render = time.monotonic()
            LOG.info("玄司 Live2D 模型已加载 parameters=%s", len(parameter_ids))
            LOG.info("Live2D 视线跟随已启用：按桌宠所在屏幕范围平滑映射")
            LOG.info(
                "玄司发丝与衣摆独立摆动已启用 hair_period=%.1fs cloth_period=%.1fs integration_hz=60",
                HAIR_SWAY_PERIOD_SECONDS,
                CLOTH_SWAY_PERIOD_SECONDS,
            )
            padding = max(2, round(self.height() * LIVE2D_MASK_PADDING_RATIO))
            LOG.info("Live2D 发丝窗口边界缓冲已启用 padding=%dpx", padding)
        except Exception:
            self._live2d_failed = True
            self._release_live2d()
            LOG.exception("玄司 Live2D 加载失败，继续使用原 PNG 形象")

    def _set_render_mode(self):
        self._live2d_active = self._live2d_requested and self._live2d_model is not None
        if self._live2d_active:
            # 小幅扩展系统窗口点击蒙版，避免裁切摆动后移出原图轮廓的发丝。
            self.setMask(self._live2d_window_mask())
            if self.isVisible():
                self.render_clock.start()
        else:
            self.render_clock.stop()
            self._shown_frame = None
            self._frame_mask()
        self._refresh_motion_capabilities()
        self.update()
        LOG.info("桌宠绘制模式已同步 mode=%s", "Live2D" if self._live2d_active else "图片")

    def resizeGL(self, width, height):
        if self._live2d_model is not None:
            scale = self.devicePixelRatioF()
            self._live2d_model.Resize(round(width * scale), round(height * scale))

    def paintGL(self):
        if self._live2d_active and self._live2d_model is not None:
            live2d = self._live2d_module
            now = time.monotonic()
            elapsed = max(0.0, min(0.1, now - self._last_render))
            self._last_render = now
            overlay = self._idle_blade_visual(now)
            if overlay is not None:
                # 拔刀图包含完整角色；该帧只显示姿态图，避免底层模型透出形成重影。
                live2d.clearBuffer(0.0, 0.0, 0.0, 0.0)
                self._present_idle_blade(overlay)
                return
            self._update_gaze(elapsed)
            self._mouth_level += (self._mouth_target - self._mouth_level) * min(1.0, elapsed * 14.0)
            model = self._live2d_model
            if self.animation == "sleep":
                model.SetParameterValue("ParamEyeLOpen", 0.0)
                model.SetParameterValue("ParamEyeROpen", 0.0)
                model.SetParameterValue("ParamMouthOpenY", 0.0)
            else:
                model.SetParameterValue("ParamEyeBallX", self._gaze_x)
                model.SetParameterValue("ParamEyeBallY", self._gaze_y)
                model.SetParameterValue("ParamMouthOpenY", self._mouth_level)
            self._update_sway(elapsed)
            for parameter, value in self._motion_parameter_values(now).items():
                model.SetParameterValue(parameter, value)
            # 先设置当帧参数，再由 Cubism 计算网格变形并绘制。
            live2d.clearBuffer(0.0, 0.0, 0.0, 0.0)
            model.Update()
            model.Draw()
            self._present_idle_blade(None)
            return
        # Live2D 与 PNG 回退都由 QOpenGLWidget 的绘制流程显示。
        # Qt 不会替重写的 paintGL 清空缓冲；透明图片和透明动图帧必须先清除旧像素。
        functions = self.context().functions()
        functions.glClearColor(0.0, 0.0, 0.0, 0.0)
        functions.glClear(0x00004000)  # GL_COLOR_BUFFER_BIT，仅清当前窗口的颜色缓冲。
        painter = QPainter(self)
        painter.drawPixmap(0, 0, self._pixmap())

    def _release_live2d(self):
        if self._live2d_module is None:
            return
        self.makeCurrent()
        try:
            if self._live2d_model is not None:
                self._live2d_model.DestroyRenderer()
            # 原生模型析构也会访问 Cubism，必须先在当前上下文中清掉模型引用。
            self._live2d_model = None
            SESSION.release(self)
            LOG.info("玄司 Live2D 渲染资源已释放")
        except Exception:
            LOG.exception("玄司 Live2D 渲染资源释放失败")
        finally:
            self.doneCurrent()
            self._live2d_model = None
            self._live2d_module = None
            self._live2d_active = False
            self._live2d_parameter_ids = frozenset()
            self._refresh_motion_capabilities()
