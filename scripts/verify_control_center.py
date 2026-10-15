"""原生标签控制中心验收：临时配置、内存账号替身，只采集本程序窗口，不启麦或联网。"""

import asyncio
import json
import logging
import sys
import tempfile
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QTabBar, QToolButton

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pet.appearance_dialog import AppearanceDialog
from pet.config import ROOT, Settings, load_settings, save_settings
from pet.live2d_session import configure_opengl_sharing
from pet.panel import Panel
from pet.platform_dialog import PlatformDialog

LOG = logging.getLogger(__name__)


class Runtime(QObject):
    platform_settings_saved = Signal(object, str)


class LocalClient:
    """验证 UI 线程、状态和取消边界；不产生 HTTP 或访问系统凭据。"""

    def __init__(self, base_url):
        self.base_url = base_url
        self.pending_model_upload = None
        self.store = SimpleNamespace(read=lambda: {"scope": "resources:read resources:write"})

    async def request(self, method, path):
        assert (method, path) == ("GET", "/me")
        return {"displayName": "界面验收账号", "emailVerified": True}

    async def upload_model(self, source, metadata, progress):
        assert source and metadata["name"]
        progress("界面验收：上传中", 35)
        await asyncio.sleep(0.2)
        progress("界面验收：完成", 100)
        return {"resourceId": "native-control-fixture"}


def wait_until(predicate, seconds=5):
    deadline = time.monotonic() + seconds
    while not predicate() and time.monotonic() < deadline:
        QTest.qWait(20)
    assert predicate(), "原生界面操作未在限定时间内完成"


