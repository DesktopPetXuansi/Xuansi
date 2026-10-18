"""配置迁移、能力证据作用域和在线数据授权的行为约定。"""

import json
from dataclasses import replace

import pytest

from pet.ai.settings import AISettings, ModelProfile
from pet.config import Settings, load_settings, save_settings


def test_legacy_settings_keep_custom_paths_and_local_policy(tmp_path):
    path = tmp_path / 'settings.json'
    path.write_text(json.dumps({'name': '旧伙伴', 'model_path': 'E:/custom/model.gguf'}), encoding='utf-8')
    settings = load_settings(path)
    assert settings.name == '旧伙伴'
    assert settings.model_path == 'E:/custom/model.gguf'
    assert settings.ai.policy == 'local_only'
    assert not settings.ai.cloud_memory and not settings.ai.cloud_observation


def test_profile_verification_is_bound_to_endpoint_model_mode_and_credential():
    profile = ModelProfile(endpoint='https://api.example.com/v1', model='vision-model', credential_ref='key-1')
    verified = replace(profile, verified_capabilities=('text', 'image', 'tools', 'stream', 'cancel'),
                       verified_at='2026-10-17T12:00:00Z', verification_fingerprint=profile.fingerprint())
    assert verified.is_verified('image', 'tools')
    for change in ({'endpoint': 'https://other.example/v1'}, {'model': 'new'}, {'mode': 'thinking'},
                   {'credential_ref': 'key-2'}, {'context_tokens': 8192}):
        assert not replace(verified, **change).is_verified('tools')


def test_api_settings_round_trip_without_secret(tmp_path):
    profile = ModelProfile(provider='openai', region='global', endpoint='https://api.openai.com/v1',
                           model='chosen-model', credential_ref='opaque-ref', capabilities=('text', 'tools'))
    settings = replace(Settings(), ai=AISettings(policy='online_first', profile=profile, voice_components=()),
                       model_path='', projector_path='')
    path = tmp_path / 'settings.json'
    save_settings(settings, path)
    assert load_settings(path) == settings
    assert 'api_key' not in path.read_text(encoding='utf-8')


@pytest.mark.parametrize('endpoint', ['http://api.example.com/v1', 'https://user:secret@example.com',
                                      'https://api.example.com/v1?key=secret'])
def test_remote_endpoint_rejects_insecure_or_secret_addresses(endpoint):
    with pytest.raises(ValueError):
        ModelProfile(endpoint=endpoint, model='model').validate()


def test_loopback_http_allowed_for_explicit_development():
    assert ModelProfile(endpoint='http://127.0.0.1:8000/v1', model='test').validate()


def test_unknown_ai_config_cannot_silently_enable_cloud(tmp_path):
    path = tmp_path / 'settings.json'
    path.write_text(json.dumps({'ai': {'schema_version': 999, 'policy': 'online_first'}}), encoding='utf-8')
    assert load_settings(path).ai.policy == 'local_only'
