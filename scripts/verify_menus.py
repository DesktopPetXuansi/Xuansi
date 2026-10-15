"""原生增量验收：只用虚拟对话/临时设置，不启麦、不播放、不读取用户记忆。"""

import ctypes
import json
import sys
import time
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pet.app as app_module
import pet.runtime as runtime_module
from pet.app import DesktopPet
from pet.config import ROOT, Settings, save_settings
from pet.desktop import DesktopState
from pet.live2d_session import configure_opengl_sharing
from pet.memory import MemoryStore


def main():
    ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    # 与桌宠生产入口一致，在任何 GL 窗口创建前启用共享。
    configure_opengl_sharing()
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    output = ROOT / "data/verification"
    output.mkdir(parents=True, exist_ok=True)
    runtime_module.MemoryStore = lambda: MemoryStore(output / "menu-test-memory.json")
    runtime_module.save_settings = lambda settings: save_settings(
        settings, output / "menu-test-settings.json"
    )
    # 自动观察关闭，前景状态替身只保证 UI 测试不会受锁屏判断影响。
    app_module.desktop_state = lambda: DesktopState(1, False, False)
    settings = replace(Settings(), observe=False, speak_replies=False, chat_hotkey="Ctrl+Alt+Shift+F24")
    pet = DesktopPet(app, settings)
    report = {}

    async def chat(config, text, images, history, **_kwargs):
        report["request_uses_saved_sampling"] = config.temperature == 0.4 and config.max_tokens == 256
        return "这是控制中心验收回复。"

    pet.runtime.engine.chat = chat

    def wait_until(predicate, seconds=3):
        deadline = time.monotonic() + seconds
        while not predicate() and time.monotonic() < deadline:
            QTest.qWait(30)
        return bool(predicate())

    def inspect():
        try:
            report["single_page_sections"] = set(pet.panel.sections) == {
                "chat", "persona", "memory", "preferences", "model", "appearance",
                "resources", "upload", "logs",
            }
            report["tray_has_three_entries"] = [
                action.text() for action in pet.tray.contextMenu().actions()
            ] == ["打开控制中心", "休眠/唤醒", "退出"]
            pet.panel.open_configuration()
            report["configuration_stays_in_control_center"] = (
                pet.panel.sections["model"].expanded
                and pet.panel.model_page.window() is pet.panel
            )
            pet.panel.model_page.temperature.setValue(0.4)
            pet.panel.model_page.tokens.setValue(256)
            pet.panel.save_button.click()
            report["configuration_saved"] = wait_until(lambda: pet.settings.temperature == 0.4)
            pet.panel.grab().save(str(output / "menu-configuration.png"))
            pet.panel.hide()

            log_path = output / "menu-test.log"
            log_path.write_text(
                "2026-09-13 14:00:00 INFO pet 测试就绪\n2026-09-13 14:00:01 WARNING pet 测试声音回避\n",
                encoding="utf-8",
            )
            pet.panel.logs.path = log_path
            pet.panel.open_logs()
            report["logs_stay_in_control_center"] = pet.panel.logs.window() is pet.panel
            report["logs_loaded"] = wait_until(lambda: "测试就绪" in pet.panel.logs.content.toPlainText())
            pet.panel.logs.level.setCurrentText("WARNING")
            report["logs_filter"] = "测试就绪" not in pet.panel.logs.content.toPlainText()
            pet.panel.logs.grab().save(str(output / "menu-logs.png"))
            pet.panel.collapse_section("logs")
            report["hidden_logs_stop_polling"] = not pet.panel.logs.timer.isActive()
            pet.panel.hide()

            # 只向自己的线程投递 WM_HOTKEY，不向用户前景软件注入按键。
            identifier = pet.ui.hotkey.active
            report["hotkey_registered"] = identifier is not None
            ctypes.windll.user32.PostThreadMessageW(
                ctypes.windll.kernel32.GetCurrentThreadId(), 0x0312, identifier, 0
            )
            report["native_hotkey_opens_control_center"] = wait_until(pet.panel.isVisible)
            panel = pet.panel
            report["focus_received"] = panel.input.hasFocus()
            report["chat_section_expanded"] = panel.sections["chat"].expanded
            report["one_control_window"] = all(
                widget.window() is panel
                for widget in (panel.chat, pet.ui.appearance, pet.ui.platform, panel.logs)
            )
            panel.input.setText("统一控制中心验收")
            QTest.keyClick(panel.input, Qt.Key.Key_Return)
            report["reply_reaches_single_chat_once"] = wait_until(
                lambda: panel.chat.toPlainText().count("这是控制中心验收回复。") == 1
            )
            panel.grab().save(str(output / "menu-control-center.png"))
            # Esc 保留原设置保存事务；完成后才允许隐藏同一个窗口。
            QTest.keyClick(panel.input, Qt.Key.Key_Escape)
            report["escape_saves_and_hides_control_center"] = wait_until(
                lambda: not panel.isVisible() and not pet.ui.saving
            )
            report["microphone_off"] = not pet.runtime.listening
            report["audio_monitor_alive"] = pet.runtime.audio_activity.thread.is_alive()
            report["audio_monitor_valid"] = pet.runtime.audio_activity._snapshot[0]
        except Exception as exc:
            report["error"] = repr(exc)
        finally:
            pet.quit()
            report["hotkey_unregistered_on_quit"] = pet.ui.hotkey.active is None
            (output / "menu-report.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(json.dumps(report, ensure_ascii=True, indent=2))

    QTimer.singleShot(500, inspect)
    app.exec()
    pet.runtime.loop.call_soon_threadsafe(pet.runtime.loop.stop)
    pet.runtime.thread.join(2)


if __name__ == "__main__":
    main()
