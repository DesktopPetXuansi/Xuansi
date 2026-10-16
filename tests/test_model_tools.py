"""工具能力、真实结果与取消边界；全程使用临时记忆和模拟执行器。"""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from pet.config import Settings
from pet.memory import MemoryStore
from pet.model_tools import ToolContext


def context(tmp_path, **overrides):
    runtime = SimpleNamespace(
        epoch=1, memory=MemoryStore(tmp_path / "memory.json"), history=[],
        engine=SimpleNamespace(select_memory=AsyncMock(return_value="匹配事项")),
        memory_loaded=SimpleNamespace(emit=Mock()),
        set_speech_enabled=Mock(), motion_actions=("blink",),
        request_motion=AsyncMock(return_value={"status": "accepted"}),
        should_speak=Mock(return_value=False),
    )
    return ToolContext(runtime, 1, overrides.pop("settings", Settings()),
                       overrides.pop("kind", "chat"), "请记住我喜欢茶", (10, 20), None, **overrides)


def call(name, **arguments):
    return SimpleNamespace(id="call_1", name=name, arguments=json.dumps(arguments))


def result(message):
    assert message["role"] == "tool"
    assert message["tool_call_id"] == "call_1"
    return json.loads(message["content"])


@pytest.mark.asyncio
async def test_save_returns_success_only_after_actual_durable_write(tmp_path):
    ctx = context(tmp_path)
    reply = result(await ctx.execute(call("save_memory", note="我喜欢茶")))
    assert reply["ok"] is True
    assert MemoryStore(ctx.runtime.memory.path).read() == "我喜欢茶"
    ctx.runtime.memory_loaded.emit.assert_called_once_with("我喜欢茶")


@pytest.mark.asyncio
async def test_source_checks_multimodal_user_text_not_assistant(tmp_path):
    ctx = context(tmp_path)
    ctx.runtime.history = [{"role": "user", "content": [
        {"type": "text", "text": "我的密码是123456"},
        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,abc"}},
    ]}]
    assert result(await ctx.execute(call("save_memory", note="123456")))["ok"] is False
    assert not ctx.runtime.memory.path.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("name,args", [
    ("set_speech_enabled", {"enabled": "true"}),
    ("capture_screen", {"path": "C:/private"}),
    ("save_memory", {"note": ""}),
    ("save_memory", {"note": "例" * 501}),
    ("search_memory", {"query": ""}),
    ("play_motion", {"action": "unknown"}),
    ("select_tts_engine", {"engine": "other"}),
    ("missing", {}),
])
async def test_invalid_parameters_never_execute(tmp_path, name, args):
    ctx = context(tmp_path)
    assert result(await ctx.execute(call(name, **args)))["ok"] is False
    ctx.runtime.set_speech_enabled.assert_not_called()
    ctx.runtime.request_motion.assert_not_awaited()
    assert not ctx.runtime.memory.path.exists()


@pytest.mark.asyncio
async def test_memory_is_read_only_on_explicit_search_and_full_tail_reaches_selector(tmp_path):
    ctx = context(tmp_path)
    notes = "例" * 5995 + "尾部资料"
    ctx.runtime.memory.save(notes)
    ctx.runtime.engine.select_memory.assert_not_awaited()
    assert result(await ctx.execute(call("search_memory", query="尾部")))["ok"] is True
    assert ctx.runtime.engine.select_memory.await_args.args[2] == notes


@pytest.mark.asyncio
async def test_observation_has_no_mutation_capabilities_and_rejects_forged_calls(tmp_path):
    ctx = context(tmp_path, kind="observation")
    names = {tool["function"]["name"] for tool in ctx.tools()}
    assert names == {"capture_screen", "search_memory", "finish_observation"}
    for name, args in [("save_memory", {"note": "事项"}),
                       ("set_speech_enabled", {"enabled": True}),
                       ("play_motion", {"action": "blink"}),
                       ("select_tts_engine", {"engine": "natural"})]:
        assert result(await ctx.execute(call(name, **args)))["ok"] is False
    assert result(await ctx.execute(call("finish_observation")))["ok"] is True
    ctx.runtime.set_speech_enabled.assert_not_called()
    ctx.runtime.request_motion.assert_not_awaited()


@pytest.mark.asyncio
async def test_tts_explicit_natural_is_not_overridden_and_speech_does_not_touch_microphone(tmp_path):
    ctx = context(tmp_path, settings=Settings(tts_engine="natural"))
    reply = result(await ctx.execute(call("select_tts_engine", engine="fast")))
    assert reply["ok"] is True
    assert ctx.selected_tts == "natural"
    assert result(await ctx.execute(call("set_speech_enabled", enabled=False)))["ok"] is True
    ctx.runtime.set_speech_enabled.assert_called_once_with(False)


@pytest.mark.asyncio
async def test_motion_returns_actual_qt_receipt_and_dynamic_capability(tmp_path):
    ctx = context(tmp_path)
    assert result(await ctx.execute(call("play_motion", action="blink")))["result"] == {"status": "accepted"}
    ctx.runtime.request_motion.assert_awaited_once_with(1, "blink")
    ctx.runtime.motion_actions = ()
    assert "play_motion" not in {tool["function"]["name"] for tool in ctx.tools()}
    assert result(await ctx.execute(call("play_motion", action="blink")))["ok"] is False


