"""选择策略只尝试用户允许的候选，已发布或执行后不可重放。"""

import asyncio
import threading
from dataclasses import replace
from functools import partial
from pathlib import Path

import pytest

from pet.ai.local_candidates import prepared_local_candidates
from pet.ai.providers.base import ProviderError
from pet.ai.selection import Candidate, InferenceRouter
from pet.ai.settings import AISettings, ModelProfile
from pet.config import Settings
from pet.tool_protocol import AssistantReply

LOCAL_CANDIDATES = partial(prepared_local_candidates, model_root=Path('C:/Unused-models'))


class FakeProvider:
    def __init__(self, failure=None):
        self.failure = failure
        self.calls = 0
        self.started = 0
        self.loaded = None
        self.stats = {}

    async def start(self, settings):
        self.started += 1
        self.settings = settings
        self.loaded = ('loaded',)

    async def complete(self, *_args, **_kwargs):
        self.calls += 1
        if self.failure:
            raise self.failure
        return AssistantReply('完成')

    async def stop(self):
        self.loaded = None


def online_settings(policy='local_first', verified=True):
    profile = ModelProfile(endpoint='https://api.example/v1', model='vision-model', credential_ref='ref')
    if verified:
        profile = replace(profile, verified_at='now', verified_capabilities=('text', 'image', 'tools', 'stream', 'cancel'),
                          verification_fingerprint=profile.fingerprint())
    return replace(Settings(), ai=AISettings(policy=policy, profile=profile))


@pytest.mark.asyncio
async def test_resource_failure_falls_back_once_and_preserves_preference():
    local, online = FakeProvider(ProviderError('resource', '资源不足')), FakeProvider()
    events = []
    router = InferenceRouter(local=local, local_candidates=LOCAL_CANDIDATES,
                             provider_factory=lambda _: online, on_event=events.append)
    settings = online_settings()
    await router.begin_turn(settings)
    assert (await router.complete(settings, [])).content == '完成'
    assert router.online and local.calls == online.calls == 1
    assert settings.ai.policy == 'local_first' and settings.ai.local_model == 'qwen3.5-9b'
    assert events[-1].reason == 'resource'


@pytest.mark.asyncio
@pytest.mark.parametrize('error', [asyncio.CancelledError(), ProviderError('authentication', '无效Key'),
                                  ProviderError('quota', '额度不足'), ProviderError('protocol', '协议错误')])
async def test_nonresource_errors_do_not_trigger_local_to_online(error):
    local, online = FakeProvider(error), FakeProvider()
    router = InferenceRouter(local=local, local_candidates=LOCAL_CANDIDATES, provider_factory=lambda _: online)
    settings = online_settings()
    await router.begin_turn(settings)
    with pytest.raises(type(error)):
        await router.complete(settings, [])
    assert online.calls == online.started == 0


@pytest.mark.asyncio
async def test_committed_turn_never_replays_after_resource_failure():
    local, online = FakeProvider(), FakeProvider()
    router = InferenceRouter(local=local, local_candidates=LOCAL_CANDIDATES, provider_factory=lambda _: online)
    settings = online_settings()
    await router.begin_turn(settings)
    await router.complete(settings, [])
    router.mark_committed()
    local.failure = ProviderError('resource', '资源不足')
    with pytest.raises(ProviderError):
        await router.complete(settings, [])
    assert online.calls == 0


@pytest.mark.asyncio
async def test_unverified_online_profile_cannot_be_automatic_fallback():
    local, online = FakeProvider(ProviderError('resource', '资源不足')), FakeProvider()
    router = InferenceRouter(local=local, local_candidates=LOCAL_CANDIDATES, provider_factory=lambda _: online)
    settings = online_settings(verified=False)
    await router.begin_turn(settings)
    with pytest.raises(ProviderError):
        await router.complete(settings, [])
    assert online.calls == 0


@pytest.mark.asyncio
async def test_online_first_does_not_wait_for_local_and_filters_unapproved_memory():
    local, online = FakeProvider(), FakeProvider()
    router = InferenceRouter(local=local, local_candidates=LOCAL_CANDIDATES, provider_factory=lambda _: online)
    settings = online_settings('online_first')
    await router.begin_turn(settings)
    assert router.online and local.started == 0
    tools = [{'function': {'name': name}} for name in ('search_memory', 'capture_screen', 'save_memory')]
    assert [tool['function']['name'] for tool in router.filter_tools(settings, tools)] == ['capture_screen', 'save_memory']


@pytest.mark.asyncio
async def test_background_observation_never_sends_to_cloud_without_own_consent():
    local, online = FakeProvider(), FakeProvider()
    router = InferenceRouter(local=local, local_candidates=LOCAL_CANDIDATES, provider_factory=lambda _: online)
    settings = online_settings('online_first')
    with pytest.raises(ValueError, match='观察'):
        await router.begin_turn(replace(settings, model_path='', projector_path=''), observation=True)
    assert online.started == 0


@pytest.mark.asyncio
async def test_actual_local_status_uses_selected_file_instead_of_stale_preference_label():
    events = []
    router = InferenceRouter(local=FakeProvider(), local_candidates=LOCAL_CANDIDATES,
                             provider_factory=lambda _: pytest.fail('本地测试不应创建在线提供方'),
                             on_event=events.append)
    settings = replace(Settings(), model_path='C:/Models/Qwen3.5-4B-Q4_K_M.gguf')
    await router.begin_turn(settings)
    assert events[-1].preferred == 'qwen3.5-9b'
    assert events[-1].current == 'Qwen3.5-4B-Q4_K_M'


