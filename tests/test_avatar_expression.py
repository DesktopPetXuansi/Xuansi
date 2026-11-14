"""回复表情只驱动内置角色的眼睑，并遵守既有动作优先级。"""

from types import SimpleNamespace

import pytest

from pet.avatar import Avatar
from pet.avatar_expression import EXPRESSION_PARAMETERS, EXPRESSION_PRESETS, ReplyExpression
from pet.avatar_live2d import AvatarLive2D


def expression_owner(**overrides):
    """以固定状态代替原生窗口，避免测试访问用户桌面或创建 GL。"""
    blink_enabled = []
    owner = SimpleNamespace(
        _reply_expression=ReplyExpression(), _live2d_active=True,
        _live2d_model=SimpleNamespace(SetAutoBlinkEnable=blink_enabled.append),
        _live2d_parameter_ids=frozenset(EXPRESSION_PARAMETERS), _platform_model_version="",
        _platform_expression=False, _motion_name=None, animation="idle", paused=False,
        _idle_blade_started=None, isVisible=lambda: True, update=lambda: None, blink_enabled=blink_enabled,
    )
    for key, value in overrides.items():
        setattr(owner, key, value)
    owner.clear_reply_expression = lambda: AvatarLive2D.clear_reply_expression(owner)
    return owner


def test_expression_fades_in_holds_and_returns_to_neutral():
    state = ReplyExpression()
    state.set("happy", 10.0)
    target = EXPRESSION_PRESETS["happy"]
    neutral = EXPRESSION_PRESETS["neutral"]

    assert state.values(10.0) == pytest.approx(neutral)
    assert state.values(10.175) == pytest.approx(tuple((start + end) * 0.5 for start, end in zip(neutral, target)))
    assert state.values(10.35) == pytest.approx(target)
    assert state.values(14.35) == pytest.approx(target)
    assert state.values(14.525) == pytest.approx(tuple((start + end) * 0.5 for start, end in zip(neutral, target)))
    assert state.values(14.7) == pytest.approx(neutral)
    assert state.name == "neutral"


def test_new_expression_preserves_current_value_before_transition():
    state = ReplyExpression()
    state.set("happy", 10.0)
    previous = state.values(10.2)
    state.set("concern", 10.2)

    assert state.values(10.2) == pytest.approx(previous)
    assert state.values(10.55) == pytest.approx(EXPRESSION_PRESETS["concern"])


def test_unknown_expression_fades_to_neutral_without_executing_actions():
    state = ReplyExpression()
    state.set("happy", 10.0)
    state.set("[motion:blink]", 11.0)

    assert state.name == "neutral"
    assert state.values(11.35) == pytest.approx(EXPRESSION_PRESETS["neutral"])


@pytest.mark.parametrize("blocked", [
    {"_live2d_active": False}, {"_platform_model_version": "external-model"},
    {"_platform_expression": True}, {"_motion_name": "blink"}, {"animation": "sleep"},
    {"paused": True}, {"_idle_blade_started": 9.0}, {"isVisible": lambda: False},
    {"_live2d_parameter_ids": frozenset({"ParamMouthForm"})},
])
def test_unavailable_or_higher_priority_state_rejects_reply_expression(monkeypatch, blocked):
    owner = expression_owner(**blocked)
    monkeypatch.setattr("pet.avatar_live2d.time.monotonic", lambda: 10.0)

    assert not AvatarLive2D.set_reply_expression(owner, "happy")
    assert owner._reply_expression.name == "neutral"


def test_reply_expression_is_accepted_without_touching_model_or_speech(monkeypatch):
    owner = expression_owner()
    monkeypatch.setattr("pet.avatar_live2d.time.monotonic", lambda: 10.0)

    assert AvatarLive2D.set_reply_expression(owner, "curious")
    values = AvatarLive2D._reply_expression_parameter_values(owner, 10.35)

    assert values == dict(zip(EXPRESSION_PARAMETERS, EXPRESSION_PRESETS["curious"]))
    assert set(values) == {"ParamEyeLOpen", "ParamEyeROpen"}
    assert "ParamMouthOpenY" not in values
    assert owner.blink_enabled == [False]


