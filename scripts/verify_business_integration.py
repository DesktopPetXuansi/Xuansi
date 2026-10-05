"""原生界面到真实模型的业务联调；临时数据、模拟收音、静音播放，不捕获桌面。"""

import json
import logging
import sys
import tempfile
import threading
import time
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import numpy as np
import psutil
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pet.app import DesktopPet
from pet.audio_activity import AudioActivity
from pet.config import DATA, Settings, load_settings, save_settings
from pet.desktop import DesktopState
from pet.memory import MemoryStore
from pet.mouse_monitor import MouseMonitor
from pet.runtime import Runtime
from scripts.verify_live_conversation import SimulatedInput

LOG = logging.getLogger(__name__)


def wait_until(predicate, message, seconds=90):
    deadline = time.monotonic() + seconds
    while not predicate() and time.monotonic() < deadline:
        QTest.qWait(20)
    assert predicate(), message


def verify_memory_chat(pet, memory_path, clips, motions, mouth_levels, reply_bubbles, report):
    """实际点击保存，再让快捷窗口经后台推理取回磁盘记忆、执行动作和朗读。"""
    pet.open_panel()
    wait_until(lambda: "blink" in pet.runtime.motion_actions, "默认 Live2D 未公布眨眼能力", 10)
    pet.panel.tabs.setCurrentIndex(2)
    pet.panel.memory.setPlainText("我喜欢喝绿茶。")
    save = next(button for button in pet.panel.findChildren(QPushButton) if button.text() == "保存记忆")
    QTest.mouseClick(save, Qt.MouseButton.LeftButton)
    wait_until(lambda: pet.panel.status.text() == "记忆已保存", "记忆页保存未完成", 10)
    assert "绿茶" in MemoryStore(memory_path).read() and not pet.runtime.history
    report["memory_page_persists_and_clears_short_context"] = True

    pet.ui.quick.show()
    pet.ui.quick.input.setText("我喜欢喝什么？请眨一下眼，并出声用一句话回答。")
    QTest.keyClick(pet.ui.quick.input, Qt.Key.Key_Return)
    wait_until(lambda: bool(pet.runtime.history) and not pet.busy
               and "绿茶" in pet.runtime.history[-1]["content"], "界面请求未完成记忆召回")
    answer = pet.runtime.history[-1]["content"]
    assert answer in pet.panel.chat.toPlainText() and answer in pet.ui.quick.chat.toPlainText()
    # 气泡定时收起，冷启动 TTS 可能晚于它；必须在回复到达时验证显示。
    assert reply_bubbles and reply_bubbles[-1], "回复到达时未显示气泡"
    assert clips, "真实 TTS 未交付音频"
    assert motions == ["blink"], f"原生动作执行不符合请求：{motions}"
    assert any(level > 0 for level in mouth_levels), "实际播放阶段未提供有效口型响度"
    report.update({
        "persisted_memory_reaches_real_model": True,
        "real_reply_reaches_both_windows_and_bubble": True,
        "real_tts_emits_audio_and_mouth_levels": True,
        "real_model_motion_reaches_live2d": True,
    })
    LOG.info("界面、磁盘记忆、真实模型、朗读与 Live2D 动作联调通过")


def verify_voice_sleep(pet, source, clips, updates, playback_checks, report):
    """只替换声卡端点，保留识别线程、Qt 信号、话轮提交和真实模型。"""
    samples, rate = pet.runtime.audio.synthesize("你好，请出声用一句话介绍一下自己。", 0, 1.08)
    converted = np.interp(
        np.arange(round(len(samples) * 16000 / rate)) * rate / 16000,
        np.arange(len(samples)), samples,
    ).astype(np.float32)
    voiced = np.flatnonzero(np.abs(converted) > 0.008)
    assert len(voiced), "合成输入没有有效语音"
    source["samples"] = converted[:voiced[-1] + 1]
    previous_clips = len(clips)
    pet.panel.voice_button.click()
    wait_until(lambda: any(update.final for update in updates) and not pet.busy
               and len(clips) > previous_clips and not pet.runtime.microphone.muted.is_set(),
               "界面开启的连续语音未完成回复或恢复收音")
    final_text = next(update.text for update in updates if update.final)
    assert "介绍一下自己" in final_text
    assert final_text in pet.panel.chat.toPlainText() and final_text in pet.ui.quick.chat.toPlainText()
    assert pet.voice_enabled and pet.runtime.listening and playback_checks and all(playback_checks)
    report["real_asr_qt_request_llm_tts_roundtrip"] = True
    report["voice_text_synchronized_and_listening_resumed"] = True
    report["playback_pauses_actual_input_pipeline"] = True

    # 唤醒用零输入，避免测试自身再次发起一轮对话。
    source["samples"] = np.zeros(1600, dtype=np.float32)
    process = pet.runtime.engine.process
    assert process is not None
    engine_pid = process.pid
    pet.panel.sleep_button.click()
    wait_until(lambda: not pet.runtime.listening and not psutil.pid_exists(engine_pid),
               "休眠未关闭输入或释放模型", 20)
    assert pet.paused and pet.voice_enabled and pet.panel.voice_button.isChecked()
    assert pet.ui.quick.voice.isChecked()
    report["sleep_preserves_selection_and_releases_real_engine"] = True
    pet.panel.sleep_button.click()
    wait_until(lambda: pet.runtime.listening and "实时聆听中" in pet.panel.status.text(),
               "唤醒未恢复实际识别线程")
    assert pet.voice_enabled and not pet.paused and pet.runtime.microphone.thread.is_alive()
    report["wake_reloads_models_and_resumes_input_thread"] = True
    pet.panel.voice_button.click()
    wait_until(lambda: not pet.runtime.listening and not pet.runtime.microphone.thread.is_alive(),
               "关闭连续对话未释放输入线程", 15)
    LOG.info("真实语音经界面提交、恢复收音、休眠卸载和唤醒联调通过")


