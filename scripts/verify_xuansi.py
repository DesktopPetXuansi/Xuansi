"""玄司形象验收：只创建自身窗口，不启模型、麦克风或屏幕捕获。"""

import ctypes
import json
import logging
import sys
import time
from ctypes import wintypes
from pathlib import Path
from types import SimpleNamespace

from PIL import Image, ImageDraw
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pet.avatar import Avatar
from pet.config import ROOT, Settings
from pet.desktop import USER32
from pet.idle_blade_animation import idle_blade_pose
from pet.panel import Panel
from pet.quick_chat import QuickChat


def main():
    logging.basicConfig(level=logging.INFO)
    USER32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    output = ROOT / "data/verification"
    output.mkdir(parents=True, exist_ok=True)
    report = {}
    original = Image.open(ROOT / "assets/xuansi/front.png")
    report["real_alpha"] = original.mode == "RGBA" and original.getchannel("A").getextrema() == (0, 255)
    avatar = Avatar()
    avatar.clock.stop()
    try:
        for size in (64, 96, 128, 160, 224, 288):
            avatar.set_size(size)
            for state, frames in avatar.frames.items():
                for index, (pixmap, region) in enumerate(frames):
                    assert not pixmap.isNull() and not region.isEmpty(), (size, state, index)
                    bounds = region.boundingRect()
                    assert bounds.left() > 0 and bounds.top() > 0, (size, state, bounds)
                    assert bounds.right() < avatar.width() - 1 and bounds.bottom() < size - 1
        report["all_sizes_and_states_unclipped"] = True
        avatar.set_size(160)
        frames = avatar.frames
        avatar.set_size(160)
        report["same_size_reuses_frames"] = avatar.frames is frames
        focus = USER32.GetForegroundWindow()
        avatar.show()
        QTest.qWait(200)
        report["idle_blade_assets_preloaded"] = len(avatar._idle_blade_frames) == 4
        report["idle_blade_live2d_supported"] = avatar.supports_idle_blade
        if avatar.start_idle_blade():
            before = time.process_time()
            started = time.perf_counter()
            QTest.qWait(1450)
            report["idle_blade_cpu_one_core_percent"] = round(
                100 * (time.process_time() - before) / (time.perf_counter() - started),
                2,
            )
            report["idle_blade_cache_megabytes"] = round(
                sum(frame.width() * frame.height() * 4 for frame in avatar._idle_blade_frames) / 2**20,
                2,
            )
            report["idle_blade_frame_at_160"] = idle_blade_pose(
                time.monotonic() - avatar._idle_blade_started
            )
            avatar.grab().save(str(output / "xuansi-idle-blade-drawn-160.png"))
            report["idle_blade_pose_rendered"] = avatar._idle_blade_started is not None
            avatar.interrupt_idle_blade()
            QTest.qWait(100)
            report["idle_blade_interrupt_fades"] = (
                0.0 < avatar._idle_blade_effect.opacity() < 1.0
            )
            QTest.qWait(120)
            report["idle_blade_interrupt_restored"] = (
                avatar._idle_blade_started is None
                and not avatar._idle_blade_overlay.isVisible()
                and avatar.mask() == avatar._live2d_window_mask()
            )
            avatar.set_size(288)
            QTest.qWait(150)
            if avatar.start_idle_blade():
                visual_calls = []
                original_visual = avatar._idle_blade_visual

                def trace_visual(now):
                    visual = original_visual(now)
                    if visual is not None:
                        visual_calls.append(visual[0])
                    return visual

                avatar._idle_blade_visual = trace_visual
                QTest.qWait(1450)
                elapsed = time.monotonic() - avatar._idle_blade_started
                report["idle_blade_large_pose_frame"] = idle_blade_pose(elapsed)
                report["idle_blade_large_visual_reached_renderer"] = bool(visual_calls)
                report["idle_blade_last_rendered_pose"] = visual_calls[-1] if visual_calls else -1
                avatar.grab().save(str(output / "xuansi-idle-blade-drawn-288.png"))
                report["idle_blade_large_pose_rendered"] = avatar._idle_blade_started is not None
                avatar._idle_blade_visual = original_visual
                avatar.interrupt_idle_blade(fade=False)
            else:
                report["idle_blade_large_pose_rendered"] = False
            avatar.set_size(160)
            QTest.qWait(100)
            avatar.start_idle_blade()
            QTest.qWait(250)
            report["idle_blade_visible_before_hide"] = avatar._idle_blade_overlay.isVisible()
            avatar.hide()
            report["idle_blade_hidden_immediately"] = (
                avatar._idle_blade_started is None and avatar._idle_blade_overlay.isHidden()
            )
            avatar.show()
            QTest.qWait(100)
            report["idle_blade_stays_hidden_after_show"] = not avatar._idle_blade_overlay.isVisible()
        else:
            report["idle_blade_pose_rendered"] = False
            report["idle_blade_interrupt_restored"] = False
            report["idle_blade_visible_before_hide"] = False
            report["idle_blade_hidden_immediately"] = False
            report["idle_blade_stays_hidden_after_show"] = False
        avatar.bubble.present("玄司在这里。", avatar)
        QTest.qWait(200)
        report["avatar_and_bubble_preserve_focus"] = USER32.GetForegroundWindow() == focus
        avatar.bubble.hide()
        rect = wintypes.RECT()
        USER32.GetWindowRect(int(avatar.winId()), ctypes.byref(rect))
        scale = (rect.right - rect.left) / avatar.width()
        solid = QPoint(avatar.width() // 2, avatar.height() // 2)
        assert avatar.mask().contains(solid)

        def hit(point):
            return USER32.WindowFromPoint(
                wintypes.POINT(
                    rect.left + round(point.x() * scale),
                    rect.top + round(point.y() * scale),
                )
            ) == int(avatar.winId())

        report["solid_receives_clicks"] = hit(solid)
        report["transparent_passes_through"] = not hit(QPoint(0, 0))
        avatar.grab().save(str(output / "xuansi-widget.png"))
        clicks = []
        avatar.open_requested.connect(lambda: clicks.append(True))

        def mouse(point):
            return SimpleNamespace(
                button=lambda: Qt.MouseButton.LeftButton,
                globalPosition=lambda: QPointF(point),
            )

        # 将事件直接交给自身窗口，不向用户正在使用的程序注入鼠标输入。
        origin = avatar.pos() + solid
        avatar.mousePressEvent(mouse(origin))
        avatar.mouseReleaseEvent(mouse(origin))
        previous = avatar.pos()
        avatar.mousePressEvent(mouse(origin))
        avatar.mouseMoveEvent(mouse(origin - QPoint(30, 20)))
        avatar.mouseReleaseEvent(mouse(origin - QPoint(30, 20)))
        report["click_opens_drag_only_moves"] = len(clicks) == 1 and avatar.pos() == previous - QPoint(30, 20)
        panel = Panel(Settings())
        quick = QuickChat(Settings(), "")
        report["all_titles_use_name"] = (
            all("玄司" in widget.windowTitle() for widget in (panel, panel.logs, quick))
            and panel.title.text() == "玄司"
        )
        panel.grab().save(str(output / "xuansi-panel.png"))
        panel.close()
        quick.close()

        # 预览只合成自有素材；同一组帧在浅色和深色底色下检查发丝边缘。
        preview = Image.new("RGB", (720, 430), "#f7f6f2")
        draw = ImageDraw.Draw(preview)
        draw.rectangle((0, 215, 720, 430), fill="#263039")
        for column, state in enumerate(avatar.frames):
            frame_path = output / f"xuansi-{state}.png"
            avatar.frames[state][2][0].save(str(frame_path))
            frame = Image.open(frame_path).convert("RGBA")
            for y in (20, 235):
                preview.paste(frame, (column * 120, y), frame)
                draw.text((column * 120 + 10, y + 165), state, fill="#a39780")
        preview.save(output / "xuansi-preview.jpg", quality=95)
        avatar.clock.start()
        before, started = time.process_time(), time.perf_counter()
        QTest.qWait(3000)
        report["avatar_cpu_one_core_percent"] = round(
            100 * (time.process_time() - before) / (time.perf_counter() - started),
            2,
        )
        report["frame_cache_megabytes"] = round(
            sum(pix.width() * pix.height() * 4 for frames in avatar.frames.values() for pix, _ in frames)
            / 2**20,
            2,
        )
        assert all(value for value in report.values() if isinstance(value, bool)), report
    finally:
        avatar.clock.stop()
        avatar.hide()
        avatar.bubble.hide()
        (output / "xuansi-report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(json.dumps(report, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
