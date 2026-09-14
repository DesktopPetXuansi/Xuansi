"""原生菜单开关验收：临时配置、虚拟对话、不启麦、不播放、不读取工作屏幕。"""

import asyncio
import ctypes
import json
import sys
import tempfile
import threading
import time
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QPoint, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pet.app as app_module
import pet.runtime as runtime_module
from pet.app import DesktopPet
from pet.config import ROOT, Settings, load_settings, save_settings
from pet.desktop import DesktopState
from pet.memory import MemoryStore
from pet.panel import Panel


def main():
    ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    application = QApplication(sys.argv)
    application.setQuitOnLastWindowClosed(False)
    temporary = tempfile.TemporaryDirectory(prefix="xuansi-avoidance-")
    folder = Path(temporary.name)
    settings_path = folder / "settings.json"
    output = ROOT / "data/verification"
    output.mkdir(parents=True, exist_ok=True)
    runtime_module.MemoryStore = lambda: MemoryStore(folder / "memory.json")
    runtime_module.save_settings = lambda value: save_settings(value, settings_path)
    app_module.desktop_state = lambda: DesktopState(1, False, False)
    settings = replace(
        Settings(),
        observe=False,
        speak_replies=False,
        chat_hotkey="Ctrl+Alt+Shift+F23",
        model_path="missing-model.gguf",
        projector_path="missing-projector.gguf",
    )
    pet = DesktopPet(application, settings)
    started, release = threading.Event(), threading.Event()
    report = {}

    async def chat(*_):
        started.set()
        while not release.is_set():
            await asyncio.sleep(0.02)
        return "开关不影响文字回复。"

    pet.runtime.engine.chat = chat

    def wait_until(predicate, seconds=3):
        deadline = time.monotonic() + seconds
        while not predicate() and time.monotonic() < deadline:
            QTest.qWait(20)
        return bool(predicate())

    def inspect():
        try:
            pet.open_panel()
            action = pet.panel.audio_avoidance_action
            configuration = pet.panel.layout().menuBar().actions()[0].menu()
            report["shared_action"] = (
                action in configuration.actions() and action in pet.tray.contextMenu().actions()
            )
            report["default_checked"] = action.isChecked() and action.isCheckable()
            pet.panel.persona.name.setText("未保存的名字草稿")
            pet.panel.model_page.temperature.setValue(0.4)
            pet.send("虚拟对话，不观察屏幕")
            assert wait_until(started.is_set)
            epoch = pet.runtime.epoch
            # 只模拟监听状态，不打开真实输入设备。
            pet.runtime.listening = True
            pet.panel.voice_state(True)
            pet.ui.quick.voice_state(True)
            action.trigger()
            assert wait_until(lambda: not pet.ui.saving)
            report["saved_off_without_models"] = not load_settings(settings_path).audio_avoidance
            report["both_menus_off"] = not action.isChecked()
            report["gate_off"] = (
                not pet.runtime.audio_activity.enabled and not pet.runtime.audio_activity.blocked
            )
            report["status_synchronized"] = (
                "已关闭" in pet.panel.audio_status.text() and "已关闭" in pet.ui.quick.audio_status.text()
            )
            report["conversation_preserved"] = (
                pet.runtime.epoch == epoch and pet.busy and pet.runtime.listening
            )
            report["draft_preserved"] = (
                pet.panel.persona.name.text() == "未保存的名字草稿"
                and pet.panel.model_page.temperature.value() == 0.4
            )
            restored = Panel(load_settings(settings_path))
            report["reload_unchecked"] = not restored.audio_avoidance_action.isChecked()
            restored.deleteLater()

            def fail(_):
                raise OSError("synthetic save failure")

            runtime_module.save_settings = fail
            action.trigger()
            assert wait_until(lambda: not pet.ui.saving)
            report["failed_save_rolled_back"] = (
                not action.isChecked()
                and not pet.settings.audio_avoidance
                and not pet.runtime.audio_activity.enabled
                and action.isEnabled()
                and not load_settings(settings_path).audio_avoidance
                and "失败" in pet.panel.status.text()
            )
            runtime_module.save_settings = lambda value: save_settings(value, settings_path)
            action.trigger()
            assert wait_until(lambda: not pet.ui.saving)
            report["reenabled_and_saved"] = (
                action.isChecked()
                and pet.runtime.audio_activity.enabled
                and load_settings(settings_path).audio_avoidance
            )
            report["still_same_conversation"] = pet.runtime.epoch == epoch and pet.runtime.listening
            configuration.popup(pet.panel.mapToGlobal(QPoint(10, 10)))
            QTest.qWait(120)
            configuration.grab().save(str(output / "avoidance-menu.png"))
            configuration.hide()
            release.set()
            assert wait_until(lambda: not pet.busy)
            report["reply_completed"] = "开关不影响文字回复。" in pet.panel.chat.toPlainText()
            report["passed"] = all(report.values())
        except Exception as exc:
            report["passed"] = False
            report["error_type"] = type(exc).__name__
        finally:
            release.set()
            pet.quit()
            (output / "avoidance-menu-report.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(json.dumps(report, ensure_ascii=False), flush=True)

    QTimer.singleShot(300, inspect)
    application.exec()
    pet.runtime.loop.call_soon_threadsafe(pet.runtime.loop.stop)
    pet.runtime.thread.join(3)
    temporary.cleanup()
    if not report.get("passed"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
