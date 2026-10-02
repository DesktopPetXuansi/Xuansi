"""主线程协调桌宠、用户操作和自动观察；后台结果按代次和窗口校验。"""

import logging
import time
from dataclasses import replace

import psutil
from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QApplication

from .avatar import Avatar
from .companion_ui import CompanionUI
from .config import Settings, load_settings
from .desktop import cursor_position, desktop_state, point_is_own_window
from .events import MouseEvent, ObservationGate
from .idle_action import IdleActionTimer
from .mouse_monitor import MouseMonitor
from .panel import Panel
from .runtime import Runtime

LOG = logging.getLogger(__name__)


class DesktopPet(QObject):
    def __init__(self, application: QApplication, settings: Settings | None = None):
        super().__init__()
        self.application = application
        self.settings = settings or load_settings()
        self.paused, self.busy, self.fullscreen = False, False, False
        # 用户开关与实际收音分别记录；休眠只暂停设备，不清掉用户选择。
        self.voice_enabled = False
        self.last_external = cursor_position()
        self.observation_window = 0
        self.observation_started = 0.0
        self.last_voice_notice = float("-inf")
        self.pending = None
        self.runtime = Runtime()
        self.runtime.audio_activity.set_enabled(self.settings.audio_avoidance)
        self.runtime.audio_activity.start()
        self.idle_action = IdleActionTimer()
        self.avatar = Avatar(self.settings.pet_size, self.settings.avatar_image)
        self.avatar.follow = self.settings.follow_mouse
        self.panel = Panel(self.settings)
        self.gate = ObservationGate(self.settings.interval)
        self.monitor = MouseMonitor()
        self._connect()
        self.ui = CompanionUI(self)
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
        self.runtime.mouth_level.connect(self.avatar.set_mouth_level)
        self.runtime.motion_requested.connect(self._execute_motion)
        self.avatar.motion_capabilities_changed.connect(self.runtime.set_motion_actions)
        self.panel.send_requested.connect(self.send)
        self.panel.voice_requested.connect(self.voice)
        self.panel.look_requested.connect(self.look)
        self.panel.sleep_requested.connect(self.toggle_sleep)
        self.panel.stop_requested.connect(self.stop_reply)
        self.panel.speech_requested.connect(self.runtime.set_speech_enabled)
        self.panel.memory_requested.connect(self.runtime.save_memory)
        self.panel.preview_requested.connect(self.preview_voice)
        self.runtime.memory_loaded.connect(self.panel.memory.setPlainText)
        self.runtime.memory_saved.connect(self.panel.status.setText)
        self.runtime.devices_loaded.connect(
            lambda devices: self.panel.preferences.set_devices(devices, self.settings.input_device)
        )
        self.runtime.reply.connect(self.on_reply)
        self.runtime.failed.connect(self.on_failed)
        self.runtime.heard.connect(
            lambda epoch, text: self.panel.append("你", text) if epoch == self.runtime.epoch else None
        )
        self.runtime.state.connect(self.on_state)
        self.runtime.finished.connect(self.on_finished)
        self.runtime.microphone_state.connect(self.on_microphone_state)
        self.runtime.segment.connect(self.on_segment)
        self.runtime.voice_update.connect(self.on_voice_update)
        self.runtime.shutdown_done.connect(self.application.quit)
        self.monitor.event.connect(self.on_mouse)
        self.monitor.activity.connect(self._on_system_activity)

    def _on_system_activity(self):
        """键鼠活动同时重置久置时间，并淡回实时 Live2D。"""
        self.idle_action.record_input(time.monotonic())
        self.avatar.interrupt_idle_blade()
        self.avatar.cancel_motion()

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
            self.runtime.cancel(notify=True)

    def on_failed(self, epoch, message):
        if epoch != self.runtime.epoch or self.paused:
            return
        self.panel.append("系统提示", message)
        if not self.fullscreen:
            self.avatar.bubble.present(message, self.avatar)

    def _execute_motion(self, epoch, motion):
        """Qt 将后台决策排入界面线程后，再校验代次和桌宠状态。"""
        if epoch != self.runtime.epoch or self.paused or self.fullscreen or not self.avatar.isVisible():
            return
        self.avatar.play_motion(motion)

    def send(self, text, with_screen=False):
        self._begin()
        self.panel.append("你", text)
        self.runtime.ask(self.settings, text, position=self.last_external if with_screen else None)

    def look(self):
        self.send("请理解提供的画面，结合红圈标记的鼠标位置，用一句话和我聊聊。", True)

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
            self.ui.quick.live_transcript.clear()
            self.busy = False
            self.avatar.set_animation("sleep" if self.paused else "idle")
        LOG.info("连续对话选择 enabled=%s paused=%s", enabled, self.paused)

    def _sync_voice_state(self):
        self.panel.voice_state(self.voice_enabled, self.paused)
        self.ui.quick.voice_state(self.voice_enabled, self.paused)

    def toggle_voice(self):
        self.voice(not self.voice_enabled)

    def on_segment(self, microphone_epoch, samples):
        if microphone_epoch == self.runtime.microphone_epoch and self.runtime.listening and not self.paused:
            self._begin()
            kind = "voice-screen" if self.panel.with_screen.isChecked() else "voice"
            self.runtime.ask(self.settings, "", kind=kind, position=self.last_external, samples=samples)

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
        self.ui.quick.status.setText(text)

    def on_voice_update(self, microphone_epoch, update):
        if microphone_epoch != self.runtime.microphone_epoch or not self.runtime.listening or self.paused:
            return
        text = "" if update.final else "正在听：" + update.text[-100:]
        self.panel.live_transcript.setText(text)
        self.ui.quick.live_transcript.setText(text)
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
            import re

            self._begin()
            with_screen = self.panel.with_screen.isChecked() or re.search(
                r"屏幕|鼠标|画面|看一[眼下]|看看|这个|这里", update.text
            )
            self.runtime.accept_voice(
                microphone_epoch, update, self.settings, self.last_external if with_screen else None
            )

    def on_state(self, epoch, text):
        if epoch == self.runtime.epoch:
            self.panel.status.setText(text)
            self.ui.quick.status.setText(text)

    def on_finished(self, epoch):
        if epoch == self.runtime.epoch:
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
        self.avatar.set_animation("happy")

    def on_mouse(self, event: MouseEvent):
        state = desktop_state()
        if state.own_window or point_is_own_window(event.x, event.y):
            return
        self.last_external = (event.x, event.y)
        blocked = (
            not state.hwnd
            or self.paused
            or self.busy
            or self.fullscreen
            or state.fullscreen
            or not self.settings.observe
            or self.runtime.listening
        )
        if not self.gate.allowed(time.monotonic(), event.when, blocked):
            return
        self.pending = (event, state.hwnd)
        # 短暂等待点击后的画面稳定；后续事件覆盖旧候选。
        QTimer.singleShot(600, self._observe)

    def _observe(self):
        pending, self.pending = self.pending, None
        if pending is None:
            return
        event, hwnd = pending
        state = desktop_state()
        blocked = (
            not state.hwnd
            or self.paused
            or self.busy
            or self.fullscreen
            or state.fullscreen
            or state.own_window
            or not self.settings.observe
            or self.runtime.listening
        )
        now = time.monotonic()
        if state.hwnd != hwnd or not self.gate.allowed(now, event.when, blocked):
            return
        self.gate.mark_sent(now)
        self.observation_window, self.observation_started = hwnd, now
        self._begin()
        prompt = (
            event.description() + "结合操作和局部画面，给出一句自然、简短的陪伴回应。"
            "不要猜测操作已成功，不要朗读隐私内容，没有值得回应的内容就只说“无需回应”。"
        )
        self.runtime.ask(
            self.settings, prompt, kind="observation", position=(event.x, event.y), observation=(hwnd, now)
        )

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
        self.ui.quick.live_transcript.clear()
        self._sync_voice_state()
        self.avatar.bubble.hide()
        self.avatar.set_animation("sleep")
        status = "已休眠 · 连续对话已暂停，唤醒后恢复" if self.voice_enabled else "已休眠 · 麦克风关闭"
        self.panel.status.setText(status)
        self.ui.quick.status.setText(status)
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
        self.ui.quick.status.setText(status)
        if self.voice_enabled and resume_voice and not self.fullscreen:
            self.voice(True)
        self.ui.refresh()
        LOG.info("退出休眠 enabled=%s resume_now=%s", self.voice_enabled, resume_voice)

    def apply_settings(self, settings: Settings, error: str, *, appearance_only=False):
        if error:
            self.panel.status.setText(error)
            return
        if (
            self.settings.audio_avoidance != settings.audio_avoidance
            and replace(self.settings, audio_avoidance=settings.audio_avoidance) == settings
        ):
            # 只改声音策略就在线切换，保留当前文字任务、麦克风和其他表单草稿。
            self.settings = self.panel.settings = settings
            self.runtime.audio_activity.set_enabled(settings.audio_avoidance)
            self.panel.audio_avoidance_action.setChecked(settings.audio_avoidance)
            self.ui.refresh()
            self.panel.status.setText("声音回避已开启" if settings.audio_avoidance else "声音回避已关闭")
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
        self.panel.setWindowTitle(f"{settings.name} · 本地 AI 桌宠")
        self.panel.logs.setWindowTitle(f"{settings.name} · 运行日志")
        self.tray.setToolTip(f"{settings.name} · 本地桌宠")
        self.panel.status.setText("已保存；下次回应使用新设置")

    def _resources(self):
        self.ui.refresh()
        state = desktop_state()
        available = psutil.virtual_memory().available / 2**30
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
        self._update_idle_action(state, time.monotonic())
        if (
            not self.busy
            and not self.runtime.listening
            and self.runtime.engine.loaded
            and time.monotonic() - self.runtime.engine.last_used > 120
        ):
            self.runtime.cancel(release=True)
        self.panel.footer.setText(
            f"仅本机处理 · 可用内存 {available:.1f} GB · 麦克风"
            + ("开启" if self.runtime.listening else "关闭")
        )

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

    def quit(self):
        self.resource_timer.stop()
        self.monitor.stop()
        self.ui.close()
        self.tray.hide()
        self.avatar.hide()
        self.avatar.bubble.hide()
        self.panel.hide()
        self.runtime.shutdown()
        LOG.info("正在退出并释放本地模型")
