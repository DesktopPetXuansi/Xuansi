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
        if kind == "voice" and not re.search(
            r"屏幕|鼠标|画面|看一[眼下]|看看|这个|这里", text
        ):
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
                    epoch, (("实时聆听中 · 说完即可回复" if settings.realtime_voice else "正在聆听，说完停顿即可")
                    if runtime.listening else "已就绪 · 麦克风关闭")
                    + (" · 朗读已关闭" if runtime.speech_override is False else "")
                )
        runtime.finished.emit(epoch)


async def generate_reply(runtime, epoch, settings, text, images, kind, observation):
    async with AsyncExitStack() as stack:
        speech = None

        def current():
            return epoch == runtime.epoch and observation_current(observation)

        def change_speech(enabled):
            if current():
                runtime.set_speech_enabled(enabled)

        async def deliver(part):
            nonlocal speech
            if not current() or not runtime.should_speak(settings, kind):
                return
            # 控制头已被模型接口消费；到第一段正文才创建流水线，允许静音状态当轮恢复。
            if speech is None:
                speech = await stack.enter_async_context(
                    SpeechStream(
                        runtime.audio_activity,
                        lambda part: runtime.audio.synthesize(
                            part, settings.speaker, settings.speed, settings.tts_engine
                        ),
                        lambda: current() and runtime.should_speak(settings, kind),
                        lambda message: runtime.state.emit(epoch, message),
                    )
                )
            await speech.feed(part)

        # 只有用户对话允许模型切换朗读；自动观察不提供控制协议。
        if kind != "observation":
            answer = await runtime.engine.chat(
                settings, text, images, runtime.history, on_chunk=deliver,
                on_speech=change_speech, speech_enabled=runtime.should_speak(settings),
            )
        else:
            answer = await runtime.engine.chat(settings, text, images, [])
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
        elif runtime.should_speak(settings, kind):
            await runtime._speak(epoch, settings, answer, observation)
