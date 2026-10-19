"""一键使用经过真实后台与安全安装，预览替身不代替实际桌宠试载回执。"""

import asyncio
import hashlib
import zipfile
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PIL import Image
from PySide6.QtTest import QTest
from test_appearance_flow import flow as flow
from test_appearance_flow import import_image, wait_for_idle

from pet import platform_resources
from pet.appearance_import import AppearanceCandidate

RESOURCE = '11111111-1111-4111-8111-111111111111'
VERSION = '22222222-2222-4222-8222-222222222222'


def online(flow, tmp_path, monkeypatch):
    _, view, platform, _ = flow
    path = tmp_path / 'online.png'
    Image.new('RGBA', (8, 8), 'green').save(path)
    payload = path.read_bytes()
    manifest = {
        'schemaVersion': 1, 'resourceId': RESOURCE, 'resourceVersionId': VERSION,
        'kind': 'IMAGE', 'version': '1.0.0', 'minimumClientVersion': '', 'capabilities': {},
        'entrypoint': 'image.png', 'dependencies': [],
        'files': [{'path': 'image.png', 'bytes': len(payload), 'sha256': hashlib.sha256(payload).hexdigest()}],
    }
    resource = {'id': RESOURCE, 'kind': 'IMAGE', 'name': '一键小猫'}
    installs = []

    async def request(method, endpoint, **kwargs):
        if endpoint.startswith('/resources?'):
            return [resource]
        if endpoint.endswith('/manifest'):
            return manifest
        return [{'id': VERSION, 'validationStatus': 'READY', 'compatibilityStatus': 'UNTESTED'}]

    async def install(resource_id, version_id, *, root):
        installs.append((resource_id, version_id))
        package = tmp_path / 'online.zip'
        with zipfile.ZipFile(package, 'w') as archive:
            archive.writestr('image.png', payload)
        await asyncio.to_thread(platform_resources.install_package, package, manifest,
                                {'bytes': package.stat().st_size, 'sha256': platform_resources.hash_file(package)}, root)

    monkeypatch.setattr(platform, 'api', lambda: SimpleNamespace(request=request, install=install))
    view.online_button.click()
    wait_for_idle(platform)
    view.choices.setCurrentRow(0)
    return installs


def test_online_one_click_downloads_saves_and_uses_without_preview_confirmation(flow, tmp_path, monkeypatch):
    coordinator, view, platform, owner = flow
    installs = online(flow, tmp_path, monkeypatch)
    preview = Mock(wraps=view.preview.set_image)
    monkeypatch.setattr(view.preview, 'set_image', preview)
    view.choice_button.click()
    view.choice_button.click()
    wait_for_idle(platform)
    assert installs == [(RESOURCE, VERSION)]
    assert len(owner.runtime.writes) == 1 and coordinator.applying.busy
    assert not preview.called and not owner.avatar.set_image.called
    owner.runtime.finish()
    owner.avatar.set_image.assert_called_once_with(view.candidate.image_id, force=True, strict=True)
    assert owner.settings.avatar_image == view.candidate.image_id
    assert '已更换' in view.status.text() and view.current.name == '一键小猫'
    assert not platform.busy


def test_installed_shape_uses_in_one_click_without_website_or_independent_preview(flow, tmp_path, monkeypatch):
    _, view, platform, owner = flow
    candidate = import_image(flow, tmp_path)
    view.show_choices('mine', [candidate])
    view.choices.setCurrentRow(0)
    monkeypatch.setattr(platform, 'api', Mock(side_effect=AssertionError('本机换装不能访问官网')))
    preview = Mock(wraps=view.preview.set_image)
    monkeypatch.setattr(view.preview, 'set_image', preview)
    owner.panel.persona.name.setText('仍未提交的人设草稿')
    view.choice_button.click()
    assert len(owner.runtime.writes) == 1 and not preview.called
    owner.runtime.finish()
    assert view.current == candidate and owner.settings.avatar_image == candidate.image_id
    assert owner.panel.persona.name.text() == '仍未提交的人设草稿'