def inspect(application, temporary, output):
    settings = replace(Settings(), observe=False, speak_replies=False, platform_url="http://127.0.0.1:1")
    panel = Panel(settings)
    panel.logs.path = temporary / "native-ui.log"
    panel.logs.path.write_text("2026-10-15 INFO control-center 原生界面验收\n", encoding="utf-8")
    owner = SimpleNamespace(panel=panel, settings=settings, runtime=Runtime())
    appearance = AppearanceDialog(panel, embedded=True)
    platform = PlatformDialog(owner, embedded=True)
    panel.mount_section("appearance", appearance, on_open=lambda: appearance.present(owner.settings.avatar_image))
    panel.mount_section("resources", platform,
                        on_open=lambda: platform.refresh_local() if platform.worker is None else None)
    panel.upload_requested.connect(platform.open_upload)
    messages, report = [], {}
    panel.send_requested.connect(lambda text, screen: messages.append((text, screen)))

    def save(settings):
        panel.saving(True)
        save_settings(settings, temporary / "settings.json")
        owner.settings = panel.settings = settings
        panel.saving(False)
        panel.form.complete("")

    panel.settings_requested.connect(save)
    try:
        panel.open_section("chat")
        QTest.qWait(120)
        panel.input.setText("同一个控制中心")
        QTest.keyClick(panel.input, Qt.Key.Key_Return)
        report["chat_sends_once"] = messages == [("同一个控制中心", False)]
        panel.append("玄司", "对话、设置、形象和资源集中在这个控制中心。")
        bar = panel.navigation.bar
        keys = tuple(panel.sections)
        report["horizontal_chrome_style_tabs"] = (
            isinstance(bar, QTabBar) and bar.count() == 9 and not bar.tabsClosable()
            and bar.shape() in (QTabBar.Shape.RoundedNorth, QTabBar.Shape.TriangularNorth)
            and len({bar.tabRect(index).center().y() for index in range(bar.count())}) == 1
        )
        panel.persona.name.setText("跨标签保留草稿")
        for key in ("persona", "preferences", "model", "chat"):
            bar.setCurrentIndex(keys.index(key))
            QTest.qWait(20)
            assert panel.navigation.current_key == key
            assert panel.navigation.stack.currentWidget() is panel.sections[key]
            assert sum(page.active for page in panel.sections.values()) == 1
        report["tab_switch_preserves_draft"] = panel.persona.name.text() == "跨标签保留草稿"
        report["one_current_page"] = panel.sections["chat"].active and not panel.sections["persona"].active
        assert panel.grab().save(str(output / "control-center-overview.png"))
        panel.open_configuration()
        panel.model_page.temperature.setValue(0.4)
        panel.save_button.click()
        saved = load_settings(temporary / "settings.json")
        report["unified_save"] = saved.temperature == 0.4 and saved.name == "跨标签保留草稿"
        panel.open_logs()
        wait_until(lambda: "原生界面验收" in panel.logs.content.toPlainText())
        panel.collapse_section("logs")
        report["leaving_logs_stops_polling"] = not panel.logs.timer.isActive()
        panel.open_section("appearance")
        wait_until(lambda: appearance.preview.renderer._live2d_active)
        report["native_preview_loaded"] = not appearance.preview.renderer._live2d_failed
        panel.collapse_section("appearance")
        report["leaving_appearance_stops_preview"] = not appearance.preview.renderer._live2d_active
        panel.open_section("appearance")
        wait_until(lambda: appearance.preview.renderer._live2d_active)
        report["preview_reopens"] = True
        panel.open_section("resources")
        wait_until(lambda: platform.worker is None)
        platform.open_upload()
        wait_until(lambda: platform.worker is None)
        upload = platform.upload_dialog
        assert upload.connected
        report["components_in_one_window"] = all(
            widget.window() is panel and not widget.isWindow()
            for widget in (appearance, platform, upload, panel.logs)
        )
        QTest.qWait(80)
        assert panel.grab().save(str(output / "control-center-upload.png"))
        upload.submit_button.click()
        assert platform.worker is not None
        panel.open_section("chat")
        report["tab_switch_keeps_upload_running"] = platform.worker is not None
        panel.hide()
        wait_until(lambda: platform.worker is None)
        report["hidden_upload_completes"] = upload.progress.value() == 100 and bool(upload.resource_id)
        panel.open_section("upload")
        wait_until(lambda: platform.worker is None)
        report["upload_form_reused"] = platform.upload_dialog is upload
        report["single_visible_control_window"] = [w for w in application.topLevelWidgets() if w.isVisible()] == [panel]
        panel.resize(560, 660)
        QTest.qWait(80)
        navigation = panel.navigation
        report["narrow_window_usable"] = (
            panel.width() == 560
            and panel.sections["upload"].horizontalScrollBar().maximum() == 0
        )
        report["no_corner_dropdown"] = not any(
            button.arrowType() == Qt.ArrowType.DownArrow
            for button in navigation.header.findChildren(QToolButton)
        )
        panel.open_section("chat")
        navigation.bar.setFocus()
        visited = []
        for key in keys:
            QTest.qWait(40)
            assert navigation.current_key == key
            assert navigation.stack.currentWidget() is panel.sections[key]
            assert sum(page.active for page in panel.sections.values()) == 1
            visited.append(key)
            QTest.keyClick(navigation.bar, Qt.Key.Key_Tab, Qt.KeyboardModifier.ControlModifier)
        report["narrow_keyboard_accesses_all_nine"] = visited == list(keys)
        report["narrow_switch_keeps_draft"] = panel.persona.name.text() == "跨标签保留草稿"
        panel.open_section("upload")
        QTest.qWait(50)
        assert panel.grab().save(str(output / "control-center-narrow.png"))
        panel.open_section("chat")
        panel.input.setFocus()
        QTest.keyClick(panel.input, Qt.Key.Key_Escape)
        report["escape_hides_center"] = not panel.isVisible()
        return report
    finally:
        platform.shutdown()
        wait_until(lambda: platform.worker is None)
        panel.hide()
        application.processEvents()
        LOG.info("原生控制中心验收结束，线程与预览已收起")


def main():
    logging.basicConfig(level=logging.INFO)
    configure_opengl_sharing()
    application = QApplication.instance() or QApplication([])
    application.setQuitOnLastWindowClosed(False)
    output = ROOT / "web/.runtime/screenshots"
    output.mkdir(parents=True, exist_ok=True)
    # 固定站点为关闭的回环端口，双重替换客户端和资源枚举，避免用户数据与外部请求。
    with tempfile.TemporaryDirectory(prefix="xuansi-control-") as directory, \
            patch("pet.platform_upload_dialog.PlatformClient", LocalClient), \
            patch("pet.platform_dialog.installed_resources", return_value=[]):
        report = inspect(application, Path(directory), output)
    report["passed"] = all(report.values())
    (output.parent / "control-center-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    application.quit()
    assert report["passed"], "控制中心原生验收有未通过项"


if __name__ == "__main__":
    main()
