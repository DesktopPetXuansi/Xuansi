"""离线语音模型；只在工作线程使用 ONNX，会话数据仅驻留内存。"""
import logging
import re
import threading
import time
import numpy as np
import sherpa_onnx
from .config import MODELS

LOG = logging.getLogger(__name__)


class AudioModels:
    def __init__(self):
        self.recognizer = None
        self.tts = None
        self.lock = threading.Lock()

    def _load_asr(self):
        root = MODELS/'sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2025-09-09'
        models = list(root.glob('*int8.onnx')) or list(root.glob('*.onnx'))
        if not models:
            raise RuntimeError('语音识别模型尚未安装完成。')
        self.recognizer = sherpa_onnx.OfflineRecognizer.from_sense_voice(
            model=str(models[0]), tokens=str(root/'tokens.txt'), num_threads=2,
            language='auto', use_itn=True, provider='cpu')
        LOG.info('本地语音识别就绪')

    def transcribe(self, samples: np.ndarray, sample_rate=16000):
        with self.lock:
            if self.recognizer is None:
                self._load_asr()
            started = time.monotonic()
            stream = self.recognizer.create_stream()
            stream.accept_waveform(sample_rate, samples)
            self.recognizer.decode_stream(stream)
            text = re.sub(r'<\|.*?\|>', '', stream.result.text).strip()
            LOG.info('识别完成 audio=%.2fs elapsed=%.2fs', len(samples)/sample_rate, time.monotonic()-started)
            return text

    def _load_tts(self):
        root = MODELS/'kokoro-int8-multi-lang-v1_1'
        models = list(root.glob('*int8.onnx')) or list(root.glob('*.onnx'))
        if not models:
            raise RuntimeError('语音合成模型尚未安装完成。')
        config = sherpa_onnx.OfflineTtsConfig(
            model=sherpa_onnx.OfflineTtsModelConfig(
                kokoro=sherpa_onnx.OfflineTtsKokoroModelConfig(
                    model=str(models[0]), voices=str(root/'voices.bin'), tokens=str(root/'tokens.txt'),
                    data_dir=str(root/'espeak-ng-data'), dict_dir=str(root/'dict'),
                    lexicon=','.join(str(root/name) for name in ('lexicon-us-en.txt', 'lexicon-zh.txt')), lang=''),
                num_threads=2, debug=False, provider='cpu'),
            rule_fsts=','.join(str(root/name) for name in ('date-zh.fst', 'number-zh.fst', 'phone-zh.fst')),
            max_num_sentences=1)
        if not config.validate():
            raise RuntimeError('语音合成配置不完整。')
        self.tts = sherpa_onnx.OfflineTts(config)
        LOG.info('本地语音合成就绪 speakers=%d', self.tts.num_speakers)

    def synthesize(self, text: str, speaker: int, speed: float):
        with self.lock:
            if self.tts is None:
                self._load_tts()
            # 清理视觉动作标记和 Markdown，避免逐字读出装饰符号。
            clean = re.sub(r'\*[^*]+\*', '', text)
            clean = re.sub(r'[`#*_]', '', clean).strip()[:240]
            if not clean:
                return np.empty(0, dtype=np.float32), 24000
            started = time.monotonic()
            result = self.tts.generate(clean, sid=speaker, speed=speed)
            LOG.info('合成完成 audio=%.2fs elapsed=%.2fs', len(result.samples)/result.sample_rate, time.monotonic()-started)
            return np.asarray(result.samples, dtype=np.float32), result.sample_rate

    def unload(self):
        with self.lock:
            self.recognizer = self.tts = None
        LOG.info('语音模型已释放')
