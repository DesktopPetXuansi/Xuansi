"""模型凭据隔离及无秘密日志回归；不访问真实 Windows 凭据。"""

import pytest

from pet.ai.credentials import CredentialStore, new_ref, ref_matches_endpoint


class Vault:
    def __init__(self):
        self.values = {}

    def read(self, target):
        return self.values.get(target)

    def write(self, target, key):
        self.values[target] = key

    def delete(self, target):
        self.values.pop(target, None)


def test_versioned_refs_bind_endpoint_and_keep_draft_independent(caplog):
    endpoint = 'https://api.example.test/v1'
    old, new = new_ref(endpoint), new_ref(endpoint)
    assert old != new
    assert ref_matches_endpoint(old, endpoint)
    assert not ref_matches_endpoint(old, endpoint + '/other')
    vault = Vault()
    store = CredentialStore(vault=vault)
    store.write(old, 'synthetic-original')
    store.write(new, 'synthetic-draft')
    store.delete(new)
    assert store.read(old) == 'synthetic-original'
    assert store.read(new) is None
    assert all(target.startswith('desktop-ai-pet/model-api/') for target in vault.values)
    assert 'synthetic-original' not in caplog.text


@pytest.mark.parametrize('reference', ['platform/website', '../secret', '', 'unknown'])
def test_bad_refs_never_reach_vault(reference):
    store = CredentialStore(vault=Vault())
    with pytest.raises(ValueError):
        store.write(reference, 'synthetic')


@pytest.mark.parametrize('key', ['', '\nsecret', 'secret\r', None])
def test_invalid_keys_rejected(key):
    with pytest.raises(ValueError):
        CredentialStore(vault=Vault()).write(new_ref('https://example.test'), key)
