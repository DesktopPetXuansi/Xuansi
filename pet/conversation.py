"""单轮对话生命周期；保存完整文本，语音分段输出并共同遵守取消代次。"""

import asyncio
import hashlib
import logging
import time
from pathlib import Path

import sounddevice as sd

from .config import MODELS
from .conversation_issues import ConversationIssue, failure_issue
from .desktop import capture_screen, desktop_state, observation_current
from .screen_sharing import ScreenShareError, ScreenTurn, screen_turn
from .streaming_speech import SpeechStream
from .tool_dialogue import run_dialogue
from .turn_latency import mark_latency, turn_latency

LOG = logging.getLogger(__name__)


async def converse(runtime, epoch, settings, text, kind, position, samples, observation=None,
                   *, screen=None, timing=None):
    keep_status = False
    turn = ScreenTurn(runtime, epoch, screen) if screen is not None else None
    scope = screen_turn.set(turn)
    timing_scope = turn_latency.set(timing)

    def check_capture():
        turn.check_capture(desktop_state().hwnd)

    try:
        runtime.microphone.muted.set()
        if epoch != runtime.epoch or not observation_current(observation):
            return
        # 资源目录初始化也属于本轮任务，失败必须恢复界面和麦克风生命周期。
        await asyncio.to_thread(runtime.audio.configure_root, Path(settings.ai.model_dir) if settings.ai.model_dir else MODELS)
        if kind == "preview":
            keep_status = await runtime._speak(epoch, settings, text, observation, kind=kind)
            return
        needs_grant = kind in ("chat-screen", "voice-screen") or (kind == "observation" and observation is not None)
        if needs_grant != (turn is not None):
            raise ScreenShareError("本轮没有屏幕授权")
        if turn is not None and screen.automatic != (kind == "observation"):
            raise ScreenShareError("本轮屏幕授权用途不符")
        if turn is not None:
            check_capture()
        if samples is not None:
            runtime.state.emit(epoch, "正在识别你的话…")
            text = (await asyncio.to_thread(runtime.audio.transcribe, samples)).strip()
            mark_latency("recognized")
            if not text:
                # 空识别可能来自杂声；保持状态提示，由 finally 恢复收音，不触发故障气泡。
                keep_status = True
                runtime.state.emit(epoch, "未识别到有效语音 · 继续聆听，可重说或检查输入设备。")
                LOG.info("整句语音识别为空，继续聆听")
                return
            runtime.heard.emit(epoch, text)
        if epoch != runtime.epoch or not observation_current(observation):
            return
        images = []
        if turn is not None:
            check_capture()
            if screen.automatic and not await asyncio.to_thread(runtime.proactive_limiter.available, time.time()):
                return
            begin = getattr(runtime.engine, "begin_turn", None)
            if begin is None:
                await runtime.engine.start(settings)
            else:
                if screen.automatic:
                    try:
                        await begin(settings, required=("image",), observation=True)
                    except Exception:
                        if turn.current():
                            runtime.observation_retry_at = time.monotonic() + 300
                            keep_status = True
                            runtime.state.emit(epoch, "本机视觉模型暂不可用 · 自动观察暂停 5 分钟")
                        return
                else:
                    await begin(settings, required=("image",))
            check_capture()
            options = {"mark_cursor": False} if screen.automatic else {}
            images.append(await asyncio.to_thread(
                capture_screen, *screen.position, screen.scope, check=check_capture, **options,
            ))
            check_capture()
            if screen.automatic:
                fingerprint = hashlib.sha256(images[0]).digest()
                frames = runtime.observation_frames
                if frames.get(screen.hwnd) == fingerprint:
                    return
                if len(frames) >= 32:
                    frames.pop(next(iter(frames)))
                frames[screen.hwnd] = fingerprint
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
        if epoch == runtime.epoch and observation_current(observation) and (turn is None or turn.current()):
            if turn is not None and turn.grant.automatic:
                runtime.observation_retry_at = time.monotonic() + 300
                runtime.state.emit(epoch, "本次观察未完成 · 自动观察暂停 5 分钟")
            else:
                runtime.state.emit(epoch, issue.message)
            if kind != "observation":
                runtime.failed.emit(epoch, issue.message)
                runtime.request_issue.emit(epoch, issue)
    finally:
        screen_turn.reset(scope)
        turn_latency.reset(timing_scope)
        if timing is not None:
            LOG.info("语音轮次计时 epoch=%s kind=%s %s", epoch, kind, timing.summary())
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
    turn = screen_turn.get()
    result = await run_dialogue(runtime, epoch, settings, text, images, kind, position, observation)
    if (result.content is None or epoch != runtime.epoch or not observation_current(observation)
            or (turn is not None and not turn.current())):
        return
    mark_latency("final_text")
    if turn is not None and turn.grant.automatic:
        if not await runtime.deliver_observation(epoch, result.content, turn.current):
            return
    if kind == "chat" and result.content.strip():
        runtime.chat_succeeded.emit(epoch)
        LOG.info("最终文字对话成功 epoch=%s", epoch)
    if not runtime.should_speak(settings, kind):
        return

    def current():
        return (epoch == runtime.epoch and observation_current(observation)
                and (turn is None or turn.current()) and runtime.should_speak(settings, kind))

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
        current, speech_state, lambda level: runtime.mouth_level.emit(epoch, level),
    ) as speech:
        await speech.feed(result.content)
        await speech.finish()
    return speech_failed
