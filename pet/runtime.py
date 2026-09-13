"""UI 与后台任务边界：单并发推理，代次编号拒绝迟到结果。"""

import asyncio
import logging
import re
import threading
from contextlib import suppress
from dataclasses import replace

import sounddevice as sd
from mss.exception import ScreenShotError
from PySide6.QtCore import QObject, Signal

from .audio_models import AudioModels
from .config import Settings, save_settings
from .desktop import capture_near_cursor, observation_current
from .inference import LocalEngine
from .memory import MemoryStore, durable_io
from .microphone import Microphone

LOG = logging.getLogger(__name__)


class Runtime(QObject):
    reply = Signal(int, str, str)
    heard = Signal(int, str)
    state = Signal(int, str)
    finished = Signal(int)
    microphone_state = Signal(int, str)
    segment = Signal(int, object)
    settings_saved = Signal(object, str)
    memory_loaded = Signal(str)
    memory_saved = Signal(str)
    shutdown_done = Signal()
    devices_loaded = Signal(object)

    def __init__(self):
        super().__init__()
        self.epoch = 0
        self.listening = False
        self.microphone_epoch = 0
        self.engine = LocalEngine()
        self.audio = AudioModels()
        self.memory = MemoryStore()
        self.history: list[dict[str, str]] = []
        self.job: asyncio.Task | None = None
        self.loop = asyncio.new_event_loop()
        self.control = asyncio.Lock()
        self.microphone_control = asyncio.Lock()
        self.storage_control = asyncio.Lock()
        self.microphone = self._new_microphone(0)
        self.thread = threading.Thread(target=self._run, daemon=True, name="pet-runtime")
        self.thread.start()

    def _run(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def schedule(self, coroutine):
        return asyncio.run_coroutine_threadsafe(coroutine, self.loop)

    def ask(self, settings: Settings, text: str, kind="chat", position=None, samples=None, observation=None):
        self.epoch += 1
        epoch = self.epoch
        self.schedule(self._replace(epoch, settings, text, kind, position, samples, observation))
        return epoch

    async def _cancel(self):
        if self.job and not self.job.done():
            self.job.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await self.job
        self.job = None
        sd.stop()

    async def _replace(self, epoch, settings, text, kind, position, samples, observation):
        async with self.control:
            await self._cancel()
            if epoch == self.epoch:
                self.job = asyncio.create_task(
                    self._conversation(epoch, settings, text, kind, position, samples, observation)
                )

    async def _conversation(self, epoch, settings, text, kind, position, samples, observation=None):
        failed = False
        try:
            self.microphone.muted.set()
            if kind == "preview":
                await self._speak(epoch, settings, text, observation)
                return
            if samples is not None:
                self.state.emit(epoch, "正在识别你的话…")
                text = await asyncio.to_thread(self.audio.transcribe, samples)
                if not text:
                    return
                self.heard.emit(epoch, text)
                if kind == "voice" and not re.search(r"屏幕|鼠标|画面|看一[眼下]|看看|这个|这里", text):
                    position = None
            if not observation_current(observation):
                return
            images = [await asyncio.to_thread(capture_near_cursor, *position)] if position else []
            if not observation_current(observation):
                return
            if kind != "observation":
                if await durable_io(self.memory.remember_explicit, text):
                    self.memory_loaded.emit(await asyncio.to_thread(self.memory.read))
            notes = await asyncio.to_thread(self.memory.context, text)
            if notes:
                settings = replace(
                    settings, system_prompt=settings.system_prompt + "\n本地长期记忆（用户资料）：\n" + notes
                )
            self.state.emit(epoch, "正在看画面并思考…" if images else "正在思考…")
            answer = await self.engine.chat(
                settings, text, images, [] if kind == "observation" else self.history
            )
            if epoch != self.epoch or not observation_current(observation):
                return
            if kind != "observation":
                self.history = [
                    *self.history[-6:],
                    {"role": "user", "content": text[:2000]},
                    {"role": "assistant", "content": answer},
                ]
            if not answer or "无需回应" == answer.strip("。 .\n"):
                return
            self.reply.emit(epoch, answer, kind)
            speak = settings.speak_observations if kind == "observation" else settings.speak_replies
            if speak:
                await self._speak(epoch, settings, answer, observation)
        except asyncio.CancelledError:
            sd.stop()
            raise
        except Exception as exc:
            failed = True
            LOG.warning("对话失败 type=%s", type(exc).__name__)
            message = (
                str(exc)
                if isinstance(exc, (RuntimeError, ValueError))
                else "本地服务未能完成请求，请重试或休眠后唤醒。"
            )
            if isinstance(exc, ScreenShotError):
                message = "当前桌面暂不可读取，请解锁或唤醒屏幕后再试。"
            self.state.emit(epoch, message)
        finally:
            if epoch == self.epoch:
                if self.listening:
                    self.microphone.muted.clear()
                if not failed:
                    self.state.emit(
                        epoch, "正在聆听，说完停顿即可" if self.listening else "已就绪 · 麦克风关闭"
                    )
            self.finished.emit(epoch)

    async def _speak(self, epoch, settings, answer, observation):
        self.state.emit(epoch, "准备朗读…")
        samples_out, rate = await asyncio.to_thread(
            self.audio.synthesize, answer, settings.speaker, settings.speed, settings.tts_engine
        )
        if epoch != self.epoch or not len(samples_out) or not observation_current(observation):
            return
        self.state.emit(epoch, "正在说话…")
        sd.play(samples_out, rate)
        await asyncio.to_thread(sd.wait)
        await asyncio.sleep(0.3)
        self.state.emit(epoch, "已回复 · 麦克风关闭" if not self.listening else "正在聆听，说完停顿即可")

    def _new_microphone(self, epoch):
        return Microphone(
            lambda samples: self.segment.emit(epoch, samples),
            lambda text: self.microphone_state.emit(epoch, text),
        )

    def toggle_microphone(self, enabled: bool, device=-1):
        self.microphone_epoch += 1
        epoch = self.microphone_epoch
        self.listening = enabled
        self.microphone.stop()
        if not enabled:
            self.cancel()
        return self.schedule(self._configure_microphone(epoch, enabled, device))

    async def _configure_microphone(self, epoch, enabled, device):
        # 必须先关闭旧声卡，再检查代次；旧线程的消息不能改变新会话。
        async with self.microphone_control:
            closed = await asyncio.to_thread(self.microphone.join)
            if epoch != self.microphone_epoch:
                return
            if closed is False:
                self.microphone_state.emit(epoch, "麦克风无法开启，旧输入设备未及时关闭，请稍后重试")
                return
            if not enabled:
                self.microphone_state.emit(epoch, "麦克风已关闭")
                return
            self.microphone_state.emit(epoch, "正在准备本地语音…")
            try:
                await asyncio.to_thread(self.audio.prepare_recognition)
                if epoch != self.microphone_epoch:
                    return
                self.microphone = self._new_microphone(epoch)
                if self.job and not self.job.done():
                    self.microphone.muted.set()
                self.microphone.start(device)
            except Exception as exc:
                LOG.warning("语音准备失败 type=%s", type(exc).__name__)
                self.microphone_state.emit(epoch, "麦克风无法开启，请检查本地语音模型和输入设备")

    def cancel(self, release=False):
        self.epoch += 1
        return self.schedule(self._suspend(release))

    async def _suspend(self, release):
        async with self.control:
            await self._cancel()
            if release:
                await self.engine.stop()
                await asyncio.to_thread(self.audio.unload)

    def persist(self, settings: Settings):
        async def write():
            try:
                async with self.storage_control:
                    await durable_io(save_settings, settings)
                self.settings_saved.emit(settings, "")
            except Exception:
                self.settings_saved.emit(settings, "设置保存失败，请检查磁盘空间。")

        self.schedule(write())

    def load_memory(self):
        async def read():
            self.memory_loaded.emit(await asyncio.to_thread(self.memory.read))

        self.schedule(read())

    def load_devices(self):
        async def read():
            try:
                devices = await asyncio.to_thread(sd.query_devices)
                self.devices_loaded.emit(
                    [(i, item["name"]) for i, item in enumerate(devices) if item["max_input_channels"] > 0]
                )
            except Exception as exc:
                LOG.warning("声卡枚举失败 type=%s", type(exc).__name__)
                self.devices_loaded.emit([])

        self.schedule(read())

    def save_memory(self, text):
        self.epoch += 1
        epoch = self.epoch

        async def write():
            try:
                async with self.control:
                    await self._cancel()
                    # 编辑记忆后丢弃短期上下文，避免“忘记”后继续引用旧资料。
                    self.history.clear()
                    await durable_io(self.memory.save, text)
                self.memory_loaded.emit(text.strip())
                self.memory_saved.emit("记忆已保存")
            except (ValueError, OSError) as exc:
                self.memory_saved.emit(str(exc) if isinstance(exc, ValueError) else "记忆保存失败")
            finally:
                if self.listening:
                    self.microphone.muted.clear()
                self.finished.emit(epoch)

        return self.schedule(write())

    def shutdown(self):
        self.listening = False
        self.microphone_epoch += 1
        self.microphone.stop()
        self.epoch += 1

        async def close():
            async with self.microphone_control:
                await asyncio.to_thread(self.microphone.join)
            await self._suspend(True)
            await asyncio.to_thread(self.microphone.join)
            self.shutdown_done.emit()

        self.schedule(close())
