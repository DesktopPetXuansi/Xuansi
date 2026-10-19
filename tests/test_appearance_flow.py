"""串起真实后台队列与形象事务；磁盘隔离，预览/桌宠/官网均为受控替身。"""

import asyncio
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PIL import Image
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from pet.appearance_flow import AppearanceFlow
from pet.appearance_import import AppearanceCandidate
from pet.config import Settings
from pet.panel import Panel
from pet.platform_dialog import PlatformDialog


class Preview(QWidget):
    load_finished = Signal(bool, str)
    motion_capabilities_changed = Signal(object)
    available_motions = ()

    def __init__(self, parent=None, *, size=160):
        super().__init__(parent)
        self.setFixedHeight(size + 14)

    def set_image(self, identifier):
        self.load_finished.emit(True, '')

    def set_model(self, prepared):
        self.load_finished.emit(True, '')

    def play_motion(self, motion):
        return False


class Runtime(QObject):
    platform_settings_saved = Signal(object, str)

    def __init__(self, settings):
        super().__init__()
        self.settings, self.writes = settings, []

    def persist_platform(self, changes):
        self.writes.append(changes)

    def finish(self, error=''):
        if not error:
            self.settings = replace(self.settings, **self.writes[-1])
        self.platform_settings_saved.emit(self.settings, error)


def wait_for_idle(platform):
    deadline = time.monotonic() + 5
    while platform.worker is not None and time.monotonic() < deadline:
        QTest.qWait(10)
    assert platform.worker is None, '真实后台线程应退出后才交付候选'
    QApplication.processEvents()


@pytest.fixture
def flow(monkeypatch, tmp_path):
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    monkeypatch.setattr('pet.appearance_hub.AppearancePreview', Preview)
    monkeypatch.setattr('pet.appearance_sources.appearance.DIRECTORY', tmp_path / 'images')
    monkeypatch.setattr('pet.appearance_sources.platform_resources.RESOURCE_ROOT', tmp_path / 'resources')
    app = QApplication.instance() or QApplication([])
    from pet.appearance_hub import AppearanceHub

    settings = replace(Settings(), observe=False, platform_url='http://127.0.0.1:1')
    panel = Panel(settings)
    panel.logs.path = tmp_path / 'panel.log'
    owner = SimpleNamespace(panel=panel, settings=settings, runtime=Runtime(settings),
                            avatar=SimpleNamespace(set_image=Mock(), select_platform_model=Mock()))
    view = AppearanceHub(panel)
    platform = PlatformDialog(owner, embedded=True)
    coordinator = AppearanceFlow(owner, view, platform, on_applied=Mock())
    panel.mount_section('appearance', view, on_open=coordinator.present)
    panel.mount_section('resources', platform)
    panel.open_section('appearance')
    app.processEvents()
    yield coordinator, view, platform, owner
    coordinator.close()
    platform.shutdown()
    wait_for_idle(platform)
    panel.hide()
    panel.deleteLater()
    app.processEvents()


def import_image(flow, tmp_path):
    coordinator, view, platform, _ = flow
    image = tmp_path / '小猫.png'
    Image.new('RGBA', (8, 8), 'red').save(image)
    view.import_requested.emit(str(image))
    wait_for_idle(platform)
    assert coordinator.sources.image_directory.joinpath(view.candidate.image_id).is_file()
    assert view.ready and view.dirty
    return view.candidate


def test_local_preview_then_explicit_use_saves_before_changing_avatar(flow, tmp_path):
    coordinator, view, platform, owner = flow
    candidate = import_image(flow, tmp_path)
    assert not owner.runtime.writes and not owner.avatar.set_image.called
    owner.panel.persona.name.setText('保留人设草稿')
    view.apply_button.click()
    view.apply_button.click()
    assert len(owner.runtime.writes) == 1 and coordinator.applying.busy and platform.busy
    assert not owner.avatar.set_image.called
    owner.runtime.finish()
    owner.avatar.set_image.assert_called_once_with(candidate.image_id, force=True, strict=True)
    assert owner.settings.avatar_image == candidate.image_id
    assert '已更换' in view.status.text() and not view.dirty
    assert owner.panel.persona.name.text() == '保留人设草稿'
    assert not platform.busy and not coordinator.applying.busy


def test_failed_save_keeps_current_shape_and_candidate_can_retry(flow, tmp_path):
    _, view, _, owner = flow
    import_image(flow, tmp_path)
    view.apply_button.click()
    owner.runtime.finish('磁盘写入失败，请重试')
    assert owner.settings.avatar_image == '' and not owner.avatar.set_image.called
    assert '失败' in view.status.text() and view.apply_button.isEnabled()


