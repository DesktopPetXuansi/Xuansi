"""在模型 HTTP 边界验证语义选择与取消，不以输入词匹配替代模型输出。"""

import asyncio
import json
from contextlib import asynccontextmanager

import httpx
import pytest

from pet.config import Settings
from pet.inference import LocalEngine, request_messages
from pet.model_tools import DEFINITIONS
from pet.tool_protocol import ToolCall


@asynccontextmanager
async def connected_engine(monkeypatch, handle):
    engine = LocalEngine()

    async def start(_):
        pass

    monkeypatch.setattr(engine, "start", start)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle), base_url="http://127.0.0.1") as client:
        engine.client = client
        yield engine


def screen_tools():
    description, properties = DEFINITIONS["capture_screen"]
    return [{"type": "function", "function": {
        "name": "capture_screen", "description": description,
        "parameters": {"type": "object", "properties": properties},
    }}]


@pytest.mark.asyncio
@pytest.mark.parametrize("text, selected", [
    ("这格为什么突然变红了？", True),
    ("不要读取我的屏幕，讲个笑话就好。", False),
    ("把‘看一眼’翻译成英文。", False),
])
async def test_screen_capture_obeys_native_model_result_with_full_context(monkeypatch, text, selected):
    requests = []
    history = [{"role": "user", "content": "我在核对这份表格。"}]
    call = ToolCall("capture", "capture_screen", "{}")

    async def handle(request):
        if request.url.path.endswith("/input_tokens"):
            return httpx.Response(200, json={"input_tokens": 30})
        payload = json.loads(request.content)
        requests.append(payload)
        message = {"content": "" if selected else "这里无需截图。"}
        if selected:
            message["tool_calls"] = [call.message()]
        return httpx.Response(200, json={"choices": [{
            "message": message, "finish_reason": "tool_calls" if selected else "stop",
        }]})

    settings = Settings()
    async with connected_engine(monkeypatch, handle) as engine:
        reply = await engine.complete(settings, request_messages(settings, text, [], history), screen_tools(), stream=False)
    assert reply.tool_calls == ((call,) if selected else ())
    assert len(requests) == 1
    assert requests[0]["temperature"] == settings.temperature
    assert requests[0]["messages"][-1]["content"][0]["text"] == text
    assert requests[0]["messages"][1] == history[0]
    assert "grammar" not in requests[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("arguments", ['{"screen":"yes"', '[1]', "invalid"])
async def test_invalid_tool_result_reports_failure_without_keyword_fallback(monkeypatch, arguments):
    async def handle(request):
        if request.url.path.endswith("/input_tokens"):
            return httpx.Response(200, json={"input_tokens": 30})
        call = ToolCall("bad", "capture_screen", arguments)
        return httpx.Response(200, json={"choices": [{
            "message": {"content": "", "tool_calls": [call.message()]}, "finish_reason": "tool_calls",
        }]})

    async with connected_engine(monkeypatch, handle) as engine:
        with pytest.raises((RuntimeError, ValueError)):
            await engine.complete(Settings(), [{"role": "user", "content": "看看我的屏幕"}], screen_tools(), stream=False)
        assert engine.client is None


@pytest.mark.asyncio
async def test_cancel_native_inference_releases_owned_service(monkeypatch):
    entered = asyncio.Event()

    async def handle(request):
        if request.url.path.endswith("/input_tokens"):
            return httpx.Response(200, json={"input_tokens": 30})
        entered.set()
        await asyncio.Future()

    async with connected_engine(monkeypatch, handle) as engine:
        task = asyncio.create_task(engine.complete(Settings(), [{"role": "user", "content": "看看"}], screen_tools(), stream=False))
        await asyncio.wait_for(entered.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert engine.client is None
