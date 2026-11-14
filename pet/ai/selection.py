"""每轮固定候选与发送授权；只在首个有效回复前处理资源回退。"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from ..screen_sharing import check_screen_destination, local_screen_destination, screen_turn
from .providers.base import Provider, ProviderError

if TYPE_CHECKING:
    from ..config import Settings
    from .settings import ModelProfile

LOG = logging.getLogger(__name__)
FULL_CAPABILITIES = ('text', 'image', 'tools', 'stream', 'cancel')


@dataclass(frozen=True)
class SelectionEvent:
    preferred: str
    current: str
    online: bool
    reason: str
    phase: str = 'before_reply'


@dataclass(frozen=True)
class Candidate:
    identifier: str
    settings: Settings
    online: bool = False
    display_name: str = ''
    verified_fallback: bool = False
    presentation_verified: bool = False


class InferenceRouter:
    def __init__(self, *, local: Provider, local_candidates: Callable[[Settings], Sequence[Candidate]],
                 provider_factory: Callable[[ModelProfile], Provider],
                 on_event: Callable[[SelectionEvent], None] | None = None):
        # 产品装配在外部完成；路由只消费候选与公共提供方契约。
        self.local = local
        self.local_candidates = local_candidates
        self.provider_factory = provider_factory
        self.on_event = on_event or (lambda _event: None)
        self.active = local
        self.online = False
        self.current = '本地 · 尚未加载'
        self.last_used = time.monotonic()
        self.stats = {}
        self.candidates = []
        self.attempted = set()
        self.committed = False
        self.required = ()
        self.observation = False
        self._candidate = None
        self._remote = None
        self._remote_fingerprint = ''
        self._cooldown = {}
        self._deadline = 0.0

    @property
    def loaded(self):
        return getattr(self.active, 'loaded', None) if not self.online else self._remote_fingerprint

    @property
    def client(self):
        return getattr(self.active, 'client', None)

    @property
    def supports_presentation(self):
        """只对明确完成过专门验证的当前候选开放回复表情协议。"""
        return bool(self._candidate and not self.online and self._candidate.presentation_verified)

    async def _choices(self, settings):
        ai = settings.ai
        # 文件准备检查可能访问慢磁盘；取消直接传播，不在事件循环内阻塞。
        local = list(await asyncio.to_thread(self.local_candidates, settings))
        screen = screen_turn.get()
        if ai.policy == 'online_first' and not (screen is not None and screen.grant.automatic):
            local = [candidate for candidate in local if candidate.verified_fallback]
        remote = []
        if ai.policy != 'local_only' and ai.profile.endpoint and ai.profile.model:
            approved = ai.profile.is_verified(*FULL_CAPABILITIES)
            if ai.policy == 'online_first' or approved:
                if not self.observation:
                    remote = [Candidate(ai.profile.model, settings, True)]
        choices = remote + local if ai.policy == 'online_first' else local + remote
        if screen is not None:
            if screen.grant.online_profile:
                choices = [item for item in remote
                           if item.settings.ai.profile.fingerprint() == screen.grant.online_profile]
            else:
                choices = [item for item in local if local_screen_destination(item.settings) == screen.grant.local_model
                           and bool(item.settings.projector_path)]
        # 资源恢复有冷却窗口；不因每次轮询在同一轮升档。
        ready = [item for item in choices if self._cooldown.get(item.identifier, 0) <= time.monotonic()]
        return ready or choices

    async def begin_turn(self, settings, *, required=(), observation=False):
        self.committed = False
        self.required, self.observation = tuple(required), observation
        self.attempted = set()
        self._candidate = None
        self._deadline = time.monotonic() + 120
        self.candidates = await self._choices(settings)
        if not self.candidates:
            raise ValueError('后台观察需要本地视觉模型。' if observation
                             else '尚未配置可用的本地或在线模型。')
        await self.start(settings)
        if screen_turn.get() is not None:
            self.mark_committed()

    async def start(self, settings):
        if not self.candidates:
            self.candidates = await self._choices(settings)
            self._deadline = time.monotonic() + 120
        if self._candidate is not None:
            return
        await self._activate_next(settings, 'preferred')

    async def _activate_next(self, settings, reason):
        for candidate in self.candidates:
            identity = ('online' if candidate.online else 'local', candidate.identifier)
            if identity in self.attempted:
                continue
            self.attempted.add(identity)
            if candidate.online and self.required and not candidate.settings.ai.profile.is_verified(*self.required):
                continue
            try:
                if candidate.online:
                    fingerprint = settings.ai.profile.fingerprint()
                    if self._remote is None or self._remote_fingerprint != fingerprint:
                        if self._remote is not None:
                            await self._remote.stop()
                        self._remote = self.provider_factory(settings.ai.profile)
                        self._remote_fingerprint = fingerprint
                    active = self._remote
                    if self.active is self.local:
                        await self.local.stop()
                else:
                    active = self.local
                remaining = self._deadline - time.monotonic()
                if remaining <= 0:
                    raise ProviderError('timeout', '模型选择与加载总等待超时。')
                async with asyncio.timeout(remaining):
                    await active.start(candidate.settings)
                self.active, self.online, self._candidate = active, candidate.online, candidate
                actual = candidate.display_name or candidate.identifier
                self.current = ('在线 · ' if candidate.online else '本地 · ') + actual
                event = SelectionEvent(settings.ai.local_model if settings.ai.policy != 'online_first'
                                       else settings.ai.profile.model, actual,
                                       candidate.online,
                                       'resource' if self._cooldown.get(settings.ai.local_model, 0) > time.monotonic()
                                       and candidate.identifier != settings.ai.local_model else reason)
                self.on_event(event)
                LOG.info('推理提供方选定 online=%s reason=%s attempts=%d',
                         self.online, reason, len(self.attempted))
                return
            except ProviderError as exc:
                if exc.category != 'resource' or self.committed:
                    raise
                reason = exc.category
                self._cooldown[candidate.identifier] = time.monotonic() + 30
                LOG.warning('模型资源暂不可用，检查已允许候选 attempts=%d', len(self.attempted))
            except TimeoutError:
                raise ProviderError('timeout', '模型选择与加载等待超时，未切换或重放本轮。') from None
        raise ProviderError('resource', '没有符合当前资源和授权的备用模型，请释放资源或修改模型设置。')

    def mark_committed(self):
        # 首个有效回复（含工具调用）之后，本轮只允许原提供方续答。
        self.committed = True

    def filter_tools(self, settings, tools):
        tools = [tool for tool in tools if tool['function']['name'] != 'present_reply'
                 or self.supports_presentation]
        if not self.online:
            return list(tools)
        profile = settings.ai.profile
        if not profile.is_verified('tools'):
            return []
        prohibited = set()
        if not settings.ai.cloud_memory:
            prohibited.add('search_memory')
        if not profile.is_verified('image'):
            prohibited.add('capture_screen')
        return [tool for tool in tools if tool['function']['name'] not in prohibited]

    async def complete(self, settings, messages, tools=(), **kwargs):
        await self.start(settings)
        while True:
            try:
                effective_tools = self.filter_tools(settings, tools)
                effective_messages = messages
                if (any(tool['function']['name'] == 'present_reply' for tool in tools)
                        and not any(tool['function']['name'] == 'present_reply' for tool in effective_tools)
                        and messages and messages[0]['role'] == 'system'):
                    from ..reply_presentation import PRESENTATION_PROMPT

                    content = messages[0]['content']
                    if isinstance(content, str) and content.endswith(PRESENTATION_PROMPT):
                        # 资源回退可能换到未验证的提供方；不让它看到不可用的展示工具指令。
                        effective_messages = [
                            {**messages[0], 'content': content.removesuffix(PRESENTATION_PROMPT)},
                            *messages[1:],
                        ]
                if kwargs.get('tool_choice') == 'required' and not effective_tools:
                    raise ProviderError('unsupported', '当前模型未验证所需工具能力。')
                # 同一轮总等待有上限；取消直接传播，不转发给其它模型。
                remaining = max(0.01, self._deadline - time.monotonic())
                async with asyncio.timeout(remaining):
                    effective = replace(self._candidate.settings, temperature=settings.temperature,
                                        top_p=settings.top_p, max_tokens=settings.max_tokens)
                    check_screen_destination(effective.ai.profile.fingerprint() if self.online else "")
                    reply = await self.active.complete(effective, effective_messages, effective_tools, **kwargs)
                self.last_used = time.monotonic()
                self.stats.update(getattr(self.active, 'stats', {}))
                return reply
            except ProviderError as exc:
                if exc.category != 'resource' or self.committed:
                    raise
                await self.active.stop()
                self._cooldown[self._candidate.identifier] = time.monotonic() + 30
                self._candidate = None
                await self._activate_next(settings, exc.category)
            except TimeoutError:
                raise ProviderError('timeout', '本轮模型等待超时，已停止后续生成。') from None

    async def input_tokens(self, settings, messages, tools=()):
        await self.start(settings)
        check_screen_destination(self._candidate.settings.ai.profile.fingerprint() if self.online else "")
        return await self.active.input_tokens(self._candidate.settings, messages, self.filter_tools(settings, tools))

    async def select_memory(self, settings, text, notes, history=(), limit=700):
        if self.online and not settings.ai.cloud_memory:
            raise ValueError('在线长期记忆检索未启用，未发送候选资料。')
        from ..model_memory import retrieve_memory
        context = settings.ai.profile.context_tokens if self.online else settings.context_size
        return await retrieve_memory(None, replace(settings, context_size=context), text, notes.splitlines(),
                                     history, limit, provider=self)

    async def warmup(self, settings):
        await self.begin_turn(settings)
        self.last_used = time.monotonic()

    async def stop(self):
        await self.local.stop()
        if self._remote is not None:
            await self._remote.stop()
        self._candidate = None
        self.candidates = []