def test_online_choice_downloads_latest_ready_then_previews_without_applying(flow, monkeypatch):
    coordinator, view, platform, owner = flow
    resource = {'id': 'public-cat', 'name': '官网小猫', 'kind': 'IMAGE'}
    requests, installs = [], []

    async def request(method, path, **options):
        requests.append((path, options))
        return [resource] if path.startswith('/resources?') else [
            {'id': 'pending', 'validationStatus': 'PENDING'},
            {'id': 'newest', 'validationStatus': 'READY'},
            {'id': 'older', 'validationStatus': 'READY'}]

    async def install(resource_id, version_id, **options):
        installs.append((resource_id, version_id))

    monkeypatch.setattr(platform, 'api', lambda: SimpleNamespace(request=request, install=install))
    monkeypatch.setattr('pet.appearance_sources.installed_candidate', lambda *args, **kwargs:
                        AppearanceCandidate('IMAGE', '原文件名', 'a' * 64 + '.png'))
    view.online_button.click()
    wait_for_idle(platform)
    assert requests == [('/resources?limit=100', {'anonymous': True})] and not installs
    view.choices.setCurrentRow(0)
    view.choice_button.click()
    wait_for_idle(platform)
    assert installs == [('public-cat', 'newest')]
    assert view.candidate.name == '官网小猫' and view.stack.currentIndex() == 0
    assert view.apply_button.isEnabled() and not owner.runtime.writes
    assert not coordinator.sources.busy


@pytest.mark.parametrize('action', ['mine', 'discover'])
def test_return_from_source_list_keeps_valid_image_draft_usable(flow, tmp_path, monkeypatch, action):
    coordinator, view, platform, _ = flow
    candidate = import_image(flow, tmp_path)

    async def request(*args, **kwargs):
        return []

    monkeypatch.setattr(platform, 'api', lambda: SimpleNamespace(request=request))
    getattr(coordinator.sources, action)()
    wait_for_idle(platform)
    assert view.stack.currentIndex() == 1
    view.back_button.click()
    assert view.candidate == candidate and view.apply_button.isEnabled()


def test_cancelled_source_keeps_previous_valid_preview_and_never_saves(flow, tmp_path, monkeypatch):
    _, view, platform, owner = flow
    candidate = import_image(flow, tmp_path)

    async def request(*args, **kwargs):
        await asyncio.sleep(30)

    monkeypatch.setattr(platform, 'api', lambda: SimpleNamespace(request=request))
    view.online_button.click()
    view.cancel_button.click()
    wait_for_idle(platform)
    assert '取消' in view.status.text() and not owner.runtime.writes
    assert view.candidate == candidate and view.apply_button.isEnabled()


def test_background_resource_task_and_business_save_block_shape_changes(flow):
    coordinator, view, platform, owner = flow
    candidate = AppearanceCandidate('IMAGE', '草稿', 'a' * 64 + '.png')
    view.show_candidate(candidate)
    coordinator.is_saving = lambda: True
    coordinator.refresh_busy()
    view.apply_button.click()
    assert not owner.runtime.writes and not view.local_button.isEnabled()
    coordinator.is_saving = lambda: False
    platform.set_busy(True)
    view.use_requested.emit(candidate)
    assert not owner.runtime.writes and not view.cancel_button.isVisible()
    platform.set_busy(False)
    assert view.apply_button.isEnabled()


def test_missing_current_model_can_restore_default_and_retry_loading(flow, monkeypatch):
    coordinator, view, platform, owner = flow
    owner.settings = replace(owner.settings, platform_model_version='missing-version')
    reads = []

    def unavailable(version, **kwargs):
        reads.append(version)
        raise ValueError('合成模型缺失')

    monkeypatch.setattr('pet.appearance_sources.installed_candidate', unavailable)
    coordinator.present()
    wait_for_idle(platform)
    assert view.current.kind == 'MODEL' and not view.apply_button.isEnabled()
    view.default_button.click()
    assert view.candidate.kind == 'DEFAULT' and view.apply_button.isEnabled()
    owner.panel.open_section('chat')
    owner.panel.open_section('appearance')
    wait_for_idle(platform)
    assert reads == ['missing-version', 'missing-version']


