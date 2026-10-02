"""休眠只暂停收音，连续对话选择与恢复使用假运行时、真实离屏 Qt 按钮验证。"""

from types import SimpleNamespace

import pytest
from PySide6.QtCore import QObject
from PySide6.QtWidgets import QApplication

from pet.app import DesktopPet
from pet.companion_ui import CompanionUI
from pet.config import Settings
from pet.desktop import DesktopState
from pet.panel import STYLE, Panel
from pet.quick_chat import QuickChat


class FakeRuntime:
    """只模拟输入预热与请求冲突，不创建声卡、模型或用户记忆。"""

    def __init__(self, owner):
        self.owner = owner
        self.epoch = 0
        self.microphone_epoch = 0
        self.listening = False
        self.warming = False
        self.pending_reply = False
        self.interrupted_warmups = 0
        self.audio_activity = SimpleNamespace(status="测试安静环境")

    def should_speak(self, settings):
        return settings.speak_replies

    def toggle_microphone(self, enabled, *_args):
        self.microphone_epoch += 1
        self.listening = enabled
        self.warming = enabled
        if not enabled:
            self.cancel()

    def cancel(self, **_kwargs):
        self.epoch += 1
        self.pending_reply = False
        self.warming = False

    def ask(self, _settings, _text, **_kwargs):
        self.epoch += 1
        # 与真实运行时一致：新文字请求会取消占用同一推理槽的开麦预热。
        if self.warming:
            self.warming = False
            self.listening = False
            self.interrupted_warmups += 1
            self.owner.on_microphone_state(
                self.microphone_epoch, "麦克风无法开启：准备被新请求中断，请重新开启"
            )
        self.pending_reply = True
        return self.epoch


