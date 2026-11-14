"""主动问候的界面门控和下一轮上下文，不产生伪造的用户消息。"""

from types import MethodType, SimpleNamespace

import pytest

from pet.app import DesktopPet
from pet.config import Settings
from pet.desktop import DesktopState
from pet.proactive_chat import ProactiveGate
from pet.tool_dialogue import run_dialogue
from pet.tool_protocol import AssistantReply


def fake_pet():
    offers, acknowledgments, displayed = [], [], []
    runtime = SimpleNamespace(
        epoch=4, listening=False, audio_activity=SimpleNamespace(blocked=False),
        request_proactive=lambda settings: offers.append(settings),
        resolve_proactive=lambda epoch, accepted, _text: acknowledgments.append((epoch, accepted)),
        proactive_pending=lambda _epoch: True,
    )
    avatar = SimpleNamespace(
        animation="idle", _motion_name=None, _idle_blade_started=None, isVisible=lambda: True,
        bubble=SimpleNamespace(present=lambda text, _avatar: displayed.append(("bubble", text))),
    )
    pet = SimpleNamespace(
        settings=Settings(proactive_chat=True), runtime=runtime, avatar=avatar,
        monitor=SimpleNamespace(input_monitor_available=True), ui=SimpleNamespace(saving=False, refresh=lambda: None),
        panel=SimpleNamespace(append=lambda name, text: displayed.append((name, text)),
                              chat=SimpleNamespace(isVisible=lambda: False)),
        proactive_gate=ProactiveGate(0), paused=False, busy=False, fullscreen=False,
        voice_enabled=False, pressure=False, _quitting=False,
        offers=offers, acknowledgments=acknowledgments, displayed=displayed,
    )
    pet._proactive_eligible = MethodType(DesktopPet._proactive_eligible, pet)
    pet.proactive_gate.record_activity(3600)
    return pet


def test_proactive_poll_requires_opt_in_recent_activity_and_available_desktop():
    pet = fake_pet()
    desktop = DesktopState(123, False, False)
    DesktopPet._update_proactive(pet, desktop, 3599)
    assert not pet.offers
    DesktopPet._update_proactive(pet, desktop, 3600)
    assert len(pet.offers) == 1
    DesktopPet._update_proactive(pet, desktop, 3602)
    assert len(pet.offers) == 1


@pytest.mark.parametrize("blocked", ["disabled", "saving", "busy", "listening", "sound", "fullscreen", "own"])
def test_proactive_poll_does_not_attempt_when_user_work_has_priority(blocked):
    pet = fake_pet()
    desktop = DesktopState(123, False, False)
    if blocked == "disabled":
        pet.settings = Settings()
    elif blocked == "saving":
        pet.ui.saving = True
    elif blocked == "busy":
        pet.busy = True
    elif blocked == "listening":
        pet.runtime.listening = True
    elif blocked == "sound":
        pet.runtime.audio_activity.blocked = True
    elif blocked == "fullscreen":
        desktop = DesktopState(123, False, True)
    else:
        desktop = DesktopState(123, True, False)
    DesktopPet._update_proactive(pet, desktop, 3600)
    assert not pet.offers


def test_only_current_visible_proactive_message_is_acknowledged(monkeypatch):
    pet = fake_pet()
    monkeypatch.setattr("pet.app.desktop_state", lambda: DesktopState(123, False, False))
    monkeypatch.setattr("pet.app.time.monotonic", lambda: 3600)
    DesktopPet._on_proactive_ready(pet, 3, "过期问候")
    assert pet.acknowledgments == [(3, False)] and not pet.displayed
    DesktopPet._on_proactive_ready(pet, 4, "想聊两句吗？")
    assert pet.acknowledgments[-1] == (4, True)
    assert pet.displayed == [("玄司", "想聊两句吗？"), ("bubble", "想聊两句吗？")]


def test_timed_out_proactive_offer_never_reaches_interface(monkeypatch):
    pet = fake_pet()
    pet.runtime.proactive_pending = lambda _epoch: False
    monkeypatch.setattr("pet.app.desktop_state", lambda: DesktopState(123, False, False))
    monkeypatch.setattr("pet.app.time.monotonic", lambda: 3600)

    DesktopPet._on_proactive_ready(pet, 4, "已经超时的问候")

    assert not pet.displayed and pet.acknowledgments == [(4, False)]


def test_failed_panel_delivery_is_acknowledged_as_not_displayed(monkeypatch):
    pet = fake_pet()
    monkeypatch.setattr("pet.app.desktop_state", lambda: DesktopState(123, False, False))
    monkeypatch.setattr("pet.app.time.monotonic", lambda: 3600)

    def fail_display(*_args):
        raise RuntimeError("显示失败")

    pet.panel.append = fail_display
    with pytest.raises(RuntimeError, match="显示失败"):
        DesktopPet._on_proactive_ready(pet, 4, "不能显示的问候")
    assert pet.acknowledgments == [(4, False)]


def test_hidden_chat_and_failed_bubble_do_not_claim_delivery(monkeypatch):
    """仅把问候加入不可见聊天记录，不代表用户看到了它。"""
    pet = fake_pet()
    monkeypatch.setattr("pet.app.desktop_state", lambda: DesktopState(123, False, False))
    monkeypatch.setattr("pet.app.time.monotonic", lambda: 3600)

    def fail_bubble(*_args):
        raise RuntimeError("气泡显示失败")

    pet.avatar.bubble.present = fail_bubble
    DesktopPet._on_proactive_ready(pet, 4, "没有显示的问候")
    assert pet.acknowledgments == [(4, False)]


@pytest.mark.parametrize("blocked", ["saving", "busy", "listening", "fullscreen"])
def test_proactive_offer_rechecks_conditions_before_display(monkeypatch, blocked):
    pet = fake_pet()
    monkeypatch.setattr("pet.app.desktop_state", lambda: DesktopState(123, False, False))
    monkeypatch.setattr("pet.app.time.monotonic", lambda: 3600)
    if blocked == "saving":
        pet.ui.saving = True
    elif blocked == "busy":
        pet.busy = True
    elif blocked == "listening":
        pet.runtime.listening = True
    else:
        pet.fullscreen = True

    DesktopPet._on_proactive_ready(pet, 4, "不能迟到的问候")

    assert pet.acknowledgments == [(4, False)]
    assert not pet.displayed


@pytest.mark.asyncio
async def test_displayed_proactive_context_does_not_become_a_fake_user_turn():
    requests, replies = [], []
    remaining = ["想聊两句吗？"]

    async def complete(_settings, messages, tools=(), **_kwargs):
        requests.append(list(messages))
        return AssistantReply("好，想聊什么？")

    async def start(_settings):
        return None

    runtime = SimpleNamespace(
        epoch=0, history=[], motion_actions=(), engine=SimpleNamespace(start=start, complete=complete),
        should_speak=lambda *_: False,
        reply=SimpleNamespace(emit=lambda _, text, kind: replies.append((text, kind))),
        state=SimpleNamespace(emit=lambda *_: None),
        consume_proactive_context=lambda: remaining.pop() if remaining else "",
    )
    await run_dialogue(runtime, 0, Settings(), "好呀", [], "chat", None, None)
    messages = requests[0]
    assert "想聊两句吗？" in messages[0]["content"]
    assert [item["role"] for item in messages] == ["system", "user"]
    assert messages[-1]["content"] == [{"type": "text", "text": "好呀"}]
    assert [item["role"] for item in runtime.history] == ["user", "assistant"]
