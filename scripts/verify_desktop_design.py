"""原生界面视觉验收：临时数据与网络替身，只采集本程序窗口，不启麦。"""

import argparse
import ctypes
import json
import logging
import sys
import tempfile
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PySide6 import __version__ as pyside_version
from PySide6.QtCore import QPoint, QRect, QTimer, qVersion
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pet.appearance_dialog import AppearanceDialog
from pet.config import Settings
from pet.live2d_session import configure_opengl_sharing
from pet.panel import Panel
from pet.platform_dialog import PlatformDialog
from scripts.verify_control_center import LocalClient, Runtime, inspect, wait_until

LOG = logging.getLogger(__name__)


def capture(panel, key, size, output, tag=None):
    """布局与后台读取完成后截图；记录逻辑尺寸及实际DPR，便于前后复查。"""
    panel.resize(*size)
    panel.open_section(key)
    QTest.qWait(100)
    page = panel.sections[key]
    content = page.content.itemAt(0).widget()
    if isinstance(content, PlatformDialog):
        wait_until(lambda: content.worker is None)
    if key == "logs":
        wait_until(lambda: not panel.logs.loading)
    page.verticalScrollBar().setValue(0)
    QApplication.processEvents()
    name = f"{tag or key}-{size[0]}x{size[1]}"
    assert panel.grab().save(str(output / f"{name}.png"))
    metrics = {
        "page": key, "requested_size": size, "actual_size": [panel.width(), panel.height()],
        "content_rect": list(panel.navigation.stack.geometry().getRect()),
        "horizontal_scroll_max": page.horizontalScrollBar().maximum(),
        "vertical_scroll_max": page.verticalScrollBar().maximum(),
        "screenshot": f"{name}.png", "dpr": panel.devicePixelRatioF(),
    }
    if key == "chat":
        send = next(button for button in content.findChildren(QPushButton) if button.text() == "发送")
        metrics["chat_height"] = panel.chat.height()
        metrics["composer_fully_visible"] = all(
            page.viewport().rect().contains(QRect(widget.mapTo(page.viewport(), QPoint()), widget.size()))
            for widget in (panel.input, send)
        )
        assert metrics["composer_fully_visible"] and metrics["vertical_scroll_max"] == 0, metrics
    assert metrics["actual_size"] == list(size) and metrics["horizontal_scroll_max"] == 0, metrics
    LOG.info("原生界面采样 page=%s size=%s dpr=%s", key, size, panel.devicePixelRatioF())
    return metrics


