"""用合成的已知中文做 TTS→ASR 闭环；不打开麦克风、不播放声音。"""

import json
import sys
import time
from pathlib import Path

import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pet.audio_models import AudioModels
from pet.config import ROOT, Settings


def main():
    settings = Settings()
    output = ROOT / "data/verification"
    output.mkdir(parents=True, exist_ok=True)
    previous = output / "audio-report.json"
    baseline = output / "audio-aishell3-baseline.json"
    if previous.exists() and not baseline.exists():
        baseline.write_bytes(previous.read_bytes())
    models = AudioModels()
    source = "你好，我是糯米。我会在这里陪着你。"
    report = {"source": source}
    try:
        started = time.monotonic()
        samples, rate = models.synthesize(source, settings.speaker, settings.speed, settings.tts_engine)
        report["tts_cold_seconds"] = round(time.monotonic() - started, 2)
        report["sample_rate"] = rate
        report["audio_seconds"] = round(len(samples) / rate, 2)
        sf.write(output / "voice-fast.wav", samples, rate)
        started = time.monotonic()
        models.synthesize(source, settings.speaker, settings.speed, settings.tts_engine)
        report["tts_warm_seconds"] = round(time.monotonic() - started, 2)
        started = time.monotonic()
        report["recognized"] = models.transcribe(samples, rate)
        report["asr_cold_seconds"] = round(time.monotonic() - started, 2)
        started = time.monotonic()
        models.transcribe(samples, rate)
        report["asr_warm_seconds"] = round(time.monotonic() - started, 2)
        report["recognizes_name_and_intent"] = all(word in report["recognized"] for word in ("糯米", "陪"))
    finally:
        models.unload()
    (output / "audio-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
