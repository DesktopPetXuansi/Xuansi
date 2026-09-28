"""单段音频输出；供试听和流式流水线共用，取消立即关闭播放设备。"""

import asyncio
import logging
import time

import numpy as np
import sounddevice as sd

LOG = logging.getLogger(__name__)


async def speak(activity, synthesize, current, state, mouth_level=None):
    if activity.blocked:
        LOG.info("声音回避：跳过朗读，仅保留文字")
        return
    state("准备朗读…")
    samples, rate = await asyncio.to_thread(synthesize)
    if await play_samples(activity, samples, rate, current, state, mouth_level):
        await asyncio.sleep(0.3)


async def play_samples(activity, samples, rate, current, state, mouth_level=None):
    if not current() or not len(samples) or activity.blocked:
        return False
    state("正在说话…")
    sd.play(samples, rate)
    started = time.monotonic()
    window_frames = max(1, int(rate * 0.05))
    waiting = asyncio.create_task(asyncio.to_thread(sd.wait))
    try:
        while not waiting.done():
            if activity.blocked or not current():
                LOG.info("声音回避：停止本次朗读，文字仍可查看")
                sd.stop()
                break
            if mouth_level is not None:
                # 每 50 毫秒取一次 RMS 响度，跟随实际播放且不阻塞音频。
                offset = int((time.monotonic() - started) * rate)
                fragment = samples[offset : offset + window_frames]
                rms = float(np.sqrt(np.mean(np.square(fragment)))) if len(fragment) else 0.0
                mouth_level(min(1.0, max(0.0, (rms - 0.012) * 5.5)))
            await asyncio.wait({waiting}, timeout=0.05)
        await asyncio.shield(waiting)
        return current() and not activity.blocked
    finally:
        # 取消协程时必须同时结束底层设备，避免迟到音频继续播放。
        sd.stop()
        if mouth_level is not None:
            mouth_level(0.0)
        await asyncio.shield(waiting)
