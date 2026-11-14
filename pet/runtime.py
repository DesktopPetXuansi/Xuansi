"""UI 与后台任务边界：单并发推理，代次编号拒绝迟到结果。"""

import asyncio
import hashlib
import logging
import threading
import time
import uuid
from concurrent.futures import Future, InvalidStateError
from contextlib import suppress
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

import sounddevice as sd
from PySide6.QtCore import QObject, Signal

from .ai.assembly import create_inference_router
from .ai.local_candidates import find_local_model, uses_catalog_paths
from .audio_activity import AudioActivity
from .audio_models import AudioModels
from .config import DATA, MODELS, Settings, save_settings
from .conversation import converse
from .conversation_issues import ConversationIssue, preview_issue
from .desktop import desktop_state, interactive_desktop, observation_current
from .live_dialogue import LiveDialogue
from .memory import MemoryStore, durable_io
from .microphone import Microphone
from .proactive_chat import ProactiveLimiter
from .screen_sharing import ScreenGrant, local_screen_destination, online_screen_destination
from .speech_output import speak
from .tool_protocol import Message
from .turn_latency import TurnLatency

LOG = logging.getLogger(__name__)


class Runtime(QObject):
    reply = Signal(int, str, str)
    reply_expression = Signal(int, str)
    # 主动问候需由界面确认实际显示，不能把排队信号当作已交付。
    proactive_ready = Signal(int, str)
    observation_ready = Signal(int, str)
    heard = Signal(int, str)
    state = Signal(int, str)
    finished = Signal(int)
    failed = Signal(int, str)
    # 最终文字与朗读独立：工具过程、试听和失败不能完成首次文字对话。
    chat_succeeded = Signal(int)
    request_issue = Signal(int, object)
    microphone_state = Signal(int, str)
    segment = Signal(int, object)
    voice_update = Signal(int, object)
    settings_saved = Signal(object, str)
    screen_mode_saved = Signal(int, str)
    platform_settings_saved = Signal(object, str)
    memory_loaded = Signal(str)
    memory_entries_loaded = Signal(object)
    memory_saved = Signal(str)
    shutdown_done = Signal()
    devices_loaded = Signal(object)
    speech_changed = Signal()
    # 用 TTS 播放响度驱动口型；麦克风输入不会触发此信号。
    mouth_level = Signal(int, float)
    motion_requested = Signal(int, str, str)
    provider_changed = Signal(object)

    def __init__(self):
        super().__init__()
        self.epoch = 0
        self.screen_mode = "off"
        self.automatic_observation = False
        self.observation_frames = {}
        self.last_observation_comment = None
        self.observation_retry_at = 0.0
        self.screen_version = 0
        self.screen_epoch = None
        self.listening = False
        self.speech_override: bool | None = None
        self.motion_actions: tuple[str, ...] = ()
        self.microphone_epoch = 0
        self.engine = create_inference_router(on_event=self.provider_changed.emit)
        self.audio = AudioModels()
        self.audio_activity = AudioActivity()
        self.memory = MemoryStore()
        self.history: list[Message] = []
        self.proactive_limiter = ProactiveLimiter(DATA / "proactive-chat.json")
        self._proactive_delivery = None
        self._proactive_context = None
        self.quiet_until = 0.0
        self.proactive_epoch = None
        self.pending_motions: dict[str, tuple[int, str, asyncio.Future[dict[str, str]], float]] = {}
        self.job: asyncio.Task | None = None
        self.loop = asyncio.new_event_loop()
        self.control = asyncio.Lock()
        self.microphone_control = asyncio.Lock()
        self.storage_control = asyncio.Lock()
        self.current_settings = Settings()
        self.live = LiveDialogue(self)
        self.microphone = self._new_microphone(0)
        self.thread = threading.Thread(target=self._run, daemon=True, name="pet-runtime")
        self.thread.start()

    def _run(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def schedule(self, coroutine):
        return asyncio.run_coroutine_threadsafe(coroutine, self.loop)

    def prepare_screen(self, settings, position, version):
        if self.screen_mode != "manual" or version != self.screen_version:
            return None
        hwnd = desktop_state().hwnd
        if settings.ai.policy != "online_first":
            settings = find_local_model(settings, model_root=MODELS) or settings
        return ScreenGrant(version, self.epoch + 1, position, settings.capture_scope, hwnd,
                           online_screen_destination(settings), local_screen_destination(settings))

    def invalidate_screen(self):
        self.screen_version += 1
        if self.screen_epoch == self.epoch:
            self.cancel(notify=True)

    def set_screen_mode(self, mode):
        if mode == "off":
            self.automatic_observation = False
        self.screen_mode = mode
        self.invalidate_screen()
        version = self.screen_version

        async def write():
            try:
                async with self.storage_control:
                    if version != self.screen_version:
                        return
                    updated = replace(self.current_settings, screen_mode=mode)
                    await durable_io(save_settings, updated)
                    self.current_settings = updated
                self.screen_mode_saved.emit(version, "")
            except Exception as exc:
                LOG.warning("屏幕设置保存失败 type=%s", type(exc).__name__)
                self.screen_mode_saved.emit(version, "屏幕设置未能保存。本次运行已应用，重启后请检查。")

        self.schedule(write())

    def set_automatic_observation(self, enabled):
        self.automatic_observation = enabled
        self.observation_frames = {}
        self.observation_retry_at = 0.0
        self.invalidate_screen()

    def prepare_observation(self, settings, position, observation):
        if not self.automatic_observation:
            return None

        def eligible():
            return (not self.listening and time.monotonic() >= self.observation_retry_at
                    and time.time() >= self.quiet_until and interactive_desktop()
                    and observation_current(observation))

        if not eligible():
            return None
        return ScreenGrant(self.screen_version, self.epoch + 1, position, settings.capture_scope,
                           observation[0], "", local_screen_destination(settings), True, eligible)

    def ask(self, settings: Settings, text: str, kind="chat", position=None, samples=None, observation=None,
            *, screen=None, endpoint_at=None):
        if kind == "observation" and (screen is None or not screen.automatic or observation is None
                                      or not self.automatic_observation or self.listening):
            return self.epoch
        self.epoch += 1
        epoch = self.epoch
        self.screen_epoch = epoch if screen is not None else None
        timing = TurnLatency(endpoint_at) if endpoint_at is not None else None
        self.schedule(self._replace(epoch, settings, text, kind, position, samples, observation,
                                    screen=screen, timing=timing))
        return epoch

    def request_proactive(self, settings: Settings):
        """主动候选只尝试空闲入口，不替换已经接受的用户任务。"""
        return self.schedule(self._try_proactive(self.epoch, settings))

    async def _try_proactive(self, candidate_epoch, settings):
        async with self.control:
            def available():
                return (
                    candidate_epoch == self.epoch
                    and settings.proactive_chat
                    and self.current_settings.proactive_chat
                    and settings == self.current_settings
                    and time.time() >= getattr(self, "quiet_until", 0.0)
                    and not self.listening
                    and not self.storage_control.locked()
                    and (self.job is None or self.job.done())
                )

            if not available():
                return
            # 预留写盘必须等待完成；用户若同时输入，代次复核会丢弃过期候选。
            text = await durable_io(self.proactive_limiter.reserve, time.time())
            if not text or not available():
                return
            self.epoch += 1
            epoch = self.epoch
            self.job = asyncio.create_task(self._run_proactive(epoch, settings, text))
            LOG.info("主动问候已进入交付流程 epoch=%s", epoch)

    async def _run_proactive(self, epoch, settings, text):
        # 界面线程需要检查并确认结果，跨线程 Future 再包装进事件循环等待。
        delivery = Future()
        self._proactive_delivery = (epoch, text, delivery)
        self.proactive_epoch = epoch
        try:
            self.proactive_ready.emit(epoch, text)
            try:
                accepted = await asyncio.wait_for(asyncio.wrap_future(delivery), 3)
            except TimeoutError:
                LOG.info("主动问候未获得界面确认 epoch=%s", epoch)
                return
            if accepted:
                mark_shown = getattr(self.proactive_limiter, "mark_shown", None)
                if mark_shown is not None:
                    await durable_io(mark_shown, text, time.time())
            if accepted and epoch == self.epoch and self.should_speak(settings, "proactive"):
                # 与普通对话使用相同语音目录，未显示或已过期的候选不合成。
                await asyncio.to_thread(
                    self.audio.configure_root,
                    Path(settings.ai.model_dir) if settings.ai.model_dir else MODELS,
                )
                if epoch == self.epoch:
                    await self._speak(epoch, settings, text, None, kind="proactive")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            LOG.warning("主动问候朗读未完成 type=%s", type(exc).__name__)
        finally:
            if self._proactive_delivery and self._proactive_delivery[0] == epoch:
                self._proactive_delivery = None
            if self.proactive_epoch == epoch:
                self.proactive_epoch = None
            self.finished.emit(epoch)

    def proactive_pending(self, epoch):
        """超时、取消或新一轮开始后，排队的界面信号不能再显示。"""
        delivery = self._proactive_delivery
        return bool(delivery and delivery[0] == epoch and epoch == self.epoch and not delivery[2].done())

    def quiet_proactive(self, today):
        now = datetime.now()
        until = datetime.combine(now.date() + timedelta(days=1), datetime.min.time()).timestamp()
        self.quiet_until = until if today else max(self.quiet_until, now.timestamp() + 3600)
        self._proactive_context = None
        if self.proactive_epoch == self.epoch:
            self.cancel(notify=True)
        if today:
            async def save():
                if not await durable_io(self.proactive_limiter.quiet_today, now.timestamp()):
                    self.state.emit(self.epoch, "今天安静已生效，重启后可能需要重新设置。")

            self.schedule(save())

    async def deliver_observation(self, epoch, text, current):
        fingerprint = hashlib.sha256("".join(text.split()).encode()).digest()
        if (fingerprint == self.last_observation_comment or not current()
                or not await durable_io(self.proactive_limiter.reserve_observation, time.time())):
            return False
        if not current():
            return False
        delivery = Future()
        self._proactive_delivery = (epoch, text, delivery)
        self.proactive_epoch = epoch
        try:
            self.observation_ready.emit(epoch, text)
            shown = await asyncio.wait_for(asyncio.wrap_future(delivery), 3)
            if shown:
                self.last_observation_comment = fingerprint
            return shown
        except TimeoutError:
            return False
        finally:
            self._proactive_delivery = None
            self.proactive_epoch = None

    def resolve_proactive(self, epoch, accepted, text, *, remember=True):
        """由界面线程确认显示结果；已显示文本只供下一次真人对话使用。"""
        delivery = self._proactive_delivery
        accepted = bool(accepted and epoch == self.epoch)
        if accepted and remember:
            # 显示前已确认候选有效；即使显示期间等待超时，展示过的文字仍可衔接。
            self._proactive_context = (text, time.monotonic())
        if delivery is None or delivery[0] != epoch:
            return
        try:
            delivery[2].set_result(accepted)
        except InvalidStateError:
            # 超时或取消可能恰好先完成；界面已展示时只保留短期衔接。
            LOG.debug("主动问候确认时交付已结束 epoch=%s", epoch)

    def consume_proactive_context(self):
        """只取一次近期确实展示的问候，不伪造用户发言或写入长期记忆。"""
        context, self._proactive_context = self._proactive_context, None
        if context is None:
            return ""
        text, shown = context
        return text if 0 <= time.monotonic() - shown <= 600 else ""

    async def _cancel(self):
        if self.job and not self.job.done():
            self.job.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await self.job
        self.job = None
        sd.stop()

    async def _replace(self, epoch, settings, text, kind, position, samples, observation, *, screen=None, timing=None):
        async with self.control:
            if epoch != self.epoch:
                return
            await self._cancel()
            if epoch == self.epoch:
                self.job = asyncio.create_task(
                    self._conversation(epoch, settings, text, kind, position, samples, observation,
                                       screen=screen, timing=timing)
                )

    async def _conversation(self, epoch, settings, text, kind, position, samples, observation=None,
                            *, screen=None, timing=None):
        await converse(self, epoch, settings, text, kind, position, samples, observation, screen=screen, timing=timing)

    async def _speak(self, epoch, settings, answer, observation, kind="chat", *, selected_engine=None):
        # 试听与对话沿用同一朗读门控；自动观察回退必须使用自己的偏好。
        def current():
            return epoch == self.epoch and observation_current(observation)

        def notify(issue):
            self.state.emit(epoch, issue.message)
            self.request_issue.emit(epoch, issue)
            LOG.info("试听未完成 action=%s", issue.action)
            return True

        if not current():
            return False
        if kind == "preview" and (issue := preview_issue(self, settings)):
            return notify(issue)
        if not self.should_speak(settings, kind) or self.audio_activity.blocked:
            return False
        if selected_engine is None:
            selected_engine = settings.tts_engine
        if epoch != self.epoch or not self.should_speak(settings, kind) or not observation_current(observation):
            return
        played = await speak(
            self.audio_activity,
            lambda: self.audio.synthesize_selected(
                answer, settings.speaker, settings.speed, settings.tts_engine, selected_engine,
            ),
            lambda: epoch == self.epoch and self.should_speak(settings, kind) and observation_current(observation),
            lambda text: self.state.emit(epoch, text),
            lambda level: self.mouth_level.emit(epoch, level),
        )
        if kind == "preview" and current() and not played:
            return notify(preview_issue(self, settings) or ConversationIssue(
                "试听未完整播放。请检查朗读开关、声音回避与系统输出设备后再次试听；文字聊天仍可使用。",
                "preferences", "检查语音设置",
            ))
        return False

    def should_speak(self, settings, kind="chat"):
        if 'tts' not in settings.ai.voice_components:
            return False
        if self.speech_override is False:
            return False
        if kind == "observation":
            return settings.speak_observations
        return settings.speak_replies if self.speech_override is None else self.speech_override

    def set_speech_enabled(self, enabled: bool | None):
        # 仅控制输出，不能关闭或偷偷开启麦克风；None 恢复已保存的偏好。
        self.speech_override = enabled
        if enabled is False:
            sd.stop()
        self.speech_changed.emit()
        LOG.info("本次运行朗读开关 enabled=%s", enabled)

    def set_motion_actions(self, actions: tuple[str, ...]):
        """由界面线程更新模型当前确有原生绑定的动作白名单。"""
        actions = tuple(actions)
        if actions == self.motion_actions:
            return
        self.motion_actions = actions
        LOG.info("当前 Live2D 可用动作=%s", ",".join(self.motion_actions) or "无")

    async def request_motion(self, epoch, action):
        """等待Qt实际绘制结束或中断；发出信号和开始播放都不是完成。"""
        if epoch != self.epoch or action not in self.motion_actions:
            return {"status": "rejected"}
        request_id = uuid.uuid4().hex
        future = self.loop.create_future()
        self.pending_motions[request_id] = (epoch, action, future, time.monotonic() + 3)
        self.motion_requested.emit(epoch, action, request_id)
        try:
            return await asyncio.wait_for(future, 3)
        except TimeoutError:
            LOG.warning("角色动作回执超时 epoch=%d", epoch)
            return {"status": "unknown"}
        finally:
            self.pending_motions.pop(request_id, None)

    def motion_pending(self, epoch, action, request_id):
        """Qt 执行前验证唯一请求；超时的排队信号不能产生迟到动作。"""
        pending = self.pending_motions.get(request_id)
        return bool(pending and pending[0] == epoch == self.epoch and pending[1] == action
                    and not pending[2].done() and time.monotonic() < pending[3])

    def resolve_motion(self, request_id, status):
        """界面线程只递交事实，Future统一回到所属事件循环完成。"""
        def resolve():
            pending = self.pending_motions.get(request_id)
            if pending is not None and not pending[2].done():
                future = pending[2]
                future.set_result({"status": status})
        self.loop.call_soon_threadsafe(resolve)

    def accept_voice(self, mic_epoch, update, settings, position=None, *, screen=None):
        return self.schedule(self.live.accept(mic_epoch, update, settings, position, screen=screen))

    def _new_microphone(self, epoch):
        return Microphone(
            lambda samples: self.segment.emit(epoch, samples),
            lambda text: self.microphone_state.emit(epoch, text),
        )

    def toggle_microphone(self, enabled: bool, device=-1, realtime=False, settings=None):
        self.microphone_epoch += 1
        epoch = self.microphone_epoch
        self.listening = enabled
        self.microphone.stop()
        if not enabled:
            self.cancel()
        return self.schedule(self._configure_microphone(epoch, enabled, device, realtime, settings))

    async def _prepare_voice(self, settings):
        await asyncio.to_thread(self.audio.configure_root, Path(settings.ai.model_dir) if settings.ai.model_dir else MODELS)
        # 开麦时预热；预热合成只进内存，不调用播放接口，也不写入对话历史。
        await self.engine.warmup(settings)
        if self.should_speak(settings):
            pending = asyncio.create_task(asyncio.to_thread(
                self.audio.synthesize, "你好。", settings.speaker, settings.speed, settings.tts_engine
            ))
            try:
                await asyncio.shield(pending)
            finally:
                await asyncio.gather(pending, return_exceptions=True)
        LOG.info("实时对话模型预热完成")

    async def _configure_microphone(self, epoch, enabled, device, realtime=False, settings=None):
        # 必须先关闭旧声卡，再检查代次；旧线程的消息不能改变新会话。
        async with self.microphone_control:
            self.live.reset()
            closed = await asyncio.to_thread(self.microphone.join)
            if epoch != self.microphone_epoch:
                return
            if closed is False:
                self.microphone_state.emit(epoch, "麦克风无法开启，旧输入设备未及时关闭，请稍后重试")
                return
            if not enabled:
                self.microphone_state.emit(epoch, "麦克风已关闭")
                return
            if settings is not None:
                required = 'realtime' if realtime else 'asr'
                if required not in settings.ai.voice_components:
                    self.listening = False
                    self.microphone_state.emit(epoch, '所选语音识别组件未安装，请在安装向导中添加后再开启。')
                    return
                await asyncio.to_thread(self.audio.configure_root,
                                        Path(settings.ai.model_dir) if settings.ai.model_dir else MODELS)
            self.microphone_state.emit(epoch, "正在准备本地语音…")
            try:
                if realtime:
                    if settings is not None:
                        async with self.control:
                            if epoch != self.microphone_epoch:
                                return
                            if not self.job or self.job.done():
                                self.job = asyncio.create_task(self._prepare_voice(settings))
                            pending = self.job
                        try:
                            await asyncio.shield(pending)
                        except asyncio.CancelledError:
                            if epoch == self.microphone_epoch and self.listening:
                                self.listening = False
                                self.microphone_state.emit(epoch, "麦克风无法开启：准备被新请求中断，请重新开启")
                            return
                        if epoch != self.microphone_epoch:
                            return
                    self.microphone = Microphone(
                        lambda samples: self.segment.emit(epoch, samples),
                        lambda text: self.microphone_state.emit(epoch, text),
                        on_update=lambda update: self.voice_update.emit(epoch, update),
                        model_root=Path(settings.ai.model_dir) if settings and settings.ai.model_dir else None,
                    )
                    self.microphone.start(device)
                    return
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

    def cancel(self, release=False, notify=False):
        self.epoch += 1
        return self.schedule(self._suspend(release, self.epoch, notify))

    async def _suspend(self, release, epoch=None, notify=False):
        async with self.control:
            if epoch is not None and epoch != self.epoch:
                return
            self.live.reset()
            await self._cancel()
            if release:
                await self.engine.stop()
                await asyncio.to_thread(self.audio.unload)
            # 旧回复因代次失效不会自行恢复收音，由本次取消完成后统一恢复。
            if epoch == self.epoch:
                if self.listening:
                    self.microphone.muted.clear()
                if notify:
                    self.state.emit(
                        epoch, "已停止回复 · 麦克风继续聆听" if self.listening else "已停止回复 · 麦克风关闭"
                    )
                self.finished.emit(epoch)
                LOG.info("本轮回复已停止 listening=%s", self.listening)

    def persist(self, settings: Settings, validate_models=True, platform_changes=None, credential_change=None):
        def validate_files():
            settings.validate()
            from .appearance import image_path

            if settings.avatar_image and not image_path(settings.avatar_image).is_file():
                raise ValueError("形象副本已丢失，请重新选择图片。")
            if (validate_models and settings.ai.policy != 'online_first'
                    and not uses_catalog_paths(settings, MODELS)
                    and not all(Path(path).is_file() for path in (settings.model_path, settings.projector_path))):
                raise ValueError("模型文件不存在，请在配置中选择配套的本地 GGUF 文件。")

        async def write():
            created_ref = ''
            try:
                async with self.storage_control:
                    await asyncio.to_thread(validate_files)
                    # 普通表单可能是旧快照，平台字段必须合并最近成功的持久状态。
                    latest = {name: getattr(self.current_settings, name) for name in (
                        "platform_url", "platform_model_version", "platform_expression_version", "avatar_image")}
                    latest.update(platform_changes or {})
                    latest["screen_mode"] = self.screen_mode
                    merged = replace(settings, **latest)
                    if credential_change is not None:
                        profile, key = credential_change
                        if profile != settings.ai.profile or not key.strip() or not profile.credential_ref:
                            raise ValueError('密钥草稿与当前在线配置不一致，请重新验证。')
                        if profile.credential_ref == self.current_settings.ai.profile.credential_ref:
                            raise ValueError('密钥修改需使用新的凭据引用，请重新验证。')
                        from .ai.credentials import CredentialStore

                        await durable_io(CredentialStore().write, profile.credential_ref, key)
                        created_ref = profile.credential_ref
                    try:
                        await durable_io(save_settings, merged)
                    except BaseException:
                        # 新引用先写后提交配置；配置失败只回收本次新引用，旧Key仍可用。
                        if created_ref:
                            await durable_io(CredentialStore().delete, created_ref)
                            created_ref = ''
                        raise
                    self.current_settings = merged
                    if not merged.proactive_chat:
                        self._proactive_context = None
                self.settings_saved.emit(merged, "")
            except Exception as exc:
                LOG.warning("设置保存失败 type=%s", type(exc).__name__)
                self.settings_saved.emit(
                    settings, str(exc) if isinstance(exc, ValueError) else "设置保存失败，请检查磁盘空间。"
                )

        self.schedule(write())

    def persist_platform(self, changes):
        """平台与普通配置共用串行队列，持锁后才基于最新配置合并字段。"""
        allowed = {"platform_url", "platform_model_version", "platform_expression_version", "avatar_image"}
        if not set(changes).issubset(allowed):
            raise ValueError("平台不能修改其他本地推理设置")

        async def write():
            try:
                async with self.storage_control:
                    merged = replace(self.current_settings, **changes)
                    await durable_io(save_settings, merged)
                    self.current_settings = merged
                self.platform_settings_saved.emit(merged, "")
            except Exception as exc:
                LOG.warning("平台设置保存失败 type=%s", type(exc).__name__)
                self.platform_settings_saved.emit(self.current_settings, "平台选择保存失败，请检查磁盘空间。")

        return self.schedule(write())

    def load_memory(self):
        return self.schedule(self.refresh_memory())

    async def refresh_memory(self):
        try:
            entries = await asyncio.to_thread(self.memory.entries)
        except OSError:
            self.memory_saved.emit("记忆无法读取，请检查本机存储。")
            return
        self.memory_entries_loaded.emit(entries)
        self.memory_loaded.emit("\n".join(entry.text for entry in entries))

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

    def save_memory(self, text, expected=None):
        return self._write_memory(self.memory.save, text, expected)

    def change_memory(self, action, identifier, revision, text):
        return self._write_memory(self.memory.change, action, identifier, revision, text)

    def _write_memory(self, operation, *args):
        self.epoch += 1
        epoch = self.epoch

        async def write():
            try:
                self.live.reset()
                async with self.control:
                    if epoch == self.epoch:
                        await self._cancel()
                    await durable_io(operation, *args)
                    # 编辑记忆后丢弃短期上下文，避免“忘记”后继续引用旧资料。
                    self.history.clear()
                    self._proactive_context = None
                await self.refresh_memory()
                self.memory_saved.emit("记忆已保存")
            except (ValueError, OSError) as exc:
                await self.refresh_memory()
                self.memory_saved.emit(str(exc) if isinstance(exc, ValueError) else "记忆保存失败")
            finally:
                if epoch == self.epoch and self.listening:
                    self.microphone.muted.clear()
                self.finished.emit(epoch)

        return self.schedule(write())

    def shutdown(self):
        self.listening = False
        self.microphone_epoch += 1
        self.microphone.stop()
        self.epoch += 1

        async def close():
            # 退出要等已接受的设置落盘，不能在原子替换前结束后台线程。
            async with self.storage_control:
                pass
            async with self.microphone_control:
                await asyncio.to_thread(self.microphone.join)
            await self._suspend(True)
            await asyncio.to_thread(self.microphone.join)
            await asyncio.to_thread(self.audio_activity.close)
            self.shutdown_done.emit()

        self.schedule(close())
