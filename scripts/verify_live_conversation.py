"""真实本地模型与模拟收音：验证说完后才朗读和首段等待时间。"""

import json
import logging
import sys
import tempfile
import threading
import time
from dataclasses import replace
from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pet.microphone as microphone_module
from pet.config import DATA, Settings
from pet.memory import MemoryStore
from pet.runtime import Runtime


class SimulatedInput:
    """每 100ms 泵入合成语音，不打开硬件；朗读阶段继续泵入以验证静音收音。"""

    def __init__(self, source, callback, metrics):
        self.source, self.callback, self.metrics = source, callback, metrics
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.pump, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.stop.set()
        self.thread.join(2)

    def pump(self):
        offset = 0
        started = time.monotonic()
        self.metrics["input_started"] = started
        while not self.stop.is_set():
            frame = np.zeros((1600, 1), dtype=np.float32)
            source = self.source[offset:offset + 1600]
            frame[:len(source), 0] = source
            self.callback(frame, 1600, None, None)
            offset += 1600
            self.stop.wait(max(0, started + offset / 16000 - time.monotonic()))


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    runtime = Runtime()
    runtime.audio_activity.set_enabled(False)
    settings = replace(Settings(), observe=False, max_tokens=100, audio_avoidance=False)
    metrics, updates, replies, states = {}, [], [], []
    target = DATA / "verification/live-conversation.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    report = {"passed": False, "device": "模拟收音和静音播放接收器；真实 ASR/LLM/TTS；无真实录音"}
    temporary = tempfile.TemporaryDirectory(prefix="xuansi-live-")
    runtime.memory = MemoryStore(Path(temporary.name) / "memory.json")

    def update(epoch, event):
        updates.append((time.monotonic(), event))
        if event.final:
            runtime.accept_voice(epoch, event, settings)

    runtime.voice_update.connect(update, Qt.ConnectionType.DirectConnection)
    runtime.reply.connect(lambda _, text, kind: replies.append((text, kind)), Qt.ConnectionType.DirectConnection)
    runtime.microphone_state.connect(lambda _, text: states.append(text), Qt.ConnectionType.DirectConnection)
    sd = microphone_module.sd
    original = sd.InputStream, sd.play, sd.wait, sd.stop

    def play(samples, rate):
        metrics.setdefault("first_audio", time.monotonic())
        assert runtime.microphone.muted.is_set(), "播放时收音未暂停"
        metrics["muted_during_playback"] = True

    try:
        samples, rate = runtime.audio.synthesize("你好，请你用一句话介绍一下自己。", 0, 1.08)
        source = np.interp(np.arange(round(len(samples) * 16000 / rate)) * rate / 16000,
                           np.arange(len(samples)), samples).astype(np.float32)
        voiced = np.flatnonzero(np.abs(source) > 0.008)
        source = source[:voiced[-1] + 1]
        sd.InputStream = lambda **kw: SimulatedInput(source, kw["callback"], metrics)
        sd.play, sd.wait, sd.stop = play, lambda: None, lambda: None
        runtime.toggle_microphone(True, 0, realtime=True, settings=settings).result(120)
        deadline = time.monotonic() + len(source) / 16000 + 30
        while time.monotonic() < deadline:
            if any(event.final and event.text for _, event in updates) and runtime.job and runtime.job.done():
                break
            time.sleep(0.05)
        started = metrics["input_started"]
        report.update({
            "mode": "warm", "input_seconds": round(len(source) / 16000, 3),
            "first_partial_seconds": round(next(t for t, event in updates if event.text) - started, 3),
            "endpoint_seconds": round(next(t for t, event in updates if event.final and event.text) - started, 3),
            "first_audio_seconds": round(metrics.get("first_audio", float("inf")) - started, 3),
            "final_transcripts": [event.text for _, event in updates if event.final and event.text],
            "replies": replies, "states": states,
            "muted_during_playback": metrics.get("muted_during_playback", False),
        })
        report["end_to_audio_seconds"] = round(report["first_audio_seconds"] - report["input_seconds"], 3)
        report["end_to_endpoint_seconds"] = round(report["endpoint_seconds"] - report["input_seconds"], 3)
        assert 0 <= report["end_to_audio_seconds"] < 3 and replies, report
        assert report["first_partial_seconds"] < report["input_seconds"], report
        assert report["muted_during_playback"] and not runtime.microphone.muted.is_set(), report
        runtime.toggle_microphone(False).result(5)
        assert runtime.microphone.join()
        report["close_stops_device"] = True
        report["passed"] = True
    finally:
        runtime.microphone.stop()
        runtime.microphone.join()
        runtime.cancel(release=True).result(20)
        runtime.loop.call_soon_threadsafe(runtime.loop.stop)
        runtime.thread.join(3)
        sd.InputStream, sd.play, sd.wait, sd.stop = original
        temporary.cleanup()
        target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