@pytest.mark.asyncio
async def test_expired_context_never_starts_io_and_errors_hide_details(tmp_path, monkeypatch):
    ctx = context(tmp_path)
    ctx.runtime.epoch = 2
    assert result(await ctx.execute(call("save_memory", note="事项")))["ok"] is False
    ctx.runtime.epoch = 1
    monkeypatch.setattr("pet.model_tools.capture_screen", Mock(side_effect=OSError("C:/secret")))
    reply = await ctx.execute(call("capture_screen"))
    assert result(reply)["ok"] is False
    assert "secret" not in reply["content"]


@pytest.mark.asyncio
async def test_screenshot_uses_context_scope_and_discards_expired_result(tmp_path, monkeypatch):
    ctx = context(tmp_path)
    capture = Mock(return_value=b"jpeg")
    monkeypatch.setattr("pet.model_tools.capture_screen", capture)
    reply = await ctx.execute(call("capture_screen"))
    capture.assert_called_once_with(10, 20, "screen")
    assert reply["content"][1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    def expires(*args):
        ctx.runtime.epoch = 2
        return b"old"
    capture.side_effect = expires
    assert result(await ctx.execute(call("capture_screen")))["ok"] is False


@pytest.mark.asyncio
async def test_cancellation_propagates_and_outer_shield_can_record_completed_write(tmp_path, monkeypatch):
    ctx = context(tmp_path)
    entered, complete = asyncio.Event(), asyncio.Event()
    async def write(operation, *args):
        entered.set()
        await complete.wait()
        return operation(*args)
    monkeypatch.setattr("pet.model_tools.durable_io", write)
    execution = asyncio.create_task(ctx.execute(call("save_memory", note="事项")))
    await entered.wait()
    waiter = asyncio.ensure_future(asyncio.shield(execution))
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    ctx.runtime.epoch = 2
    complete.set()
    assert result(await execution)["ok"] is True
    assert ctx.runtime.memory.read() == "事项"
    ctx.runtime.memory_loaded.emit.assert_not_called()
    ctx.runtime.epoch = 1
    execution = asyncio.create_task(ctx.execute(call("search_memory", query="事项")))
    ctx.runtime.engine.select_memory.side_effect = asyncio.CancelledError
    with pytest.raises(asyncio.CancelledError):
        await execution



@pytest.mark.asyncio
async def test_observation_expiry_blocks_effects_and_allows_tts_only_when_speaking(tmp_path, monkeypatch):
    ctx = context(tmp_path, kind="observation")
    ctx.runtime.should_speak.return_value = True
    assert "select_tts_engine" in {tool["function"]["name"] for tool in ctx.tools()}
    assert result(await ctx.execute(call("select_tts_engine", engine="natural")))["ok"] is True
    monkeypatch.setattr("pet.model_tools.observation_current", lambda observation: False)
    assert result(await ctx.execute(call("finish_observation")))["ok"] is False
    assert result(await ctx.execute(call("capture_screen")))["ok"] is False


@pytest.mark.asyncio
async def test_saved_result_survives_ui_refresh_failure(tmp_path):
    ctx = context(tmp_path)
    ctx.runtime.memory_loaded.emit.side_effect = RuntimeError("private path")
    assert result(await ctx.execute(call("save_memory", note="事项")))["result"] == {"saved": True}
    assert ctx.runtime.memory.read() == "事项"


@pytest.mark.asyncio
@pytest.mark.parametrize("arguments", ['{"enabled":', '[]', 'null', '{"enabled":1}',
                                        '{"enabled":true,"other":true}'])
async def test_raw_protocol_invalid_json_and_extra_fields_never_execute(tmp_path, arguments):
    ctx = context(tmp_path)
    invocation = SimpleNamespace(id="call_1", name="set_speech_enabled", arguments=arguments)
    assert result(await ctx.execute(invocation))["ok"] is False
    ctx.runtime.set_speech_enabled.assert_not_called()


@pytest.mark.asyncio
async def test_unknown_qt_outcome_does_not_claim_success(tmp_path):
    ctx = context(tmp_path)
    ctx.runtime.request_motion.return_value = {"status": "unknown"}
    assert result(await ctx.execute(call("play_motion", action="blink")))["ok"] is False
    assert result(await ctx.execute(call("finish_observation")))["ok"] is False


@pytest.mark.asyncio
async def test_search_history_excludes_tool_protocol_and_image_payload(tmp_path):
    ctx = context(tmp_path)
    ctx.runtime.memory.save("事项")
    ctx.runtime.history = [
        {"role": "user", "content": [
            {"type": "text", "text": "看这个"},
            {"type": "image_url", "image_url": {"url": "data:private"}},
        ]},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "old"}]},
        {"role": "tool", "tool_call_id": "old", "content": "private result"},
        {"role": "assistant", "content": "回答"},
    ]
    assert result(await ctx.execute(call("search_memory", query="事项")))["ok"] is True
    assert ctx.runtime.engine.select_memory.await_args.args[3] == [
        {"role": "user", "content": "看这个"}, {"role": "assistant", "content": "回答"},
    ]


@pytest.mark.asyncio
async def test_missing_position_does_not_offer_or_execute_capture(tmp_path):
    ctx = context(tmp_path)
    ctx.position = None
    assert "capture_screen" not in {tool["function"]["name"] for tool in ctx.tools()}
    assert result(await ctx.execute(call("capture_screen")))["ok"] is False
