"""独立加载真实 Live2D 模型，记录三周期并导出原生 OpenGL 动画预览。"""

import hashlib
import json
import logging
import sys
import time
from pathlib import Path

import live2d.v3 as live2d
from PIL import Image, ImageChops
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QSurfaceFormat
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "verification"
LOG = logging.getLogger("原生火柴人预览")


class Preview(QOpenGLWidget):
    """只运行模型 SDK，不导入业务模块和用户配置。"""

    def __init__(self):
        super().__init__()
        self.model = None
        self.error = None
        self.playing = False
        self.neutral = False
        self.restarts = 0
        self.setWindowTitle("火柴人 Live2D 原生预览")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.resize(512, 768)

    def initializeGL(self):
        """SDK 的 GL 初始化必须在 Qt 已激活的上下文里进行。"""
        try:
            live2d.init()
            live2d.glInit()
            self.model = live2d.LAppModel()
            self.model.LoadModelJson(str(ROOT / "stickman.model3.json"))
            self.model.SetAutoBlinkEnable(False)
            self.model.SetAutoBreathEnable(False)
            self.resizeGL(self.width(), self.height())
            LOG.info("真实模型已载入，参数=%s，网格=%s", self.model.GetParamIds(), self.model.GetDrawableIds())
        except Exception as error:
            self.error = error
            LOG.exception("原生模型初始化失败")

    def resizeGL(self, width, height):
        if self.model is not None:
            ratio = self.devicePixelRatioF()
            self.model.Resize(round(width * ratio), round(height * ratio))

    def paintGL(self):
        live2d.clearBuffer(0, 0, 0, 0)
        if self.model is not None and self.error is None:
            if self.neutral:
                # 对真实模型保存零参数，获得确定的中立姿态而不依赖墙钟时间。
                self.model._model.SetAndSaveParameterValueById("ParamWave", 0)
            if self.playing and self.model.IsMotionFinished():
                # 一些绑定忽略动作 JSON 的 Loop；自然结束后重新播放同一条动作。
                self.model.StartMotion("Wave", 0, 3)
                self.restarts += 1
                LOG.info("挥手动作重新播放，次数=%s", self.restarts)
            self.model.Update()
            self.model.Draw()

    def capture(self):
        """读取实际帧缓冲，不使用素材模拟 SDK 画面。"""
        rendered = self.grabFramebuffer().convertToFormat(QImage.Format.Format_RGBA8888)
        return Image.frombytes("RGBA", (rendered.width(), rendered.height()), bytes(rendered.constBits()),
                               "raw", "RGBA", rendered.bytesPerLine()).copy()

    def release(self):
        """先销毁模型渲染器，再释放当前进程的 SDK。"""
        if self.model is not None:
            self.makeCurrent()
            self.model.DestroyRenderer()
            self.model = None
            live2d.glRelease()
            live2d.dispose()
            self.doneCurrent()


def check_frames(frames, report):
    """比较四个真实姿态：透明、完整边界、静止下半身和变化前臂。"""
    snapshots = []
    positive = max(frames, key=lambda frame: frame[1])
    negative = min(frames, key=lambda frame: frame[1])
    between = [frame for frame in frames if min(positive[0], negative[0]) < frame[0] < max(positive[0], negative[0])]
    middle = min(between or frames[1:], key=lambda frame: abs(frame[1]))
    poses = [frames[0], positive, middle, negative]
    assert positive[1] > 0.95 and negative[1] < -0.95, "原生截帧未覆盖完整前臂极限姿态"
    for index, (elapsed, value, image) in enumerate(poses):
        image.save(OUTPUT / f"frame-{index}.png")
        bbox = image.getchannel("A").getbbox()
        assert bbox is not None, "模型帧没有可见像素"
        assert 2 < bbox[0] < bbox[2] < image.width - 2 and 2 < bbox[1] < bbox[3] < image.height - 2, "全身触碰帧边界"
        assert image.getpixel((0, 0))[3] == 0, "OpenGL 帧背景不透明"
        snapshots.append(image)
        report.setdefault("poses", []).append({"file": f"frame-{index}.png", "seconds": elapsed,
                                               "parameter": value, "visibleBounds": list(bbox)})
    bounds = snapshots[0].getchannel("A").getbbox()
    # 前臂位于上半部；从角色高度的 45% 以下开始比较躯干和完整双腿。
    lower = (0, round(bounds[1] + (bounds[3] - bounds[1]) * 0.45), snapshots[0].width, snapshots[0].height)
    base = snapshots[0].crop(lower)
    differences = [ImageChops.difference(base, frame.crop(lower)).convert("RGB").getbbox() for frame in snapshots[1:]]
    assert all(bbox is None for bbox in differences), "躯干或腿部在挥手期间发生变化"
    upper_change = ImageChops.difference(snapshots[1], snapshots[3]).convert("RGB").getbbox()
    assert upper_change is not None and upper_change[3] <= lower[1], "前臂没有实际移动，或移动影响下半身"
    assert bounds[3] - bounds[1] > snapshots[0].height * 0.6, "全身显示比例异常"
    # 边界与运动正常不能证明 UV 正确；静止部分必须与源素材逐像素对齐。
    expected = Image.open(ROOT / "preview-neutral.png").convert("RGBA").resize(snapshots[0].size)
    scale_x = snapshots[0].width / 512
    scale_y = snapshots[0].height / 768
    regions = {"头部": (156, 89, 284, 217), "躯干": (210, 310, 230, 449), "双腿": (125, 450, 322, 702)}
    coverage = {}
    similarity = {}
    for label, region in regions.items():
        x0, y0, x1, y1 = region
        region = (round(x0 * scale_x), round(y0 * scale_y), round(x1 * scale_x), round(y1 * scale_y))
        expected_alpha = expected.crop(region).getchannel("A").tobytes()
        actual_alpha = snapshots[0].crop(region).getchannel("A").tobytes()
        expected_pixels = sum(alpha > 128 for alpha in expected_alpha)
        matches = sum(source > 128 and actual > 128 for source, actual in zip(expected_alpha, actual_alpha))
        union = sum(source > 128 or actual > 128 for source, actual in zip(expected_alpha, actual_alpha))
        coverage[label] = matches / max(1, expected_pixels)
        similarity[label] = {
            "alphaIoU": matches / max(1, union),
            "alphaMAE": sum(abs(source - actual) for source, actual in zip(expected_alpha, actual_alpha)) / max(1, len(expected_alpha)),
        }
    report["sourceShapeCoverage"] = coverage
    report["sourceShapeSimilarity"] = similarity
    assert all(item["alphaIoU"] > 0.8 for item in similarity.values()), f"原生图像与源素材不符，可能存在 UV 翻转：{similarity}"
    report.update({"transparentBackground": True, "fullBodyUnclipped": True,
                   "bodyAndLegsStatic": True, "forearmPixelsChanged": True, "matchesSourceShape": True})


