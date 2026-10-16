"""声卡错误与格式化回复回归；不加载模型、不接触真实音频设备。"""

from types import SimpleNamespace

import numpy as np
import pytest

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


@pytest.mark.parametrize("text", ["😊", "无需回应", "普通文字"])
def test_empty_tts_result_keeps_input_and_does_not_divide_by_zero(text):
    spoken = []
    models = AudioModels()

    def generate(value, sid, speed):
        spoken.append(value)
        return SimpleNamespace(samples=np.empty(0), sample_rate=0)

    models.tts = SimpleNamespace(generate=generate)
    models.tts_engine = "fast"
    samples, _ = models.synthesize(text, 0, 1.0)
    assert len(samples) == 0
    assert spoken == [text]  # 依据真实空波形处理，不能按正文字符过滤。


def test_nonempty_tts_result_with_invalid_rate_is_reported():
    models = AudioModels()
    models.tts = SimpleNamespace(generate=lambda *_args, **_kwargs: SimpleNamespace(
        samples=np.zeros(10), sample_rate=0,
    ))
    models.tts_engine = "fast"
    with pytest.raises(RuntimeError, match="采样率"):
        models.synthesize("你好", 0, 1.0)


def test_synthesis_selection_does_not_guess_language_from_text():
    assert select_tts_engine("Hello, how are you?", "fast") == "fast"
    assert select_tts_engine("OpenAI can help.", "fast") == "fast"
    assert select_tts_engine("你好", "natural") == "natural"


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
    models.synthesize_selected("An unknown English word.", 46, 1.0, "fast", "natural")
    assert models.tts_engine == "natural"
    assert spoken == [("An unknown English word.", 46, 1.0)]


def test_automatic_model_selection_can_fall_back_but_explicit_choice_cannot(monkeypatch, caplog):
    models = AudioModels()
    attempts = []

    def missing_natural():
        attempts.append("natural")
        raise RuntimeError("语音合成模型尚未安装完成。")

    def load_fast():
        attempts.append("fast")
        models.tts = SimpleNamespace(generate=lambda *_args, **_kwargs: SimpleNamespace(
            samples=np.zeros(1), sample_rate=24000,
        ))

    monkeypatch.setattr(models, "_load_tts", missing_natural)
    monkeypatch.setattr(models, "_load_fast_tts", load_fast)
    samples, rate = models.synthesize_selected("Hello", 0, 1.0, "fast", "natural")
    assert len(samples) == 1 and rate == 24000
    assert attempts == ["natural", "fast"]
    assert "回退" in caplog.text
    attempts.clear()
    with pytest.raises(RuntimeError, match="尚未安装"):
        models.synthesize_selected("Hello", 0, 1.0, "natural", "natural")
    assert attempts == ["natural"]


@pytest.mark.parametrize("error_type", [RuntimeError, IndexError])
def test_loaded_natural_generation_errors_are_not_hidden_by_fallback(monkeypatch, caplog, error_type):
    models = AudioModels()

    def broken_generate(*_args, **_kwargs):
        raise error_type("合成阶段错误")

    def unexpected_fallback():
        pytest.fail("已加载模型的生成错误不能静默回退")

    models.tts = SimpleNamespace(generate=broken_generate)
    models.tts_engine = "natural"
    monkeypatch.setattr(models, "_load_fast_tts", unexpected_fallback)
    with pytest.raises(error_type, match="合成阶段错误"):
        models.synthesize_selected("Hello", 0, 1.0, "fast", "natural")
    assert "回退" not in caplog.text


def test_microphone_error_is_not_overwritten_by_closed_status(monkeypatch):
    states = []

    def unavailable(**_):
        raise ValueError("test device unavailable")

    monkeypatch.setattr("pet.microphone.sd.InputStream", unavailable)
    microphone = Microphone(lambda _: None, states.append)
    microphone._run(-1)
    assert len(states) == 1
    assert states[0].startswith("麦克风无法开启")