def test_click_highlighted_appearance_tab_returns_from_secondary_pages(flow):
    _, _, _, owner = flow
    panel = owner.panel
    for key in ('resources', 'upload'):
        panel.open_section(key)
        bar = panel.navigation.bar
        QTest.mouseClick(bar, Qt.MouseButton.LeftButton,
                         pos=bar.tabRect(bar.currentIndex()).center())
        assert panel.navigation.current_key == 'appearance'


def test_login_from_online_chooser_can_be_cancelled_without_leaving_page(flow, monkeypatch):
    _, view, platform, _ = flow

    async def authorize(_):
        await asyncio.sleep(30)

    monkeypatch.setattr('pet.platform_dialog.authorize', authorize)
    monkeypatch.setattr(platform, 'api', lambda: SimpleNamespace(base_url='http://127.0.0.1:1',
                        store=SimpleNamespace(read=lambda: None)))
    view.show_choices('online', [])
    view.login_button.click()
    assert view.cancel_button.isVisible() and '浏览器' in view.status.text()
    view.cancel_button.click()
    wait_for_idle(platform)
    assert '取消' in view.status.text()
    assert view.stack.currentIndex() == 1


@pytest.mark.parametrize('kind', ['MODEL', 'IMAGE', 'ANIMATION', 'DEFAULT'])
@pytest.mark.parametrize('fails', [False, True])
def test_legacy_resource_buttons_use_shared_saved_trial_receipt(flow, kind, fails):
    coordinator, view, platform, owner = flow
    used = []
    coordinator.applying.used.connect(used.append)
    if fails:
        target = owner.avatar.select_platform_model if kind == 'MODEL' else owner.avatar.set_image
        target.side_effect = RuntimeError('合成试载失败')
    if kind == 'DEFAULT':
        platform.restore_default()
    else:
        manifest = {'kind': kind, 'name': '资源形象', 'resourceVersionId': 'selected-version'}
        platform.completed('apply', ((manifest, Path('test.model3.json')), None if kind == 'MODEL' else 'new.png'))
    assert len(owner.runtime.writes) == 1 and not used
    assert platform.pending_settings is None
    owner.runtime.finish()
    if fails:
        assert coordinator.applying.busy and len(owner.runtime.writes) == 2
        owner.runtime.finish()
        assert not used and '未更换' in platform.status.text()
    else:
        assert [candidate.kind for candidate in used] == [kind]
        assert view.current.kind == kind and '成功' in platform.status.text()
    assert not coordinator.applying.busy


def test_legacy_action_and_startup_restore_do_not_create_appearance_receipts(flow):
    coordinator, _, platform, owner = flow
    used = []
    coordinator.applying.used.connect(used.append)
    owner.avatar.apply_platform_action = Mock()
    for kind, command in [('MOTION', 'apply'), ('EXPRESSION', 'apply'), ('MODEL', 'restore')]:
        manifest = {'kind': kind, 'resourceVersionId': 'existing-version'}
        prepared = (manifest, Path('existing.model3.json'))
        platform.completed(command, (prepared, None))
        assert platform.pending_settings is not None
        owner.runtime.finish()
    assert owner.avatar.apply_platform_action.call_count == 2
    assert owner.avatar.select_platform_model.call_count == 1
    assert used == []


@pytest.mark.parametrize('outcome', ['success', 'save-failed', 'load-failed'])
def test_legacy_worker_finishes_before_save_keeps_other_operations_blocked(flow, outcome):
    coordinator, _, platform, owner = flow
    used = []
    coordinator.applying.used.connect(used.append)
    if outcome == 'load-failed':
        owner.avatar.set_image.side_effect = RuntimeError('合成试载失败')

    async def prepare():
        manifest = {'kind': 'IMAGE', 'name': '资源形象', 'resourceVersionId': 'selected-version'}
        return (manifest, Path('image.png')), 'new.png'

    assert platform.start('apply', prepare)
    wait_for_idle(platform)
    # completed 已发起异步保存，但下载准备线程 finished 不能提前解锁界面。
    assert coordinator.applying.busy and platform.busy
    assert not platform.url.isEnabled() and not platform.local.isEnabled()
    assert not platform.start('login', prepare)
    assert not platform.start('apply', prepare)
    owner.runtime.finish('合成保存失败' if outcome == 'save-failed' else '')
    if outcome == 'load-failed':
        assert coordinator.applying.busy and platform.busy
        assert not platform.start('login', prepare)
        owner.runtime.finish()
    assert not coordinator.applying.busy and not platform.busy
    assert platform.url.isEnabled() and platform.local.isEnabled()
    assert len(used) == (1 if outcome == 'success' else 0)
