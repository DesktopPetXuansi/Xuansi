"""整句识别保留完整波形和边界上下文；真实误识别波形另作模型复验。"""

from types import SimpleNamespace

import numpy as np
import pytest

from pet.audio_models import AudioModels


@pytest.mark.parametrize("rate", [16000, 48000])
def test_abrupt_utterance_has_context_without_losing_initial_syllable(rate):
    """直接送入短句也应提供静音上下文，且不裁剪、不改写输入音频。"""
    source = np.linspace(0.1, 0.2, rate // 2, dtype=np.float32)
    original = source.copy()
    captured = []
    stream = SimpleNamespace(
        accept_waveform=lambda sr, data: captured.append((sr, data.copy())),
        result=SimpleNamespace(text="记住我喜欢喝绿茶"),
    )
    audio = AudioModels()
    audio.recognizer = SimpleNamespace(create_stream=lambda: stream, decode_stream=lambda _: None)

    assert audio.transcribe(source, rate) == "记住我喜欢喝绿茶"
    sr, waveform = captured[0]
    voiced = np.flatnonzero(waveform)
    assert sr == rate and voiced[0] >= rate * 0.1
    assert len(waveform) - voiced[-1] - 1 >= rate * 0.3
    np.testing.assert_array_equal(waveform[voiced[0]:voiced[-1] + 1], original)
    np.testing.assert_array_equal(source, original)


def test_empty_input_cannot_hallucinate_a_memory_command(monkeypatch):
    """没有音频时不调用识别器，防止模型在空波形上生成误导指令。"""
    audio = AudioModels()

    def unexpected_load():
        raise AssertionError("空输入不应加载识别模型")

    monkeypatch.setattr(audio, "_load_asr", unexpected_load)
    assert audio.transcribe(np.empty(0, dtype=np.float32)) == ""
    assert audio.recognizer is None