def test_preview_remains_optional_and_never_applies_until_use(flow, tmp_path, monkeypatch):
    _, view, platform, owner = flow
    online(flow, tmp_path, monkeypatch)
    view.preview_choice_button.click()
    wait_for_idle(platform)
    assert view.ready and view.dirty and not owner.runtime.writes
    view.apply_button.click()
    assert len(owner.runtime.writes) == 1
    owner.runtime.finish()
    assert owner.settings.avatar_image == view.candidate.image_id


@pytest.mark.parametrize('outcome', ['save-failed', 'load-failed'])
def test_direct_failure_preserves_original_and_only_success_writes_history(flow, tmp_path, outcome):
    coordinator, view, _, owner = flow
    candidate = import_image(flow, tmp_path)
    receipts = []
    coordinator.applying.used.connect(receipts.append)
    view.show_choices('mine', [candidate])
    view.choices.setCurrentRow(0)
    if outcome == 'load-failed':
        owner.avatar.set_image.side_effect = RuntimeError('合成真实试载失败')
    view.choice_button.click()
    assert len(owner.runtime.writes) == 1
    owner.runtime.finish('合成保存失败' if outcome == 'save-failed' else '')
    if outcome == 'load-failed':
        owner.runtime.finish()
    assert owner.settings.avatar_image == '' and view.current.kind == 'DEFAULT'
    assert not receipts and not coordinator.applying.busy
    assert view.choice_button.isEnabled()


@pytest.mark.parametrize('cancel', [False, True])
def test_waits_for_business_save_and_can_cancel_without_using_late_result(flow, tmp_path, monkeypatch, cancel):
    coordinator, view, platform, owner = flow
    online(flow, tmp_path, monkeypatch)
    saving = [False]
    coordinator.is_saving = lambda: saving[0]
    view.choice_button.click()
    saving[0] = True
    wait_for_idle(platform)
    assert not owner.runtime.writes and view.busy
    if cancel:
        view.cancel_button.click()
    saving[0] = False
    owner.runtime.settings_saved.emit(owner.settings, '')
    QTest.qWait(10)
    assert len(owner.runtime.writes) == (0 if cancel else 1)
    if not cancel:
        owner.runtime.finish()
    assert not view.busy


def test_close_during_wait_discards_late_save_event(flow, tmp_path, monkeypatch):
    coordinator, view, platform, owner = flow
    online(flow, tmp_path, monkeypatch)
    view.choice_button.click()
    coordinator.is_saving = lambda: True
    wait_for_idle(platform)
    coordinator.close()
    coordinator.is_saving = lambda: False
    owner.runtime.settings_saved.emit(owner.settings, '')
    QTest.qWait(10)
    assert not owner.runtime.writes and not owner.avatar.set_image.called


def test_cancel_during_download_never_applies_late_candidate(flow, monkeypatch):
    _, view, platform, owner = flow

    async def blocked(*args, **kwargs):
        await asyncio.sleep(30)

    monkeypatch.setattr(platform, 'api', lambda: SimpleNamespace(request=blocked))
    view.show_choices('online', [{'id': RESOURCE, 'kind': 'IMAGE', 'name': '取消目标'}])
    view.choices.setCurrentRow(0)
    view.choice_button.click()
    view.cancel_button.click()
    wait_for_idle(platform)
    assert not owner.runtime.writes and view.current.kind == 'DEFAULT'
    assert view.choice_button.isEnabled()


def test_reselect_current_shape_does_not_save_or_duplicate_receipt(flow):
    coordinator, view, _, owner = flow
    receipts = []
    coordinator.applying.used.connect(receipts.append)
    view.show_choices('mine', [AppearanceCandidate('DEFAULT', '玄司')])
    view.choices.setCurrentRow(0)
    view.choice_button.click()
    assert not owner.runtime.writes and not receipts and '已经' in view.status.text()
