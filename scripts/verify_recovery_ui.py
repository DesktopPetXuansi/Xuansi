"""以临时配置和假模型验证关闭保存、失败提示与回复恢复，不使用物理音频。"""

import asyncio
import json
import logging
import sys
import tempfile
import threading
import time
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pet.app as app_module
import pet.runtime as runtime_module
from pet.app import DesktopPet
from pet.audio_activity import AudioActivity
from pet.config import ROOT, Settings, load_settings, save_settings
from pet.desktop import DesktopState
from pet.memory import MemoryStore
from pet.mouse_monitor import MouseMonitor
from pet.runtime import Runtime

LOG = logging.getLogger(__name__)


def wait_until(predicate, seconds=5):
    deadline = time.monotonic() + seconds
    while not predicate() and time.monotonic() < deadline:
        QTest.qWait(20)
    assert predicate(), "界面状态未在期限内达到预期"


def inspect(pet, settings_path, fail_save, output):
    report = {}
    panel = pet.panel
    pet.open_panel()
    panel.persona.name.setText("回归测试伙伴")
    panel.preferences.interval.setValue(37)
    panel.model_page.temperature.setValue(0.3)
    panel.close()
    wait_until(lambda: not panel.isVisible() and not pet.ui.saving)
    saved = load_settings(settings_path)
    assert (saved.name, saved.interval, saved.temperature) == ("回归测试伙伴", 37, 0.3)
    pet.open_panel()
    assert panel.persona.name.text() == saved.name
    assert panel.preferences.interval.value() == saved.interval
    report["close_saves_and_reopen_retains_configuration"] = True

    fail_save.set()
    panel.persona.name.setText("失败后保留的草稿")
    panel.close()
    wait_until(lambda: not pet.ui.saving)
    assert panel.isVisible() and panel.persona.name.text() == "失败后保留的草稿"
    assert load_settings(settings_path) == saved
    assert "未保存" in panel.form.hint.text()
    panel.grab().save(str(output / "settings-save-failure.png"))
    report["save_failure_preserves_window_draft_and_disk"] = True
    fail_save.clear()
    panel.close()
    wait_until(lambda: not panel.isVisible() and not pet.ui.saving)

    async def settled():
        # 保存会异步关闭旧输入并卸载模型；模拟开麦前等它们完成。
        async with pet.runtime.control:
            pass
        async with pet.runtime.microphone_control:
            pass

    ready = pet.runtime.schedule(settled())
    wait_until(ready.done)
    ready.result()
    QApplication.processEvents()

    entered = threading.Event()

    async def chat(_settings, text, *_args, **_kwargs):
        if text == "等待测试":
            entered.set()
            await asyncio.sleep(30)
        if text == "失败测试":
            raise OSError("synthetic-private-detail")
        return "恢复测试完成。"

    pet.runtime.engine.chat = chat
    pet.runtime.listening = True  # 仅设置状态，不启动输入设备。
    pet.open_panel()
    panel.input.setText("等待测试")
    panel._send()
    wait_until(entered.is_set)
    assert panel.stop_button.isEnabled() and pet.ui.quick.stop_button.isEnabled()
    panel.stop_button.click()
    wait_until(lambda: not pet.busy and not pet.runtime.microphone.muted.is_set())
    assert pet.runtime.listening
    pet.ui.quick.input.setText("下一轮测试")
    pet.ui.quick.send()
    wait_until(lambda: not pet.busy and "恢复测试完成。" in panel.chat.toPlainText())
    assert "恢复测试完成。" in pet.ui.quick.chat.toPlainText()
    report["stop_resumes_listening_and_next_turn_replies_in_both_windows"] = True

    panel.input.setText("失败测试")
    panel._send()
    wait_until(lambda: not pet.busy and "系统提示" in panel.chat.toPlainText())
    assert "本地服务未能完成请求" in pet.ui.quick.chat.toPlainText()
    assert "synthetic-private-detail" not in panel.chat.toPlainText()
    report["failure_is_visible_in_both_chats_without_private_detail"] = True

    panel.speech_button.click()
    assert pet.runtime.should_speak(pet.settings)
    assert pet.ui.quick.speech_button.isChecked()
    pet.ui.quick.speech_button.click()
    assert not pet.runtime.should_speak(pet.settings)
    assert pet.runtime.listening and not panel.speech_button.isChecked()
    report["speech_buttons_sync_without_closing_microphone"] = True
    pet.runtime.listening = False
    pet.ui.quick.show()
    QTest.qWait(50)
    panel.grab().save(str(output / "recovery-panel.png"))
    pet.ui.quick.grab().save(str(output / "recovery-quick.png"))
    return report


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    output = ROOT / "data/verification/recovery"
    output.mkdir(parents=True, exist_ok=True)
    fail_save = threading.Event()
    report = {}
    with tempfile.TemporaryDirectory(prefix="xuansi-recovery-") as temporary:
        directory = Path(temporary)
        settings_path = directory / "settings.json"
        for name in ("model.gguf", "projector.gguf"):
            (directory / name).touch()
        settings = replace(
            Settings(), observe=False, speak_replies=False, audio_avoidance=False,
            model_path=str(directory / "model.gguf"), projector_path=str(directory / "projector.gguf"),
            chat_hotkey="Ctrl+Alt+Shift+F23",
        )

        def persist(value):
            if fail_save.is_set():
                raise OSError("synthetic write failure")
            save_settings(value, settings_path)

        with (
            patch.object(runtime_module, "MemoryStore", lambda: MemoryStore(directory / "memory.json")),
            patch.object(runtime_module, "save_settings", persist),
            patch.object(app_module, "desktop_state", lambda: DesktopState(1, False, False)),
            patch.object(MouseMonitor, "start", lambda _: None),
            patch.object(AudioActivity, "start", lambda _: None),
            patch.object(Runtime, "load_devices", lambda runtime: runtime.devices_loaded.emit([])),
            patch.object(runtime_module.sd, "stop", lambda: None),
        ):
            pet = DesktopPet(app, settings)
            pet.resource_timer.stop()
            closed = []
            pet.runtime.shutdown_done.connect(lambda: closed.append(True))
            try:
                report = inspect(pet, settings_path, fail_save, output)
                report["passed"] = True
                LOG.info("原生界面恢复流程验收通过")
            finally:
                pet.quit()
                wait_until(lambda: bool(closed))
                pet.runtime.loop.call_soon_threadsafe(pet.runtime.loop.stop)
                pet.runtime.thread.join(3)
                (output / "ui-report.json").write_text(
                    json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
                )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
