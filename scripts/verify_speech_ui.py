"""原生 Qt 朗读控制验收；临时存储和模型替身，不启麦、不截工作屏幕。"""

import json
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pet.app import DesktopPet
from pet.config import ROOT, Settings
from pet.desktop import DesktopState
from pet.memory import MemoryStore


def wait_until(predicate):
    deadline = time.monotonic() + 3
    while not predicate() and time.monotonic() < deadline:
        QTest.qWait(20)
    assert predicate(), "原生界面状态未及时更新"


def main():
    application = QApplication(sys.argv)
    application.setQuitOnLastWindowClosed(False)
    output = ROOT / "data/verification"
    output.mkdir(parents=True, exist_ok=True)
    report = {}
    with tempfile.TemporaryDirectory(prefix="xuansi-speech-ui-") as temporary, \
            patch("pet.runtime.MemoryStore", lambda: MemoryStore(Path(temporary) / "memory.json")), \
            patch("pet.app.desktop_state", lambda: DesktopState(1, False, False)), \
            patch("pet.app.MouseMonitor.start", lambda _: None), \
            patch("pet.runtime.AudioActivity.start", lambda _: None), \
            patch("pet.runtime.Runtime.load_devices", lambda _: None), \
            patch("pet.runtime.sd.stop", lambda: None), \
            patch("pet.runtime.sd.play", lambda *_: None), \
            patch("pet.runtime.sd.wait", lambda: None):
        pet = DesktopPet(application, Settings(observe=False, audio_avoidance=False,
                                               chat_hotkey="Ctrl+Alt+Shift+F22"))
        pet.resource_timer.stop()
        decisions = iter([False, True])

        async def chat(*_, on_chunk, on_speech, **kwargs):
            enabled = next(decisions)
            on_speech(enabled)
            text = "好的，我安静陪你。" if not enabled else "可以，现在继续用声音陪你。"
            await on_chunk(text)
            return text

        pet.runtime.engine.chat = chat
        pet.runtime.audio.synthesize = lambda *_: (np.zeros(80), 8000)
        closed = threading.Event()
        pet.runtime.shutdown_done.connect(closed.set, Qt.ConnectionType.DirectConnection)
        try:
            pet.panel.show()
            pet.ui.quick.show()
            pet.runtime.listening = True
            pet.panel.voice_state(True)
            pet.ui.quick.voice_state(True)
            pet.panel.persona.name.setText("尚未保存的人设草稿")
            pet.panel.input.setText("让我安静工作一会儿。")
            QTest.keyClick(pet.panel.input, Qt.Key.Key_Return)
            wait_until(lambda: not pet.busy and pet.runtime.speech_override is False)
            report["both_off"] = all("回复朗读已关闭" in widget.text() for widget in (
                pet.panel.audio_status, pet.ui.quick.audio_status,
            ))
            report["microphone_kept"] = (pet.runtime.listening and pet.panel.voice_button.isChecked()
                                         and pet.ui.quick.voice.isChecked())
            report["draft_kept"] = pet.panel.persona.name.text() == "尚未保存的人设草稿"
            pet.panel.grab().save(str(output / "speech-muted-panel.png"))
            pet.ui.quick.grab().save(str(output / "speech-muted-quick.png"))
            pet.ui.quick.input.setText("现在可以出声了。")
            QTest.keyClick(pet.ui.quick.input, Qt.Key.Key_Return)
            wait_until(lambda: not pet.busy and pet.runtime.speech_override is True)
            report["both_on"] = all("回复朗读已开启" in widget.text() for widget in (
                pet.panel.audio_status, pet.ui.quick.audio_status,
            ))
            report["transcripts_match"] = pet.panel.chat.toPlainText() == pet.ui.quick.chat.toPlainText()
            pet.runtime.set_speech_enabled(False)
            pet.apply_settings(pet.settings, "")  # 即使表单值不变，显式保存也恢复默认。
            report["same_settings_restore_default"] = (
                pet.runtime.speech_override is None and pet.runtime.should_speak(pet.settings)
            )
            report["passed"] = all(report.values())
        finally:
            pet.quit()
            wait_until(closed.is_set)
            pet.runtime.loop.call_soon_threadsafe(pet.runtime.loop.stop)
            pet.runtime.thread.join(3)
            (output / "speech-ui-report.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
            )
    print(json.dumps(report, ensure_ascii=False), flush=True)
    if not report.get("passed"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
