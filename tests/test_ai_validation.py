"""合成验证全闭环与取消清理，不使用真实 API Key 或付费请求。"""

import asyncio
import base64
import io
import json

import httpx
import pytest
from PIL import Image

from pet.ai.credentials import new_ref
from pet.ai.providers import ProviderError
from pet.ai.settings import ModelProfile
from pet.ai.validation import IMAGE, validate_profile


class CancellableStream(httpx.AsyncByteStream):
    def __init__(self):
        self.closed = False

    async def __aiter__(self):
        yield b'data: {"choices":[{"delta":{"content":"1"},"finish_reason":null}]}\n\n'
        await asyncio.Event().wait()

    async def aclose(self):
        self.closed = True


def response(text='', calls=()):
    return httpx.Response(200, json={'choices': [{'message': {'content': text, 'tool_calls': list(calls)},
                                                'finish_reason': 'tool_calls' if calls else 'stop'}]})


def draft():
    endpoint = 'https://synthetic.test/v1'
    return ModelProfile(endpoint=endpoint, model='synthetic', credential_ref=new_ref(endpoint),
                        context_tokens=65536,
                        capabilities=('text', 'image', 'tools', 'stream', 'cancel'))


@pytest.mark.asyncio
@pytest.mark.parametrize('image_reply', [
    '{"left":"red","right":"blue"}',
    '```json\n{"left": "red", "right": "blue"}\n```',
    '```\n{"left":"red","right":"blue"}\n```',
])
async def test_validation_checks_real_image_tool_receipt_stream_and_started_cancel(image_reply):
    calls = []
    pending = CancellableStream()

    async def handle(request):
        payload = json.loads(request.content)
        calls.append(payload)
        step = len(calls)
        if step == 1:
            return response('pet-validation')
        if step == 2:
            content = payload['messages'][0]['content']
            assert 'red' not in content[0]['text'] and 'blue' not in content[0]['text']
            encoded = content[1]['image_url']['url'].split(',')[1]
            image = Image.open(io.BytesIO(base64.b64decode(encoded))).convert('RGB')
            assert image.getpixel((16, 32)) == (255, 0, 0)
            assert image.getpixel((48, 32)) == (0, 0, 255)
            return response(image_reply)
        if step == 3:
            assert payload['tool_choice'] == 'auto'
            return response(calls=[{'id': 'test-call', 'type': 'function', 'function': {
                'name': 'validation_echo', 'arguments': '{"value":"pet-validation"}'}}])
        if step == 4:
            assert payload['messages'][-1]['tool_call_id'] == 'test-call'
            return response('receipt-ok')
        if step == 5:
            query = json.loads(payload['messages'][-1]['content'])
            assert query['candidates'] == [
                {'id': 0, 'text': '用户不喝咖啡'}, {'id': 1, 'text': '朋友小林喜欢咖啡'},
                {'id': 2, 'text': '桌宠玄司喜欢茶'}]
            return response('{"selections":[{"id":0,"excerpt":"用户不喝咖啡"}]}')
        if step == 6:
            assert payload['tools'][0]['function']['name'] == 'validation_echo'
            assert '动画真好看' in payload['messages'][-1]['content']
            return response('谢谢你的喜欢。')
        if step == 7:
            return httpx.Response(200, text='data: {"choices":[{"delta":{"content":"stream-ok"},'
                                 '"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n')
        return httpx.Response(200, stream=pending)

    profile = draft()
    validated = await asyncio.wait_for(validate_profile(profile, 'synthetic',
                transport=httpx.MockTransport(handle)), 5)
    assert validated.is_verified('text', 'image', 'tools', 'stream', 'cancel')
    assert validated.credential_ref == profile.credential_ref
    assert not profile.verified_capabilities
    assert pending.closed and len(calls) == 8


@pytest.mark.asyncio
@pytest.mark.parametrize('image_reply', [
    'image-ok',
    '{"left":"blue","right":"red"}',
    '```json\n{"left":"blue","right":"red"}\n```',
    '图片如下：{"left":"red","right":"blue"}',
    '```json\n{"left":"red","right":"blue"}\n```\n额外文字',
])
async def test_image_failure_cannot_mark_any_capability_verified(image_reply):
    count = 0
    async def handle(request):
        nonlocal count
        count += 1
        return response('pet-validation' if count == 1 else image_reply)
    profile = draft()
    with pytest.raises(ProviderError, match='色块'):
        await validate_profile(profile, 'synthetic', transport=httpx.MockTransport(handle))
    assert profile.verified_capabilities == () and count == 2


@pytest.mark.asyncio
async def test_user_cancel_closes_inflight_validation():
    pending = CancellableStream()
    started = asyncio.Event()
    async def handle(request):
        started.set()
        return httpx.Response(200, stream=pending)
    task = asyncio.create_task(validate_profile(draft(), 'synthetic', transport=httpx.MockTransport(handle)))
    await asyncio.wait_for(started.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert pending.closed


def test_synthetic_image_has_actual_pixels():
    image = Image.open(io.BytesIO(IMAGE))
    assert image.size == (64, 64)


@pytest.mark.asyncio
@pytest.mark.parametrize('excerpt', ['朋友小林喜欢咖啡', '桌宠玄司喜欢茶', '喝咖啡', '用户喝咖啡'])
async def test_semantic_validation_rejects_wrong_person_or_lost_negation(excerpt):
    async def handle(request):
        payload = json.loads(request.content)
        messages = payload['messages']
        if messages[0].get('role') == 'system' and '长期记忆检索器' in messages[0].get('content', ''):
            candidates = json.loads(messages[-1]['content'])['candidates']
            index = next((item['id'] for item in candidates if excerpt in item['text']), 0)
            return response(json.dumps({'selections': [{'id': index, 'excerpt': excerpt}]}, ensure_ascii=False))
        return initial_validation_response(payload)

    profile = draft()
    with pytest.raises(ProviderError, match='记忆'):
        await validate_profile(profile, 'synthetic', transport=httpx.MockTransport(handle))
    assert not profile.is_verified('tools')


@pytest.mark.asyncio
async def test_semantic_validation_rejects_tool_call_for_animation_praise():
    async def handle(request):
        payload = json.loads(request.content)
        messages = payload['messages']
        if messages[0].get('role') == 'system' and '长期记忆检索器' in messages[0].get('content', ''):
            return response('{"selections":[{"id":0,"excerpt":"用户不喝咖啡"}]}')
        if '动画真好看' in str(messages[-1]['content']):
            return response(calls=[{'id': 'unsolicited', 'type': 'function', 'function': {
                'name': 'validation_echo', 'arguments': '{"value":"pet-validation"}'}}])
        return initial_validation_response(payload)

    with pytest.raises(ProviderError, match='意图'):
        await validate_profile(draft(), 'synthetic', transport=httpx.MockTransport(handle))


def initial_validation_response(payload):
    """四个已有协议步骤的受控响应；语义错误由各测试独立构造。"""
    content = payload['messages'][-1]['content']
    if isinstance(content, list):
        return response('{"left":"red","right":"blue"}')
    if 'receipt-ok' in content:
        return response('receipt-ok')
    if '必须调用 validation_echo' in content:
        return response(calls=[{'id': 'test-call', 'type': 'function', 'function': {
            'name': 'validation_echo', 'arguments': '{"value":"pet-validation"}'}}])
    if payload.get('stream'):
        return httpx.Response(200, text='data: {"choices":[{"delta":{"content":"stream-ok"},'
                             '"finish_reason":"stop"}]}\n\n')
    return response('pet-validation')
