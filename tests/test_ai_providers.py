"""隔离 HTTP 协议验收；证明转换/完整性，不宣称服务商联网实测。"""

import asyncio
import json
from dataclasses import replace
from types import SimpleNamespace

import httpx
import pytest

from pet.ai.credentials import new_ref
from pet.ai.provider_catalog import preset_profiles
from pet.ai.providers import ProviderError, create_provider
from pet.ai.settings import ModelProfile

SETTINGS = SimpleNamespace(max_tokens=512)
TOOL = {'type': 'function', 'function': {'name': 'echo', 'description': '回显',
        'parameters': {'type': 'object', 'properties': {}}}}
MESSAGES = [{'role': 'user', 'content': '测试'}]


def profile(provider='custom', **kwargs):
    return ModelProfile(provider=provider, endpoint='https://synthetic.test/v1', model='synthetic', **kwargs)


def completion(content='完成', calls=None, finish=None, **metadata):
    return {'choices': [{'message': {'content': content, 'tool_calls': calls or [], **metadata},
                         'finish_reason': finish or ('tool_calls' if calls else 'stop')}]}


def call():
    return {'id': 'call-1', 'type': 'function', 'function': {'name': 'echo', 'arguments': '{}'}}


def stream_response(events):
    data = ''.join('data: ' + json.dumps(event) + '\n\n' for event in events)
    return httpx.Response(200, text=data, headers={'content-type': 'text/event-stream'})


@pytest.mark.asyncio
async def test_openai_metadata_roundtrip_and_no_local_parameters():
    requests = []

    async def handle(request):
        body = json.loads(request.content)
        requests.append(body)
        assert request.headers['Authorization'] == 'Bearer synthetic-only'
        return httpx.Response(200, json=completion('', [call()], reasoning_content='private-thought',
                                                  encrypted_content='private-signature'))

    provider = create_provider(profile('deepseek'), key='synthetic-only', transport=httpx.MockTransport(handle))
    try:
        reply = await provider.complete(SETTINGS, MESSAGES, [TOOL], stream=False)
        history = [*MESSAGES, reply.message(), {'role': 'tool', 'tool_call_id': 'call-1', 'content': 'ok'}]
        await provider.complete(SETTINGS, history, [TOOL], stream=False)
        assert requests[-1]['messages'][1]['reasoning_content'] == 'private-thought'
        assert requests[-1]['messages'][1]['encrypted_content'] == 'private-signature'
        assert 'provider_metadata' not in requests[-1]['messages'][1]
        assert not {'chat_template_kwargs', 'top_k', 'min_p', 'reasoning_budget_tokens'} & requests[-1].keys()
        foreign = create_provider(replace(provider.profile, model='other'), key='synthetic-only')
        assert 'reasoning_content' not in foreign.messages(history)[1]
    finally:
        await provider.stop()