def test_reply_expression_still_blinks_then_restores_the_expression():
    state = ReplyExpression()
    state.set("happy", 10.0)

    assert state.eye_values(11.7) == pytest.approx((0.0, 0.0))
    assert state.eye_values(12.0) == pytest.approx(EXPRESSION_PRESETS["happy"])


def test_motion_clears_pending_expression_and_cannot_replay_after_completion(monkeypatch):
    owner = expression_owner()
    monkeypatch.setattr("pet.avatar_live2d.time.monotonic", lambda: 10.0)
    AvatarLive2D.set_reply_expression(owner, "happy")
    owner._motion_name = "blink"

    assert AvatarLive2D._reply_expression_parameter_values(owner, 10.35) == dict.fromkeys(EXPRESSION_PARAMETERS, 1.0)
    owner._motion_name = None
    assert AvatarLive2D._reply_expression_parameter_values(owner, 10.4) == {}
    assert owner._reply_expression.name == "neutral"


def test_explicit_clear_discards_expression_without_waiting_for_fade(monkeypatch):
    owner = expression_owner()
    monkeypatch.setattr("pet.avatar_live2d.time.monotonic", lambda: 10.0)
    AvatarLive2D.set_reply_expression(owner, "concern")

    AvatarLive2D.clear_reply_expression(owner)

    assert owner._reply_expression.name == "neutral"
    assert owner._reply_expression.values(10.2) == EXPRESSION_PRESETS["neutral"]
    assert owner.blink_enabled == [False, True]


def test_rejected_reply_during_idle_action_restores_sdk_blink(monkeypatch):
    """待机动作打断回复表情时，之后的普通眨眼不能一直被关闭。"""
    owner = expression_owner()
    monkeypatch.setattr("pet.avatar_live2d.time.monotonic", lambda: 10.0)
    assert AvatarLive2D.set_reply_expression(owner, "happy")
    owner._idle_blade_started = 10.1

    assert not AvatarLive2D.set_reply_expression(owner, "curious")
    assert owner.blink_enabled == [False, True]
    assert owner._reply_expression.started is None


def test_rejected_reply_does_not_override_platform_expression(monkeypatch):
    """平台表情拥有自己的眼睑控制，回复被拒绝时不改变其眨眼设置。"""
    owner = expression_owner()
    monkeypatch.setattr("pet.avatar_live2d.time.monotonic", lambda: 10.0)
    assert AvatarLive2D.set_reply_expression(owner, "happy")
    owner._platform_expression = True

    assert not AvatarLive2D.set_reply_expression(owner, "curious")
    assert owner.blink_enabled == [False]


def test_idle_action_interrupts_active_expression_and_restores_blink(monkeypatch):
    """待机姿态开始后，即使没有新回复，也要恢复之后的普通眨眼。"""
    owner = expression_owner()
    monkeypatch.setattr("pet.avatar_live2d.time.monotonic", lambda: 10.0)
    assert AvatarLive2D.set_reply_expression(owner, "happy")
    owner._idle_blade_started = 10.1

    AvatarLive2D._reply_expression_parameter_values(owner, 10.2)
    assert owner._reply_expression.started is None
    assert owner.blink_enabled == [False, True]


def test_idle_expression_does_not_repeat_native_parameter_writes():
    owner = expression_owner()

    assert AvatarLive2D._reply_expression_parameter_values(owner, 10.0) == {}
    assert AvatarLive2D._reply_expression_parameter_values(owner, 11.0) == {}


def test_reply_completion_does_not_reenable_sdk_blink_during_expression():
    blink = []
    expression = ReplyExpression()
    expression.set("happy", 10.0)
    owner = SimpleNamespace(
        animation="thinking", frames={"idle": ()}, native_animation=True,
        _reply_expression=expression, _live2d_active=True, _motion_name=None, _platform_model_version="",
        _live2d_model=SimpleNamespace(SetAutoBlinkEnable=blink.append, SetParameterValue=lambda *_: None),
        update=lambda: None,
    )

    Avatar.set_animation(owner, "idle")

    assert blink == [False]
