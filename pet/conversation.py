"""单轮对话生命周期；保存完整文本，语音分段输出并共同遵守取消代次。"""

import asyncio
import logging
from pathlib import Path

import sounddevice as sd

from .config import MODELS
from .conversation_issues import ConversationIssue, failure_issue
from .desktop import capture_screen, observation_current
from .streaming_speech import SpeechStream
from .tool_dialogue import run_dialogue

LOG = logging.getLogger(__name__)


async def converse(runtime, epoch, settings, text, kind, position, samples, observation=None):
    keep_status = False
    try:
        runtime.microphone.muted.set()
        if epoch != runtime.epoch or not observation_current(observation):
            return
        # 资源目录初始化也属于本轮任务，失败必须恢复界面和麦克风生命周期。
        await asyncio.to_thread(runtime.audio.configure_root, Path(settings.ai.model_dir) if settings.ai.model_dir else MODELS)
        if kind == "preview":
            keep_status = await runtime._speak(epoch, settings, text, observation, kind=kind)
            return
        if samples is not None:
            runtime.state.emit(epoch, "正在识别你的话…")
            text = (await asyncio.to_thread(runtime.audio.transcribe, samples)).strip()
            if not text:
                # 空识别可能来自杂声；保持状态提示，由 finally 恢复收音，不触发故障气泡。
                keep_status = True
                runtime.state.emit(epoch, "未识别到有效语音 · 继续聆听，可重说或检查输入设备。")
                LOG.info("整句语音识别为空，继续聆听")
                return
            runtime.heard.emit(epoch, text)
        if epoch != runtime.epoch or not observation_current(observation):
            return
        # 明确附图和自动观察直接提供当前画面；其他请求由模型选择截图工具。
        images = (
            [await asyncio.to_thread(capture_screen, *position, settings.capture_scope)]
            if position and kind in ("chat-screen", "voice-screen", "observation") else []
        )
        if epoch != runtime.epoch or not observation_current(observation):
            return
        runtime.state.emit(epoch, "正在看画面并思考…" if images else "正在思考…")
        keep_status = await generate_reply(runtime, epoch, settings, text, images, kind, observation, position)
    except asyncio.CancelledError:
        sd.stop()
        raise
    except Exception as exc:
        keep_status = True
        LOG.warning("对话失败 type=%s", type(exc).__name__)
        issue = failure_issue(exc, kind)
        if epoch == runtime.epoch and observation_current(observation):
            runtime.state.emit(epoch, issue.message)
            if kind != "observation":
                runtime.failed.emit(epoch, issue.message)
                runtime.request_issue.emit(epoch, issue)
    finally:
        if epoch == runtime.epoch:
            if runtime.listening:
                runtime.microphone.muted.clear()
            if not keep_status:
                runtime.state.emit(
                    epoch, (("实时聆听中 · 说完即可回复" if settings.realtime_voice else "正在聆听，说完停顿即可")
                    if runtime.listening else "已就绪 · 麦克风关闭")
                    + (" · 朗读已关闭" if runtime.speech_override is False else "")
                )
        runtime.finished.emit(epoch)


async def generate_reply(runtime, epoch, settings, text, images, kind, observation, position=None):
    result = await run_dialogue(runtime, epoch, settings, text, images, kind, position, observation)
    if result.content is None or epoch != runtime.epoch or not observation_current(observation):
        return
    if kind == "chat" and result.content.strip():
        runtime.chat_succeeded.emit(epoch)
        LOG.info("最终文字对话成功 epoch=%s", epoch)
    if not runtime.should_speak(settings, kind):
        return

    def current():
        return epoch == runtime.epoch and observation_current(observation) and runtime.should_speak(settings, kind)

    speech_failed = False

    def speech_state(message):
        nonlocal speech_failed
        if current():
            runtime.state.emit(epoch, message)
            # 合成和播放失败留下可检查的通知，不改变已经交付的原始正文。
            if message.startswith(("语音合成失败", "语音播放失败")):
                speech_failed = True
                runtime.failed.emit(epoch, message)
                runtime.request_issue.emit(epoch, ConversationIssue(
                    message + "。请检查语音组件与输出设备，文字回复仍可查看。", "preferences", "检查语音设置",
                ))

    # 原生响应完整后才开始朗读，工具过程文字不进入音频流水线。
    async with SpeechStream(
        runtime.audio_activity,
        lambda part: runtime.audio.synthesize_selected(
            part, settings.speaker, settings.speed, settings.tts_engine, result.selected_tts,
        ),
        current, speech_state, runtime.mouth_level.emit,
    ) as speech:
        await speech.feed(result.content)
        await speech.finish()
    return speech_failed
