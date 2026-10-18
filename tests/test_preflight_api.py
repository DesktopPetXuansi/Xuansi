"""安装前凭据生命周期用隔离替身验证，不读取用户真实凭据、不发付费请求。"""

import json
from dataclasses import replace

import pytest

from scripts.preflight_api import cleanup_profile, receipt_path, validate_install_profile


class Vault:
    def __init__(self):
        self.keys = {}

    def write(self, reference, key):
        self.keys[reference] = key

    def delete(self, reference):
        self.keys.pop(reference, None)


@pytest.mark.asyncio
async def test_install_verification_stores_only_reference_and_cancellation_cleans_it(tmp_path):
    draft, output = tmp_path / 'draft.json', tmp_path / 'verified.json'
    draft.write_text(json.dumps({'endpoint': 'https://api.example/v1', 'model': 'test'}), encoding='utf-8')

    async def verify(profile, key):
        assert key == 'synthetic-secret'
        return replace(profile, verified_capabilities=('text', 'image', 'tools', 'stream', 'cancel'),
                       verified_at='now', verification_fingerprint=profile.fingerprint())

    vault = Vault()
    profile = await validate_install_profile(draft, output, 'synthetic-secret', validator=verify, store=vault)
    assert vault.keys[profile.credential_ref] == 'synthetic-secret'
    assert all('synthetic-secret' not in path.read_text(encoding='utf-8') for path in tmp_path.iterdir())
    cleanup_profile(output, store=vault)
    assert not vault.keys and not output.exists()


@pytest.mark.asyncio
async def test_failed_capability_verification_never_writes_key(tmp_path):
    draft, output = tmp_path / 'draft.json', tmp_path / 'verified.json'
    draft.write_text(json.dumps({'endpoint': 'https://api.example/v1', 'model': 'test'}), encoding='utf-8')

    async def fail(_profile, _key):
        raise ValueError('图片验证失败')

    vault = Vault()
    with pytest.raises(ValueError, match='图片'):
        await validate_install_profile(draft, output, 'synthetic-secret', validator=fail, store=vault)
    assert not vault.keys and not output.exists()


@pytest.mark.asyncio
async def test_cleanup_receipt_precedes_vault_write_for_hard_timeout_recovery(tmp_path):
    draft, output = tmp_path / 'draft.json', tmp_path / 'verified.json'
    draft.write_text(json.dumps({'endpoint': 'https://api.example/v1', 'model': 'test'}), encoding='utf-8')

    async def verify(profile, _key):
        return replace(profile, verified_capabilities=('text', 'image', 'tools', 'stream', 'cancel'),
                       verified_at='now', verification_fingerprint=profile.fingerprint())

    class ReceiptCheckingVault(Vault):
        def write(self, reference, key):
            assert receipt_path(output).read_text(encoding='utf-8') == reference
            assert json.loads(output.read_text(encoding='utf-8'))['credential_ref'] == reference
            super().write(reference, key)

    vault = ReceiptCheckingVault()
    await validate_install_profile(draft, output, 'synthetic-secret', validator=verify, store=vault)
    cleanup_profile(output, store=vault)
    assert not vault.keys
