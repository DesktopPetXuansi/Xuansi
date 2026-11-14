"""主动问候不抢占用户任务，仅将实际交付内容交给下一轮真人对话。"""

import asyncio
import time
from concurrent.futures import Future
from dataclasses import replace
from types import MethodType, SimpleNamespace

import pytest

from pet.config import Settings
from pet.runtime import Runtime


def fake_runtime():
    offered, finished, reservations = [], [], []
    settings = replace(Settings(), proactive_chat=True, speak_replies=False)
    runtime = SimpleNamespace(
        epoch=2, listening=False, job=None, current_settings=settings,
        control=asyncio.Lock(), storage_control=asyncio.Lock(),
        proactive_limiter=SimpleNamespace(reserve=lambda now: reservations.append(now) or "想聊两句吗？"),
        proactive_ready=SimpleNamespace(emit=lambda epoch, text: offered.append((epoch, text))),
        finished=SimpleNamespace(emit=lambda epoch: finished.append(epoch)),
        should_speak=lambda *_: False,
        _proactive_delivery=None, _proactive_context=None,
        loop=asyncio.get_running_loop(), offered=offered, finished_epochs=finished,
        reservations=reservations,
    )
    runtime._run_proactive = MethodType(Runtime._run_proactive, runtime)
    return runtime, settings


@pytest.mark.asyncio
@pytest.mark.parametrize("blocked", ["disabled", "busy", "listening", "stale", "saving"])
async def test_runtime_rejects_proactive_before_reservation(blocked):
    runtime, settings = fake_runtime()
    candidate_epoch = runtime.epoch
    active = None
    if blocked == "disabled":
        settings = replace(settings, proactive_chat=False)
    elif blocked == "busy":
        active = runtime.job = asyncio.create_task(asyncio.sleep(30))
    elif blocked == "listening":
        runtime.listening = True
    elif blocked == "stale":
        runtime.epoch += 1
    else:
        await runtime.storage_control.acquire()
    try:
        await Runtime._try_proactive(runtime, candidate_epoch, settings)
        assert runtime.reservations == [] and runtime.offered == []
        if active:
            assert not active.cancelled() and runtime.job is active
    finally:
        if active:
            active.cancel()
            await asyncio.gather(active, return_exceptions=True)
        if runtime.storage_control.locked():
            runtime.storage_control.release()


@pytest.mark.asyncio
async def test_display_acknowledgment_is_required_for_next_turn_context():
    runtime, settings = fake_runtime()
    await Runtime._try_proactive(runtime, 2, settings)
    await asyncio.sleep(0)
    assert runtime.offered == [(3, "想聊两句吗？")]
    assert runtime._proactive_context is None
    Runtime.resolve_proactive(runtime, 3, True, "想聊两句吗？")
    await runtime.job
    assert Runtime.consume_proactive_context(runtime) == "想聊两句吗？"
    assert Runtime.consume_proactive_context(runtime) == ""
    assert runtime.finished_epochs == [3]


@pytest.mark.asyncio
async def test_rejected_or_cancelled_offer_does_not_become_context():
    runtime, settings = fake_runtime()
    await Runtime._try_proactive(runtime, 2, settings)
    await asyncio.sleep(0)
    Runtime.resolve_proactive(runtime, 3, False, "想聊两句吗？")
    await runtime.job
    assert Runtime.consume_proactive_context(runtime) == ""
    await Runtime._try_proactive(runtime, 3, settings)
    await asyncio.sleep(0)
    runtime.epoch += 1
    runtime.job.cancel()
    await asyncio.gather(runtime.job, return_exceptions=True)
    Runtime.resolve_proactive(runtime, 4, True, "想聊两句吗？")
    await asyncio.sleep(0)
    assert Runtime.consume_proactive_context(runtime) == ""


@pytest.mark.asyncio
async def test_user_input_during_disk_reservation_is_not_replaced():
    runtime, settings = fake_runtime()

    def reserve(_now):
        runtime.epoch += 1
        return "不能展示的旧问候"

    runtime.proactive_limiter.reserve = reserve
    await Runtime._try_proactive(runtime, 2, settings)
    assert runtime.job is None and runtime.offered == [] and runtime.epoch == 3


@pytest.mark.asyncio
async def test_old_proactive_greeting_is_not_described_as_recent():
    runtime, _ = fake_runtime()
    runtime._proactive_context = ("过期问候", time.monotonic() - 601)
    assert Runtime.consume_proactive_context(runtime) == ""


@pytest.mark.asyncio
async def test_pending_offer_expires_with_future_or_epoch():
    runtime, _ = fake_runtime()
    future = Future()
    runtime._proactive_delivery = (2, "仅测试", future)
    assert Runtime.proactive_pending(runtime, 2)
    runtime.epoch += 1
    assert not Runtime.proactive_pending(runtime, 2)
    runtime.epoch = 2
    future.cancel()
    assert not Runtime.proactive_pending(runtime, 2)


@pytest.mark.asyncio
async def test_greeting_displayed_before_timeout_cleanup_remains_context():
    """界面显示期间恰好超时，已经显示的文字仍可衔接下一轮。"""
    runtime, _ = fake_runtime()
    runtime._proactive_delivery = None  # 显示前已验过 pending，显示期间被后台超时清理。

    Runtime.resolve_proactive(runtime, 2, True, "想聊两句吗？")

    assert Runtime.consume_proactive_context(runtime) == "想聊两句吗？"


@pytest.mark.asyncio
async def test_failed_or_obsolete_display_never_becomes_context():
    runtime, _ = fake_runtime()
    Runtime.resolve_proactive(runtime, 2, False, "没有显示")
    Runtime.resolve_proactive(runtime, 1, True, "过期问候")
    assert Runtime.consume_proactive_context(runtime) == ""