def screen_samples(application, temporary, output):
    """在真实主事件循环中逐页显示，采集本窗口占据的桌面区域。"""
    panel = Panel(replace(Settings(), observe=False))
    panel.logs.path = temporary / "screen.log"
    panel.speech_button.setChecked(True)
    appearance = AppearanceDialog(panel, embedded=True)
    panel.mount_section("appearance", appearance, on_open=lambda: appearance.present(""))
    keys = iter(("chat", "preferences", "appearance"))
    records, errors = [], []

    def advance():
        key = next(keys, None)
        if key is None:
            application.quit()
            return
        try:
            panel.open_section(key)
            # 返回外层事件循环后再采样；只靠QTest.qWait不能证明合成帧已经提交。
            QTimer.singleShot(650, lambda: sample(key))
        except Exception as exc:
            errors.append(exc)
            application.quit()

    def sample(key):
        try:
            assert panel.isVisible() and panel.isActiveWindow()
            screen = panel.screen()
            origin = panel.mapToGlobal(QPoint()) - screen.geometry().topLeft()
            # 不抓取整个桌面，也不使用可能保留旧合成帧的窗口句柄读取方式。
            pixels = screen.grabWindow(0, origin.x(), origin.y(), panel.width(), panel.height())
            filename = f"{key}-880x760-screen.png"
            assert not pixels.isNull() and pixels.save(str(output / filename))
            if key == "appearance":
                assert appearance.preview.renderer._live2d_active and not appearance.preview.renderer._live2d_failed
                assert appearance.preview.renderer.grabFramebuffer().save(str(output / "appearance-framebuffer.png"))
            records.append({"page": key, "file": filename, "visible": True, "active": True,
                            "dpr": screen.devicePixelRatio(), "pixels": [pixels.width(), pixels.height()]})
            QTimer.singleShot(0, advance)
        except Exception as exc:
            errors.append(exc)
            application.quit()

    QTimer.singleShot(0, advance)
    try:
        application.exec()
    finally:
        panel.hide()
        application.processEvents()
    if errors:
        raise errors[0]
    (output / "screen-report.json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    LOG.info("真实桌面采样完成 pages=%s", len(records))


def state_samples(panel, platform, output):
    """额外状态为明确标记的UI样例，业务恢复能力由原生验收另证。"""
    states = output / "states"
    states.mkdir(exist_ok=True)
    platform.set_busy(True)
    platform.task_progress("后台上传进度样例35%", 35)
    assert "35%" in panel.footer.text()
    capture(panel, "chat", (520, 480), states, "background-upload-sample")
    platform.set_busy(False)
    panel.voice_state(True)
    panel.status.setText("实时聆听中 · 说完即可回复")
    panel.live_transcript.setText("转写样例：今天有几件事要做，陪我一起完成。")
    capture(panel, "chat", (520, 480), states, "listening-sample")
    panel.live_transcript.setText("")
    panel.voice_state(True, paused=True)
    panel.status.setText("已休眠 · 连续对话已暂停")
    panel.sleep_button.setText("唤醒")
    capture(panel, "chat", (520, 480), states, "sleep-sample")
    panel.voice_state(False)
    panel.sleep_button.setText("休眠")
    panel.persona.name.setText("未保存的人设草稿")
    capture(panel, "persona", (880, 760), states, "unsaved-sample")
    panel.form.complete("保存失败样例：目录暂不可写，草稿已保留。")
    capture(panel, "persona", (880, 760), states, "save-failure-sample")
    panel.persona.name.setText(panel.settings.name)
    panel.form.refresh()
    platform.completed("remote", [{"id": "design-fixture", "name": "界面验收模型", "kind": "MODEL"}])
    capture(panel, "resources", (880, 760), states, "resource-loaded-sample")
    platform.upload_dialog.set_busy(True)
    platform.upload_dialog.show_progress("上传进度样例：正在整理和传输模型…", 35)
    capture(panel, "upload", (880, 760), states, "upload-progress-sample")
    platform.upload_dialog.set_busy(False)


def inspect_pages(application, temporary, output):
    settings = replace(Settings(), observe=False, platform_url="http://127.0.0.1:1")
    panel = Panel(settings)
    panel.logs.path = temporary / "design-review.log"
    panel.logs.path.write_text("2026-10-16 10:00:00 INFO pet 界面调研样例：控制中心已就绪\n", encoding="utf-8")
    panel.speech_button.setChecked(settings.speak_replies)
    owner = SimpleNamespace(panel=panel, settings=settings, runtime=Runtime())
    appearance = AppearanceDialog(panel, embedded=True)
    platform = PlatformDialog(owner, embedded=True)
    panel.mount_section("appearance", appearance, on_open=lambda: appearance.present(""))
    panel.mount_section("resources", platform,
                        on_open=lambda: platform.refresh_local() if platform.worker is None else None)
    panel.upload_requested.connect(platform.open_upload)
    platform.activity_changed.connect(panel.footer.set_activity)
    pages = []
    try:
        pages.append(capture(panel, "chat", (720, 560), output))
        panel.append("你", "今天有几件事要做，陪我一起慢慢完成吧。")
        panel.append("玄司", "好，我们先从手边的一件小事开始。")
        assert panel.grab().save(str(output / "chat-example-720x560.png"))
        for key in ("persona", "memory", "preferences", "model", "appearance", "resources"):
            pages.append(capture(panel, key, (720, 560), output))
            if key == "appearance":
                assert appearance.preview.renderer._live2d_active and not appearance.preview.renderer._live2d_failed
                assert appearance.preview.renderer.grabFramebuffer().save(str(output / "appearance-framebuffer.png"))
        platform.open_upload()
        wait_until(lambda: platform.worker is None)
        platform.upload_dialog.source.setText("D:/AI/Models/xuansi/xuansi.model3.json")
        for key in ("upload", "logs"):
            pages.append(capture(panel, key, (720, 560), output))
        for key in ("chat", "preferences", "resources", "upload"):
            pages.append(capture(panel, key, (560, 660), output))
        for key in ("chat", "preferences", "model"):
            pages.append(capture(panel, key, (520, 480), output))
        pages.append(capture(panel, "chat", (880, 760), output))
        pages.append(capture(panel, "chat", (1040, 800), output))
        assert pages[0]["chat_height"] >= 230 and pages[0]["content_rect"][3] >= 420
        assert pages[-1]["chat_height"] > pages[0]["chat_height"]
        state_samples(panel, platform, output)
        return pages
    finally:
        platform.shutdown()
        wait_until(lambda: platform.worker is None)
        panel.hide()
        application.processEvents()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="独立验收目录，不覆盖改版前基线")
    parser.add_argument("--screens-only", action="store_true", help="仅补采真实主事件循环中的桌面像素")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    configure_opengl_sharing()
    application = QApplication.instance() or QApplication([])
    application.setQuitOnLastWindowClosed(False)
    args.output.mkdir(parents=True, exist_ok=True)
    checks_output = args.output / "native-checks"
    checks_output.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="xuansi-design-") as directory, \
            patch("pet.platform_upload_dialog.PlatformClient", LocalClient), \
            patch("pet.platform_dialog.installed_resources", return_value=[]):
        temporary = Path(directory)
        if args.screens_only:
            screen_samples(application, temporary, args.output)
            return
        checks = inspect(application, temporary, checks_output)
        assert all(checks.values()), checks
        pages = inspect_pages(application, temporary, args.output)
        screen_samples(application, temporary, args.output)
    screen = application.primaryScreen()
    report = {
        "pyside_version": pyside_version, "qt_version": qVersion(), "platform": application.platformName(),
        "dpr": screen.devicePixelRatio(), "logical_dpi": screen.logicalDotsPerInch(),
        "capture": "实际Qt和Live2D；语言模型、账号、网络与音频为替身，不启麦。真实桌面像素和GL另存。",
        "checks": checks, "pages": pages, "passed": all(checks.values()),
    }
    (args.output / "layout-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    LOG.info("原生界面验收完成 checks=%s pages=%s dpr=%s", len(checks), len(pages), report["dpr"])
    application.quit()


if __name__ == "__main__":
    main()
