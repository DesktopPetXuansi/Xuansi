"""推理只返回协议，不执行任何工具或朗读控制。"""
import json

import httpx
import pytest

from pet.config import Settings
from pet.inference import LocalEngine
from pet.tool_protocol import AssistantReply, ToolCall


@pytest.mark.asyncio
async def test_native_tools_are_returned_without_control_classification(monkeypatch):
    requests = []

    async def handle(request):
        payload = json.loads(request.content)
        requests.append((request.url.path, payload))
        if request.url.path.endswith('/input_tokens'):
            return httpx.Response(200, json={'input_tokens': 100})
        return httpx.Response(200, json={'choices': [{
            'finish_reason': 'tool_calls', 'message': {
                'reasoning_content': '这里是模型独立的内部推理，并非用户可见回答。',
                'content': ' 我先关闭朗读。\n', 'tool_calls': [{
                    'id': 'call_1', 'type': 'function',
                    'function': {'name': 'set_speech_enabled', 'arguments': '{"enabled":false}'},
                }],
            },
        }]})

    async def start(_):
        pass

    engine = LocalEngine()
    monkeypatch.setattr(engine, 'start', start)
    tools = ({'type': 'function', 'function': {'name': 'set_speech_enabled',
              'description': '改变朗读开关', 'parameters': {'type': 'object'}}},)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle), base_url='http://local') as client:
        engine.client = client
        reply = await engine.complete(Settings(), [{'role': 'user', 'content': '关闭朗读'}], tools, stream=False)
    assert reply == AssistantReply(' 我先关闭朗读。\n', (
        ToolCall('call_1', 'set_speech_enabled', '{"enabled":false}'),
    ), 'tool_calls')
    assert len(requests) == 2
    assert requests[0][1]['tools'] == requests[1][1]['tools']
    assert requests[1][1]['parallel_tool_calls'] is False
    payload = requests[1][1]
    assert payload['chat_template_kwargs']['enable_thinking'] is True
    assert payload['reasoning_format'] == 'deepseek'
    assert payload['reasoning_budget_tokens'] > 0
    assert payload['max_tokens'] >= Settings().max_tokens + payload['reasoning_budget_tokens']
    assert requests[0][1] == payload
    assert 'grammar' not in requests[1][1]


def test_reply_serializes_assistant_tool_call():
    reply = AssistantReply('', (ToolCall('id', 'capture_screen', '{}'),), 'tool_calls')
    assert reply.message() == {'role': 'assistant', 'content': '', 'tool_calls': [{
        'id': 'id', 'type': 'function', 'function': {'name': 'capture_screen', 'arguments': '{}'},
    }]}

@pytest.mark.asyncio
async def test_required_tool_choice_rejects_plain_answer(monkeypatch):
    async def handle(request):
        if request.url.path.endswith('/input_tokens'):
            return httpx.Response(200, json={'input_tokens': 100})
        return httpx.Response(200, json={'choices': [{
            'finish_reason': 'stop', 'message': {'content': '我没有调用工具'},
        }]})

    async def start(_):
        pass

    engine = LocalEngine()
    monkeypatch.setattr(engine, 'start', start)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle), base_url='http://local') as client:
        engine.client = client
        with pytest.raises(RuntimeError, match='工具'):
            await engine.complete(Settings(), [{'role': 'user', 'content': '查看'}],
                                  ({'type': 'function', 'function': {'name': 'capture_screen'}},),
                                  tool_choice='required', stream=False)
