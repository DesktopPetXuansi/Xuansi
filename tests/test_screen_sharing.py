"""The capture and provider boundaries use synthetic frames and mock HTTP."""

import asyncio
import json
import threading
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from pet.ai.providers import create_provider
from pet.ai.providers.base import ProviderError
from pet.ai.selection import Candidate, InferenceRouter
from pet.ai.settings import ModelProfile
from pet.config import Settings, load_settings, save_settings
from pet.conversation import converse
from pet.inference import request_messages
from pet.runtime import Runtime
from pet.screen_sharing import (
    ScreenGrant,
    ScreenShareError,
    ScreenTurn,
    local_screen_destination,
    screen_turn,
)
from pet.tool_protocol import AssistantReply


def profile(provider="openai"):
    value = ModelProfile(provider=provider, endpoint="https://example.test/v1", model="vision",
                         capabilities=("text", "image", "tools"), context_tokens=32768)
    return replace(value, verified_at="test", verified_capabilities=value.capabilities,
                   verification_fingerprint=value.fingerprint())


def grant(runtime, settings, online=None):
    return ScreenGrant(runtime.screen_version, runtime.epoch, (-320, 200), "nearby", 11,
                       online.fingerprint() if online else "", local_screen_destination(settings))


def dialogue(engine, monkeypatch, *, mode="manual"):
    monkeypatch.setattr("pet.conversation.desktop_state", lambda: SimpleNamespace(hwnd=11))
    runtime = SimpleNamespace(
        epoch=1, screen_version=1, screen_mode=mode, listening=True, history=[], engine=engine,
        microphone=SimpleNamespace(muted=threading.Event()), audio=SimpleNamespace(configure_root=Mock()),
        motion_actions=(), should_speak=lambda *_: False, speech_override=None,
    )
    for name in ("reply", "heard", "state", "finished", "failed", "request_issue", "chat_succeeded"):
        setattr(runtime, name, SimpleNamespace(emit=Mock()))
    return runtime


def test_old_settings_do_not_grant_sharing_or_upgrade_to_full_screen(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"name": "旧人设", "observe": True, "capture_scope": "screen",
                               "ai": {"cloud_observation": True}}), encoding="utf-8")
    settings = load_settings(path)
    assert (settings.name, settings.screen_mode, settings.capture_scope) == ("旧人设", "off", "nearby")
    save_settings(replace(settings, screen_mode="manual", capture_scope="screen"), path)
    settings = load_settings(path)
    assert (settings.screen_mode, settings.capture_scope) == ("manual", "screen")


@pytest.mark.asyncio
async def test_local_image_and_derived_reply_never_reach_next_online_request(monkeypatch):
    requests = []

    async def send(request):
        requests.append(json.loads(request.content))
        event = {"choices": [{"delta": {"content": "在线纯文字"}, "finish_reason": "stop"}]}
        return httpx.Response(200, text=f"data: {json.dumps(event)}\n\ndata: [DONE]\n\n")

    online = profile()
    adapter = create_provider(online, key="test", transport=httpx.MockTransport(send))
    local = SimpleNamespace(
        start=AsyncMock(), stop=AsyncMock(), complete=AsyncMock(return_value=AssistantReply("画面专属内容")),
    )
    router = InferenceRouter(local=local, local_candidates=lambda settings: [Candidate("local", settings)],
                             provider_factory=lambda _: adapter)
    runtime = dialogue(router, monkeypatch)
    settings = Settings()
    runtime.history.extend([{"role": "user", "content": "之前的普通问题"},
                            {"role": "assistant", "content": "之前的普通回复"}])
    capture = Mock(return_value=b"synthetic private frame")
    monkeypatch.setattr("pet.conversation.capture_screen", capture)
    try:
        await converse(runtime, 1, settings, "这条只用于截图轮", "chat-screen", None, None,
                       screen=grant(runtime, settings))
        local_messages = local.complete.await_args.args[1]
        assert local_messages[-1]["content"][1]["type"] == "image_url"
        assert runtime.reply.emit.call_args.args[1] == "画面专属内容"
        assert capture.call_count == 1

        runtime.screen_mode, runtime.screen_version, runtime.epoch = "off", 2, 2
        settings = replace(settings, ai=replace(settings.ai, policy="online_first", profile=online))
        await converse(runtime, 2, settings, "继续普通文字聊天", "chat", (-320, 200), None)
        assert len(requests) == 1
        actual = json.dumps(requests[0], ensure_ascii=False)
        assert "之前的普通回复" in actual
        assert "继续普通文字聊天" in actual
        for forbidden in ("image_url", "capture_screen", "画面专属内容", "这条只用于截图轮"):
            assert forbidden not in actual
        assert capture.call_count == 1
    finally:
        await router.stop()


