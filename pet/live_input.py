"""边说边识别，但只在用户停顿后提交；部分文字仅用于界面预览。"""

import logging
from dataclasses import dataclass

import numpy as np
import sherpa_onnx

from .config import MODELS

LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class VoiceUpdate:
    turn: int
    text: str
    final: bool = False


class PartialTurn:
    def __init__(self):
        self.turn = 0

    def update(self, text, final=False):
        result = VoiceUpdate(self.turn, text, final)
        if final:
            self.turn += 1
        return result


class OnlineInput:
    def __init__(self, emit):
        root = MODELS / "streaming-paraformer"
        if not all((root / name).is_file() for name in ("tokens.txt", "encoder.int8.onnx", "decoder.int8.onnx")):
            raise RuntimeError("实时识别模型未安装，请运行 scripts/download_realtime.py。")
        self.recognizer = sherpa_onnx.OnlineRecognizer.from_paraformer(
            tokens=str(root / "tokens.txt"), encoder=str(root / "encoder.int8.onnx"),
            decoder=str(root / "decoder.int8.onnx"), num_threads=2, provider="cpu",
        )
        self.emit = emit
        self.turn = PartialTurn()
        self.stream = self.recognizer.create_stream()
        self.silence = self.elapsed = 0.0
        self.voiced = False
        self.last_text = ""
        LOG.info("在线 Paraformer 就绪 threads=2")

    def _decode(self, samples, rate):
        self.stream.accept_waveform(rate, samples)
        while self.recognizer.is_ready(self.stream):
            self.recognizer.decode_stream(self.stream)
        return self.recognizer.get_result(self.stream).strip()

    def reset(self):
        if self.elapsed or self.last_text:
            # 仅在实际丢弃了一段输入时重置，静音循环不重复创建 ONNX 流。
            self.stream = self.recognizer.create_stream()
            self.silence = self.elapsed = 0.0
            self.voiced = False
            self.last_text = ""

    def feed(self, samples, rate=48000):
        duration = len(samples) / rate
        self.elapsed += duration
        rms = float(np.sqrt(np.mean(samples * samples)))
        if rms > 0.008:
            self.voiced = True
            self.silence = 0.0
        else:
            self.silence += duration
        text = self._decode(samples, rate)
        endpoint = self.voiced and self.silence >= 0.35
        if endpoint:
            # Paraformer 有前瞻窗口；补尾部静音才能取到最后几个字。
            text = self._decode(np.zeros(int(rate * 0.6), dtype=np.float32), rate)
            text = text[-2000:]
            self.emit(self.turn.update(text, final=True))
            self.stream = self.recognizer.create_stream()
            self.silence = self.elapsed = 0.0
            self.voiced = False
            self.last_text = ""
            LOG.info("实时话段结束 chars=%d", len(text))
        else:
            combined = text[-2000:]
            if combined and combined != self.last_text:
                self.emit(self.turn.update(combined))
                self.last_text = combined
            if self.elapsed >= 15 and not self.voiced:
                # 空闲时释放识别缓存；用户仍在说话就继续听，不强制截断。
                self.reset()
