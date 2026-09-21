"""声卡错误与格式化回复回归；不加载模型、不接触真实音频设备。"""

from types import SimpleNamespace

import numpy as np

from pet.audio_models import AudioModels, select_tts_engine
from pet.microphone import Microphone


def test_formatted_reply_still_has_spoken_content():
    spoken = []

    def generate(text, sid, speed):
        spoken.append(text)
        return SimpleNamespace(samples=np.zeros(10, dtype=np.float32), sample_rate=44100)

    models = AudioModels()
    models.tts = SimpleNamespace(generate=generate)
    models.tts_engine = "fast"
    models.synthesize("**你好**，我在这里。", 0, 1.0)
    assert spoken == ["你好，我在这里。"]


def test_pure_english_reply_uses_g2p_voice_engine():
    assert select_tts_engine("Hello, how are you?", "fast") == "natural"
    assert select_tts_engine("OpenAI can help.", "fast") == "natural"


def test_chinese_or_explicit_voice_choice_is_preserved():
    assert select_tts_engine("你好，AI 助手。", "fast") == "fast"
    assert select_tts_engine("Hello, how are you?", "natural") == "natural"


def test_english_synthesis_switches_to_g2p_model(monkeypatch):
    spoken = []
    models = AudioModels()

    def generate(text, sid, speed):
        spoken.append((text, sid, speed))
        return SimpleNamespace(samples=np.zeros(10, dtype=np.float32), sample_rate=24000)

    def load_natural():
        models.tts = SimpleNamespace(generate=generate)

    monkeypatch.setattr(models, "_load_tts", load_natural)
    models.synthesize("An unknown English word.", 46, 1.0, "fast")
    assert models.tts_engine == "natural"
    assert spoken == [("An unknown English word.", 46, 1.0)]


def test_microphone_error_is_not_overwritten_by_closed_status(monkeypatch):
    states = []

    def unavailable(**_):
        raise ValueError("test device unavailable")

    monkeypatch.setattr("pet.microphone.sd.InputStream", unavailable)
    microphone = Microphone(lambda _: None, states.append)
    microphone._run(-1)
    assert len(states) == 1
    assert states[0].startswith("麦克风无法开启")