@pytest.mark.asyncio
async def test_tool_images_preserve_receipt_batch_before_related_data():
    provider = create_provider(profile(), key='synthetic-only')
    messages = [*MESSAGES, {'role': 'assistant', 'content': '', 'tool_calls': [call()]},
                {'role': 'tool', 'tool_call_id': 'call-1', 'content': [
                    {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,AA=='}},
                    {'type': 'text', 'text': '不可信工具资料'}]},
                {'role': 'tool', 'tool_call_id': 'call-2', 'content': '第二个结果'}]
    converted = provider.messages(messages)
    assert [message['role'] for message in converted] == ['user', 'assistant', 'tool', 'tool', 'user']
    assert converted[2]['content'] == '不可信工具资料'
    assert 'call-1' in converted[-1]['content'][0]['text']
    estimate = await provider.input_tokens(SETTINGS, messages, [TOOL])
    assert estimate.tokens > 16384 and estimate.exact is False


@pytest.mark.asyncio
@pytest.mark.parametrize('finish', [None, 'length', 'content_filter'])
async def test_unfinished_stream_never_returns_executable_reply(finish):
    async def handle(request):
        return stream_response([{'choices': [{'delta': {'content': '半截'}, 'finish_reason': finish}]}])
    provider = create_provider(profile(), key='synthetic', transport=httpx.MockTransport(handle))
    try:
        with pytest.raises(ProviderError, match='完整结束'):
            await provider.complete(SETTINGS, MESSAGES)
    finally:
        await provider.stop()


@pytest.mark.asyncio
async def test_openai_stream_combines_tool_arguments_and_reasoning():
    async def handle(request):
        return stream_response([
            {'choices': [{'delta': {'reasoning_content': 'one', 'tool_calls': [
                {'index': 0, 'id': 'call-', 'function': {'name': 'echo', 'arguments': '{'}}]},
                'finish_reason': None}]},
            {'choices': [{'delta': {'reasoning_content': 'two', 'tool_calls': [
                {'index': 0, 'id': '1', 'function': {'arguments': '}'}}]}, 'finish_reason': 'tool_calls'}]},
            {'choices': [], 'usage': {'total_tokens': 30}},
        ])
    provider = create_provider(profile(), key='synthetic', transport=httpx.MockTransport(handle))
    try:
        reply = await provider.complete(SETTINGS, MESSAGES, [TOOL])
        assert reply.tool_calls[0].arguments == '{}'
        assert reply.metadata['native']['reasoning_content'] == 'onetwo'
    finally:
        await provider.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize('status,category', [(401, 'authentication'), (402, 'quota'),
                                           (429, 'rate_limit'), (503, 'unavailable')])
async def test_errors_do_not_expose_server_response(status, category, caplog):
    async def handle(request):
        return httpx.Response(status, json={'error': 'synthetic-secret-and-user-content'})
    provider = create_provider(profile(), key='synthetic-key', transport=httpx.MockTransport(handle))
    try:
        with pytest.raises(ProviderError) as error:
            await provider.complete(SETTINGS, MESSAGES, stream=False)
        assert error.value.category == category
        assert 'synthetic-secret' not in str(error.value) + caplog.text
    finally:
        await provider.stop()


@pytest.mark.asyncio
async def test_success_status_with_error_payload_is_still_protocol_failure():
    async def handle(request):
        return httpx.Response(200, json={'error': {'message': 'synthetic-private'}})
    provider = create_provider(profile('claude'), key='synthetic', transport=httpx.MockTransport(handle))
    try:
        with pytest.raises(ProviderError) as error:
            await provider.input_tokens(SETTINGS, MESSAGES)
        assert error.value.category == 'protocol'
        assert 'synthetic-private' not in str(error.value)
    finally:
        await provider.stop()


@pytest.mark.asyncio
async def test_endpoint_change_blocks_credential_read_and_network(monkeypatch):
    from pet.ai.credentials import CredentialStore
    touched = []
    monkeypatch.setattr(CredentialStore, 'read', lambda self, ref: touched.append(ref))
    provider = create_provider(profile(credential_ref=new_ref('https://other.test/v1')))
    with pytest.raises(ProviderError, match='端点已变更'):
        await provider.start(SETTINGS)
    assert not touched


@pytest.mark.asyncio
@pytest.mark.parametrize('provider_name,model', [('deepseek', 'deepseek-flash'),
                                               ('claude', 'claude-sonnet-5-5')])
async def test_model_specific_forced_tool_restrictions_are_local(provider_name, model):
    provider = create_provider(replace(profile(provider_name), model=model), key='synthetic')
    with pytest.raises(ProviderError) as error:
        await provider.complete(SETTINGS, MESSAGES, [TOOL], tool_choice='required')
    assert error.value.category == 'unsupported'
    assert provider.client is None


@pytest.mark.asyncio
async def test_gemini_function_response_returns_original_call_id():
    provider = create_provider(profile('gemini'), key='synthetic')
    message = {'role': 'assistant', 'content': '', 'tool_calls': [call()],
               'provider_metadata': provider.metadata({'parts': [{'functionCall': {
                   'id': 'native-id', 'name': 'echo', 'args': {}}, 'thoughtSignature': 'signature'}]})}
    payload = provider.payload([*MESSAGES, message,
                {'role': 'tool', 'tool_call_id': 'call-1', 'content': 'ok'}], [TOOL])
    assert payload['contents'][-1]['parts'][0]['functionResponse']['id'] == 'native-id'


@pytest.mark.asyncio
@pytest.mark.parametrize('provider_name', ['claude', 'gemini'])
async def test_native_tool_and_signature_roundtrip_and_token_count(provider_name):
    requests = []
    claude_blocks = [{'type': 'thinking', 'thinking': 'private', 'signature': 'unchanged'},
                     {'type': 'tool_use', 'id': 'call-1', 'name': 'echo', 'input': {}}]
    gemini_parts = [{'functionCall': {'name': 'echo', 'args': {}}, 'thoughtSignature': 'unchanged'}]

    async def handle(request):
        body = json.loads(request.content)
        requests.append(body)
        if 'count' in request.url.path.lower():
            return httpx.Response(200, json={'input_tokens': 50, 'totalTokens': 50})
        if provider_name == 'claude':
            assert request.headers['x-api-key'] == 'synthetic'
            return httpx.Response(200, json={'content': claude_blocks, 'stop_reason': 'tool_use'})
        assert request.headers['x-goog-api-key'] == 'synthetic'
        assert 'key=' not in str(request.url)
        return httpx.Response(200, json={'candidates': [{'content': {'parts': gemini_parts}, 'finishReason': 'STOP'}]})

    provider = create_provider(profile(provider_name), key='synthetic', transport=httpx.MockTransport(handle))
    try:
        reply = await provider.complete(SETTINGS, MESSAGES, [TOOL], stream=False)
        assert reply.content == '' and reply.tool_calls[0].name == 'echo'
        messages = [*MESSAGES, reply.message(), {'role': 'tool', 'tool_call_id': reply.tool_calls[0].id,
                    'content': [{'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,AA=='}},
                                {'type': 'text', 'text': 'result'}]}]
        await provider.complete(SETTINGS, messages, [TOOL], stream=False)
        body = requests[-1]
        if provider_name == 'claude':
            assert body['messages'][1]['content'] == claude_blocks
            assert body['messages'][2]['content'][0]['type'] == 'tool_result'
        else:
            assert body['contents'][1]['parts'] == gemini_parts
            assert body['contents'][2]['parts'][0]['functionResponse']['name'] == 'echo'
        count = await provider.input_tokens(SETTINGS, messages, [TOOL])
        assert count.tokens == (562 if provider_name == 'claude' else 50)
        assert count.exact == (provider_name == 'gemini')
    finally:
        await provider.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize('provider_name', ['claude', 'gemini'])
