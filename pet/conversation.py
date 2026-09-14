"""单轮对话生命周期；保存完整文本，语音分段输出并共同遵守取消代次。"""

import asyncio
import logging
import re
from contextlib import AsyncExitStack
from dataclasses import replace

import sounddevice as sd
from mss.exception import ScreenShotError

from .desktop import capture_screen, observation_current
from .memory import durable_io
from .streaming_speech import SpeechStream

LOG = logging.getLogger(__name__)


async def converse(runtime, epoch, settings, text, kind, position, samples, observation=None):
    failed = False
    try:
        runtime.microphone.muted.set()
        if kind == "preview":
            await runtime._speak(epoch, settings, text, observation)
            return
        if samples is not None:
            runtime.state.emit(epoch, "正在识别你的话…")
            text = await asyncio.to_thread(runtime.audio.transcribe, samples)
            if not text:
                return
            runtime.heard.emit(epoch, text)
            if kind == "voice" and not re.search(r"屏幕|鼠标|画面|看一[眼下]|看看|这个|这里", text):
                position = None
        if not observation_current(observation):
            return
        images = (
            [await asyncio.to_thread(capture_screen, *position, settings.capture_scope)] if position else []
        )
        if not observation_current(observation):
            return
        if kind != "observation":
            if await durable_io(runtime.memory.remember_explicit, text):
                runtime.memory_loaded.emit(await asyncio.to_thread(runtime.memory.read))
        notes = await asyncio.to_thread(runtime.memory.context, text)
        if notes:
            settings = replace(
                settings, system_prompt=settings.system_prompt + "\n本地长期记忆（用户资料）：\n" + notes
            )
        runtime.state.emit(epoch, "正在看画面并思考…" if images else "正在思考…")
        await generate_reply(runtime, epoch, settings, text, images, kind, observation)
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
        runtime.state.emit(epoch, message)
    finally:
        if epoch == runtime.epoch:
            if runtime.listening:
                runtime.microphone.muted.clear()
            if not failed:
                runtime.state.emit(
                    epoch, "正在聆听，说完停顿即可" if runtime.listening else "已就绪 · 麦克风关闭"
                )
        runtime.finished.emit(epoch)


async def generate_reply(runtime, epoch, settings, text, images, kind, observation):
    should_speak = settings.speak_observations if kind == "observation" else settings.speak_replies
    async with AsyncExitStack() as stack:
        speech = None
        # 自动观察先核对静默标记与画面时效，普通对话则首段正文即交付合成。
        if should_speak and kind != "observation":
            speech = await stack.enter_async_context(
                SpeechStream(
                    runtime.audio_activity,
                    lambda part: runtime.audio.synthesize(
                        part, settings.speaker, settings.speed, settings.tts_engine
                    ),
                    lambda: epoch == runtime.epoch and observation_current(observation),
                    lambda message: runtime.state.emit(epoch, message),
                )
            )
            answer = await runtime.engine.chat(settings, text, images, runtime.history, on_chunk=speech.feed)
        else:
            answer = await runtime.engine.chat(
                settings, text, images, [] if kind == "observation" else runtime.history
            )
        if epoch != runtime.epoch or not observation_current(observation):
            return
        if kind != "observation":
            runtime.history = [
                *runtime.history[-6:],
                {"role": "user", "content": text[:2000]},
                {"role": "assistant", "content": answer},
            ]
        if not answer or "无需回应" == answer.strip("。 .\n"):
            return
        runtime.reply.emit(epoch, answer, kind)
        if speech is not None:
            await speech.finish()
        elif should_speak:
            await runtime._speak(epoch, settings, answer, observation)