@pytest.mark.parametrize("change", ["disabled", "focus", "revoked_while_capturing", "another_turn"])
@pytest.mark.asyncio
async def test_stale_screen_cannot_capture_or_deliver(monkeypatch, change):
    engine = SimpleNamespace(start=AsyncMock(), complete=AsyncMock())
    runtime = dialogue(engine, monkeypatch)
    settings = Settings()
    screen = grant(runtime, settings)

    def capture(*_args, check):
        check()
        runtime.screen_version += 1
        return b"late synthetic frame"

    worker = Mock(side_effect=capture)
    monkeypatch.setattr("pet.conversation.capture_screen", worker)
    if change == "disabled":
        runtime.screen_mode = "off"
    elif change == "focus":
        monkeypatch.setattr("pet.conversation.desktop_state", lambda: SimpleNamespace(hwnd=12))
    elif change == "another_turn":
        runtime.epoch += 1
    await converse(runtime, runtime.epoch, settings, "看看", "chat-screen", None, None, screen=screen)
    assert worker.call_count == int(change == "revoked_while_capturing")
    engine.complete.assert_not_awaited()
    runtime.reply.emit.assert_not_called()
    assert not runtime.microphone.muted.is_set()


@pytest.mark.asyncio
async def test_late_image_reply_is_discarded_without_changing_plain_history(monkeypatch):
    async def complete(*_args, **_kwargs):
        runtime.screen_version += 1
        return AssistantReply("截图已经撤回，旧模型才返回这段内容。")

    runtime = dialogue(SimpleNamespace(start=AsyncMock(), complete=complete), monkeypatch)
    monkeypatch.setattr("pet.conversation.capture_screen", Mock(return_value=b"synthetic"))
    settings = Settings()
    await converse(runtime, 1, settings, "看图", "chat-screen", None, None, screen=grant(runtime, settings))
    runtime.reply.emit.assert_not_called()
    assert runtime.history == [] and not runtime.microphone.muted.is_set()


def test_legacy_settings_cannot_start_an_observation_without_a_session_grant(monkeypatch):
    runtime = SimpleNamespace(epoch=7, schedule=Mock())
    monkeypatch.setattr("pet.conversation.capture_screen", Mock(side_effect=AssertionError))
    assert Runtime.ask(runtime, Settings(observe=True), "", kind="observation", position=(2, 2)) == 7
    runtime.schedule.assert_not_called()


def test_automatic_grant_requires_runtime_opt_in_and_is_revoked_immediately():
    runtime = SimpleNamespace(epoch=5, screen_version=1, screen_mode="off", automatic_observation=False,
                              listening=False, quiet_until=0)
    settings = Settings()
    authorization = replace(grant(runtime, settings), automatic=True)
    turn = ScreenTurn(runtime, 5, authorization)
    assert not turn.current()
    runtime.automatic_observation = True
    assert turn.current()
    runtime.listening = True
    assert not turn.current()
    runtime.listening = False
    runtime.screen_version += 1
    assert not turn.current()


@pytest.mark.asyncio
async def test_automatic_observation_uses_local_model_deduplicates_and_keeps_private_history(monkeypatch):
    import time

    online = profile()
    settings = Settings()
    settings = replace(settings, ai=replace(settings.ai, policy="online_first", profile=online))
    local = SimpleNamespace(start=AsyncMock(), stop=AsyncMock(),
                            complete=AsyncMock(return_value=AssistantReply("构建失败。")))
    remote = Mock()
    router = InferenceRouter(local=local, local_candidates=lambda item: [Candidate("local", item)],
                             provider_factory=remote)
    runtime = dialogue(router, monkeypatch, mode="off")
    runtime.listening = False
    runtime.automatic_observation = True
    runtime.observation_frames = {}
    runtime.proactive_limiter = SimpleNamespace(available=lambda *_: True)
    runtime.deliver_observation = AsyncMock(return_value=True)
    monkeypatch.setattr("pet.conversation.observation_current", lambda _: True)
    monkeypatch.setattr("pet.model_tools.observation_current", lambda _: True)
    capture = Mock(return_value=b"same frame")
    monkeypatch.setattr("pet.conversation.capture_screen", capture)
    for epoch in (1, 2):
        runtime.epoch = epoch
        screen = replace(grant(runtime, settings), automatic=True)
        await converse(runtime, epoch, settings, "观察", "observation", None, None, (11, time.monotonic()),
                       screen=screen)
    assert capture.call_count == 2 and local.complete.await_count == 1
    runtime.deliver_observation.assert_awaited_once()
    remote.assert_not_called()
    runtime.reply.emit.assert_not_called()
    assert runtime.history == []