async def test_native_streams_require_complete_termination(provider_name):
    if provider_name == 'claude':
        events = [{'type': 'content_block_start', 'index': 0, 'content_block': {'type': 'text', 'text': ''}},
                  {'type': 'content_block_delta', 'index': 0, 'delta': {'type': 'text_delta', 'text': '完成'}},
                  {'type': 'content_block_stop', 'index': 0},
                  {'type': 'message_delta', 'delta': {'stop_reason': 'end_turn'}}, {'type': 'message_stop'}]
    else:
        events = [{'candidates': [{'content': {'parts': [{'text': '完成'}]}, 'finishReason': 'STOP'}]}]

    async def handle(request):
        if 'count' in request.url.path.lower():
            return httpx.Response(200, json={'input_tokens': 50, 'totalTokens': 50})
        return stream_response(events)
    provider = create_provider(profile(provider_name), key='synthetic', transport=httpx.MockTransport(handle))
    try:
        reply = await provider.complete(SETTINGS, MESSAGES)
        assert reply.content == '完成'
        events.pop()
        with pytest.raises(ProviderError):
            await provider.complete(SETTINGS, MESSAGES)
    finally:
        await provider.stop()


class WaitingStream(httpx.AsyncByteStream):
    def __init__(self):
        self.closed = False

    async def __aiter__(self):
        yield b'data: {"choices":[{"delta":{"content":"1"},"finish_reason":null}]}\n\n'
        await asyncio.Event().wait()

    async def aclose(self):
        self.closed = True