@pytest.mark.asyncio
async def test_online_first_never_implicitly_falls_back_to_unverified_cpu_or_custom_local_files():
    local, online = FakeProvider(), FakeProvider(ProviderError('resource', '资源不足'))
    router = InferenceRouter(local=local, local_candidates=LOCAL_CANDIDATES, provider_factory=lambda _: online)
    settings = online_settings('online_first')
    settings = replace(settings, ai=replace(settings.ai, local_backend='cpu'))
    await router.begin_turn(settings)
    with pytest.raises(ProviderError):
        await router.complete(settings, [])
    assert local.started == 0


@pytest.mark.asyncio
@pytest.mark.parametrize('backend,gpu_layers,custom', [
    ('cuda', 99, False), ('cpu', 0, False), ('cuda', 0, False), ('cuda', 99, True),
])
async def test_online_first_local_fallback_requires_verified_backend_and_exact_files(
        tmp_path, backend, gpu_layers, custom):
    """存在文件不等于通过能力验证，自动链必须同时匹配后端和目录。"""
    from pet.ai.catalog import MODELS

    model = MODELS['qwen3.5-9b']
    paths = [tmp_path / model.model_path, tmp_path / model.projector_path]
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    if custom:
        paths[0] = tmp_path / 'custom.gguf'
        paths[0].touch()
    settings = online_settings('online_first')
    settings = replace(settings, model_path=str(paths[0]), projector_path=str(paths[1]), gpu_layers=gpu_layers,
                       ai=replace(settings.ai, local_backend=backend, model_dir=str(tmp_path)))
    local, online = FakeProvider(), FakeProvider(ProviderError('resource', '资源不足'))
    router = InferenceRouter(local=local, local_candidates=LOCAL_CANDIDATES, provider_factory=lambda _: online)
    await router.begin_turn(settings)
    if backend == 'cuda' and gpu_layers and not custom:
        assert (await router.complete(settings, [])).content == '完成'
        assert not router.online and local.started == local.calls == 1
    else:
        with pytest.raises(ProviderError):
            await router.complete(settings, [])
        assert local.started == local.calls == 0


@pytest.mark.asyncio
async def test_failed_light_model_never_enters_automatic_backup_chain(tmp_path):
    """已安装轻量文件也不能绕过现有语义验收失败记录。"""
    from pet.ai.catalog import MODELS

    backup = MODELS['qwen3.5-4b']
    assert backup.verification == 'failed'
    paths = [tmp_path / backup.model_path, tmp_path / backup.projector_path]
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    settings = Settings(ai=AISettings(local_backend='cuda', model_dir=str(tmp_path),
                                      backup_model_path=str(paths[0]), backup_projector_path=str(paths[1])))
    local = FakeProvider(ProviderError('resource', '资源不足'))
    router = InferenceRouter(local=local, local_candidates=LOCAL_CANDIDATES,
                             provider_factory=lambda _: pytest.fail('本地测试不应创建在线提供方'))
    await router.begin_turn(settings)
    with pytest.raises(ProviderError):
        await router.complete(settings, [])
    assert local.started == local.calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('verified', [False, True])
async def test_router_consumes_injected_candidates_without_product_file_discovery(verified):
    """路由只使用候选契约，既不推断型号也不重新检查产品文件。"""
    settings = replace(online_settings('online_first'), model_path='', projector_path='')
    selected = replace(settings, context_size=8192)
    local, online = FakeProvider(), FakeProvider(ProviderError('resource', '资源不足'))
    events, resolver_threads = [], []

    def candidates(_settings):
        resolver_threads.append(threading.get_ident())
        return (Candidate('injected-model', selected, display_name='注入模型', verified_fallback=verified),)

    router = InferenceRouter(local=local, local_candidates=candidates,
                             provider_factory=lambda _: online, on_event=events.append)
    await router.begin_turn(settings)
    assert resolver_threads and resolver_threads[0] != threading.get_ident()
    if verified:
        assert (await router.complete(settings, [])).content == '完成'
        assert local.settings is selected
        assert router.current == '本地 · 注入模型' and events[-1].current == '注入模型'
    else:
        with pytest.raises(ProviderError):
            await router.complete(settings, [])
        assert local.started == 0


@pytest.mark.asyncio
async def test_cancel_during_candidate_resolution_never_starts_any_provider():
    """取消只停止本轮等待；只读的后台文件检查结束后不能继续发起请求。"""
    entered, release = threading.Event(), threading.Event()
    local, online = FakeProvider(), FakeProvider()

    def candidates(settings):
        entered.set()
        assert release.wait(3), '测试必须释放候选解析线程'
        return (Candidate('injected-model', settings, verified_fallback=True),)

    router = InferenceRouter(local=local, local_candidates=candidates, provider_factory=lambda _: online)
    task = asyncio.create_task(router.begin_turn(online_settings('online_first')))
    try:
        assert await asyncio.wait_for(asyncio.to_thread(entered.wait, 2), timeout=3)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert local.started == online.started == 0
    finally:
        release.set()
