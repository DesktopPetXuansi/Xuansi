"""本机反馈验收：临时设置、真实Qt与HTTP，只抓本程序窗口，不启麦或读取用户数据。"""

import argparse
import json
import logging
import sys
import tempfile
import time
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QTabBar

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pet.app as app_module
import pet.runtime as runtime_module
from pet.app import DesktopPet
from pet.audio_activity import AudioActivity
from pet.config import ROOT, Settings, save_settings
from pet.desktop import DesktopState
from pet.live2d_session import configure_opengl_sharing
from pet.memory import MemoryStore
from pet.mouse_monitor import MouseMonitor
from pet.platform_auth import CredentialStore
from pet.runtime import Runtime

LOG = logging.getLogger(__name__)


def wait_until(predicate, seconds=20):
    deadline = time.monotonic() + seconds
    while not predicate() and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.005)  # 原生测试也需让后台Python循环获得执行时间。
    assert predicate(), "反馈操作未在期限内完成"


def inside(widget, parent):
    return (parent.rect().contains(widget.mapTo(parent, widget.rect().topLeft()))
            and parent.rect().contains(widget.mapTo(parent, widget.rect().bottomRight())))


def inspect(pet, origin, output):
    report = {"checks": [], "screenshots": []}
    panel, controller = pet.panel, pet.ui.feedback
    view = controller.dialog
    pet.open_panel()
    for width, height in ((720, 560), (520, 480)):
        panel.resize(width, height)
        QTest.qWait(50)
        assert inside(panel.feedback_button, panel) and inside(panel.save_button, panel)
        assert panel.findChild(QTabBar).count() == 7
        filename = f"panel-{width}.png"
        assert panel.grab().save(str(output / filename))
        report["screenshots"].append(filename)
    panel.feedback_button.click()
    assert view.isVisible() and not view.include_diagnostics.isChecked()
    assert controller.pending is None and controller.diagnostic_job is None
    report["checks"].append("七个主标签不变；默认与最小控制中心的反馈入口可见，打开不自动发送或采集")

    view.title_input.setText("合成验收：软件反馈中心")
    view.description.setPlainText("这是一条本机自动验收反馈，用于确认软件提交、服务端收据与管理员后台一致。")
    view.submit_button.click()
    wait_until(lambda: controller.pending is None)
    assert "无法连接" in view.status.text() and view.title_input.text().startswith("合成验收")
    view.close()
    feedback_action = next(action for action in pet.tray.contextMenu().actions() if action.text() == "反馈中心")
    feedback_action.trigger()
    assert view.isVisible() and view.description.toPlainText().startswith("这是一条")
    report["checks"].append("真实断网失败保留内容；托盘入口重新打开仍保留草稿")

    view.include_diagnostics.setChecked(True)
    wait_until(lambda: controller.diagnostic_job is None)
    view.preview_button.click()
    assert view.preview.isVisible() and "Qt" in view.preview.toPlainText()
    for width, height in ((520, 580), (440, 480)):
        view.resize(width, height)
        QTest.qWait(50)
        assert inside(view.submit_button, view) and inside(view.copy_button, view)
        assert view.scroll.horizontalScrollBar().maximum() == 0
        filename = f"feedback-{width}.png"
        assert view.grab().save(str(output / filename))
        report["screenshots"].append(filename)
    report["checks"].append("勾选后才异步整理并预览版本；两种反馈窗口尺寸均无水平滚动，提交固定可达")

    # 只改变本次内存设置，绝不保存或覆盖实际用户的官网连接。
    pet.settings = replace(pet.settings, platform_url=origin)
    receipts = []
    controller.submission_finished.connect(lambda receipt, error: receipts.append((receipt, error)))
    view.submit_button.click()
    view.submit_button.click()
    wait_until(lambda: controller.pending is None)
    assert len(receipts) == 1 and receipts[0][1] == ""
    assert "已收到" in view.status.text() and view.submit_button.text() == "再写一条"
    receipt = receipts[0][0]
    report["receipt"] = {"id": receipt.id, "createdAt": receipt.created_at, "status": receipt.status}
    assert view.grab().save(str(output / "feedback-received.png"))
    report["screenshots"].append("feedback-received.png")
    report["checks"].append("真实匿名HTTP提交仅一次；取得匹配的服务端编号后才显示已收到")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origin", default="http://localhost:3100")
    parser.add_argument("--output", type=Path, default=ROOT / "data/verification/feedback-center-2026-10-19/native")
    args = parser.parse_args()
    assert urlsplit(args.origin).hostname in {"localhost", "127.0.0.1", "::1"}, "验收只允许本机网站"
    args.output.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    configure_opengl_sharing()
    application = QApplication(sys.argv[:1])
    application.setQuitOnLastWindowClosed(False)
    report = {"passed": False}
    with tempfile.TemporaryDirectory(prefix="xuansi-feedback-") as directory:
        temporary = Path(directory)
        settings = replace(Settings(), observe=False, speak_replies=False, audio_avoidance=False,
                           platform_url="http://127.0.0.1:1", chat_hotkey="Ctrl+Alt+Shift+F23")
        with (
            patch.object(app_module, "DATA", temporary),
            patch.object(runtime_module, "MemoryStore", lambda: MemoryStore(temporary / "memory.json")),
            patch.object(runtime_module, "save_settings", lambda value: save_settings(value, temporary / "settings.json")),
            patch.object(app_module, "desktop_state", lambda: DesktopState(1, False, False)),
            patch.object(MouseMonitor, "start", lambda _: None),
            patch.object(AudioActivity, "start", lambda _: None),
            patch.object(Runtime, "load_devices", lambda runtime: runtime.devices_loaded.emit([])),
            patch.object(runtime_module.sd, "stop", lambda: None),
            patch.object(CredentialStore, "read", side_effect=AssertionError("验收不得读取官网凭据")),
        ):
            pet = DesktopPet(application, settings)
            pet.resource_timer.stop()
            closed = []
            pet.runtime.shutdown_done.connect(lambda: closed.append(True))
            try:
                report = inspect(pet, args.origin, args.output)
            finally:
                pet.quit()
                wait_until(lambda: bool(closed))
                assert pet.ui.feedback.closed and not pet.ui.feedback.dialog.isVisible()
                pet.runtime.loop.call_soon_threadsafe(pet.runtime.loop.stop)
                pet.runtime.thread.join(3)
                assert not pet.runtime.thread.is_alive()
                report.setdefault("checks", []).append("真实桌宠退出完成，反馈窗口与异步循环均已停止")
                report["passed"] = "receipt" in report
                (args.output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    LOG.info("反馈中心原生界面与本机HTTP验收通过")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
