"""生产装配走真实路由与适配器，网络、模型和凭据均使用隔离替身。"""

import json
from dataclasses import replace
from functools import partial

import httpx
import pytest

from pet.ai import assembly
from pet.ai.providers import create_provider
from pet.ai.providers.base import ProviderError
from pet.ai.settings import AISettings, ModelProfile
from pet.config import Settings
from pet.tool_protocol import AssistantReply


@pytest.mark.asyncio
@pytest.mark.parametrize('policy', ['local_only', 'local_first', 'online_first'])
async def test_product_assembly_preserves_local_custom_paths_and_api_only_routing(monkeypatch, policy):
    requests, starts, events = [], [], []

    class Local:
        async def start(self, settings):
            starts.append(settings)

        async def complete(self, *_args, **_kwargs):
            if policy == 'local_first':
                raise ProviderError('resource', '合成本地资源不足')
            return AssistantReply('本地完成')

        async def stop(self):
            pass

    async def handle(request):
        requests.append(json.loads(request.content))
        event = {'choices': [{'delta': {'content': '在线完成'}, 'finish_reason': 'stop'}]}
        return httpx.Response(200, text='data: ' + json.dumps(event) + '\n\ndata: [DONE]\n\n',
                              headers={'content-type': 'text/event-stream'})

    monkeypatch.setattr(assembly, 'LocalEngine', Local)
    monkeypatch.setattr(assembly, 'create_provider',
                        partial(create_provider, key='synthetic-only', transport=httpx.MockTransport(handle)))
    profile = ModelProfile(endpoint='https://synthetic.test/v1', model='synthetic-model')
    profile = replace(profile, verified_at='synthetic',
                      verified_capabilities=('text', 'image', 'tools', 'stream', 'cancel'),
                      verification_fingerprint=profile.fingerprint())
    # API-only 无本地路径；另两种策略保留用户明确选择的自定义文件。
    settings = Settings(ai=AISettings(policy=policy, profile=profile),
                        model_path='' if policy == 'online_first' else 'C:/Custom/manual.gguf',
                        projector_path='' if policy == 'online_first' else 'C:/Custom/projector.gguf')
    router = assembly.create_inference_router(on_event=events.append)
    try:
        await router.begin_turn(settings)
        reply = await router.complete(settings, [{'role': 'user', 'content': '合成测试'}])
        assert reply.content == ('本地完成' if policy == 'local_only' else '在线完成')
        assert len(starts) == (0 if policy == 'online_first' else 1)
        assert len(requests) == (0 if policy == 'local_only' else 1)
        if requests:
            assert requests[0]['model'] == profile.model and requests[0]['stream'] is True
        if policy == 'local_first':
            assert events[0].current == 'manual' and events[-1].reason == 'resource'
        assert settings.ai.policy == policy
    finally:
        await router.stop()
