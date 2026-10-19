"""历史只使用临时目录和合成凭据，不访问用户配置或网络。"""

import asyncio
import json
import threading

import pytest

from pet.ai.settings import AISettings, ModelProfile
from pet.appearance_import import AppearanceCandidate
from pet.personal_history import AppearanceHistory, ModelHistory


def test_appearance_history_bounded_and_corruption_preserved(tmp_path):
    store = AppearanceHistory(tmp_path / 'appearance.json', limit=2)
    for name in ('一', '二', '三'):
        store.record(AppearanceCandidate('DEFAULT', name))
    assert [item['name'] for item in store.read()['entries']] == ['三', '二']
    store.path.write_text('{broken', encoding='utf-8')
    with pytest.raises(ValueError, match='损坏'):
        store.record(AppearanceCandidate('DEFAULT', '新'))
    assert store.path.read_text() == '{broken'


def test_sync_default_off_and_does_not_backfill_or_cross_account(tmp_path):
    store = AppearanceHistory(tmp_path / 'appearance.json')
    old = store.record(AppearanceCandidate('DEFAULT', '旧'))
    assert not store.read()['sync']['enabled']
    store.bind('https://example.test', 'account-a')
    new = store.record(AppearanceCandidate('DEFAULT', '新'))
    assert [item['id'] for item in store.pending('https://example.test', 'account-a')] == [new['id']]
    assert old['sync'] == 'local'
    assert store.pending('https://example.test', 'account-b') == []
    assert store.pending('https://another.test', 'account-a') == []
    store.bind('https://example.test', 'account-b')
    assert store.pending('https://example.test', 'account-b') == []
    store.disable()
    assert store.pending('https://example.test', 'account-a') == []


def test_payload_never_contains_local_paths_or_credentials(tmp_path):
    store = AppearanceHistory(tmp_path / 'appearance.json')
    item = store.record(AppearanceCandidate('IMAGE', '我的图片', 'a' * 64 + '.png'))
    payload = store.payload(item)
    assert set(payload) == {'kind', 'appearanceKind', 'resourceId', 'resourceVersionId', 'name',
                            'occurredAt', 'deviceLabel'}
    assert payload['resourceId'] is None and 'image_id' not in json.dumps(payload)


def test_history_image_missing_has_actionable_error(tmp_path):
    store = AppearanceHistory(tmp_path / 'appearance.json')
    item = store.record(AppearanceCandidate('IMAGE', '图片', 'a' * 64 + '.png'))
    with pytest.raises(ValueError, match='丢失'):
        store.candidate(item['id'], image_directory=tmp_path)


def test_model_history_only_saved_config_and_no_secret_body(tmp_path):
    store = ModelHistory(tmp_path / 'models.json')
    settings = AISettings(profile=ModelProfile(endpoint='https://example.test/v1', model='test'))
    store.record(settings, 'model.gguf', 'projector.gguf')
    assert store.read()['entries'][0]['ai']['profile']['model'] == 'test'
    assert 'api_key' not in store.path.read_text()
    assert store.configuration(store.read()['entries'][0]['id'])[0] == settings


def test_network_failure_keeps_local_history_pending(tmp_path):
    from pet.history_sync import synchronize

    class Client:
        base_url = 'https://example.test'

        async def request(self, method, path, payload=None):
            if path == '/me':
                return {'id': 'account-a'}
            raise OSError('offline')

    store = AppearanceHistory(tmp_path / 'appearance.json')
    store.bind(Client.base_url, 'account-a')
    item = store.record(AppearanceCandidate('DEFAULT', '默认'))
    with pytest.raises(OSError):
        asyncio.run(synchronize(store, Client()))
    assert store.read()['entries'][0]['id'] == item['id']
    assert store.pending(Client.base_url, 'account-a')[0]['sync'] == 'pending'


def test_model_history_deduplicates_saved_configuration(tmp_path):
    store = ModelHistory(tmp_path / 'models.json')
    settings = AISettings()
    store.record(settings, 'model.gguf', 'projector.gguf')
    store.record(settings, 'model.gguf', 'projector.gguf')
    assert len(store.read()['entries']) == 1
    store.remove()
    assert store.read()['entries'] == []


def test_history_restore_uses_default_image_directory(tmp_path, monkeypatch):
    from pet import appearance

    identifier = 'b' * 64 + '.png'
    store = AppearanceHistory(tmp_path / 'appearance.json')
    item = store.record(AppearanceCandidate('IMAGE', '图片', identifier))
    monkeypatch.setattr(appearance, 'image_path', lambda value: tmp_path / value)
    (tmp_path / identifier).write_bytes(b'image-placeholder')
    assert store.candidate(item['id']).image_id == identifier


def test_sync_rechecks_switch_and_marks_only_completed(tmp_path):
    from pet.history_sync import synchronize

    store = AppearanceHistory(tmp_path / 'appearance.json')
    store.bind('https://example.test', 'account-a')
    store.record(AppearanceCandidate('DEFAULT', '一'))
    store.record(AppearanceCandidate('DEFAULT', '二'))

    class Client:
        base_url = 'https://example.test'

        def __init__(self):
            self.sent = []

        async def request(self, method, path, payload=None):
            if path == '/me':
                return {'id': 'account-a'}
            self.sent.append(path)
            store.disable()

    client = Client()
    assert asyncio.run(synchronize(store, client)) == 1
    assert len(client.sent) == 1
    assert [item['sync'] for item in store.read()['entries']] == ['synced', 'pending']


def test_sync_honors_immediate_cancel_before_disk_disable_finishes(tmp_path):
    from pet.history_sync import synchronize

    store = AppearanceHistory(tmp_path / 'appearance.json')
    store.bind('https://example.test', 'account-a')
    store.record(AppearanceCandidate('DEFAULT', '新'))
    cancelled = threading.Event()

    class Client:
        base_url = 'https://example.test'

        async def request(self, method, path, payload=None):
            assert path == '/me', '关闭已经生效，不应发送形象历史'
            cancelled.set()
            return {'id': 'account-a'}

    assert asyncio.run(synchronize(store, Client(), cancelled=cancelled)) == 0
    assert store.read()['entries'][0]['sync'] == 'pending'
