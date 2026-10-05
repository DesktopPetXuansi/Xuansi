"""真实模型理解语音、记忆及指代；合成输入与临时存储，不使用物理声卡。"""

import argparse
import asyncio
import json
import logging
import sys
import tempfile
from dataclasses import replace
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pet.audio_models import AudioModels
from pet.config import DATA, Settings
from pet.inference import LocalEngine
from pet.memory import MemoryStore, durable_io
from pet.speech_control import ControlCallbacks

LOG = logging.getLogger(__name__)
PREFERENCE = [
    {"role": "user", "content": "我喜欢喝绿茶。"},
    {"role": "assistant", "content": "好的，这个偏好要保存为长期记忆吗？"},
]
CASES = [
    ("明确记忆", "记住，我喜欢喝绿茶。", [], True, "绿茶"),
    ("自然表达", "帮我把我喜欢喝绿茶这件事保存下来，以后推荐时记得。", [], True, "绿茶"),
    ("指代事项", "把刚才那个口味偏好记下来。", PREFERENCE, True, "绿茶"),
    ("确认保存", "对，保存下来吧。", PREFERENCE, True, "绿茶"),
    ("指代多事项", "把刚才这些都帮我记住。", [
        {"role": "user", "content": "我喜欢喝绿茶，希望你回复简短一些。"},
        {"role": "assistant", "content": "好的，你喜欢绿茶，也偏好简短的回复。"},
    ], True, ("绿茶", "简短")),
    ("普通偏好", "我喜欢喝绿茶。", [], True, None),
    ("普通称呼", "店主我喜欢喝绿茶。", [], True, None),
    ("否定保存", "不要记住我喜欢喝绿茶。", [], True, None),
    ("引用翻译", "把‘记住我喜欢喝绿茶’翻译成英文。", [], True, None),
    ("假设记忆", "如果我说记住我喜欢喝绿茶，你会怎么办？", [], True, None),
    ("过去请求", "昨天我让你记住我喜欢喝绿茶，你还记得吗？", [], True, None),
    ("拒绝指代", "不用保存，继续聊吧。", PREFERENCE, True, None),
    ("模糊转写", "地重我喜欢喝绿茶", [], True, None),
    ("静音普通聊天", "今天工作有点累。", [], False, None),
]


def verify_audio(report, reproduction):
    audio = AudioModels()
    try:
        for speed in (0.85, 1.0, 1.08):
            samples, rate = audio.synthesize("记住，我喜欢喝绿茶。", 0, speed)
            source = np.interp(np.arange(int(len(samples) * 16000 / rate)) * rate / 16000,
                               np.arange(len(samples)), samples).astype(np.float32)
            for peak in (None, 0.006):
                waveform = source if peak is None else source * (peak / float(np.max(np.abs(source))))
                text = audio.transcribe(waveform)
                entry = {"speed": speed, "quiet": peak is not None, "recognized": text,
                         "source": "记住，我喜欢喝绿茶。", "expected_save": True,
                         "asr_exact": text.startswith("记住") and "绿茶" in text}
                report["audio"].append(entry)
                LOG.info("短句识别 speed=%s quiet=%s exact=%s", speed, peak is not None, entry["asr_exact"])
        if reproduction is not None:
            # 重用失败波形，避免重新合成的随机差异掩盖旧问题。
            with np.load(reproduction) as originals:
                for name in ("failed_2", "failed_3"):
                    text = audio.transcribe(originals[name])
                    report["audio"].append({
                        "speed": "原始失败波形 " + name, "quiet": name == "failed_2", "recognized": text,
                        "source": "记住，我喜欢喝绿茶。", "expected_save": True,
                        "asr_exact": text.startswith("记住") and "绿茶" in text,
                    })
        for source_text in ("我喜欢喝绿茶。", "不要记住我喜欢喝绿茶。"):
            samples, rate = audio.synthesize(source_text, 0, 1.0)
            text = audio.transcribe(samples, rate)
            report["audio"].append({
                "source": source_text, "speed": 1.0, "quiet": False, "recognized": text,
                "expected_save": False, "asr_exact": None,
            })
    finally:
        audio.unload()


