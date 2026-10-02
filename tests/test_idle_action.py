"""久置待机动作的计时边界与重置行为。"""

from types import SimpleNamespace

from PySide6.QtCore import QObject

from pet.app import DesktopPet
from pet.desktop import DesktopState
from pet.idle_action import IdleActionTimer
from pet.mouse_monitor import MouseMonitor


def test_action_starts_only_after_five_minutes_and_only_once():
    """连续空闲刚满五分钟时触发一次，当前空闲周期不会重复播放。"""
    timer = IdleActionTimer(inactivity_seconds=300)

    assert not timer.poll(10, eligible=True)
    assert not timer.poll(309.99, eligible=True)
    assert timer.poll(310, eligible=True)
    assert not timer.poll(900, eligible=True)


def test_new_input_restarts_the_idle_countdown():
    """任意新输入会重置倒计时，并开启新的单次播放周期。"""
    timer = IdleActionTimer(inactivity_seconds=300)
    timer.poll(0, eligible=True)
    timer.record_input(120)

    assert not timer.poll(419.99, eligible=True)
    assert timer.poll(420, eligible=True)


def test_ineligible_state_restarts_countdown_when_it_becomes_eligible():
    """休眠、对话或全屏期间不累计空闲时间，恢复后从零计时。"""
    timer = IdleActionTimer(inactivity_seconds=300)
    timer.poll(0, eligible=True)

    assert not timer.poll(500, eligible=False)
    assert not timer.poll(501, eligible=True)
    assert not timer.poll(800.99, eligible=True)
    assert timer.poll(801, eligible=True)


def test_initially_ineligible_timer_waits_for_first_eligible_poll():
    """应用启动时已有很长系统空闲，也不能立即触发动作。"""
    timer = IdleActionTimer(inactivity_seconds=300)

    assert not timer.poll(3600, eligible=False)
    assert not timer.poll(7200, eligible=True)
    assert not timer.poll(7499.99, eligible=True)
    assert timer.poll(7500, eligible=True)


def test_clock_rollback_does_not_trigger_early():
    """注入的时间早于最近活动时，不会错误地满足空闲时长。"""
    timer = IdleActionTimer(inactivity_seconds=300)
    timer.poll(100, eligible=True)
    timer.record_input(200)

    assert not timer.poll(150, eligible=True)
    assert not timer.poll(499.99, eligible=True)
    assert timer.poll(500, eligible=True)


def test_system_input_timestamp_change_emits_activity_without_payload():
    """系统输入只发出无参数活动信号，不暴露键值或鼠标内容。"""

    class FakeSampler:
        available = True

        def __init__(self):
            self.tick = 20

        def read(self):
            return self.tick

    monitor = MouseMonitor.__new__(MouseMonitor)
    QObject.__init__(monitor)
    monitor._system_input = FakeSampler()
    monitor._last_input_tick = 20
    monitor.input_monitor_available = True
    activities = []
    monitor.activity.connect(lambda: activities.append(True))

    monitor._poll_system_input()
    monitor._system_input.tick = 21
    monitor._poll_system_input()
    monitor._poll_system_input()

    assert activities == [True]


def test_system_input_sampling_failure_disables_idle_detection(caplog):
    """API 采样失败后关闭新功能，不反复调用失效接口。"""

    class FailedSampler:
        available = False

        def read(self):
            raise AssertionError("已禁用时不得再次读取")

    monitor = MouseMonitor.__new__(MouseMonitor)
    QObject.__init__(monitor)
    monitor._system_input = FailedSampler()
    monitor._last_input_tick = 0
    monitor.input_monitor_available = False

    monitor._poll_system_input()

    assert not monitor.input_monitor_available


def test_desktop_pet_starts_the_animation_after_five_eligible_minutes():
    """资源轮询只在持续可用的 Live2D 空闲状态触发一次动作。"""
    starts = []
    avatar = SimpleNamespace(
        supports_idle_blade=True,
        animation="idle",
        start_idle_blade=lambda: starts.append("start") or True,
        interrupt_idle_blade=lambda fade=True: None,
    )
    pet = SimpleNamespace(
        monitor=SimpleNamespace(input_monitor_available=True),
        avatar=avatar,
        idle_action=IdleActionTimer(inactivity_seconds=300),
        paused=False,
        busy=False,
        fullscreen=False,
        runtime=SimpleNamespace(listening=False),
    )
    desktop = DesktopState(123, False, False)

    DesktopPet._update_idle_action(pet, desktop, 0)
    DesktopPet._update_idle_action(pet, desktop, 299.99)
    DesktopPet._update_idle_action(pet, desktop, 300)
    DesktopPet._update_idle_action(pet, desktop, 900)

    assert starts == ["start"]


def test_desktop_pet_restarts_idle_count_after_a_suppressed_state():
    """繁忙、休眠或全屏后必须重新静止五分钟才会触发动作。"""
    starts = []
    avatar = SimpleNamespace(
        supports_idle_blade=True,
        animation="idle",
        start_idle_blade=lambda: starts.append("start") or True,
        interrupt_idle_blade=lambda fade=True: None,
    )
    pet = SimpleNamespace(
        monitor=SimpleNamespace(input_monitor_available=True),
        avatar=avatar,
        idle_action=IdleActionTimer(inactivity_seconds=300),
        paused=False,
        busy=False,
        fullscreen=False,
        runtime=SimpleNamespace(listening=False),
    )
    desktop = DesktopState(123, False, False)

    DesktopPet._update_idle_action(pet, desktop, 0)
    pet.busy = True
    DesktopPet._update_idle_action(pet, desktop, 300)
    pet.busy = False
    DesktopPet._update_idle_action(pet, desktop, 301)
    DesktopPet._update_idle_action(pet, desktop, 600.99)
    DesktopPet._update_idle_action(pet, desktop, 601)

    assert starts == ["start"]


def test_keyboard_or_mouse_activity_cancels_and_restarts_the_countdown(monkeypatch):
    """系统活动信号会立即淡出动作，并按活动时刻重置计时。"""
    cancelled = []
    pet = SimpleNamespace(
        idle_action=IdleActionTimer(inactivity_seconds=300),
        avatar=SimpleNamespace(
            interrupt_idle_blade=lambda: cancelled.append("idle"),
            cancel_motion=lambda: cancelled.append("native"),
        ),
    )
    pet.idle_action.poll(0, eligible=True)
    monkeypatch.setattr("pet.app.time.monotonic", lambda: 120)

    DesktopPet._on_system_activity(pet)

    assert cancelled == ["idle", "native"]
    assert not pet.idle_action.poll(419.99, eligible=True)
    assert pet.idle_action.poll(420, eligible=True)
