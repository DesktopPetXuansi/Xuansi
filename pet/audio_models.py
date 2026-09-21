"""离线语音模型；只在工作线程使用 ONNX，会话数据仅驻留内存。"""

import logging
import re
import threading
import time

import numpy as np
import sherpa_onnx

from .config import MODELS

LOG = logging.getLogger(__name__)
_CJK_TEXT = re.compile(r"[\u3400-\u9fff]")
_LATIN_WORD = re.compile(r"[A-Za-z]+")


def select_tts_engine(text: str, requested: str):
    """让纯英文默认使用带 G2P 的 Kokoro，避免 Melo 词典外单词按字母处理。"""
    if requested != "fast" or _CJK_TEXT.search(text):
        return requested
    return "natural" if len("".join(_LATIN_WORD.findall(text))) >= 2 else requested


class AudioModels:
    def __init__(self):
        self.recognizer = None
        self.tts = None
        self.tts_engine = ""
        self.lock = threading.Lock()

    def _load_asr(self):
        root = MODELS / "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2025-09-09"
        models = list(root.glob("*int8.onnx")) or list(root.glob("*.onnx"))
        if not models:
            raise RuntimeError("语音识别模型尚未安装完成。")
        self.recognizer = sherpa_onnx.OfflineRecognizer.from_sense_voice(
            model=str(models[0]),
            tokens=str(root / "tokens.txt"),
            num_threads=2,
            language="auto",
            use_itn=True,
            provider="cpu",
        )
        LOG.info("本地语音识别就绪")

    def transcribe(self, samples: np.ndarray, sample_rate=16000):
        with self.lock:
            if self.recognizer is None:
                self._load_asr()
            started = time.monotonic()
            stream = self.recognizer.create_stream()
            stream.accept_waveform(sample_rate, samples)
            self.recognizer.decode_stream(stream)
            text = re.sub(r"<\|.*?\|>", "", stream.result.text).strip()
            LOG.info(
                "识别完成 audio=%.2fs elapsed=%.2fs", len(samples) / sample_rate, time.monotonic() - started
            )
            return text

    def prepare_recognition(self):
        with self.lock:
            if self.recognizer is None:
                self._load_asr()

    def _load_fast_tts(self):
        root = MODELS / "vits-melo-tts-zh_en"
        config = sherpa_onnx.OfflineTtsConfig(
            model=sherpa_onnx.OfflineTtsModelConfig(
                vits=sherpa_onnx.OfflineTtsVitsModelConfig(
                    model=str(root / "model.onnx"),
                    lexicon=str(root / "lexicon.txt"),
                    tokens=str(root / "tokens.txt"),
                ),
                num_threads=4,
                provider="cpu",
            ),
            rule_fsts=",".join(str(root / name) for name in ("phone.fst", "date.fst", "number.fst")),
        )
        if not config.validate():
            raise RuntimeError("轻量中文语音模型尚未安装完成。")
        self.tts = sherpa_onnx.OfflineTts(config)
        LOG.info("Melo 本地中英语音就绪")

    def _load_tts(self):
        root = MODELS / "kokoro-int8-multi-lang-v1_1"
        models = list(root.glob("*int8.onnx")) or list(root.glob("*.onnx"))
        if not models:
            raise RuntimeError("语音合成模型尚未安装完成。")
        config = sherpa_onnx.OfflineTtsConfig(
            model=sherpa_onnx.OfflineTtsModelConfig(
                kokoro=sherpa_onnx.OfflineTtsKokoroModelConfig(
                    model=str(models[0]),
                    voices=str(root / "voices.bin"),
                    tokens=str(root / "tokens.txt"),
                    data_dir=str(root / "espeak-ng-data"),
                    lexicon=",".join(str(root / name) for name in ("lexicon-us-en.txt", "lexicon-zh.txt")),
                    lang="",
                ),
                num_threads=2,
                debug=False,
                provider="cpu",
            ),
            rule_fsts=",".join(str(root / name) for name in ("date-zh.fst", "number-zh.fst", "phone-zh.fst")),
            max_num_sentences=1,
        )
        if not config.validate():
            raise RuntimeError("语音合成配置不完整。")
        self.tts = sherpa_onnx.OfflineTts(config)
        LOG.info("本地语音合成就绪 speakers=%d", self.tts.num_speakers)

    def synthesize(self, text: str, speaker: int, speed: float, engine="fast"):
        with self.lock:
            # 去除 Markdown 装饰，保留加粗/斜体中的正文，避免整句变成静音。
            clean = re.sub(r"[`#*_]", "", text).strip()[:240]
            if not clean:
                return np.empty(0, dtype=np.float32), 24000
            selected_engine = select_tts_engine(clean, engine)
            automatic_english = engine == "fast" and selected_engine == "natural"
            if self.tts is None or selected_engine != self.tts_engine:
                self.tts = None
                try:
                    self._load_fast_tts() if selected_engine == "fast" else self._load_tts()
                except Exception as exc:
                    if not automatic_english:
                        raise
                    # 可选 Kokoro 缺失时保留原有 Melo 朗读能力，并记录可诊断原因。
                    LOG.warning("英文 G2P 语音不可用，回退 Melo type=%s", type(exc).__name__)
                    self._load_fast_tts()
                    selected_engine = "fast"
                self.tts_engine = selected_engine
                if automatic_english and selected_engine == "natural":
                    LOG.info("纯英文回复自动使用 Kokoro G2P 语音")
            started = time.monotonic()
            result = self.tts.generate(clean, sid=speaker, speed=speed)
            LOG.info(
                "合成完成 audio=%.2fs elapsed=%.2fs",
                len(result.samples) / result.sample_rate,
                time.monotonic() - started,
            )
            return np.asarray(result.samples, dtype=np.float32), result.sample_rate

    def unload(self):
        with self.lock:
            self.recognizer = self.tts = None
        LOG.info("语音模型已释放")
