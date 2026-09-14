"""受控 SSE 在尾包到达前交付正文，推理标记和断流不污染会话。"""

import asyncio
import json

import httpx
import pytest

from pet.config import Settings
from pet.inference import LocalEngine


def event(content=None, **extra):
    delta = {"content": content} if content is not None else {}
    return "data: " + json.dumps({"choices": [{"delta": delta, **extra}]}, ensure_ascii=False) + "\n\n"


@pytest.mark.asyncio
async def test_first_content_arrives_before_end_and_split_thinking_is_hidden(monkeypatch):
    first = asyncio.Event()
    received = []

    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            prefix = (
                ": heartbeat\n\n" + event("<thi") + event("nk>内部草稿</th") + event("ink>你好。")
            ).encode()
            # 包边界刻意切进 UTF-8 汉字及 data 行，交给 HTTPX 增量解码。
            for start in range(0, len(prefix), 7):
                yield prefix[start : start + 7]
            await asyncio.wait_for(first.wait(), 1)
            yield (event("我在这里。") + event(finish_reason="stop") + "data: [DONE]\n\n").encode()

    async def handle(request):
        payload = json.loads(request.content)
        if request.url.path == "/tokenize":
            return httpx.Response(200, json={"tokens": [1]})
        assert payload["stream"] is True
        return httpx.Response(200, stream=Stream())

    async def start(_):
        pass

    async def chunk(text):
        received.append(text)
        first.set()

    engine = LocalEngine()
    monkeypatch.setattr(engine, "start", start)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handle), base_url="http://127.0.0.1"
    ) as client:
        engine.client = client
        answer = await asyncio.wait_for(engine.chat(Settings(), "你好", [], [], on_chunk=chunk), 2)
    assert first.is_set()
    assert answer == "你好。我在这里。" == "".join(received)
    assert "内部草稿" not in answer


@pytest.mark.asyncio
@pytest.mark.parametrize("ending", ["", 'data: {"error":{"message":"private detail"}}\n\n'])
async def test_broken_or_error_stream_is_not_a_successful_answer(monkeypatch, ending):
    async def handle(request):
        if request.url.path == "/tokenize":
            return httpx.Response(200, json={"tokens": [1]})
        return httpx.Response(200, content=(event("半句话") + ending).encode())

    async def start(_):
        pass

    async def chunk(_):
        pass

    engine = LocalEngine()
    monkeypatch.setattr(engine, "start", start)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handle), base_url="http://127.0.0.1"
    ) as client:
        engine.client = client
        with pytest.raises(RuntimeError, match="流式") as error:
            await engine.chat(Settings(), "你好", [], [], on_chunk=chunk)
    assert "private detail" not in str(error.value)


@pytest.mark.asyncio
async def test_cancel_stream_closes_connection_and_stops_owned_engine(monkeypatch):
    entered, closed, stopped = asyncio.Event(), asyncio.Event(), asyncio.Event()

    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield event("开头。").encode()
            entered.set()
            await asyncio.Event().wait()

        async def aclose(self):
            closed.set()

    async def handle(request):
        if request.url.path == "/tokenize":
            return httpx.Response(200, json={"tokens": [1]})
        return httpx.Response(200, stream=Stream())

    async def start(_):
        pass

    async def stop():
        stopped.set()

    async def chunk(_):
        pass

    engine = LocalEngine()
    monkeypatch.setattr(engine, "start", start)
    monkeypatch.setattr(engine, "stop", stop)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handle), base_url="http://127.0.0.1"
    ) as client:
        engine.client = client
        job = asyncio.create_task(engine.chat(Settings(), "你好", [], [], on_chunk=chunk))
        try:
            await asyncio.wait_for(entered.wait(), 1)
        finally:
            job.cancel()
            with pytest.raises(asyncio.CancelledError):
                await job
    assert closed.is_set() and stopped.is_set()