@pytest.mark.parametrize(("provider", "data"), [
    ("openai", {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}),
    ("gemini", {"candidates": [{"content": {"parts": [{"text": "ok"}]}, "finishReason": "STOP"}]}),
    ("claude", {"content": [{"type": "text", "text": "ok"}], "stop_reason": "end_turn"}),
])
@pytest.mark.asyncio
async def test_online_adapter_sends_only_to_authorized_profile_and_skips_remote_count(monkeypatch, provider, data):
    requests = []

    async def send(request):
        requests.append(request)
        return httpx.Response(200, json=data)

    online = profile(provider)
    adapter = create_provider(online, key="test", transport=httpx.MockTransport(send))
    changed = create_provider(replace(online, endpoint="https://different.test/v1"), key="test",
                              transport=httpx.MockTransport(send))
    runtime = dialogue(adapter, monkeypatch)
    settings = Settings()
    messages = request_messages(settings, "看图", [b"synthetic"], [])
    scope = screen_turn.set(ScreenTurn(runtime, 1, grant(runtime, settings, online)))
    try:
        assert (await adapter.complete(settings, messages, stream=False)).content == "ok"
        assert len(requests) == 1 and requests[0].url.host == "example.test"
        assert "count" not in requests[0].url.path
        assert b"c3ludGhldGlj" in requests[0].content
        with pytest.raises(ScreenShareError):
            await changed.complete(settings, messages, stream=False)
        runtime.screen_version += 1
        with pytest.raises(ScreenShareError):
            await adapter.complete(settings, messages, stream=False)
        with pytest.raises(ScreenShareError):
            await anext(adapter.events(settings, "generation", {}))
        assert len(requests) == 1
    finally:
        screen_turn.reset(scope)
        await adapter.stop()
        await changed.stop()


@pytest.mark.asyncio
async def test_failed_local_screen_route_never_falls_back_to_cloud(monkeypatch):
    online = profile()
    settings = Settings()
    online = replace(online, capabilities=("text", "image", "tools", "stream", "cancel"),
                     verified_capabilities=("text", "image", "tools", "stream", "cancel"))
    online = replace(online, verification_fingerprint=online.fingerprint())
    settings = replace(settings, ai=replace(settings.ai, policy="local_first", profile=online))
    local = SimpleNamespace(start=AsyncMock(side_effect=ProviderError("resource", "test")))
    factory = Mock()
    router = InferenceRouter(local=local, local_candidates=lambda item: [Candidate("primary", item)],
                             provider_factory=factory)
    runtime = dialogue(router, monkeypatch)
    capture = Mock()
    monkeypatch.setattr("pet.conversation.capture_screen", capture)
    await converse(runtime, 1, settings, "这轮看图", "chat-screen", None, None, screen=grant(runtime, settings))
    local.start.assert_awaited_once()
    factory.assert_not_called()
    capture.assert_not_called()
    assert runtime.request_issue.emit.call_args.args[1].action == "chat"


@pytest.mark.asyncio
async def test_revoke_save_failure_stays_off_and_does_not_cancel_plain_chat(monkeypatch):
    tasks = []
    runtime = SimpleNamespace(
        screen_mode="manual", screen_version=4, screen_epoch=None, epoch=8, listening=True,
        current_settings=Settings(screen_mode="manual"), storage_control=asyncio.Lock(), cancel=Mock(),
        screen_mode_saved=SimpleNamespace(emit=Mock()),
        schedule=lambda work: tasks.append(asyncio.create_task(work)),
    )
    runtime.invalidate_screen = lambda: Runtime.invalidate_screen(runtime)
    monkeypatch.setattr("pet.runtime.save_settings", Mock(side_effect=OSError))
    Runtime.set_screen_mode(runtime, "off")
    assert runtime.screen_mode == "off" and runtime.screen_version == 5
    await tasks[0]
    runtime.cancel.assert_not_called()
    assert runtime.listening and "未能保存" in runtime.screen_mode_saved.emit.call_args.args[1]
