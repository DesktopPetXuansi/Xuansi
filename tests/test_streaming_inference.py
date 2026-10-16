"""SSE 收齐完整原生工具调用后返回，不把半截数据交给执行器。"""

import asyncio
import json

import httpx
import pytest

from pet.config import Settings
from pet.inference import LocalEngine
from pet.text_stream import read_completion
from pet.tool_protocol import ToolCall


def event(content=None, *, calls=None, **extra):
    delta = {'content': content} if content is not None else {}
    if calls is not None:
        delta['tool_calls'] = calls
    return 'data: ' + json.dumps({'choices': [{'delta': delta, **extra}]}, ensure_ascii=False) + '\n\n'


@pytest.mark.asyncio
async def test_stream_accumulates_interleaved_tool_fragments_and_unmodified_content():
    # 推理字段按协议分离；正文中的同名标签仍必须原样保留。
    body = 'data: ' + json.dumps({'choices': [{'delta': {
        'reasoning_content': '内部思考：不要展示，也不能据此执行工具。'
    }}]}, ensure_ascii=False) + '\n\n'
    body += event(' \n无需回应<think>原文</think>')
    body += event(calls=[{'index': 1, 'id': 'call_', 'type': 'function',
                         'function': {'name': 'search_', 'arguments': '{"q":'}},
                        {'index': 0, 'id': 'first', 'type': 'function',
                         'function': {'name': 'capture_screen', 'arguments': '{}'}}])
    body += event('长' * 6500, calls=[{'index': 1, 'id': '2',
                                    'function': {'name': 'memory', 'arguments': '"猫"}'}}])
    body += event(finish_reason='tool_calls') + 'data: [DONE]\n\n'
    async with httpx.AsyncClient(transport=httpx.MockTransport(
        lambda _: httpx.Response(200, text=body)), base_url='http://local') as client:
        async with client.stream('GET', '/') as response:
            reply = await read_completion(response)
    assert reply.content == ' \n无需回应<think>原文</think>' + '长' * 6500
    assert reply.tool_calls == (ToolCall('first', 'capture_screen', '{}'),
                                ToolCall('call_2', 'search_memory', '{"q":"猫"}'))


@pytest.mark.asyncio
@pytest.mark.parametrize('ending', ['', 'data: [DONE]\n\n', event(finish_reason='length'),
                                    'data: {"error":{"message":"private detail"}}\n\n'])
async def test_incomplete_or_error_stream_is_not_a_successful_answer(ending):
    async with httpx.AsyncClient(transport=httpx.MockTransport(
        lambda _: httpx.Response(200, text=event('半句话') + ending)), base_url='http://local') as client:
        async with client.stream('GET', '/') as response:
            with pytest.raises(RuntimeError, match='流式') as error:
                await read_completion(response)
    assert 'private detail' not in str(error.value)


@pytest.mark.asyncio
@pytest.mark.parametrize('fragment', [
    {'index': 0, 'id': 'x', 'function': {'name': 'save_memory', 'arguments': '{'}},
    {'index': 0, 'function': {'name': 'save_memory', 'arguments': '{}'}},
    {'index': 1, 'id': 'x', 'function': {'name': 'save_memory', 'arguments': '{}'}},
])
async def test_partial_or_missing_tool_fields_are_rejected(fragment):
    body = event(calls=[fragment]) + event(finish_reason='tool_calls')
    async with httpx.AsyncClient(transport=httpx.MockTransport(
        lambda _: httpx.Response(200, text=body)), base_url='http://local') as client:
        async with client.stream('GET', '/') as response:
            with pytest.raises(RuntimeError, match='流式'):
                await read_completion(response)


@pytest.mark.asyncio
async def test_cancel_stream_closes_connection_and_stops_owned_engine(monkeypatch):
    entered, closed, stopped = asyncio.Event(), asyncio.Event(), asyncio.Event()

    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield event('开头。').encode()
            entered.set()
            await asyncio.Event().wait()

        async def aclose(self):
            closed.set()

    async def handle(request):
        if request.url.path.endswith('/input_tokens'):
            return httpx.Response(200, json={'input_tokens': 1})
        return httpx.Response(200, stream=Stream())

    async def start(_):
        pass

    async def stop():
        stopped.set()

    engine = LocalEngine()
    monkeypatch.setattr(engine, 'start', start)
    monkeypatch.setattr(engine, 'stop', stop)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle), base_url='http://local') as client:
        engine.client = client
        job = asyncio.create_task(engine.complete(Settings(), [{'role': 'user', 'content': '你好'}]))
        try:
            await asyncio.wait_for(entered.wait(), 1)
        finally:
            job.cancel()
            with pytest.raises(asyncio.CancelledError):
                await job
    assert closed.is_set() and stopped.is_set()
