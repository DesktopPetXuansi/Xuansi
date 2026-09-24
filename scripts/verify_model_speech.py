"""真实本地模型语义及 TTS 验收：仅合成对话、临时记忆和静音播放接收器。"""

import json
import logging
import sys
import tempfile
import time
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import Qt

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pet.config import ROOT, Settings
from pet.memory import MemoryStore
from pet.runtime import Runtime

LOG = logging.getLogger(__name__)
CASES = [
    ("直接关闭", "你先不要说话了。", True, [False]),
    ("委婉关闭", "我正在开会，你用文字陪我就好。", True, [False]),
    ("环境意图", "旁边有人睡着了，我们打字聊。", True, [False]),
    ("恢复", "现在可以出声了，我想听听你的声音。", False, [True]),
    ("否定停止", "别停，我还在听。", False, [True]),
    ("否定关闭", "不要关闭语音，我还想听你说。", True, [True]),
    ("翻译引用", "翻译这句话：请不要说话。", True, []),
    ("指定翻译", "把‘请不要说话’翻译成英文。", True, []),
    ("谈论他人", "帮我写一句提醒同事不要说话的标语。", True, []),
    ("假设", "如果我说别出声，你会怎么做？", True, []),
    ("询问方法", "语音功能要怎么关闭？", True, []),
    ("静音中普通聊天", "继续解释刚才的问题。", False, []),
]


async def verify(runtime, report):
    settings = replace(Settings(), observe=False, max_tokens=100)
    for label, text, enabled, expected in CASES:
        changes, chunks = [], []

        async def receive(part):
            chunks.append(part)

        answer = await runtime.engine.chat(
            replace(settings, temperature=0.0), text, [], [], on_chunk=receive,
            on_speech=changes.append, speech_enabled=enabled,
        )
        entry = {
            "case": label, "input": text, "changes": changes, "expected": expected, "answer": answer,
            "passed": changes == expected and answer == "".join(chunks).strip() and "[voice:" not in answer,
            "first_text_seconds": runtime.engine.stats.get("first_text_seconds"),
        }
        report["semantics"].append(entry)
        LOG.info("语义验收 case=%s passed=%s", label, entry["passed"])

    # 必须结合前文理解“现在可以了”，不能靠本句的开关词。
    changes = []
    answer = await runtime.engine.chat(
        replace(settings, temperature=0.0), "现在可以了。", [], [
            {"role": "user", "content": "先不要出声，等我说现在可以了，你再恢复语音。"},
            {"role": "assistant", "content": "好的，我先安静地用文字陪你。"},
        ], on_speech=changes.append, speech_enabled=False,
    )
    report["semantics"].append({
        "case": "上下文指代", "changes": changes, "answer": answer, "passed": changes == [True],
    })

    clips, replies, states = [], [], []
    runtime.reply.connect(lambda _, text, kind: replies.append(text), Qt.ConnectionType.DirectConnection)
    runtime.state.connect(lambda _, text: states.append(text), Qt.ConnectionType.DirectConnection)
    runtime.listening = True  # 仅模拟已开麦状态，绝不调用 start 打开真实输入设备。
    with patch("pet.runtime.sd.play", lambda data, rate: clips.append((len(data), rate))), \
            patch("pet.runtime.sd.wait", lambda: None), patch("pet.runtime.sd.stop", lambda: None):
        for text, expected in [
            ("我在开会，接下来请只用文字回复。", False),
            ("给我一句简短的工作鼓励。", False),
            ("会议结束了，恢复语音和我聊吧。", True),
        ]:
            clips.clear()
            replies.clear()
            runtime.epoch += 1
            started = time.monotonic()
            await runtime._conversation(runtime.epoch, settings, text, "voice-final", None, None)
            entry = {
                "input": text, "enabled": runtime.should_speak(settings), "expected": expected,
                "clips": len(clips), "sample_rates": sorted({rate for _, rate in clips}),
                "answer": replies[-1] if replies else "", "seconds": round(time.monotonic() - started, 3),
                "microphone_kept": runtime.listening and not runtime.microphone.muted.is_set(),
            }
            entry["passed"] = (
                entry["enabled"] == expected and bool(clips) == expected and bool(replies)
                and entry["microphone_kept"] and runtime.microphone_epoch == 0
            )
            report["runtime"].append(entry)
            LOG.info("真实语音链路 enabled=%s clips=%d passed=%s", entry["enabled"], len(clips), entry["passed"])
    report["passed"] = all(item["passed"] for item in report["semantics"] + report["runtime"])


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    output = ROOT / "data/verification/model-speech-report.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "sink": "真实本机模型和 TTS，静音接收器；不启麦、不截图、不读写用户记忆或偏好",
        "semantics_temperature": 0.0, "runtime_temperature": Settings().temperature,
        "semantics": [], "runtime": [], "passed": False,
    }
    runtime = Runtime()
    runtime.audio_activity.set_enabled(False)
    with tempfile.TemporaryDirectory(prefix="xuansi-model-speech-") as temporary:
        runtime.memory = MemoryStore(Path(temporary) / "memory.json")
        try:
            runtime.schedule(verify(runtime, report)).result(180)
        finally:
            runtime.listening = False
            runtime.cancel(release=True).result(20)
            runtime.loop.call_soon_threadsafe(runtime.loop.stop)
            runtime.thread.join(3)
            output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False), flush=True)
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
