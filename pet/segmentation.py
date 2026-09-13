"""轻量能量断句：有界缓存、前置缓冲和最长句长，静音不触发识别。"""

from collections import deque

import numpy as np


class Segmenter:
    def __init__(self, sample_rate=16000, silence_seconds=0.8, max_seconds=12):
        self.sample_rate = sample_rate
        self.silence_seconds = silence_seconds
        self.max_seconds = max_seconds
        self.reset()

    def reset(self):
        self.pre_roll: deque[np.ndarray] = deque(maxlen=3)
        self.frames: list[np.ndarray] = []
        self.voiced = 0.0
        self.quiet = 0.0
        self.total = 0.0
        self.noise = 0.003

    def feed(self, samples: np.ndarray):
        duration = len(samples) / self.sample_rate
        rms = float(np.sqrt(np.mean(samples * samples))) if len(samples) else 0.0
        threshold = max(0.012, min(self.noise * 3.5, 0.05))
        speech = rms > threshold
        if not self.frames:
            if not speech:
                self.noise = 0.96 * self.noise + 0.04 * rms
                self.pre_roll.append(samples.copy())
                return None
            self.frames.extend(self.pre_roll)
            self.total = sum(len(frame) for frame in self.pre_roll) / self.sample_rate
            self.pre_roll.clear()
        self.frames.append(samples.copy())
        self.total += duration
        self.voiced += duration if speech else 0
        self.quiet = 0 if speech else self.quiet + duration
        if self.quiet < self.silence_seconds and self.total < self.max_seconds:
            return None
        # 前置缓冲同样计入句长上限，避免持续噪声增长内存。
        output = (
            np.concatenate(self.frames)[: int(self.max_seconds * self.sample_rate)]
            if self.voiced >= 0.25
            else None
        )
        self.reset()
        return output