def verify_close_settings(pet, settings_path, report):
    """语音与休眠操作之后再保存表单，核对配置写入和重开状态。"""
    pet.panel.persona.name.setText("业务联调测试伙伴")
    pet.panel.preferences.interval.setValue(37)
    pet.panel.close()
    wait_until(lambda: not pet.panel.isVisible() and not pet.ui.saving, "关闭前保存未完成", 15)
    saved = load_settings(settings_path)
    assert saved.name == "业务联调测试伙伴" and saved.interval == 37
    pet.open_panel()
    assert pet.panel.persona.name.text() == saved.name
    assert pet.panel.preferences.interval.value() == saved.interval
    assert not pet.voice_enabled and not pet.runtime.listening
    report["close_save_reload_retains_configuration_after_voice_and_sleep"] = True
    LOG.info("跨语音与休眠流程的配置关闭保存、重开联调通过")


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    application = QApplication(sys.argv)
    application.setQuitOnLastWindowClosed(False)
    target = DATA / "verification/business-integration-report.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    report = {"passed": False, "devices": "模拟收音和静音播放；真实 ASR/LLM/TTS、Qt 和 Live2D"}
    source = {"samples": np.zeros(1600, dtype=np.float32)}
    clips, updates, motions, mouth_levels, playback_checks, failures = [], [], [], [], [], []
    reply_bubbles = []
    closed = threading.Event()
    pet = None

    with tempfile.TemporaryDirectory(prefix="xuansi-business-") as temporary:
        folder = Path(temporary)
        settings_path, memory_path = folder / "settings.json", folder / "memory.json"

        def fake_input(**kwargs):
            return SimulatedInput(source["samples"], kwargs["callback"], {})

        def silent_play(samples, rate):
            clips.append({"samples": len(samples), "rate": rate})
            if pet.runtime.listening:
                playback_checks.append(pet.runtime.microphone.muted.is_set())

        # 禁用外部观察与设备枚举；生产业务对象、线程和模型均保持原实现。
        with (
            patch("pet.runtime.MemoryStore", lambda: MemoryStore(memory_path)),
            patch("pet.runtime.save_settings", lambda value: save_settings(value, settings_path)),
            patch("pet.app.desktop_state", lambda: DesktopState(1, False, False)),
            patch.object(MouseMonitor, "start", lambda _: None),
            patch.object(AudioActivity, "start", lambda _: None),
            patch.object(Runtime, "load_devices", lambda _: None),
            patch("pet.microphone.sd.InputStream", fake_input),
            patch("pet.runtime.sd.play", silent_play),
            patch("pet.runtime.sd.wait", lambda: time.sleep(0.15)),
            patch("pet.runtime.sd.stop", lambda: None),
        ):
            try:
                settings = replace(Settings(), observe=False, audio_avoidance=False, temperature=0.0,
                                   max_tokens=100, chat_hotkey="Ctrl+Alt+Shift+F21")
                pet = DesktopPet(application, settings)
                pet.resource_timer.stop()
                pet.runtime.shutdown_done.connect(closed.set, Qt.ConnectionType.DirectConnection)
                pet.runtime.voice_update.connect(lambda _, update: updates.append(update))
                pet.runtime.mouth_level.connect(mouth_levels.append)
                pet.runtime.failed.connect(lambda _, message: failures.append(message))
                pet.runtime.reply.connect(lambda *_: reply_bubbles.append(pet.avatar.bubble.isVisible()))
                original_motion = pet.avatar.play_motion

                def observe_motion(motion):
                    # 记录真实动作执行结果，继续调用原始 Live2D 方法。
                    accepted = original_motion(motion)
                    if accepted:
                        motions.append(motion)
                    return accepted

                pet.avatar.play_motion = observe_motion
                verify_memory_chat(pet, memory_path, clips, motions, mouth_levels, reply_bubbles, report)
                verify_voice_sleep(pet, source, clips, updates, playback_checks, report)
                verify_close_settings(pet, settings_path, report)
                assert not failures, "联调期间出现业务故障提示"
                report["no_business_failures"] = True
                pet.panel.grab().save(str(target.parent / "business-integration-panel.png"))
                pet.ui.quick.grab().save(str(target.parent / "business-integration-quick.png"))
                report["passed"] = True
            finally:
                if pet is not None:
                    pet.quit()
                    wait_until(closed.is_set, "退出未完成后台清理", 20)
                    pet.runtime.loop.call_soon_threadsafe(pet.runtime.loop.stop)
                    pet.runtime.thread.join(3)
                    assert not pet.runtime.thread.is_alive(), "退出后运行时线程仍存活"
                    report["shutdown_releases_runtime_thread"] = True
                target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
                LOG.info("业务联调结束 passed=%s", report["passed"])
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