@pytest.fixture
def pet(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    application = QApplication.instance() or QApplication([])
    application.setQuitOnLastWindowClosed(False)
    owner = DesktopPet.__new__(DesktopPet)
    QObject.__init__(owner)
    owner.settings = Settings()
    owner.paused = owner.busy = owner.fullscreen = False
    owner.voice_enabled = False
    owner.pending = None
    owner.last_external = (0, 0)
    owner.panel = Panel(owner.settings)
    quick = QuickChat(owner.settings, STYLE)
    owner.runtime = FakeRuntime(owner)
    owner.avatar = SimpleNamespace(
        paused=False,
        bubble=SimpleNamespace(hide=lambda: None, present=lambda *_: None),
        cancel_motion=lambda: None,
        set_animation=lambda animation: setattr(owner.avatar, "animation", animation),
    )
    owner.ui = SimpleNamespace(owner=owner, quick=quick, hotkey=SimpleNamespace(active=1))
    owner.ui.refresh = lambda: CompanionUI.refresh(owner.ui)
    owner.panel.voice_requested.connect(owner.voice)
    quick.voice_requested.connect(owner.voice)
    yield owner
    owner.panel.hide()
    owner.panel.logs.hide()
    quick.hide()
    owner.panel.deleteLater()
    owner.panel.logs.deleteLater()
    quick.deleteLater()
    owner.deleteLater()
    application.processEvents()


def test_sleep_keeps_voice_selected_but_stops_physical_input(pet):
    """关闭的是实际收音，两处开关仍保留用户已开启的选择。"""
    pet.voice(True)
    pet.toggle_sleep()

    assert pet.paused and not pet.runtime.listening
    assert pet.panel.voice_button.isChecked()
    assert pet.ui.quick.voice.isChecked()
    assert "休眠" in pet.panel.status.text()
    assert "休眠" in pet.ui.quick.status.text()


def test_wake_restores_previously_enabled_continuous_voice(pet):
    pet.voice(True)
    pet.toggle_sleep()
    pet.toggle_sleep()

    assert not pet.paused and pet.runtime.listening
    assert pet.panel.voice_button.isChecked() and pet.ui.quick.voice.isChecked()


def test_wake_does_not_open_voice_that_was_never_enabled(pet):
    pet.toggle_sleep()
    pet.toggle_sleep()

    assert not pet.paused and not pet.runtime.listening
    assert not pet.panel.voice_button.isChecked() and not pet.ui.quick.voice.isChecked()


def test_user_can_turn_voice_off_while_asleep(pet):
    pet.voice(True)
    pet.toggle_sleep()
    # 托盘用 toggle_voice；此时物理输入已停，不能按 listening 反向切换。
    pet.toggle_voice()

    assert pet.paused and not pet.runtime.listening
    assert not pet.panel.voice_button.isChecked() and not pet.ui.quick.voice.isChecked()
    pet.toggle_sleep()
    assert not pet.runtime.listening


def test_delayed_input_close_keeps_sleep_message_and_voice_selection(pet):
    pet.voice(True)
    pet.toggle_sleep()
    pet.on_microphone_state(pet.runtime.microphone_epoch, "麦克风已关闭")

    assert pet.paused and not pet.runtime.listening
    assert pet.panel.voice_button.isChecked() and pet.ui.quick.voice.isChecked()
    assert "休眠" in pet.panel.status.text() and "休眠" in pet.ui.quick.status.text()


def test_failed_wake_clears_selection_and_leaves_readable_failure(pet):
    pet.voice(True)
    pet.toggle_sleep()
    pet.toggle_sleep()
    pet.on_microphone_state(pet.runtime.microphone_epoch, "麦克风无法开启，请检查输入设备")

    assert not pet.runtime.listening
    assert not pet.panel.voice_button.isChecked() and not pet.ui.quick.voice.isChecked()
    assert "麦克风无法开启" in pet.panel.status.text()
    assert "麦克风无法开启" in pet.panel.chat.toPlainText()
    # 再次休眠唤醒也不能悄悄重试已经失败的开启选择。
    pet.toggle_sleep()
    pet.toggle_sleep()
    assert not pet.runtime.listening


def test_text_wakes_pet_then_resumes_voice_after_reply_without_preheat_collision(pet):
    """文字先完成，原开启的收音随后恢复，不能取消当前请求或开麦预热。"""
    pet.voice(True)
    pet.toggle_sleep()
    pet.send("文字唤醒测试")

    assert not pet.paused and pet.busy and pet.runtime.pending_reply
    assert not pet.runtime.listening
    assert pet.panel.voice_button.isChecked() and pet.ui.quick.voice.isChecked()
    assert pet.runtime.interrupted_warmups == 0

    pet.runtime.pending_reply = False
    pet.on_finished(pet.runtime.epoch)

    assert not pet.busy and pet.runtime.listening
    assert pet.panel.voice_button.isChecked() and pet.ui.quick.voice.isChecked()
    assert pet.runtime.interrupted_warmups == 0


def resource_desktop(pet, monkeypatch, state):
    """资源轮询只读取注入的桌面状态，不查询真实窗口或资源。"""
    desktop = SimpleNamespace(state=state)
    monkeypatch.setattr("pet.app.desktop_state", lambda: desktop.state)
    monkeypatch.setattr("pet.app.psutil.virtual_memory", lambda: SimpleNamespace(available=8 * 2**30))
    pet.runtime.engine = SimpleNamespace(loaded=False)
    pet._update_idle_action = lambda *_: None
    pet.avatar.show = pet.avatar.hide = lambda: None
    return desktop


@pytest.mark.parametrize("state", [DesktopState(0, False, False), DesktopState(123, False, True)])
def test_suppressed_desktop_keeps_sleeping_voice_selection(pet, monkeypatch, state):
    """先休眠再锁屏或进入全屏，不能由资源轮询清掉已保留的开启选择。"""
    resource_desktop(pet, monkeypatch, state)
    pet.voice(True)
    pet.toggle_sleep()
    pet._resources()

    assert pet.paused and pet.fullscreen and not pet.runtime.listening
    assert pet.voice_enabled
    assert pet.panel.voice_button.isChecked() and pet.ui.quick.voice.isChecked()


@pytest.mark.parametrize("state", [DesktopState(0, False, False), DesktopState(123, False, True)])
def test_wake_defers_voice_until_desktop_is_available(pet, monkeypatch, state):
    """抑制状态中唤醒只恢复选择；可用桌面出现后才实际恢复收音。"""
    desktop = resource_desktop(pet, monkeypatch, state)
    pet.voice(True)
    pet.toggle_sleep()
    pet.fullscreen = True  # 模拟休眠期间已获知桌面抑制状态。
    pet.toggle_sleep()

    assert not pet.paused and pet.voice_enabled
    assert not pet.runtime.listening
    pet._resources()
    assert not pet.runtime.listening

    desktop.state = DesktopState(123, False, False)
    pet._resources()

    assert not pet.fullscreen and pet.runtime.listening
    assert pet.voice_enabled
    assert pet.panel.voice_button.isChecked() and pet.ui.quick.voice.isChecked()
