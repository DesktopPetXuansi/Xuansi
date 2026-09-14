"""单段音频输出；供试听和流式流水线共用，取消立即关闭播放设备。"""

import asyncio
import logging

import sounddevice as sd

LOG = logging.getLogger(__name__)


async def speak(activity, synthesize, current, state):
    if activity.blocked:
        LOG.info("声音回避：跳过朗读，仅保留文字")
        return
    state("准备朗读…")
    samples, rate = await asyncio.to_thread(synthesize)
    if await play_samples(activity, samples, rate, current, state):
        await asyncio.sleep(0.3)


async def play_samples(activity, samples, rate, current, state):
    if not current() or not len(samples) or activity.blocked:
        return False
    state("正在说话…")
    sd.play(samples, rate)
    waiting = asyncio.create_task(asyncio.to_thread(sd.wait))
    try:
        while not waiting.done():
            if activity.blocked or not current():
                LOG.info("声音回避：停止本次朗读，文字仍可查看")
                sd.stop()
                break
            await asyncio.wait({waiting}, timeout=0.05)
        await asyncio.shield(waiting)
        return current() and not activity.blocked
    finally:
        # 取消协程时必须同时结束底层设备，避免迟到音频继续播放。
        sd.stop()
        await asyncio.shield(waiting)
