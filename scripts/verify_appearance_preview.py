"""真实 Qt / Live2D 预览验收；只显示本项目形象，不启麦、不读取用户配置。"""

import argparse
import json
import logging
import sys
import tempfile
import time
from functools import partial
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw
from PySide6.QtCore import QPoint, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pet.appearance import image_path, import_image
from pet.appearance_dialog import AppearanceDialog
from pet.avatar import LIVE2D_PARAMETERS, Avatar
from pet.config import ROOT
from pet.live2d_session import SESSION, configure_opengl_sharing

LOG = logging.getLogger(__name__)


def wait_until(predicate, seconds=5):
    deadline = time.monotonic() + seconds
    while not predicate() and time.monotonic() < deadline:
        QTest.qWait(20)
    return bool(predicate())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "data/verification/appearance-preview-report.json")
    output = parser.parse_args().output
    output.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO)
    # 多个顶层窗口的 Cubism 着色器必须位于同一 OpenGL 共享组。
    configure_opengl_sharing()
    application = QApplication(sys.argv)
    application.setQuitOnLastWindowClosed(False)
    desktop = Avatar()
    dialog = AppearanceDialog(None)
    report = {}
    requests = []
    dialog.apply_requested.connect(requests.append)

    def check(name, condition):
        report[name] = bool(condition)
        assert condition, name

    def has_character(view):
        rendered = view.grabFramebuffer()
        return not rendered.isNull() and sum(
            rendered.pixelColor(x, y).alpha() > 128
            for y in range(rendered.height()) for x in range(rendered.width())
        ) > rendered.width() * rendered.height() * 0.15

    def inspect_imports():
        # 导入副本、文件选择和异步回调全部留在临时目录，不修改用户当前形象。
        with tempfile.TemporaryDirectory(prefix="pet-preview-") as directory:
            temporary = Path(directory)
            assets = temporary / "assets"
            paths = partial(image_path, directory=assets)
            imports = partial(import_image, directory=assets)
            with (
                patch("pet.character_frames.image_path", paths),
                patch("pet.native_animation.image_path", paths),
                patch("pet.appearance_dialog.image_path", paths),
                patch("pet.appearance_dialog.import_image", imports),
            ):
                static = temporary / "static.png"
                pixels = Image.new("RGBA", (140, 180))
                ImageDraw.Draw(pixels).ellipse((20, 10, 120, 170), fill="#507b86")
                pixels.save(static)
                dialog.import_file(str(static))
                assert wait_until(lambda: not dialog.loading and dialog.candidate.endswith(".png"))
                check("static_import_disables_blink", not dialog.blink_button.isEnabled())
                check("static_import_releases_preview_model", len(SESSION.owners) == 1)
                check("static_preview_keeps_existing_animation", dialog.preview.timer.isActive())
                check("unapplied_import_preserves_desktop", desktop.image_id == "" and not requests)

                frames = [pixels.copy(), Image.new("RGBA", pixels.size, "#b79159")]
                animation = temporary / "animated.png"
                frames[0].save(animation, save_all=True, append_images=frames[1:], duration=[80, 160], loop=0)
                dialog.import_file(str(animation))
                assert wait_until(lambda: not dialog.loading and dialog.candidate.endswith(".apng"))
                check("animated_import_preserves_frame_timing", dialog.preview.durations == [80, 160])
                initial = dialog.preview.index
                check("animated_preview_advances", wait_until(lambda: dialog.preview.index != initial))
                check("animated_import_disables_blink", not dialog.blink_button.isEnabled())
                dialog.use_default()
                check("restore_default_loads_live2d", wait_until(lambda: dialog.preview.renderer._live2d_active))
                check("restore_default_enables_blink", dialog.blink_button.isEnabled())
                check("restore_default_has_two_models", len(SESSION.owners) == 2)

    def inspect():
        try:
            desktop.show()
            assert wait_until(lambda: desktop._live2d_active), "桌宠 Live2D 未能加载"
            dialog.present("")
            assert wait_until(
                lambda: getattr(getattr(dialog.preview, "renderer", None), "_live2d_active", False)
            ), "默认形象预览仍未接入 Live2D"
            check("default_preview_uses_live2d", True)
            renderer = dialog.preview.renderer
            check("opening_creates_exactly_one_preview_model", len(SESSION.owners) == 2)
            check("default_preview_stops_old_png_timer", not dialog.preview.timer.isActive())
            check("blink_button_is_available", dialog.blink_button.isEnabled())
            check("preview_has_no_desktop_bubble_or_idle_blade", renderer.bubble is None and not renderer.supports_idle_blade)
            initial = renderer.grabFramebuffer()
            QTest.qWait(240)
            check("preview_draws_live_animation", initial != renderer.grabFramebuffer())
            check("hair_and_cloth_advance", renderer._hair_sway.tip != 0 and renderer._cloth_sway_phase > 0)
            background = renderer.grabFramebuffer()
            check(
                "transparent_background_has_two_colors",
                background.pixelColor(1, 1).name() == "#efeee8"
                and background.pixelColor(background.width() - 2, 1).name() == "#35413d",
            )
            with patch("pet.avatar.QCursor") as cursor:
                cursor.pos.return_value = renderer.mapToGlobal(QPoint(renderer.width() + 300, 0))
                check("gaze_follows_synthetic_cursor", wait_until(lambda: renderer._gaze_x > 0.1))
            check("preview_has_rectangular_canvas", renderer.mask().isEmpty() or renderer.mask().contains(QPoint(0, 0)))
            dialog.blink_button.click()
            check("blink_button_starts_motion", renderer._motion_name == "blink")
            eye = list(renderer._live2d_model.GetParamIds()).index("ParamEyeLOpen")
            check("blink_reaches_closed_eyes", wait_until(lambda: renderer._live2d_model.GetParameterValue(eye) < 0.1))
            check("blink_finishes_and_opens_eyes", wait_until(lambda: renderer._motion_name is None))
            check("blink_does_not_apply_or_create_draft", not dialog.dirty and not requests and desktop._motion_name is None)
            dialog.grab().save(str(output.with_suffix(".png")))

            # 关闭和重开不能使桌宠模型的纹理或公共着色器失效。
            dialog.close()
            check("closing_releases_only_preview_model", len(SESSION.owners) == 1 and renderer._live2d_model is None)
            check("closing_stops_all_preview_timers", not renderer.clock.isActive() and not renderer.render_clock.isActive())
            check("desktop_renders_after_preview_close", desktop._live2d_active and has_character(desktop))
            dialog.present("")
            check("reopening_restores_live2d", wait_until(lambda: renderer._live2d_active))
            check("reopening_has_no_leaked_models", len(SESSION.owners) == 2)
            inspect_imports()

            # 桌宠当前使用自定义形象时，默认候选可能是应用中的唯一 Live2D 模型。
            desktop.hide()
            desktop._release_live2d()
            dialog.close()
            check("last_preview_close_keeps_core_for_reopen", not SESSION.owners and not SESSION.disposed)
            dialog.present("")
            check("sole_preview_reopens_successfully", wait_until(lambda: renderer._live2d_active))
            check("sole_preview_has_no_extra_model", len(SESSION.owners) == 1)
            dialog.close()
            # 真实模型已分配但参数校验失败，必须回收模型且明确禁用动作。
            with patch("pet.avatar.LIVE2D_PARAMETERS", (*LIVE2D_PARAMETERS, "missing_for_preview_test")):
                dialog.present("")
                check("failed_model_disables_blink", renderer._live2d_failed and not dialog.blink_button.isEnabled())
                check("failed_model_leaves_no_resource_owner", not SESSION.owners)
                check("failed_model_has_visible_hint", "暂不可用" in dialog.motion_hint.text())
                dialog.close()
            dialog.present("")
            check("reopening_recovers_after_failure", wait_until(lambda: renderer._live2d_active))
            check("recovered_model_enables_blink", dialog.blink_button.isEnabled())
            report["all_passed"] = all(report.values())
        except Exception as exc:
            LOG.exception("形象动态预览验收失败")
            report["error"] = str(exc)
            report["all_passed"] = False
        finally:
            dialog.close()
            desktop.hide()
            desktop.bubble.hide()
            desktop._release_live2d()
            output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(report, ensure_ascii=False, indent=2))
            application.quit()

    QTimer.singleShot(100, inspect)
    application.exec()
    assert report.get("all_passed"), report


if __name__ == "__main__":
    main()
