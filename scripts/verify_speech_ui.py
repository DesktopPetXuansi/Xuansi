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
from pet.live2d_session import configure_opengl_sharing
from pet.memory import MemoryStore
from pet.tool_protocol import AssistantReply, ToolCall


def wait_until(predicate):
    deadline = time.monotonic() + 3
    while not predicate() and time.monotonic() < deadline:
        QTest.qWait(20)
    assert predicate(), "原生界面状态未及时更新"


def main():
    # 与桌宠生产入口一致，在任何 GL 窗口创建前启用共享。
    configure_opengl_sharing()
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

        async def complete(_settings, messages, *_args, **_kwargs):
            if messages[-1]["role"] != "tool":
                enabled = next(decisions)
                return AssistantReply("", (ToolCall("speech-ui", "set_speech_enabled", json.dumps({"enabled": enabled})),), "tool_calls")
            # 只有执行回执成功后才返回与开关状态对应的确认正文。
            receipt = json.loads(messages[-1]["content"])
            assert receipt["ok"]
            enabled = receipt["result"]["enabled"]
            return AssistantReply("好的，我安静陪你。" if not enabled else "可以，现在继续用声音陪你。")

        async def start(_settings):
            # Qt 验收仅用模型替身，不能启动 GPU 或真实输入设备。
            pass

        pet.runtime.engine.complete = complete
        pet.runtime.engine.start = start
        pet.runtime.engine.warmup = start
        pet.runtime.audio.synthesize = lambda *_: (np.zeros(80), 8000)
        closed = threading.Event()
        pet.runtime.shutdown_done.connect(closed.set, Qt.ConnectionType.DirectConnection)
        try:
            pet.open_panel()
            pet.voice_enabled = True  # 与用户开启选择一致；仍使用模拟输入，不启麦。
            pet.runtime.listening = True
            pet.panel.voice_state(True)
            pet.panel.persona.name.setText("尚未保存的人设草稿")
            pet.panel.input.setText("让我安静工作一会儿。")
            QTest.keyClick(pet.panel.input, Qt.Key.Key_Return)
            wait_until(lambda: not pet.busy and pet.runtime.speech_override is False)
            report["speech_off"] = (
                "回复朗读已关闭" in pet.panel.audio_status.text()
                and not pet.panel.speech_button.isChecked()
            )
            report["microphone_kept"] = pet.runtime.listening and pet.panel.voice_button.isChecked()
            report["draft_kept"] = pet.panel.persona.name.text() == "尚未保存的人设草稿"
            pet.panel.grab().save(str(output / "speech-muted-panel.png"))
            pet.panel.input.setText("现在可以出声了。")
            QTest.keyClick(pet.panel.input, Qt.Key.Key_Return)
            wait_until(lambda: not pet.busy and pet.runtime.speech_override is True)
            report["speech_on"] = (
                "回复朗读已开启" in pet.panel.audio_status.text()
                and pet.panel.speech_button.isChecked()
            )
            report["both_turns_reach_single_chat"] = all(
                text in pet.panel.chat.toPlainText()
                for text in ("好的，我安静陪你。", "可以，现在继续用声音陪你。")
            )
            pet.runtime.set_speech_enabled(False)
            pet.apply_settings(pet.settings, "")  # 即使表单值不变，显式保存也恢复默认。
            report["same_settings_restore_default"] = (
                pet.runtime.speech_override is None and pet.runtime.should_speak(pet.settings)
            )
            # 使用真实 Qt/Live2D 绘制而非定时器伪造完成，不经过模型替身决定动作。
            wait_until(lambda: "blink" in pet.avatar.available_motions)
            motion = pet.runtime.schedule(pet.runtime.request_motion(pet.runtime.epoch, "blink"))
            wait_until(motion.done)
            report["motion_draw_completed"] = motion.result() == {"status": "completed"}
            interrupted = pet.runtime.schedule(pet.runtime.request_motion(pet.runtime.epoch, "blink"))
            wait_until(lambda: pet.avatar._motion_name == "blink")
            pet.avatar.cancel_motion()
            wait_until(interrupted.done)
            report["motion_interruption_reported"] = interrupted.result() == {"status": "cancelled"}
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
