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
        self.last_external = cursor_position()
        self.observation_window = 0
        self.observation_started = 0.0
        self.pending = None
        self.runtime = Runtime()
        self.runtime.audio_activity.set_enabled(self.settings.audio_avoidance)
        self.runtime.audio_activity.start()
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
        self.panel.send_requested.connect(self.send)
        self.panel.voice_requested.connect(self.voice)
        self.panel.look_requested.connect(self.look)
        self.panel.sleep_requested.connect(self.toggle_sleep)
        self.panel.memory_requested.connect(self.runtime.save_memory)
        self.panel.preview_requested.connect(self.preview_voice)
        self.runtime.memory_loaded.connect(self.panel.memory.setPlainText)
        self.runtime.memory_saved.connect(self.panel.status.setText)
        self.runtime.devices_loaded.connect(
            lambda devices: self.panel.preferences.set_devices(devices, self.settings.input_device)
        )
        self.runtime.reply.connect(self.on_reply)
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

    def open_panel(self):
        # 只有显式点击才显示并激活可输入窗口。
        self.panel.show()
        self.panel.raise_()
        self.panel.activateWindow()

    def _begin(self):
        if self.paused:
            self.toggle_sleep()
        self.busy = True
        self.avatar.set_animation("thinking")

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
        if enabled and self.paused:
            self.toggle_sleep()
        self.panel.voice_state(enabled)
        self.ui.quick.voice_state(enabled)
        self.runtime.toggle_microphone(
            enabled, self.settings.input_device, self.settings.realtime_voice, self.settings
        )
        if not enabled:
            self.panel.live_transcript.clear()
            self.ui.quick.live_transcript.clear()
            self.busy = False
            self.avatar.set_animation("idle")

    def toggle_voice(self):
        self.voice(not self.runtime.listening)

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
            self.panel.voice_state(False)
            self.ui.quick.voice_state(False)
        self.panel.status.setText(text)
        self.ui.quick.status.setText(text)

    def on_voice_update(self, microphone_epoch, update):
        if microphone_epoch != self.runtime.microphone_epoch or not self.runtime.listening or self.paused:
            return
        text = "" if update.final else "正在听：" + update.text[-100:]
        self.panel.live_transcript.setText(text)
        self.ui.quick.live_transcript.setText(text)
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
            self.avatar.set_animation("idle" if not self.paused else "sleep")

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
        self.paused = not self.paused
        self.avatar.paused = self.paused
        self.panel.sleep_button.setText("唤醒" if self.paused else "休眠")
        if self.paused:
            self.voice(False)
            self.runtime.cancel(release=True)
            self.avatar.bubble.hide()
            self.avatar.set_animation("sleep")
            self.panel.status.setText("已休眠，正在释放模型资源")
        else:
            self.avatar.set_animation("idle")
            self.panel.status.setText("已唤醒 · 麦克风关闭")
        self.pending = None
        self.busy = False
        LOG.info("休眠状态=%s", self.paused)

    def apply_settings(self, settings: Settings, error: str):
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
        if (
            self.settings.avatar_image != settings.avatar_image
            and replace(self.settings, avatar_image=settings.avatar_image) == settings
        ):
            # 仅更换外观不停止正在进行的对话，也不改写未保存的人设输入。
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
                self.voice(False)
                self.runtime.cancel(release=True)
                self.panel.status.setText(
                    "桌面暂不可用 · 已暂停观察和对话" if not state.hwnd else "全屏模式 · 已暂停观察和对话"
                )
            else:
                self.avatar.show()
        if available < 2 and not self.paused:
            self.toggle_sleep()
            self.panel.status.setText("可用内存偏低，已自动休眠")
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
