"""无效原生工具不得触发副作用，回执和日志不暴露模型私密内容。"""

import json
import logging
from types import SimpleNamespace

import pytest

from pet.config import Settings
from pet.memory import MemoryStore
from pet.model_tools import ToolContext
from pet.tool_protocol import ToolCall


@pytest.mark.asyncio
@pytest.mark.parametrize("name, arguments", [
    ("set_speech_enabled", {"enabled": "toggle"}),
    ("set_speech_enabled", {"enabled": 1}),
    ("select_tts_engine", {"engine": "guess"}),
    ("play_motion", {"action": "raise_hand"}),
    ("save_memory", {"note": None}),
    ("save_memory", {"note": "测试私密正文" * 200}),
    ("save_memory", {"note": "测试私密正文", "extra": True}),
])
async def test_invalid_tool_never_changes_speech_motion_or_saved_memory(tmp_path, caplog, name, arguments):
    changes, motions = [], []
    memory = MemoryStore(tmp_path / "memory.json")

    async def request_motion(*args):
        motions.append(args)
        return {"status": "completed"}

    runtime = SimpleNamespace(
        epoch=0, motion_actions=("blink",), memory=memory, history=[],
        should_speak=lambda *_: True, set_speech_enabled=changes.append,
        request_motion=request_motion,
    )
    context = ToolContext(runtime, 0, Settings(), "chat", "处理这次请求", None, None)
    caplog.set_level(logging.INFO)
    result = await context.execute(ToolCall("invalid", name, json.dumps(arguments)))
    assert json.loads(result["content"])["ok"] is False
    assert not changes and not motions and not memory.path.exists()
    assert context.selected_tts == "fast"
    assert "测试私密正文" not in result["content"] + caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("question, selected", [
    ("请把你好翻译成英文，只给译文", "natural"),
    ("Please answer in Chinese: how are you?", "fast"),
])
async def test_tts_uses_model_tool_choice_instead_of_input_language(question, selected):
    runtime = SimpleNamespace(epoch=0, motion_actions=(), should_speak=lambda *_: True)
    context = ToolContext(runtime, 0, Settings(), "chat", question, None, None)
    result = await context.execute(ToolCall("tts", "select_tts_engine", json.dumps({"engine": selected})))
    assert json.loads(result["content"])["ok"]
    assert context.selected_tts == selected


@pytest.mark.asyncio
async def test_explicit_natural_choice_is_not_overridden_by_model():
    runtime = SimpleNamespace(epoch=0, motion_actions=(), should_speak=lambda *_: True)
    context = ToolContext(runtime, 0, Settings(tts_engine="natural"), "chat", "你好", None, None)
    result = await context.execute(ToolCall("tts", "select_tts_engine", '{"engine":"fast"}'))
    assert json.loads(result["content"])["result"]["engine"] == "natural"
    assert context.selected_tts == "natural"
