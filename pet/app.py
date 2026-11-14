"""主线程协调桌宠、用户操作和自动观察；后台结果按代次和窗口校验。"""

import logging
import time
from dataclasses import replace

import psutil
from PySide6.QtCore import QObject, Qt, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from .avatar import Avatar
from .companion_ui import CompanionUI
from .config import DATA, Settings, load_settings_result
from .desktop import cursor_position, desktop_state, interactive_desktop, point_is_own_window
from .events import MouseEvent, ObservationGate
from .first_chat import FirstChatFlow
from .idle_action import IdleActionTimer
from .mouse_monitor import MouseMonitor
from .panel import Panel
from .proactive_chat import ProactiveGate
from .runtime import Runtime

LOG = logging.getLogger(__name__)


class DesktopPet(QObject):
    def __init__(self, application: QApplication, settings: Settings | None = None):
        super().__init__()
        self.application = application
        settings_warning = ""
        if settings is None:
            loaded = load_settings_result()
            self.settings = loaded.settings
            settings_warning = loaded.warning
        else:
            self.settings = settings
        self.paused, self.busy, self.fullscreen = False, False, False
        self.pressure = False
        # 用户开关与实际收音分别记录；休眠只暂停设备，不清掉用户选择。
        self.voice_enabled = False
        self.last_external = cursor_position()
        self.observation_window = 0
        self.observation_started = 0.0
        self.last_voice_notice = float("-inf")
        self.pending = None
        self.runtime = Runtime()
        self.runtime.current_settings = self.settings
        self.runtime.screen_mode = self.settings.screen_mode
        self._quitting = False
        self._runtime_shutdown_complete = False
        self._platform_shutdown_complete = False
        self.runtime.audio_activity.set_enabled(self.settings.audio_avoidance)
        self.runtime.audio_activity.start()
        self.idle_action = IdleActionTimer()
        self.proactive_gate = ProactiveGate(time.monotonic())
        self.avatar = Avatar(self.settings.pet_size, self.settings.avatar_image)
        self.avatar.follow = self.settings.follow_mouse
        self.panel = Panel(self.settings, window_state_path=DATA / 'panel-window.json',
                           settings_warning=settings_warning)
        preference = ('首选在线 · ' + self.settings.ai.profile.model if self.settings.ai.policy == 'online_first'
                      else '首选本地 · ' + self.settings.ai.local_model)
        self.panel.footer.set_provider(preference + ' · 尚未连接')
        self.gate = ObservationGate(self.settings.interval)
        self.monitor = MouseMonitor()
        self._connect()
        self.ui = CompanionUI(self)
        self.first_chat = FirstChatFlow(self, path=DATA / 'first-chat.json')
        self.ui.platform.shutdown_done.connect(self._platform_shutdown_finished)
        self.tray = self.ui.tray
        self.monitor.start()
        self.resource_timer = QTimer(self)
        self.resource_timer.setInterval(2000)
        self.resource_timer.timeout.connect(self._resources)
        self.resource_timer.start()
        self.runtime.load_memory()
        self.runtime.load_devices()
        self.avatar.show()
        LOG.info("桌宠启动，麦克风默认关闭")

    def _connect(self):
        self.avatar.open_requested.connect(self.open_panel)
        self.runtime.mouth_level.connect(self.on_mouth_level)
        self.runtime.motion_requested.connect(self._execute_motion)
        self.avatar.motion_finished.connect(self.runtime.resolve_motion)
        self.avatar.motion_capabilities_changed.connect(self.runtime.set_motion_actions)
        self.panel.send_requested.connect(self.send)
        self.panel.voice_requested.connect(self.voice)
        self.panel.look_requested.connect(self.look)
        self.panel.screen_mode_requested.connect(self._set_screen_mode)
        self.panel.automatic_observation_requested.connect(self._set_automatic_observation)
        self.panel.quiet_requested.connect(self._quiet_proactive)
        self.runtime.screen_mode_saved.connect(self._screen_mode_saved)
        self.panel.sleep_requested.connect(self.toggle_sleep)
        self.panel.stop_requested.connect(self.stop_reply)
        self.panel.speech_requested.connect(self.runtime.set_speech_enabled)
        self.panel.memory_requested.connect(lambda text: self.runtime.save_memory(text, self.panel._memory_draft_base))
        self.panel.memory_change_requested.connect(self.runtime.change_memory)
        self.panel.preview_requested.connect(self.preview_voice)
        self.runtime.memory_entries_loaded.connect(self.panel.set_memory_entries)
        self.runtime.memory_saved.connect(self.panel.status.setText)
        self.runtime.devices_loaded.connect(
            lambda devices: self.panel.preferences.set_devices(devices, self.settings.input_device)
        )
        self.runtime.provider_changed.connect(self._provider_changed)
        self.runtime.reply.connect(self.on_reply)
        self.runtime.reply_expression.connect(self.on_reply_expression)
        self.runtime.proactive_ready.connect(self._on_proactive_ready)
        self.runtime.observation_ready.connect(self._on_observation_ready)
        self.runtime.failed.connect(self.on_failed)
        self.runtime.heard.connect(
            lambda epoch, text: self.panel.append("你", text) if epoch == self.runtime.epoch else None
        )
        self.runtime.state.connect(self.on_state)
        self.runtime.finished.connect(self.on_finished)
        self.runtime.microphone_state.connect(self.on_microphone_state)
        self.runtime.segment.connect(self.on_segment)
        self.runtime.voice_update.connect(self.on_voice_update)
        self.runtime.shutdown_done.connect(self._runtime_shutdown_finished)
        self.monitor.event.connect(self.on_mouse)
        self.monitor.activity.connect(self._on_system_activity)

    def _on_system_activity(self):
        """键鼠活动同时重置久置时间，并淡回实时 Live2D。"""
        now = time.monotonic()
        self.idle_action.record_input(now)
        proactive = getattr(self, "proactive_gate", None)
        if proactive is not None:
            proactive.record_activity(now)
        self.avatar.interrupt_idle_blade()
        self.avatar.cancel_motion()

    def _provider_changed(self, event):
        """区分首选和实际位置；状态独立于资源和后台上传提示。"""
        label = ('在线 · ' if event.online else '本地 · ') + event.current
        if event.reason == 'resource':
            label += ' · 资源回退'
        if event.online and not self.settings.ai.cloud_memory:
            label += ' · 在线记忆检索未启用'
        if event.online and not self.settings.ai.profile.is_verified('image', 'tools'):
            label += ' · 图片与工具待验证'
        self.panel.footer.set_provider(label)
        self.panel.footer.setAccessibleDescription(f'首选 {event.preferred}；当前 {label}')
        self.tray.setToolTip(f'{self.settings.name} · {label}')
        LOG.info('界面已同步实际推理位置 online=%s reason=%s', event.online, event.reason)

    def open_panel(self):
        # 只有显式点击才显示并激活可输入窗口。
        self.panel.show()
        self.panel.raise_()
        self.panel.activateWindow()

    def _begin(self):
        if self.paused:
            # 先完成唤醒后的当前请求，再恢复收音，避免新请求取消语音预热。
            self._wake(resume_voice=False)
        self.avatar.cancel_motion()
        self.busy = True
        self.ui.refresh()
        self.avatar.set_animation("thinking")

    def stop_reply(self):
        """用户明确停止本轮后恢复聆听，不需要先关闭再打开麦克风。"""
        if self.busy:
            self.on_state(self.runtime.epoch, "正在停止当前回复…")
            self.avatar.clear_reply_expression()
            self.avatar.set_mouth_level(0.0)
            self.runtime.cancel(notify=True)

    def on_failed(self, epoch, message):
        if epoch != self.runtime.epoch or self.paused:
            return
        self.panel.append("系统提示", message)
        if not self.fullscreen:
            self.avatar.bubble.present(message, self.avatar)

    def _execute_motion(self, epoch, motion, request_id):
        """Qt 将后台决策排入界面线程后，再校验代次和桌宠状态。"""
        if (not self.runtime.motion_pending(epoch, motion, request_id)
                or self.paused or self.fullscreen or not self.avatar.isVisible()):
            self.runtime.resolve_motion(request_id, "rejected")
            return
        try:
            accepted = self.avatar.play_motion(motion, request_id=request_id)
        except Exception as exc:
            LOG.warning("角色动作未受理 type=%s", type(exc).__name__)
            self.runtime.resolve_motion(request_id, "unknown")
            return
        if not accepted:
            self.runtime.resolve_motion(request_id, "rejected")
        # 已开始的动作由渲染完成或中断信号回传，不能把受理当作完成。

    def _set_screen_mode(self, mode):
        if self.runtime.screen_epoch == self.runtime.epoch:
            self.avatar.clear_reply_expression()
            self.avatar.set_mouth_level(0.0)
        self.settings = self.panel.settings = replace(self.settings, screen_mode=mode)
        self.panel.screen_mode(mode)
        self.panel.screen_status.hide()
        self.runtime.set_screen_mode(mode)
        if mode == "off":
            self.panel.automatic_observation.blockSignals(True)
            self.panel.automatic_observation.setChecked(False)
            self.panel.automatic_observation.blockSignals(False)
        self.panel.screen_warning.setText("正在保存屏幕权限…")
        self.panel.screen_warning.show()

    def _screen_mode_saved(self, version, error):
        if version == self.runtime.screen_version:
            self.panel.screen_warning.setText(error)
            self.panel.screen_warning.setVisible(bool(error))

    def _quiet_proactive(self, today):
        self.runtime.quiet_proactive(today)
        self.panel.status.setText("今天安静 · 仍可主动对话" if today else "接下来一小时安静 · 仍可主动对话")

    def _set_automatic_observation(self, enabled):
        self.pending = None
        if not enabled and self.runtime.screen_epoch == self.runtime.epoch:
            self.avatar.set_mouth_level(0.0)
        self.runtime.set_automatic_observation(enabled)
        self.panel.status.setText("本机自动观察已开启 · 仅本次运行" if enabled else "本机自动观察已关闭")

    def _prepare_screen_share(self):
        settings = self.settings
        version = self.runtime.screen_version
        epoch = self.runtime.epoch
        position = self.last_external
        if self.runtime.screen_mode != "manual":
            self.panel.status.setText("屏幕分享已关闭。")
            return None
        scope = "鼠标所在显示器" if settings.capture_scope == "screen" else "鼠标附近的局部画面"
        profile = settings.ai.profile
        if settings.ai.policy == "online_first":
            if not profile.is_verified("image"):
                self.panel.status.setText("此在线模型尚未验证识图。可取消附图发送，或先在模型设置验证识图。")
                return None
            dialog = QMessageBox(self.panel)
            dialog.setWindowTitle("确认本轮在线屏幕分享")
            dialog.setTextFormat(Qt.TextFormat.PlainText)
            dialog.setText(f"向 {profile.provider} 的 {profile.model} 发送一张{scope}截图？")
            dialog.setInformativeText(f"发送地址：{profile.endpoint}")
            dialog.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
            dialog.button(QMessageBox.StandardButton.Yes).setText("分享这一张")
            dialog.setDefaultButton(QMessageBox.StandardButton.Cancel)
            if dialog.exec() != QMessageBox.StandardButton.Yes:
                return None
        grant = self.runtime.prepare_screen(settings, position, version) if epoch == self.runtime.epoch else None
        if grant is not None:
            destination = profile.model if grant.online_profile else "本机模型"
            self.panel.screen_status.setText(f"本轮分享 · {scope} → {destination}")
            self.panel.screen_status.show()
        return grant

    def _send_turn(self, text, screen):
        if screen is None:
            self.panel.screen_status.hide()
        self._begin()
        self.panel.append("你", text)
        self.runtime.ask(self.settings, text, kind="chat-screen" if screen else "chat", screen=screen)

    def send(self, text, with_screen=False):
        screen = None
        if with_screen:
            self.panel.take_screen_attachment()
            screen = self._prepare_screen_share()
            if screen is None:
                if not self.panel.input.text():
                    self.panel.input.setText(text)
                return
        self._send_turn(text, screen)

    def look(self):
        self.panel.take_screen_attachment()
        screen = self._prepare_screen_share()
        if screen is not None:
            self._send_turn("请理解提供的画面，结合红圈标记的鼠标位置，用一句话和我聊聊。", screen)

    def preview_voice(self, settings):
        self._begin()
        self.runtime.ask(settings, f"你好，我是{settings.name}。我会在这里陪着你。", kind="preview")

    def voice(self, enabled):
        self.voice_enabled = enabled
        if enabled and self.paused:
            self._wake(resume_voice=False)
        self._sync_voice_state()
        self.runtime.toggle_microphone(
            enabled, self.settings.input_device, self.settings.realtime_voice, self.settings
        )
        if not enabled:
            self.panel.live_transcript.clear()
            self.busy = False
            self.avatar.set_animation("sleep" if self.paused else "idle")
        LOG.info("连续对话选择 enabled=%s paused=%s", enabled, self.paused)

    def _sync_voice_state(self):
        self.panel.voice_state(self.voice_enabled, self.paused)

    def toggle_voice(self):
        self.voice(not self.voice_enabled)

    def on_segment(self, microphone_epoch, samples):
        if microphone_epoch == self.runtime.microphone_epoch and self.runtime.listening and not self.paused:
            endpoint_at = time.monotonic()
            screen = self._prepare_screen_share() if self.panel.take_screen_attachment() else None
            if microphone_epoch != self.runtime.microphone_epoch or not self.runtime.listening or self.paused:
                return
            self._begin()
            kind = "voice-screen" if screen else "voice"
            self.runtime.ask(self.settings, "", kind=kind, samples=samples, screen=screen, endpoint_at=endpoint_at)

    def on_microphone_state(self, microphone_epoch, text):
        if microphone_epoch != self.runtime.microphone_epoch:
            return
        if text == "麦克风已关闭" or text.startswith("麦克风无法"):
            self.runtime.listening = False
            if text == "麦克风已关闭" and self.voice_enabled and (self.paused or self.busy or self.fullscreen):
                # 暂停设备的通知可能迟到；不能覆盖休眠或等待本轮结束的开启选择。
                return
            self.voice_enabled = False
            self._sync_voice_state()
        if text.startswith("麦克风无法"):
            self.on_failed(self.runtime.epoch, text)
        self.panel.status.setText(text)

    def on_voice_update(self, microphone_epoch, update):
        if microphone_epoch != self.runtime.microphone_epoch or not self.runtime.listening or self.paused:
            return
        text = "" if update.final else "正在听：" + update.text[-100:]
        self.panel.live_transcript.setText(text)
        if update.final and not update.text:
            message = "未识别到有效语音 · 继续聆听，可重说或检查输入设备。"
            self.on_state(self.runtime.epoch, message)
            # 杂声也会触发空话段；只更新状态，日志限频，不作为故障弹气泡或写入聊天。
            now = time.monotonic()
            if now - self.last_voice_notice >= 10:
                self.last_voice_notice = now
                LOG.info("空语音话段已忽略，继续聆听")
            return
        if update.final and update.text:
            self.panel.append("你", update.text)
        if update.text and update.final:
            screen = self._prepare_screen_share() if self.panel.take_screen_attachment() else None
            if microphone_epoch != self.runtime.microphone_epoch or not self.runtime.listening or self.paused:
                return
            self._begin()
            self.runtime.accept_voice(microphone_epoch, update, self.settings, screen=screen)

    def on_state(self, epoch, text):
        if epoch == self.runtime.epoch:
            self.panel.status.setText(text)

    def on_finished(self, epoch):
        if epoch == self.runtime.epoch:
            self.panel.screen_status.hide()
            if self.runtime.screen_epoch == epoch:
                self.runtime.screen_epoch = None
            self.busy = False
            self.ui.refresh()
            self.avatar.set_animation("idle" if not self.paused else "sleep")
            if self.voice_enabled and not self.runtime.listening and not self.paused and not self.fullscreen:
                self.voice(True)

    def on_reply(self, epoch, text, kind):
        if epoch != self.runtime.epoch or self.paused:
            return
        if kind == "observation":
            state = desktop_state()
            if (
                state.hwnd != self.observation_window
                or state.fullscreen
                or time.monotonic() - self.observation_started > 30
            ):
                return
        self.panel.append(self.settings.name, text)
        if not self.fullscreen:
            self.avatar.bubble.present(text, self.avatar)
        self.avatar.set_animation("idle")

    def on_reply_expression(self, epoch, expression):
        """回复表现与正文分流，忽略旧代次及不可见桌面上的迟到结果。"""
        if epoch == self.runtime.epoch and not self.paused and not self.fullscreen:
            self.avatar.set_reply_expression(expression)

    def on_mouth_level(self, epoch, level):
        if epoch == self.runtime.epoch and not self.paused and not self.fullscreen:
            self.avatar.set_mouth_level(level)

    def on_mouse(self, event: MouseEvent):
        state = desktop_state()
        if state.own_window or point_is_own_window(event.x, event.y):
            return
        self.last_external = (event.x, event.y)
        blocked = not getattr(self.runtime, "automatic_observation", False) or not self._observation_eligible(state)
        if not self.gate.allowed(time.monotonic(), event.when, blocked):
            return
        self.pending = (event, state.hwnd, self.runtime.screen_version, self.runtime.epoch)
        # 短暂等待点击后的画面稳定；后续事件覆盖旧候选。
        QTimer.singleShot(600, self._observe)

    def _observe(self):
        pending, self.pending = self.pending, None
        if pending is None:
            return
        event, hwnd, version, epoch = pending
        if version != self.runtime.screen_version or epoch != self.runtime.epoch:
            return
        state = desktop_state()
        blocked = not self._observation_eligible(state)
        now = time.monotonic()
        if state.hwnd != hwnd or not self.gate.allowed(now, event.when, blocked):
            return
        observation = (hwnd, now)
        grant = self.runtime.prepare_observation(self.settings, (event.x, event.y), observation)
        if grant is None:
            return
        self.gate.mark_sent(now)
        self.observation_window, self.observation_started = hwnd, now
        self._begin()
        prompt = (
            "根据本机事件触发的画面，判断是否有值得提醒的明确情况。"
            "不要猜测操作已成功，不要朗读隐私内容；是否发言由你判断，没有值得评论的内容时结束本次观察。"
        )
        self.runtime.ask(
            self.settings, prompt, kind="observation", observation=observation, screen=grant,
        )

    def _observation_eligible(self, state):
        return (self.runtime.automatic_observation and time.time() >= self.runtime.quiet_until
                and time.monotonic() >= self.runtime.observation_retry_at
                and state.hwnd and not state.own_window and not state.fullscreen and not self.fullscreen
                and not self.paused and not self.busy and not self.voice_enabled and not self.runtime.listening
                and not self._quitting and not self.ui.saving and not self.pressure and interactive_desktop())

    def _on_observation_ready(self, epoch, text):
        state = desktop_state()
        accepted = (self.runtime.automatic_observation and self.runtime.proactive_pending(epoch)
                    and not self.paused and not self.fullscreen and not self.voice_enabled
                    and not self.runtime.listening and not self._quitting and time.time() >= self.runtime.quiet_until
                    and state.hwnd == self.observation_window and not state.own_window and not state.fullscreen
                    and time.monotonic() - self.observation_started <= 30 and interactive_desktop())
        displayed = False
        try:
            if accepted:
                self.on_reply(epoch, text, "observation")
                displayed = True
        finally:
            self.runtime.resolve_proactive(epoch, displayed, text, remember=False)

    def toggle_sleep(self):
        if self.paused:
            self._wake()
            return
        self.paused = self.avatar.paused = True
        self.panel.sleep_button.setText("唤醒")
        # 保留 voice_enabled 和按钮勾选；实际关闭声卡以暂停收音并释放资源。
        self.runtime.toggle_microphone(False)
        self.runtime.cancel(release=True)
        self.panel.live_transcript.clear()
        self._sync_voice_state()
        self.avatar.bubble.hide()
        self.avatar.set_animation("sleep")
        status = "已休眠 · 连续对话已暂停，唤醒后恢复" if self.voice_enabled else "已休眠 · 麦克风关闭"
        self.panel.status.setText(status)
        self.pending = None
        self.busy = False
        self.ui.refresh()
        LOG.info("进入休眠，保留连续对话选择 enabled=%s", self.voice_enabled)

    def _wake(self, resume_voice=True):
        self.paused = self.avatar.paused = False
        self.panel.sleep_button.setText("休眠")
        self.avatar.set_animation("idle")
        self._sync_voice_state()
        self.pending = None
        self.busy = False
        status = "已唤醒 · 麦克风关闭"
        if self.voice_enabled:
            status = "已唤醒 · 正在恢复连续对话" if resume_voice else "已唤醒 · 回复后恢复连续对话"
            if self.fullscreen:
                status = "已唤醒 · 桌面恢复可用后继续连续对话"
        self.panel.status.setText(status)
        if self.voice_enabled and resume_voice and not self.fullscreen:
            self.voice(True)
        self.ui.refresh()
        LOG.info("退出休眠 enabled=%s resume_now=%s", self.voice_enabled, resume_voice)

    def apply_settings(self, settings: Settings, error: str, *, appearance_only=False):
        if error:
            self.panel.status.setText(error)
            return
        settings = replace(settings, screen_mode=self.settings.screen_mode)
        if (
            self.settings.audio_avoidance != settings.audio_avoidance
            and replace(self.settings, audio_avoidance=settings.audio_avoidance) == settings
        ):
            # 只改声音策略就在线切换，保留当前文字任务、麦克风和其他表单草稿。
            self.settings = self.panel.settings = settings
            self.runtime.audio_activity.set_enabled(settings.audio_avoidance)
            self.panel.audio_avoidance_action.setChecked(settings.audio_avoidance)
            self.ui.refresh()
            self.panel.status.setText("已开启：其他软件发声时暂停朗读" if settings.audio_avoidance
                                      else "已关闭：朗读可与其他软件同时播放")
            return
        if appearance_only or (
            self.settings.avatar_image != settings.avatar_image
            and replace(self.settings, avatar_image=settings.avatar_image) == settings
        ):
            # 重导入相同标识也刷新缓存；外观保存不停止对话或改写其他表单草稿。
            self.settings = self.panel.settings = settings
            self.avatar.set_image(settings.avatar_image, force=True)
            self.ui.refresh_icon()
            self.panel.status.setText("形象已应用，重启后继续使用")
            LOG.info("桌宠形象已应用 custom=%s", bool(settings.avatar_image))
            return
        self.voice(False)
        self.runtime.cancel(release=True)
        self.settings = self.panel.settings = settings
        self.runtime.set_speech_enabled(None)
        self.runtime.audio_activity.set_enabled(settings.audio_avoidance)
        self.panel.audio_avoidance_action.setChecked(settings.audio_avoidance)
        self.gate.interval = settings.interval
        self.avatar.set_size(settings.pet_size)
        self.avatar.set_image(settings.avatar_image)
        self.ui.refresh_icon()
        self.avatar.follow = settings.follow_mouse
        self.panel.title.setText(settings.name)
        self.panel.setWindowTitle(f"{settings.name} · 控制中心")
        self.panel.logs.setWindowTitle(f"{settings.name} · 运行日志")
        self.tray.setToolTip(f"{settings.name} · 桌面伙伴")
        self.panel.footer.set_provider('设置已更新 · 等待下次连接')
        self.panel.status.setText("已保存；下次回应使用新设置")

    def _resources(self):
        self.ui.refresh()
        state = desktop_state()
        available = psutil.virtual_memory().available / 2**30
        self._adjust_resource_pressure(available)
        # 锁屏/切换用户/显示器不可用时常没有前景窗口，此时停止抓图。
        suppressed = state.fullscreen or not state.hwnd
        if suppressed != self.fullscreen:
            self.fullscreen = suppressed
            if self.fullscreen:
                self.avatar.hide()
                self.avatar.bubble.hide()
                # 休眠已经停止实际输入；锁屏或全屏不能清掉其保留的开启选择。
                if not self.paused:
                    self.voice(False)
                self.runtime.cancel(release=True)
                self.panel.status.setText(
                    "桌面暂不可用 · 已暂停观察和对话" if not state.hwnd else "全屏模式 · 已暂停观察和对话"
                )
            else:
                self.avatar.show()
                if self.voice_enabled and not self.paused and not self.busy and not self.runtime.listening:
                    self.voice(True)
        if available < 2 and not self.paused:
            self.toggle_sleep()
            self.panel.status.setText("可用内存偏低，已自动休眠")
        now = time.monotonic()
        self._update_idle_action(state, now)
        if getattr(self, "proactive_gate", None) is not None:
            self._update_proactive(state, now)
        if (
            not self.busy
            and not self.runtime.listening
            and self.runtime.engine.loaded
            and time.monotonic() - self.runtime.engine.last_used > 120
        ):
            self.runtime.cancel(release=True)
        self.panel.footer.setText(
            f"可用内存 {available:.1f} GB · 麦克风"
            + ("开启" if self.runtime.listening else "关闭")
        )

    def _adjust_resource_pressure(self, available):
        # 这是后台调度余量，不是模型硬件最低配置；恢复边界留出余量避免反复跳变。
        previous = self.pressure
        self.pressure = available < (5 if previous else 4)
        self.gate.interval = self.settings.interval * (3 if self.pressure else 1)
        interval = 66 if self.pressure and not self.busy else 33
        if self.avatar.render_clock.interval() != interval:
            self.avatar.render_clock.setInterval(interval)
        if previous != self.pressure:
            LOG.info('后台资源调度调整 pressure=%s', self.pressure)

    def _update_idle_action(self, state, now):
        """仅在桌面可用且默认 Live2D 空闲时推进五分钟待机计时。"""
        eligible = (
            self.monitor.input_monitor_available
            and self.avatar.supports_idle_blade
            and self.avatar.animation == "idle"
            and not self.paused
            and not self.busy
            and not self.fullscreen
            and not state.fullscreen
            and bool(state.hwnd)
            and not self.runtime.listening
        )
        if not eligible:
            self.idle_action.poll(now, eligible=False)
            self.avatar.interrupt_idle_blade(fade=not self.paused and not self.fullscreen)
            return

        if self.idle_action.poll(now, eligible=True) and self.avatar.start_idle_blade():
            LOG.info("系统连续空闲达到五分钟，开始玄司拔刀待机动作")

    def _proactive_eligible(self, state):
        """只在用户启用且桌面和输入都空闲时考虑本机短问候。"""
        return bool(
            self.settings.proactive_chat
            and self.monitor.input_monitor_available
            and state.hwnd and not state.fullscreen and not state.own_window
            and not self.paused and not self.busy and not self.fullscreen
            and not self.voice_enabled and not self.runtime.listening
            and not self.ui.saving and not self._quitting and not self.pressure
            and not self.runtime.audio_activity.blocked
            and self.avatar.isVisible() and self.avatar.animation == "idle"
            and self.avatar._motion_name is None and self.avatar._idle_blade_started is None
        )

    def _update_proactive(self, state, now):
        if self.proactive_gate.can_attempt(now, eligible=self._proactive_eligible(state)):
            # 申请失败也退避，避免界面线程每两秒重复发起磁盘或音频任务。
            self.proactive_gate.record_attempt(now)
            self.runtime.request_proactive(self.settings)

    def _on_proactive_ready(self, epoch, text):
        """显示前重新核对桌面和代次；只有实际交付才记入下一轮上下文。"""
        now = time.monotonic()
        recent = 0 <= now - self.proactive_gate.last_activity <= 120
        accepted = (epoch == self.runtime.epoch and self.runtime.proactive_pending(epoch) and recent
                    and self._proactive_eligible(desktop_state()))
        displayed = False
        try:
            if accepted:
                self.busy = True
                self.panel.append(self.settings.name, text)
                # 控制中心可能收起或停在其他标签；仅追加记录不算用户可见。
                displayed = self.panel.chat.isVisible()
                try:
                    self.avatar.bubble.present(text, self.avatar)
                    displayed = True
                except Exception as exc:
                    LOG.warning("主动问候气泡未显示 type=%s", type(exc).__name__)
                self.ui.refresh()
                LOG.info("主动问候显示结果 epoch=%s visible=%s", epoch, displayed)
        finally:
            self.runtime.resolve_proactive(epoch, displayed, text)

    def quit(self):
        if self._quitting:
            return
        self._quitting = True
        self.resource_timer.stop()
        self.monitor.stop()
        self.first_chat.close()
        self.ui.close()
        self.tray.hide()
        self.avatar.hide()
        self.avatar.bubble.hide()
        self.panel.hide()
        self.runtime.shutdown()
        LOG.info("正在退出并释放本地模型")

    def _runtime_shutdown_finished(self):
        self._runtime_shutdown_complete = True
        self._finish_shutdown()

    def _platform_shutdown_finished(self):
        self._platform_shutdown_complete = True
        self._finish_shutdown()

    def _finish_shutdown(self):
        # Qt 事件循环保留到资源线程与推理运行时全部结束，禁止提前销毁 QThread。
        if self._quitting and self._runtime_shutdown_complete and self._platform_shutdown_complete:
            self.application.quit()
