"""远端记忆走提供方预算与生成边界，摘录仍由本机验证。"""

import json

import httpx
import pytest

from pet.ai.providers.base import TokenEstimate
from pet.config import Settings
from pet.inference import LocalEngine
from pet.model_memory import retrieve_memory
from pet.tool_protocol import AssistantReply


class MemoryProvider:
    def __init__(self):
        self.candidates = []
        self.counts = 0

    async def input_tokens(self, settings, messages, tools=()):
        self.counts += 1
        return TokenEstimate(len(json.dumps(messages, ensure_ascii=False).encode('utf-8')), False)

    async def complete(self, settings, messages, tools=(), **kwargs):
        assert kwargs['json_mode'] and not kwargs['stream']
        assert settings.temperature == 0.0
        candidates = json.loads(messages[-1]['content'])['candidates']
        self.candidates.extend(item['text'] for item in candidates)
        selected = [{'id': item['id'], 'excerpt': '用户不喝咖啡'} for item in candidates
                    if '用户不喝咖啡' in item['text']]
        return AssistantReply(json.dumps({'selections': selected}, ensure_ascii=False))


@pytest.mark.asyncio
async def test_provider_scans_candidates_without_local_private_http():
    provider = MemoryProvider()
    notes = ['无关资料' * 300, '用户不喝咖啡', '另一个人喜欢咖啡']
    result = await retrieve_memory(None, Settings(), '用户喝咖啡吗？', notes, provider=provider)
    assert result == '用户不喝咖啡'
    assert provider.counts > 0
    assert '另一个人喜欢咖啡' in provider.candidates


@pytest.mark.asyncio
async def test_local_json_generation_preserves_the_counted_memory_prompt(monkeypatch):
    """记忆分片已经贴近容量边界，生成阶段不能额外插入未计数的指令。"""
    messages = [{'role': 'system', 'content': '只返回JSON'}, {'role': 'user', 'content': '合成候选'}]

    async def handle(request):
        payload = json.loads(request.content)
        assert payload['messages'] == messages
        if request.url.path.endswith('/input_tokens'):
            return httpx.Response(200, json={'input_tokens': 100})
        return httpx.Response(200, json={'choices': [{'finish_reason': 'stop',
                              'message': {'content': '{"selections":[]}'}}]})

    engine = LocalEngine()

    async def start(_settings):
        pass

    monkeypatch.setattr(engine, 'start', start)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle), base_url='http://local') as client:
        engine.client = client
        await engine.complete(Settings(), messages, tool_choice='none', stream=False, json_mode=True)
