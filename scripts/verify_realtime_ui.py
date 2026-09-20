"""原生 Qt 控件检查；使用临时设置和固定文字，不开启麦克风。"""

import json
import sys
import tempfile
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pet.app import DesktopPet
from pet.config import DATA, Settings, load_settings, save_settings
from pet.live_input import VoiceUpdate
from pet.panel import STYLE, Panel
from pet.quick_chat import QuickChat


def main():
    app = QApplication.instance() or QApplication([])
    settings = replace(Settings(), observe=False)
    panel, quick = Panel(settings), QuickChat(settings, STYLE)
    calls, saved = [], []
    report = {}
    panel.message_added.connect(quick.append)
    panel.settings_requested.connect(saved.append)
    runtime = SimpleNamespace(microphone_epoch=1, listening=True, accept_voice=lambda *args: calls.append(args))
    host = SimpleNamespace(runtime=runtime, paused=False, panel=panel, ui=SimpleNamespace(quick=quick),
                           settings=settings, last_external=(0, 0), _begin=lambda: None)
    try:
        panel.show()
        panel.layout().menuBar().actions()[0].menu().actions()[2].trigger()
        QTest.qWait(100)
        report["menu_opens_voice_preferences"] = panel.tabs.currentIndex() == 3
        report["default_enabled"] = panel.preferences.realtime.isChecked()
        DesktopPet.on_voice_update(host, 1, VoiceUpdate(0, "请你听我说完<b>文字</b>"))
        report["partial_only_preview"] = not calls and not panel.chat.toPlainText()
        report["preview_plain_text"] = (
            panel.live_transcript.textFormat() == Qt.TextFormat.PlainText
            and quick.live_transcript.text() == panel.live_transcript.text()
        )
        DesktopPet.on_voice_update(host, 1, VoiceUpdate(0, "请你听我说完", final=True))
        report["final_sends_once"] = len(calls) == 1 and calls[0][1].final
        report["both_chats_receive_final"] = "请你听我说完" in panel.chat.toPlainText() == quick.chat.toPlainText()
        DesktopPet.on_voice_update(host, 0, VoiceUpdate(1, "旧设备文字", final=True))
        report["old_device_ignored"] = len(calls) == 1
        panel.preferences.realtime.setChecked(False)
        panel.preferences.save_button.click()
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "settings.json"
            save_settings(saved[-1], path)
            report["saved_and_reloaded"] = not load_settings(path).realtime_voice
        output = DATA / "verification"
        output.mkdir(parents=True, exist_ok=True)
        panel.grab().save(str(output / "realtime-preferences.png"))
        report["passed"] = all(report.values())
        (output / "realtime-ui.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report))
        assert report["passed"], report
    finally:
        panel.hide()
        quick.hide()
        panel.logs.close()
        app.quit()


if __name__ == "__main__":
    main()
