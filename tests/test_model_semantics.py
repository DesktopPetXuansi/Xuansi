"""在模型 HTTP 边界验证语义选择与取消，不以输入词匹配替代模型输出。"""

import asyncio
import json
from contextlib import asynccontextmanager

import httpx
import pytest

from pet.config import Settings
from pet.inference import LocalEngine


@asynccontextmanager
async def connected_engine(monkeypatch, handle):
    engine = LocalEngine()

    async def start(_):
        pass

    monkeypatch.setattr(engine, "start", start)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle), base_url="http://127.0.0.1") as client:
        engine.client = client
        yield engine


@pytest.mark.asyncio
@pytest.mark.parametrize("text, selected", [
    ("这格为什么突然变红了？", True),
    ("不要读取我的屏幕，讲个笑话就好。", False),
    ("把‘看一眼’翻译成英文。", False),
])
async def test_screen_capture_obeys_model_result_with_full_context(monkeypatch, text, selected):
    requests = []
    history = [{"role": "user", "content": "我在核对这份表格。"}]

    async def handle(request):
        if request.url.path == "/tokenize":
            return httpx.Response(200, json={"tokens": [1]})
        payload = json.loads(request.content)
        requests.append(payload)
        return httpx.Response(200, json={"choices": [{
            "message": {"content": json.dumps({"screen": selected})}, "finish_reason": "stop",
        }]})

    async with connected_engine(monkeypatch, handle) as engine:
        assert await engine.needs_screen(Settings(), text, history) is selected
    assert len(requests) == 1 and requests[0]["temperature"] == 0.0
    assert requests[0]["messages"][-1]["content"][0]["text"] == text
    assert requests[0]["messages"][1] == history[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("content", ['{"screen":"yes"}', '{"screen":1}', '{"other":true}', "invalid"])
async def test_invalid_screen_decision_reports_failure_without_keyword_fallback(monkeypatch, content):
    async def handle(request):
        if request.url.path == "/tokenize":
            return httpx.Response(200, json={"tokens": [1]})
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    async with connected_engine(monkeypatch, handle) as engine:
        with pytest.raises(RuntimeError):
            await engine.needs_screen(Settings(), "看看我的屏幕", [])
        assert engine.client is None


@pytest.mark.asyncio
async def test_cancel_screen_inference_releases_owned_service(monkeypatch):
    entered = asyncio.Event()

    async def handle(request):
        if request.url.path == "/tokenize":
            return httpx.Response(200, json={"tokens": [1]})
        entered.set()
        await asyncio.Future()

    async with connected_engine(monkeypatch, handle) as engine:
        task = asyncio.create_task(engine.needs_screen(Settings(), "看看", []))
        await asyncio.wait_for(entered.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert engine.client is None


@pytest.mark.asyncio
async def test_nonstreaming_tts_choice_comes_from_model(monkeypatch):
    async def handle(request):
        if request.url.path == "/tokenize":
            return httpx.Response(200, json={"tokens": [1]})
        return httpx.Response(200, json={"choices": [{
            "message": {"content": '{"tts":"natural"}'}, "finish_reason": "stop",
        }]})

    async with connected_engine(monkeypatch, handle) as engine:
        assert await engine.choose_tts(Settings(), "This is the generated reply.") == "natural"
