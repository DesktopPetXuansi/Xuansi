"""本机语音→记忆→模型回复→合成闭环；测试音频替代真实麦克风。"""

import json
import sys
import tempfile
import threading
from dataclasses import replace
from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pet.runtime as module
from pet.config import ROOT, Settings
from pet.memory import MemoryStore
from pet.runtime import Runtime


def main():
    runtime = Runtime()
    settings = Settings(name="团子", speak_replies=True)
    heard, replies, playback, states = [], [], [], []
    finished = threading.Event()
    runtime.heard.connect(lambda _, text: heard.append(text), Qt.ConnectionType.DirectConnection)
    runtime.reply.connect(lambda _, text, kind: replies.append(text), Qt.ConnectionType.DirectConnection)
    runtime.state.connect(lambda _, text: states.append(text), Qt.ConnectionType.DirectConnection)
    runtime.finished.connect(lambda _: finished.set(), Qt.ConnectionType.DirectConnection)
    # 不制造突如其来的声音；真实声卡试听留给用户点击面板完成。
    module.sd.play = lambda data, rate: playback.append({"samples": len(data), "rate": rate})
    module.sd.wait = lambda: None
    report = {"playback": "测试接收器；真实扬声器由用户试听验收"}
    temporary = tempfile.TemporaryDirectory(prefix="pet-memory-")
    runtime.memory = MemoryStore(Path(temporary.name) / "memory.json")
    try:
        source = "记住，我喜欢喝绿茶。"
        samples, rate = runtime.audio.synthesize(source, 0, 1.0, "fast")
        # 输入层固定 16 kHz；虚拟麦克风按真实采样率提供浮点音频。
        converted = np.interp(
            np.arange(int(len(samples) * 16000 / rate)) * rate / 16000, np.arange(len(samples)), samples
        ).astype(np.float32)
        runtime.ask(settings, "", kind="voice", samples=converted)
        assert finished.wait(90), "语音闭环超时"
        report["recognized"] = heard
        report["first_reply"] = replies[-1] if replies else ""
        report["saved_memory"] = runtime.memory.read()
        report["synthesized_playback"] = playback
        runtime.cancel(release=True).result(15)
        # 丢弃进程和短期上下文，重新从文件读取验证长期记忆。
        runtime.history.clear()
        runtime.memory = MemoryStore(runtime.memory.path)
        finished.clear()
        runtime.ask(replace(settings, speak_replies=False), "我喜欢喝什么？")
        assert finished.wait(60), "重载记忆超时"
        report["recalled_after_reload"] = replies[-1]
        report["memory_roundtrip_passed"] = "绿茶" in report["saved_memory"] and "绿茶" in replies[-1]
        report["voice_roundtrip_passed"] = bool(heard and playback and playback[0]["samples"] > 0)
        report["states"] = states
    finally:
        runtime.cancel(release=True).result(15)
        runtime.loop.call_soon_threadsafe(runtime.loop.stop)
        runtime.thread.join(2)
        temporary.cleanup()
    target = ROOT / "data/verification/conversation-report.json"
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