@pytest.mark.asyncio
async def test_cancel_after_first_event_closes_response():
    body = WaitingStream()
    async def handle(request):
        return httpx.Response(200, stream=body)
    provider = create_provider(profile(), key='synthetic', transport=httpx.MockTransport(handle))
    task = asyncio.create_task(provider.complete(SETTINGS, MESSAGES))
    try:
        await asyncio.wait_for(provider.stream_started.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert body.closed
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await provider.stop()


def test_catalog_declares_no_remote_verified_profiles():
    profiles = preset_profiles()
    assert {p.provider for p in profiles} == {'openai', 'bailian', 'deepseek', 'kimi', 'zhipu',
                                           'doubao', 'claude', 'gemini'}
    assert not any(p.is_verified('text') for p in profiles)


@pytest.mark.asyncio
async def test_context_budget_drops_whole_old_round_but_keeps_current_receipts():
    generated = []
    async def handle(request):
        generated.append(json.loads(request.content))
        return httpx.Response(200, json=completion())
    provider = create_provider(profile(context_tokens=1024), key='synthetic',
                               transport=httpx.MockTransport(handle))
    current = [{'role': 'user', 'content': '当前问题'},
               {'role': 'assistant', 'content': '', 'tool_calls': [call()]},
               {'role': 'tool', 'tool_call_id': 'call-1', 'content': '真实回执'}]
    messages = [{'role': 'system', 'content': '规则'}, {'role': 'user', 'content': '旧' * 2000},
                {'role': 'assistant', 'content': '旧回答'}, *current]
    try:
        await provider.complete(SETTINGS, messages, stream=False, max_tokens=128)
        assert generated[0]['messages'] == [messages[0], *current]
        assert len(messages) == 6  # 共享历史不原地修改。
    finally:
        await provider.stop()


@pytest.mark.asyncio
async def test_single_oversized_round_never_starts_generation():
    generated = []
    async def handle(request):
        generated.append(request)
        return httpx.Response(200, json=completion())
    provider = create_provider(profile(context_tokens=1024), key='synthetic',
                               transport=httpx.MockTransport(handle))
    try:
        with pytest.raises(ProviderError) as error:
            await provider.complete(SETTINGS, [{'role': 'user', 'content': '大' * 2000}], stream=False)
        assert error.value.category == 'context'
        assert generated == []
    finally:
        await provider.stop()


@pytest.mark.asyncio
async def test_claude_json_generation_has_same_prompt_as_token_count():
    counted, generated = [], []
    async def handle(request):
        body = json.loads(request.content)
        if request.url.path.endswith('count_tokens'):
            counted.append(body)
            return httpx.Response(200, json={'input_tokens': 100})
        generated.append(body)
        return httpx.Response(200, json={'content': [{'type': 'text', 'text': '{}'}], 'stop_reason': 'end_turn'})
    provider = create_provider(profile('claude'), key='synthetic', transport=httpx.MockTransport(handle))
    messages = [{'role': 'system', 'content': '只返回 JSON 对象。'}, *MESSAGES]
    try:
        await provider.complete(SETTINGS, messages, json_mode=True, stream=False)
        assert len(counted) == len(generated) == 1
        assert counted[0]['system'] == generated[0]['system']
        assert counted[0]['messages'] == generated[0]['messages']
    finally:
        await provider.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize('provider_name', ['claude', 'gemini'])
async def test_native_single_oversized_round_calls_only_count_endpoint(provider_name):
    paths = []
    async def handle(request):
        paths.append(request.url.path)
        assert 'count' in request.url.path.lower()
        return httpx.Response(200, json={'input_tokens': 4000, 'totalTokens': 4000})
    provider = create_provider(profile(provider_name, context_tokens=1024), key='synthetic',
                               transport=httpx.MockTransport(handle))
    try:
        with pytest.raises(ProviderError) as error:
            await provider.complete(SETTINGS, MESSAGES, stream=False)
        assert error.value.category == 'context' and len(paths) == 1
    finally:
        await provider.stop()


@pytest.mark.asyncio
async def test_custom_small_image_budget_is_clearly_estimated_and_never_sent():
    provider = create_provider(profile(), key='synthetic')
    messages = [{'role': 'user', 'content': [{'type': 'image_url',
                 'image_url': {'url': 'data:image/png;base64,AA=='}}]}]
    with pytest.raises(ProviderError, match='保守估算') as error:
        await provider.complete(SETTINGS, messages, stream=False)
    assert error.value.category == 'context' and provider.client is None