def main():
    """先确认真实 moc 存在，再执行实际播放和截图验收。"""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    assert (ROOT / "stickman.moc3").is_file(), "真实 stickman.moc3 尚未生成，不能运行原生验收"
    OUTPUT.mkdir(parents=True, exist_ok=True)
    surface = QSurfaceFormat()
    surface.setAlphaBufferSize(8)
    surface.setSamples(0)
    QSurfaceFormat.setDefaultFormat(surface)
    application = QApplication(sys.argv)
    window = Preview()
    model_hash = hashlib.sha256((ROOT / "stickman.moc3").read_bytes()).hexdigest()
    report = {"passed": False, "renderer": "PySide6 QOpenGLWidget / live2d.v3", "modelSha256": model_hash, "samples": []}
    try:
        window.show()
        QTest.qWait(300)
        if window.error is not None:
            raise window.error
        assert window.model is not None, "OpenGL 初始化未完成"
        model = window.model
        parameter_ids = model.GetParamIds()
        drawable_ids = model.GetDrawableIds()
        assert parameter_ids == ["ParamWave"], f"参数数量或绑定错误：{parameter_ids}"
        assert len(drawable_ids) == 7, f"实际网格数量错误：{drawable_ids}"
        report.update({"parameters": parameter_ids, "drawables": drawable_ids, "parts": model.GetPartIds()})
        model.StopAllMotions()
        window.neutral = True
        neutral_frame = window.capture()
        neutral_value = model.GetParameterValue(0)
        assert neutral_value == 0, f"中立帧参数不是零：{neutral_value}"
        neutral_frame.save(OUTPUT / "frame-neutral.png")
        report["neutralParameter"] = neutral_value
        window.neutral = False
        window.playing = True
        model.StartMotion("Wave", 0, 3)
        start = time.monotonic()
        frames = [(0, neutral_value, neutral_frame)]
        last_capture = -1
        while time.monotonic() - start < 6.2:
            window.update()
            QTest.qWait(16)
            elapsed = time.monotonic() - start
            value = model.GetParameterValue(0)
            report["samples"].append({"seconds": elapsed, "value": value})
            if elapsed - last_capture >= 1 / 12:
                image = window.capture()
                # grabFramebuffer 会触发一次真实绘制，记录绘制后的实际参数。
                frames.append((time.monotonic() - start, model.GetParameterValue(0), image))
                last_capture = elapsed
        for cycle in range(3):
            values = [sample["value"] for sample in report["samples"] if cycle * 2 <= sample["seconds"] < (cycle + 1) * 2]
            bounds = [min(values), max(values)]
            report.setdefault("cycles", []).append({"index": cycle + 1, "minimum": bounds[0], "maximum": bounds[1]})
            assert bounds[0] <= -0.8 and bounds[1] >= 0.8, f"第 {cycle + 1} 周期未完整挥手：{bounds}"
        playback_duration = time.monotonic() - start
        report["motionRestarts"] = window.restarts
        check_frames(frames, report)
        # GIF 不支持渐变透明，将实际帧合成到统一米白背景并保留循环。
        gif_frames = []
        for _, _, frame in frames:
            background = Image.new("RGBA", frame.size, "#faf9f6")
            background.alpha_composite(frame)
            gif_frames.append(background.convert("RGB"))
        gif_frames[0].save(ROOT / "preview-wave.gif", save_all=True, append_images=gif_frames[1:],
                           duration=83, loop=0, disposal=2)
        assert hashlib.sha256((ROOT / "stickman.moc3").read_bytes()).hexdigest() == model_hash, "验收期间模型文件发生变化"
        report.update({"passed": True, "durationSeconds": playback_duration, "capturedFrames": len(frames)})
        LOG.info("原生验收通过：三周期完整挥手，七网格，透明且全身无裁切")
    except Exception as error:
        report["error"] = str(error)
        LOG.exception("原生验收未通过")
        raise
    finally:
        (OUTPUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        window.release()
        window.close()
        application.processEvents()


if __name__ == "__main__":
    main()