async def verify_audio_roundtrip(engine, settings, report, temporary):
    """按已知原始语音意图验收；错字不等于含糊，模型理解不依赖固定口令。"""
    for index, entry in enumerate(report["audio"]):
        memory = MemoryStore(Path(temporary) / f"voice-memory-{index}.json")

        async def remember(note):
            await durable_io(memory.remember, note)

        controls = ControlCallbacks(lambda _: None, lambda _: None, (), remember)
        text = entry["recognized"]
        answer = await engine.chat(settings, text, [], [], on_speech=controls)
        saved_before_confirmation = memory.read()
        entry["first_reply"] = answer
        if not entry["expected_save"]:
            entry["saved_after_reload"] = MemoryStore(memory.path).read()
            entry["passed"] = not entry["saved_after_reload"]
            LOG.info("非授权语音写入检查 passed=%s", entry["passed"])
            continue
        needs_confirmation = not saved_before_confirmation
        entry["needs_confirmation"] = needs_confirmation
        if needs_confirmation:
            # 检查实际回复询问保存，不以“未保存”代替必要的确认提示。
            entry["clarification_asked"] = (
                any(word in answer for word in ("保存", "记住", "记下", "长期记忆"))
                and any(word in answer for word in ("吗", "是否", "要不要", "是不是", "呢"))
            )
            entry["confirmed_reply"] = await engine.chat(
                settings, "对，请保存下来。", [], [
                    {"role": "user", "content": text}, {"role": "assistant", "content": answer},
                ], on_speech=controls,
            )
        reloaded = MemoryStore(memory.path).read()
        entry["saved_after_reload"] = reloaded
        entry["passed"] = (
            "绿茶" in reloaded
            and (not needs_confirmation or entry.get("clarification_asked", False))
        )
        LOG.info("语音记忆闭环 speed=%s quiet=%s confirmation=%s passed=%s",
                 entry["speed"], entry["quiet"], needs_confirmation, entry["passed"])


async def verify_model(report, temporary):
    engine = LocalEngine()
    settings = replace(Settings(), observe=False, max_tokens=90)
    try:
        await verify_audio_roundtrip(engine, settings, report, temporary)
        for index, (label, text, history, enabled, expected) in enumerate(CASES):
            changes, written, chunks = [], [], []
            memory = MemoryStore(Path(temporary) / f"memory-{index}.json")

            async def remember(note):
                await durable_io(memory.remember, note)
                written.append(note)

            async def receive(part):
                chunks.append(part)

            answer = await engine.chat(
                settings, text, [], history, on_chunk=receive,
                on_speech=ControlCallbacks(changes.append, lambda _: None, (), remember),
                speech_enabled=enabled,
            )
            reloaded = MemoryStore(memory.path).read()
            expected_terms = (expected,) if isinstance(expected, str) else expected
            expected_memory = bool(reloaded and all(term in reloaded for term in expected_terms)) \
                if expected_terms else not reloaded
            entry = {"case": label, "input": text, "changes": changes, "written": written,
                     "saved_after_reload": reloaded, "answer": answer,
                     "passed": expected_memory and len(written) == (1 if expected else 0)
                     and not changes and answer == "".join(chunks).strip() and "[voice:" not in answer}
            report["memory"].append(entry)
            LOG.info("记忆理解 case=%s passed=%s", label, entry["passed"])

        for text in ("你好喜出生用一句话介绍一下自己", "今天工作有点累", "记住我喜欢喝绿茶"):
            for trial in range(5):
                changes = []
                answer = await engine.chat(settings, text, [], [], on_speech=changes.append, speech_enabled=True)
                entry = {"input": text, "trial": trial, "changes": changes,
                         "answer": answer, "passed": not changes and bool(answer)}
                report["speech"].append(entry)
                LOG.info("误静音复验 trial=%d passed=%s", trial, entry["passed"])
    finally:
        await engine.stop()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repro-audio", type=Path, help="本地合成失败波形 NPZ，用相同输入复验")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    output = DATA / "verification/voice-reliability-report.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    report = {"device": "合成音频、真实 ASR/LLM、临时记忆；无物理麦克风或扬声器",
              "reply_temperature": Settings().temperature, "control_temperature": 0.0,
              "audio": [], "memory": [], "speech": [], "passed": False}
    try:
        verify_audio(report, args.repro_audio)
        with tempfile.TemporaryDirectory(prefix="voice-reliability-") as temporary:
            asyncio.run(verify_model(report, temporary))
        report["passed"] = all(item["passed"] for group in ("audio", "memory", "speech") for item in report[group])
    finally:
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False), flush=True)
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
