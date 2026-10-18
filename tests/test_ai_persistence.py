"""API-only保存与独立凭据提交失败必须保留旧配置和旧Key。"""

import asyncio
from dataclasses import replace
from types import SimpleNamespace

import pytest

from pet.ai.credentials import new_ref
from pet.ai.settings import AISettings, ModelProfile
from pet.config import Settings, load_settings, save_settings
from pet.runtime import Runtime


class Vault:
    def __init__(self):
        self.values = {}

    def write(self, reference, key):
        self.values[reference] = key

    def delete(self, reference):
        self.values.pop(reference, None)


def prepare_runtime(baseline):
    tasks, events = [], []

    def schedule(coroutine):
        task = asyncio.create_task(coroutine)
        tasks.append(task)
        return task

    runtime = SimpleNamespace(current_settings=baseline, storage_control=asyncio.Lock(), schedule=schedule,
                              settings_saved=SimpleNamespace(emit=lambda *args: events.append(args)))
    return runtime, tasks, events


@pytest.mark.asyncio
async def test_api_only_settings_save_without_any_gguf(tmp_path, monkeypatch):
    path = tmp_path / 'settings.json'
    profile = ModelProfile(endpoint='https://api.example/v1', model='chosen-model')
    settings = replace(Settings(), model_path='', projector_path='',
                       ai=AISettings(policy='online_first', profile=profile, voice_components=()))
    monkeypatch.setattr('pet.runtime.save_settings', lambda value: save_settings(value, path))
    runtime, tasks, events = prepare_runtime(Settings())
    Runtime.persist(runtime, settings)
    await asyncio.gather(*tasks)
    assert events == [(settings, '')]
    assert load_settings(path) == settings


@pytest.mark.asyncio
async def test_failed_settings_commit_rolls_back_only_new_credential(monkeypatch):
    endpoint = 'https://api.example/v1'
    old_profile = ModelProfile(endpoint=endpoint, model='chosen', credential_ref=new_ref(endpoint))
    new_profile = replace(old_profile, credential_ref=new_ref(endpoint))
    baseline = replace(Settings(), ai=AISettings(policy='online_first', profile=old_profile))
    draft = replace(baseline, ai=replace(baseline.ai, profile=new_profile))
    store = Vault()
    store.values[old_profile.credential_ref] = 'old-synthetic-key'
    monkeypatch.setattr('pet.ai.credentials.CredentialStore', lambda: store)

    def failed_write(_settings):
        raise OSError('disk unavailable')

    monkeypatch.setattr('pet.runtime.save_settings', failed_write)
    runtime, tasks, events = prepare_runtime(baseline)
    Runtime.persist(runtime, draft, credential_change=(new_profile, 'new-synthetic-key'))
    await asyncio.gather(*tasks)
    assert runtime.current_settings == baseline
    assert store.values == {old_profile.credential_ref: 'old-synthetic-key'}
    assert events[-1][1] and 'synthetic-key' not in events[-1][1]


@pytest.mark.asyncio
async def test_mismatched_key_draft_never_reaches_vault(monkeypatch):
    endpoint = 'https://api.example/v1'
    profile = ModelProfile(endpoint=endpoint, model='chosen', credential_ref=new_ref(endpoint))
    settings = replace(Settings(), ai=AISettings(policy='online_first', profile=profile))
    store = Vault()
    monkeypatch.setattr('pet.ai.credentials.CredentialStore', lambda: store)
    runtime, tasks, events = prepare_runtime(Settings())
    Runtime.persist(runtime, settings, credential_change=(replace(profile, model='other'), 'synthetic-key'))
    await asyncio.gather(*tasks)
    assert not store.values and events[-1][1]
