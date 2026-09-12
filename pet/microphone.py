"""连续对话收音：音频回调只入有界队列，识别永不阻塞声卡回调。"""
import logging
from queue import Queue, Empty, Full
import threading
from collections.abc import Callable
import numpy as np
import sounddevice as sd
from .segmentation import Segmenter

LOG = logging.getLogger(__name__)


class Microphone:
    def __init__(self, on_segment: Callable[[np.ndarray], None], on_state: Callable[[str], None]):
        self.on_segment = on_segment
        self.on_state = on_state
        self.stop_event = threading.Event()
        self.muted = threading.Event()
        self.thread: threading.Thread | None = None
        self.frames: Queue[np.ndarray] = Queue(maxsize=20)

    def start(self, device=-1):
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.muted.clear()
        self.thread = threading.Thread(target=self._run, args=(device,), daemon=True, name='pet-microphone')
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        self.muted.set()

    def join(self):
        if self.thread:
            self.thread.join(timeout=3)

    def _callback(self, data, frames, timing, status):
        if self.stop_event.is_set() or self.muted.is_set():
            return
        try:
            self.frames.put_nowait(data[:, 0].copy())
        except Full:
            # 丢弃拥塞音频，绝不在实时回调中等待识别或磁盘。
            pass

    def _run(self, device):
        segmenter = Segmenter()
        try:
            while not self.frames.empty():
                self.frames.get_nowait()
            with sd.InputStream(samplerate=16000, channels=1, dtype='float32', blocksize=1600,
                                device=None if device == -1 else device, callback=self._callback):
                self.on_state('正在聆听，说完停顿即可')
                LOG.info('麦克风已开启')
                while not self.stop_event.is_set():
                    try:
                        samples = self.frames.get(timeout=.1)
                    except Empty:
                        if self.muted.is_set():
                            segmenter.reset()
                        continue
                    if self.muted.is_set():
                        segmenter.reset()
                        continue
                    utterance = segmenter.feed(samples)
                    if utterance is not None:
                        self.muted.set()
                        self.on_segment(utterance)
        except Exception as exc:
            LOG.warning('麦克风无法使用 type=%s', type(exc).__name__)
            self.on_state('麦克风无法开启，请在设置中选择可用输入设备')
        finally:
            self.on_state('麦克风已关闭')
            LOG.info('麦克风已关闭')
