"""回复增量分段、单线程合成与顺序播放；有界队列及整轮静音锁存。"""

import asyncio
import logging
import re
import time

import sounddevice as sd

from .speech_output import play_samples

LOG = logging.getLogger(__name__)


class SpeechChunks:
    def __init__(self):
        self.pending = ""
        self.first = True

    def feed(self, text):
        self.pending += text
        parts = []
        while self.pending:
            # 小数点不作句末；英文长句优先在词间切开，限制首段等待。
            # 首段允许在短问候后的逗号开始朗读，后续保持更完整的韵律。
            minimum = 2 if self.first else 12
            match = re.search(rf"[。！？!?；;\n]|(?<!\d)\.(?!\d)|(?<=.{{{minimum}}})[，,:：]", self.pending)
            end = match.end() if match else 0
            if not end or end > 48:
                if len(self.pending) < 48:
                    break
                space = self.pending.rfind(" ", 16, 48)
                end = space + 1 if space >= 16 else 48
            parts.append(self.pending[:end])
            self.first = False
            self.pending = self.pending[end:]
        return parts

    def finish(self):
        remaining, self.pending = self.pending, ""
        return [remaining] if remaining else []


class SpeechStream:
    def __init__(self, activity, synthesize, current, state):
        self.activity, self.synthesize = activity, synthesize
        self.current, self.state = current, state
        self.chunks = SpeechChunks()
        self.texts = asyncio.Queue(maxsize=8)
        self.clips = asyncio.Queue(maxsize=1)
        self.suppressed = False
        self.closed = False
        self.tasks = []
        self.started = time.monotonic()
        self.first_audio_seconds = None

    async def __aenter__(self):
        self.tasks = [
            asyncio.create_task(self._produce()),
            asyncio.create_task(self._play()),
            asyncio.create_task(self._monitor()),
        ]
        return self

    async def __aexit__(self, *_):
        self.closed = True
        # 先停声卡，再等待不可中途取消的当前 ONNX 短段退出。
        sd.stop()
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)

    def _silence(self, message):
        if not self.suppressed:
            self.suppressed = True
            sd.stop()
            self.state(message)
            LOG.info("流式朗读停止：整轮待播内容已丢弃")

    def _allowed(self):
        if self.closed or self.suppressed:
            return False
        if not self.current() or self.activity.blocked:
            self._silence("本轮仅文字 · 流式朗读已停止")
            return False
        return True

    async def _monitor(self):
        while True:
            self._allowed()
            await asyncio.sleep(0.05)

    async def feed(self, text):
        if not self._allowed():
            return
        for part in self.chunks.feed(text):
            await self.texts.put(part)

    async def finish(self):
        if self._allowed():
            for part in self.chunks.finish():
                await self.texts.put(part)
        await self.texts.put(None)
        # shield 让取消先进入 __aexit__ 停声卡，而不是先等 ONNX 计算。
        await asyncio.shield(self.tasks[0])
        await asyncio.shield(self.tasks[1])
        if self.first_audio_seconds is not None and not self.suppressed:
            await asyncio.sleep(0.25)  # 扬声器尾音消退后再恢复收音。

    async def _produce(self):
        while (text := await self.texts.get()) is not None:
            if not self._allowed() or not text.strip():
                continue
            pending = asyncio.create_task(asyncio.to_thread(self.synthesize, text))
            try:
                samples, rate = await asyncio.shield(pending)
                if self._allowed() and len(samples):
                    await self.clips.put((samples, rate))
            except asyncio.CancelledError:
                # 不让旧 ONNX 任务跨入新对话；线程结果只能被丢弃。
                await asyncio.gather(pending, return_exceptions=True)
                raise
            except Exception as exc:
                LOG.warning("流式合成失败 type=%s", type(exc).__name__)
                self._silence("语音合成失败 · 回复仍以文字显示")
        await self.clips.put(None)

    async def _play(self):
        while (clip := await self.clips.get()) is not None:
            if not self._allowed():
                continue
            try:
                if self.first_audio_seconds is None:
                    self.first_audio_seconds = time.monotonic() - self.started
                    LOG.info("流式首段音频就绪 elapsed=%.3fs", self.first_audio_seconds)
                played = await play_samples(
                    self.activity,
                    *clip,
                    self._allowed,
                    lambda _: self.state("正在流式朗读…"),
                )
                if not played:
                    self._silence("本轮仅文字 · 流式朗读已停止")
            except Exception as exc:
                LOG.warning("流式播放失败 type=%s", type(exc).__name__)
                self._silence("语音播放失败 · 回复仍以文字显示")
