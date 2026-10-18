"""提供方公共契约、脱敏错误和有界异步 HTTP 生命周期。"""

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Protocol

import httpx

from ...tool_protocol import AssistantReply, Message, ToolDefinition

LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class TokenEstimate:
    tokens: int
    exact: bool = False


class ProviderError(RuntimeError):
    """消息由客户端控制，绝不回显远端错误正文或请求 URL。"""

    def __init__(self, category, message):
        self.category = category
        super().__init__(message)


class Provider(Protocol):
    async def start(self, settings): ...
    async def complete(self, settings, messages: list[Message], tools: list[ToolDefinition] = (),
                       *, tool_choice='auto', stream=True, json_mode=False,
                       max_tokens=None) -> AssistantReply: ...
    async def input_tokens(self, settings, messages, tools=()) -> TokenEstimate: ...
    async def stop(self): ...


def http_error(status):
    category = {401: 'authentication', 403: 'authentication', 402: 'quota',
                429: 'rate_limit', 408: 'timeout', 413: 'context'}.get(status)
    category = category or ('unavailable' if status >= 500 else 'request')
    return ProviderError(category, f'在线模型请求失败（{category}，HTTP {status}）。')


class HTTPProvider:
    def __init__(self, profile, *, key=None, transport=None, client=None):
        profile.validate()
        if not profile.endpoint or not profile.model:
            raise ProviderError('request', '请填写 API 端点与具体模型。')
        self.profile = profile
        self._key = key
        self._transport = transport
        self.client = client
        self._owns_client = client is None
        self.stats = {}
        self.stream_started = asyncio.Event()

    async def start(self, settings):
        if self.client is not None:
            return
        if self._key is None:
            from ..credentials import CredentialStore, ref_matches_endpoint
            if not ref_matches_endpoint(self.profile.credential_ref, self.profile.endpoint):
                raise ProviderError('authentication', 'API 端点已变更，请重新填写并验证 Key。')
            self._key = await asyncio.to_thread(CredentialStore().read, self.profile.credential_ref)
        if not self._key:
            raise ProviderError('authentication', '请先配置在线模型 API Key。')
        self.client = httpx.AsyncClient(timeout=httpx.Timeout(90, connect=10), trust_env=False,
                                        follow_redirects=False, transport=self._transport)
        LOG.info('在线模型客户端已准备 provider=%s', self.profile.provider)

    def headers(self):
        return {'Authorization': f'Bearer {self._key}'}

    def url(self, path):
        return self.profile.endpoint.rstrip('/') + '/' + path.lstrip('/')

    async def post(self, settings, path, payload):
        await self.start(settings)
        try:
            response = await self.client.post(self.url(path), headers=self.headers(), json=payload)
            if response.status_code >= 300:
                raise http_error(response.status_code)
            data = response.json()
            if not isinstance(data, dict) or 'error' in data:
                raise ProviderError('protocol', '在线模型返回无效响应对象。')
            return data
        except httpx.TimeoutException:
            raise ProviderError('timeout', '在线模型请求超时。') from None
        except httpx.HTTPError:
            raise ProviderError('network', '在线模型连接失败，请检查网络。') from None
        except (ValueError, TypeError):
            raise ProviderError('protocol', '在线模型返回无效 JSON。') from None

    async def events(self, settings, path, payload):
        await self.start(settings)
        try:
            async with self.client.stream('POST', self.url(path), headers=self.headers(), json=payload) as response:
                if response.status_code >= 300:
                    raise http_error(response.status_code)
                # 传输读取设单条上限；结束原因由各协议验证，断开不等于成功。
                from ...text_stream import sse_events
                async for event in sse_events(response):
                    if event.strip() == '[DONE]':
                        break
                    value = json.loads(event)
                    if not isinstance(value, dict) or 'error' in value:
                        raise ProviderError('protocol', '在线模型流式响应无效。')
                    self.stream_started.set()
                    yield value
        except httpx.TimeoutException:
            raise ProviderError('timeout', '在线模型响应超时。') from None
        except httpx.HTTPError:
            raise ProviderError('network', '在线模型连接中断。') from None
        except (ValueError, TypeError):
            raise ProviderError('protocol', '在线模型流式响应无效。') from None

    def metadata(self, native):
        return {'scope': self.profile.fingerprint(), 'native': native}

    def native(self, message):
        metadata = message.get('provider_metadata', {})
        if isinstance(metadata, dict) and metadata.get('scope') == self.profile.fingerprint():
            native = metadata.get('native', {})
            return native if isinstance(native, dict) else {}
        return {}

    async def stop(self):
        if self.client is not None and self._owns_client:
            await self.client.aclose()
            self.client = None
        LOG.info('在线模型客户端已关闭 provider=%s', self.profile.provider)

    async def input_tokens(self, settings, messages, tools=()):
        # 兼容协议没有统一计数接口。UTF-8字节作保守文本预算，图像逐张另留上限；并非实测token数。
        text_messages, images = [], 0
        for message in messages:
            content = message.get('content', '')
            if isinstance(content, list):
                images += sum(part.get('type') == 'image_url' for part in content)
                content = [part for part in content if part.get('type') != 'image_url']
            text_messages.append({**message, 'content': content})
        size = len(json.dumps([text_messages, list(tools)], ensure_ascii=False).encode('utf-8'))
        return self.capacity_estimate(size + images * 16384 + 256)

    def capacity_estimate(self, tokens, *, exact=False):
        """估算余量进入公共预算值，使记忆分片计数与生成采用完全相同的边界。"""
        margin = 0 if exact else min(2048, max(256, self.profile.context_tokens // 32))
        return TokenEstimate(tokens + margin, exact)

    def output_tokens(self, settings, requested):
        return min(requested or settings.max_tokens, self.profile.context_tokens // 2)

    async def fit_messages(self, settings, messages, tools, output_tokens):
        """按完整旧 user 轮裁剪；当前轮中的工具请求与真实回执始终整体保留。"""
        kept = list(messages)
        while True:
            estimate = await self.input_tokens(settings, kept, tools)
            if type(estimate.tokens) is not int or estimate.tokens < 0:
                raise ProviderError('protocol', '在线模型容量计数无效。')
            # input_tokens统一包含估算误差余量，避免记忆计数与生成保护分别增减预算。
            if estimate.tokens + output_tokens <= self.profile.context_tokens:
                if len(kept) != len(messages):
                    LOG.info('在线模型裁剪完整旧会话 provider=%s removed=%d exact=%s',
                             self.profile.provider, len(messages) - len(kept), estimate.exact)
                return kept
            users = [index for index, message in enumerate(kept) if message['role'] == 'user']
            if len(users) < 2:
                detail = '' if estimate.exact else '（当前为保守估算，图片预算较大）'
                raise ProviderError('context', '当前问题、图片、工具及回执超出配置的上下文预算'
                                    + detail + '，请缩短输入或调整已确认的模型窗口。')
            first, following = users[:2]
            kept = kept[:first] + kept[following:]

    def check_choice(self, tools, choice):
        if choice not in ('auto', 'none', 'required') or choice == 'required' and not tools:
            raise ProviderError('request', '工具选择或工具列表无效。')
        if choice == 'required' and self.profile.provider == 'deepseek' and self.profile.mode != 'nonthinking':
            raise ProviderError('unsupported', '该思考模式不支持强制工具调用，请使用自动选择。')
        if (choice == 'required' and self.profile.provider == 'claude'
                and self.profile.model.startswith(('claude-sonnet-5-5', 'claude-opus-5-5', 'claude-fable-5'))):
            raise ProviderError('unsupported', '该 Claude 型号不支持强制工具调用，请使用自动选择。')

    def check_reply(self, reply, tools, choice):
        if reply.tool_calls and (choice == 'none' or not tools):
            raise ProviderError('protocol', '模型返回了本次未授权的工具调用。')
        if choice == 'required' and not reply.tool_calls:
            raise ProviderError('protocol', '模型未返回要求的工具调用。')
        LOG.info('在线模型回复完成 provider=%s calls=%d chars=%d',
                 self.profile.provider, len(reply.tool_calls), len(reply.content))
        return reply
