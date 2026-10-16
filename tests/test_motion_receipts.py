"""每次动作请求独立关联Qt回执，过期排队信号不能执行或串到新调用。"""

import asyncio
import time
from types import MethodType, SimpleNamespace
from unittest.mock import Mock

import pytest

from pet.app import DesktopPet
from pet.runtime import Runtime


def runtime():
    value = SimpleNamespace(epoch=1, motion_actions=('blink',), pending_motions={},
                            loop=asyncio.get_running_loop(), motion_requested=SimpleNamespace(emit=Mock()))
    value.motion_pending = MethodType(Runtime.motion_pending, value)
    value.resolve_motion = MethodType(Runtime.resolve_motion, value)
    return value


@pytest.mark.asyncio
async def test_late_receipt_never_completes_next_same_action(monkeypatch):
    value = runtime()
    wait_for = asyncio.wait_for
    calls = 0

    async def short_first(future, timeout):
        nonlocal calls
        calls += 1
        return await wait_for(future, 0.001 if calls == 1 else timeout)

    monkeypatch.setattr('pet.runtime.asyncio.wait_for', short_first)
    first = await Runtime.request_motion(value, 1, 'blink')
    assert first == {'status': 'unknown'}
    first_id = value.motion_requested.emit.call_args.args[2]
    second = asyncio.create_task(Runtime.request_motion(value, 1, 'blink'))
    await asyncio.sleep(0)
    second_id = value.motion_requested.emit.call_args.args[2]
    assert first_id != second_id
    assert not value.motion_pending(1, 'blink', first_id)
    assert value.motion_pending(1, 'blink', second_id)
    value.resolve_motion(first_id, 'completed')
    await asyncio.sleep(0)
    assert not second.done()
    value.resolve_motion(second_id, 'rejected')
    assert await second == {'status': 'rejected'}
    assert value.pending_motions == {}


@pytest.mark.asyncio
async def test_qt_does_not_execute_expired_or_wrong_request():
    value = runtime()
    app = SimpleNamespace(runtime=value, paused=False, fullscreen=False,
                          avatar=SimpleNamespace(isVisible=lambda: True, play_motion=Mock(return_value=True)))
    task = asyncio.create_task(Runtime.request_motion(value, 1, 'blink'))
    await asyncio.sleep(0)
    request_id = value.motion_requested.emit.call_args.args[2]
    assert not value.motion_pending(1, 'different', request_id)
    assert not value.motion_pending(2, 'blink', request_id)
    pending = value.pending_motions[request_id]
    value.pending_motions[request_id] = (*pending[:3], time.monotonic() - 1)
    DesktopPet._execute_motion(app, 1, 'blink', request_id)
    app.avatar.play_motion.assert_not_called()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_current_qt_request_waits_for_actual_completion():
    value = runtime()
    app = SimpleNamespace(runtime=value, paused=False, fullscreen=False,
                          avatar=SimpleNamespace(isVisible=lambda: True, play_motion=Mock(return_value=True)))
    task = asyncio.create_task(Runtime.request_motion(value, 1, 'blink'))
    await asyncio.sleep(0)
    request_id = value.motion_requested.emit.call_args.args[2]
    DesktopPet._execute_motion(app, 1, 'blink', request_id)
    await asyncio.sleep(0)
    assert not task.done()  # 开始播放不能冒充完成。
    app.avatar.play_motion.assert_called_once_with('blink', request_id=request_id)
    value.resolve_motion(request_id, 'completed')
    assert await task == {'status': 'completed'}
    assert not value.motion_pending(1, 'blink', request_id)
    assert value.pending_motions == {}


@pytest.mark.asyncio
async def test_interrupted_animation_is_not_reported_as_completed():
    value = runtime()
    task = asyncio.create_task(Runtime.request_motion(value, 1, 'blink'))
    await asyncio.sleep(0)
    request_id = value.motion_requested.emit.call_args.args[2]
    value.resolve_motion(request_id, 'cancelled')
    assert await task == {'status': 'cancelled'}
