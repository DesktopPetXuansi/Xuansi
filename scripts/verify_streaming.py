"""真实本机模型与分段 TTS 验收；合成资料、临时记忆和静音播放接收器。"""

import json
import logging
import sys
import tempfile
import threading
import time
from dataclasses import replace
from pathlib import Path

import numpy as np
import soundfile as sf
from PySide6.QtCore import Qt

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pet.runtime as module
from pet.config import ROOT, Settings
from pet.memory import MemoryStore
from pet.runtime import Runtime

LOG = logging.getLogger(__name__)


def main():
    output = ROOT / "data/verification"
    output.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    runtime = Runtime()
    runtime.audio_activity.clock = lambda: 10.0
    runtime.audio_activity.update(False, now=10.0)
    temporary = tempfile.TemporaryDirectory(prefix="xuansi-stream-")
    runtime.memory = MemoryStore(Path(temporary.name) / "memory.json")
    settings = replace(Settings(), observe=False, max_tokens=300)
    clips, replies, states = [], [], []
    finished = threading.Event()
    runtime.finished.connect(lambda _: finished.set(), Qt.ConnectionType.DirectConnection)
    runtime.reply.connect(
        lambda _, text, kind: replies.append((time.monotonic(), text)), Qt.ConnectionType.DirectConnection
    )
    runtime.state.connect(lambda _, text: states.append(text), Qt.ConnectionType.DirectConnection)
    module.sd.play = lambda data, rate: clips.append((time.monotonic(), np.copy(data), rate))
    module.sd.wait = lambda: None
    module.sd.stop = lambda: None
    report = {
        "sink": "静音测试接收器；实际模型合成音频，没有启麦或读取工作屏幕",
        "runs": [],
        "passed": False,
    }
    try:
        for mode in ("cold", "warm"):
            clips.clear()
            replies.clear()
            states.clear()
            finished.clear()
            runtime.history.clear()
            started = time.monotonic()
            runtime.ask(
                settings,
                "请先原样说“你好，我是玄司。”然后分别用一句话给出整理桌面、休息眼睛、"
                "保存工作的建议。只写可直接朗读的正文，不用标题，全文约一百字。",
            )
            if not finished.wait(150):
                raise RuntimeError("真实流式语音验收超时")
            if not clips or not replies:
                raise RuntimeError("没有得到完整文本或音频片段：" + str(states[-2:]))
            end, answer = replies[-1]
            entry = {
                "mode": mode,
                "first_text_seconds": runtime.engine.stats.get("first_text_seconds"),
                "first_audio_seconds": round(clips[0][0] - started, 3),
                "text_complete_seconds": round(end - started, 3),
                "all_audio_seconds": round(time.monotonic() - started, 3),
                "first_audio_before_text_complete": clips[0][0] < end,
                "audio_parts": len(clips),
                "answer": answer,
                "history_complete": runtime.history[-1]["content"] == answer,
                "streaming_state_visible": "正在流式朗读…" in states,
                "rates": sorted({rate for _, _, rate in clips}),
            }
            report["runs"].append(entry)
            assert entry["rates"] == [44100]
            assert entry["history_complete"] and entry["streaming_state_visible"]
            assert entry["audio_parts"] >= 2
            if mode == "warm":
                assert entry["first_audio_before_text_complete"], "热启动首段没有早于文本结束"
            audio = np.concatenate([samples for _, samples, _ in clips])
            sf.write(output / f"streaming-{mode}.wav", audio, 44100)
            entry["generated_audio_seconds"] = round(len(audio) / 44100, 3)
            LOG.info(
                "流式验收 %s first_audio=%.3fs text_complete=%.3fs parts=%d",
                mode,
                entry["first_audio_seconds"],
                entry["text_complete_seconds"],
                entry["audio_parts"],
            )
    finally:
        runtime.cancel(release=True).result(20)
        runtime.loop.call_soon_threadsafe(runtime.loop.stop)
        runtime.thread.join(3)
        temporary.cleanup()
        # 失败也留下真实结果，不能只保存成功样例。
        (output / "streaming-report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    report["passed"] = True
    (output / "streaming-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
