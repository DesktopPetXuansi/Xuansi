"""语义检索所用的短会话；旧脚本客户端通过局部兼容层复用同一预算边界。"""

from dataclasses import replace

from .providers.base import TokenEstimate


class MemorySession:
    def __init__(self, provider, settings):
        self.provider = provider
        self.settings = replace(settings, temperature=0.0, top_p=1.0)

    async def count(self, messages):
        return await self.provider.input_tokens(self.settings, messages)

    async def generate(self, messages, output_tokens):
        reply = await self.provider.complete(self.settings, messages, tool_choice='none', stream=False,
                                             json_mode=True, max_tokens=output_tokens)
        if reply.finish_reason != 'stop' or reply.tool_calls:
            raise RuntimeError('记忆检索未完整结束。')
        return reply.content


class LegacyMemorySession:
    """保留公开脚本的原客户端参数；私有本地端点集中在这一兼容边界。"""

    def __init__(self, client):
        self.client = client

    async def count(self, messages):
        response = await self.client.post('/v1/chat/completions/input_tokens', json={
            'model': 'local-pet', 'messages': messages, 'chat_template_kwargs': {'enable_thinking': False},
        })
        response.raise_for_status()
        try:
            count = response.json()['input_tokens']
            if type(count) is not int or count < 0:
                raise ValueError('计数无效')
            return TokenEstimate(count, True)
        except (KeyError, TypeError, ValueError):
            raise RuntimeError('无法确认记忆检索的上下文容量，请重试。') from None

    async def generate(self, messages, output_tokens):
        response = await self.client.post('/v1/chat/completions', json={
            'model': 'local-pet', 'messages': messages, 'max_tokens': output_tokens,
            'temperature': 0.0, 'top_p': 1.0, 'stream': False,
            'response_format': {'type': 'json_object'}, 'chat_template_kwargs': {'enable_thinking': False},
        })
        response.raise_for_status()
        choice = response.json()['choices'][0]
        if choice.get('finish_reason') != 'stop':
            raise ValueError('检索结果未完整结束')
        return choice['message']['content']
