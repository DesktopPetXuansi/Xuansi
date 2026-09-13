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
from pet.memory import MemoryStore


def main():
    ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
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

    async def chat(config, text, images, history):
        report["request_uses_saved_sampling"] = config.temperature == 0.4 and config.max_tokens == 256
        return "这是快捷对话验收回复。"

    pet.runtime.engine.chat = chat

    def wait_until(predicate, seconds=3):
        deadline = time.monotonic() + seconds
        while not predicate() and time.monotonic() < deadline:
            QTest.qWait(30)
        return bool(predicate())

    def inspect():
        try:
            menu = pet.panel.layout().menuBar()
            report["panel_menus"] = [action.text() for action in menu.actions()]
            report["tray_menus"] = [action.text() for action in pet.tray.contextMenu().actions()]
            pet.panel.open_configuration()
            pet.panel.model_page.temperature.setValue(0.4)
            pet.panel.model_page.tokens.setValue(256)
            pet.panel.model_page.save_button.click()
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
            report["logs_loaded"] = wait_until(lambda: "测试就绪" in pet.panel.logs.content.toPlainText())
            pet.panel.logs.level.setCurrentText("WARNING")
            report["logs_filter"] = "测试就绪" not in pet.panel.logs.content.toPlainText()
            pet.panel.logs.grab().save(str(output / "menu-logs.png"))
            pet.panel.logs.hide()
            report["hidden_logs_stop_polling"] = not pet.panel.logs.timer.isActive()

            # 只向自己的线程投递 WM_HOTKEY，不向用户前景软件注入按键。
            identifier = pet.ui.hotkey.active
            report["hotkey_registered"] = identifier is not None
            ctypes.windll.user32.PostThreadMessageW(
                ctypes.windll.kernel32.GetCurrentThreadId(), 0x0312, identifier, 0
            )
            report["native_hotkey_opens_quick_chat"] = wait_until(pet.ui.quick.isVisible)
            quick = pet.ui.quick
            report["focus_received"] = quick.input.hasFocus()
            frame = quick.frameGeometry()
            area = quick.screen().availableGeometry()
            report["quick_inside_work_area"] = area.contains(frame)
            report["right_bottom_margin"] = [area.right() - frame.right(), area.bottom() - frame.bottom()]
            quick.input.setText("快捷对话验收")
            QTest.keyClick(quick.input, Qt.Key.Key_Return)
            report["reply_in_both_windows"] = wait_until(
                lambda: (
                    "这是快捷对话验收回复。" in quick.chat.toPlainText()
                    and "这是快捷对话验收回复。" in pet.panel.chat.toPlainText()
                )
            )
            quick.grab().save(str(output / "menu-quick-chat.png"))
            QTest.keyClick(quick.input, Qt.Key.Key_Escape)
            report["escape_hides_quick_chat"] = wait_until(lambda: not quick.isVisible(), 0.5)
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
