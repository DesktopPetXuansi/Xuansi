"""真实 Qt/Live2D 眼睑表现探针；只读取内置形象，不启麦或读取用户配置。"""

import argparse
import json
import logging
import sys
import time
from pathlib import Path

import numpy as np
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pet.avatar import Avatar
from pet.live2d_session import configure_opengl_sharing

LOG = logging.getLogger(__name__)


def pixels(image):
    """复制帧缓冲，避免 QImage 被释放后数组引用失效。"""
    image = image.convertToFormat(QImage.Format.Format_RGBA8888)
    return np.frombuffer(image.bits(), dtype=np.uint8).copy().reshape(image.height(), image.width(), 4)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    output = parser.parse_args().output
    output.mkdir(parents=True, exist_ok=False)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    configure_opengl_sharing()
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    avatar = Avatar(224)
    avatar.move(-10000, -10000)
    report = {"passed": False, "expressions": {}, "input": "仅内置角色，不读取用户设置"}
    try:
        avatar.show()
        deadline = time.monotonic() + 8
        while not avatar._live2d_active and time.monotonic() < deadline:
            QTest.qWait(20)
        if not avatar._live2d_active:
            raise RuntimeError("内置 Live2D 未能加载")
        avatar.render_clock.stop()
        avatar.clock.stop()
        avatar._update_gaze = lambda _elapsed: None
        avatar._update_sway = lambda _elapsed: None
        avatar._mouth_level = avatar._mouth_target = 0.0
        model = avatar._live2d_model
        model.SetAutoBlinkEnable(False)
        model.SetParameterValue("ParamEyeLOpen", 1.0)
        model.SetParameterValue("ParamEyeROpen", 1.0)
        avatar.repaint()
        neutral = avatar.grabFramebuffer()
        if neutral.isNull():
            raise RuntimeError("无法读取内置形象帧缓冲")
        neutral.save(str(output / "neutral.png"))
        baseline = pixels(neutral)
        report["visible_pixels"] = int(np.count_nonzero(baseline[:, :, 3] > 0))
        for name in ("happy", "concern", "curious"):
            avatar.clear_reply_expression()
            if not avatar.set_reply_expression(name):
                raise RuntimeError(f"表情未受理：{name}")
            # 固定在淡入完成后的保持阶段；不依赖屏幕截图或人工操作。
            avatar._reply_expression.started = time.monotonic() - 1.0
            avatar.repaint()
            frame = avatar.grabFramebuffer()
            frame.save(str(output / f"{name}.png"))
            diff = np.any(pixels(frame) != baseline, axis=2)
            changed = int(np.count_nonzero(diff))
            report["expressions"][name] = {"changed_pixels": changed}
            LOG.info("眼睑表现验证 expression=%s changed_pixels=%d", name, changed)
            if changed == 0:
                raise RuntimeError(f"表情没有可见像素变化：{name}")
        # 同一表情的眨眼阶段必须与保持阶段不同，且仍由现有绘制时钟驱动。
        avatar.clear_reply_expression()
        avatar.set_reply_expression("happy")
        avatar._reply_expression.started = time.monotonic() - 1.0
        avatar.repaint()
        held = pixels(avatar.grabFramebuffer())
        avatar._reply_expression.started = time.monotonic() - 1.7
        avatar.repaint()
        blink = avatar.grabFramebuffer()
        blink.save(str(output / "happy-blink.png"))
        report["blink_changed_pixels"] = int(np.count_nonzero(np.any(pixels(blink) != held, axis=2)))
        if not report["blink_changed_pixels"]:
            raise RuntimeError("表情期间没有可见眨眼")
        avatar.clear_reply_expression()
        avatar._mouth_level = avatar._mouth_target = 0.8
        avatar.set_reply_expression("concern")
        avatar._reply_expression.started = time.monotonic() - 1.0
        avatar.repaint()
        avatar.grabFramebuffer()
        mouth_index = list(model.GetParamIds()).index("ParamMouthOpenY")
        report["mouth_during_expression"] = float(model.GetParameterValue(mouth_index))
        if report["mouth_during_expression"] < 0.7:
            raise RuntimeError("表情覆盖了语音口型")
        report["passed"] = True
    except Exception as exc:
        report["error"] = {"type": type(exc).__name__, "message": str(exc)}
        LOG.exception("真实 Live2D 表情探针未通过")
    finally:
        avatar.hide()
        avatar._release_live2d()
        app.processEvents()
        (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
