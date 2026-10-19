"""首次换形象的界面回归；使用假预览和临时日志，不启动SDK或网络。"""

import importlib

import pytest
from PySide6.QtCore import QPoint, QRect, Signal
from PySide6.QtWidgets import QApplication, QWidget

from pet.appearance_import import AppearanceCandidate
from pet.config import Settings
from pet.panel import Panel


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

    def stop(self):
        pass

    def play_motion(self, motion):
        return motion in self.available_motions


@pytest.fixture
def hub(monkeypatch, tmp_path):
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    module = importlib.import_module('pet.appearance_hub')
    monkeypatch.setattr(module, 'AppearancePreview', Preview)
    app = QApplication.instance() or QApplication([])
    panel = Panel(Settings())
    panel.logs.path = tmp_path / 'panel.log'
    view = module.AppearanceHub(panel)
    panel.mount_section('appearance', view)
    panel.open_section('appearance')
    view.set_current(AppearanceCandidate('DEFAULT', '默认玄司'))
    app.processEvents()
    yield view, panel
    panel.hide()
    panel.deleteLater()
    app.processEvents()


def test_first_open_explains_current_shape_and_next_actions(hub):
    view, _ = hub
    assert '当前使用' in view.current_label.text()
    assert view.local_button.text() == '本地导入'
    assert view.online_button.text() == '在线挑选'
    assert not view.apply_button.isEnabled()


def test_preview_only_changes_after_explicit_use(hub):
    view, _ = hub
    candidate = AppearanceCandidate('IMAGE', '测试形象', 'a' * 64 + '.png')
    requests = []
    view.use_requested.connect(requests.append)
    view.show_candidate(candidate)
    assert '默认玄司' in view.current_label.text() and requests == []
    assert view.apply_button.isEnabled()
    view.apply_button.click()
    assert requests == [candidate]
    assert '默认玄司' in view.current_label.text()


def test_failed_preview_cannot_be_used(hub):
    view, _ = hub
    view.show_candidate(AppearanceCandidate('IMAGE', '坏图片', 'a' * 64 + '.png'))
    view.preview.load_finished.emit(False, '文件损坏，请重新导入')
    assert not view.apply_button.isEnabled() and '重新导入' in view.status.text()


def test_success_receipt_keeps_next_step_clear_and_motion_preview_independent(hub):
    view, _ = hub
    view.show_candidate(AppearanceCandidate('IMAGE', '小猫', 'a' * 64 + '.png'))
    view.preview.load_finished.emit(True, '形象预览已就绪')
    assert '使用这个形象' in view.status.text()
    assert not view.motion_button.isEnabled()
    view.preview.available_motions = ('blink',)
    view.preview.motion_capabilities_changed.emit(('blink',))
    assert view.motion_button.isEnabled() and view.dirty


def test_use_and_optional_preview_have_independent_explicit_actions(hub):
    view, _ = hub
    selected, used = [], []
    view.choice_requested.connect(selected.append)
    view.choice_use_requested.connect(used.append)
    resource = {'id': 'public-id', 'name': '小猫', 'kind': 'MODEL'}
    view.show_choices('online', [resource])
    view.choices.setCurrentRow(0)
    assert view.choice_button.text() == '使用这个形象'
    assert selected == used == []
    view.choice_button.click()
    assert used == [resource] and not selected
    view.preview_choice_button.click()
    assert selected == [resource] and used == [resource]


def test_busy_state_prevents_duplicate_apply_and_keeps_cancel_available(hub):
    view, _ = hub
    view.show_candidate(AppearanceCandidate('IMAGE', '小猫', 'a' * 64 + '.png'))
    view.set_busy(True, cancellable=True)
    assert not view.apply_button.isEnabled() and not view.local_button.isEnabled()
    assert view.cancel_button.isVisible() and view.cancel_button.isEnabled()


def test_success_clearly_marks_current_and_is_not_a_business_form_change(hub):
    view, panel = hub
    candidate = AppearanceCandidate('IMAGE', '小猫', 'a' * 64 + '.png')
    view.show_candidate(candidate)
    view.applied(candidate)
    assert '小猫' in view.current_label.text() and '已更换' in view.status.text()
    assert not view.apply_button.isEnabled() and not panel.form.changed()


def test_back_from_chooser_keeps_ready_candidate_usable(hub):
    view, _ = hub
    view.show_candidate(AppearanceCandidate('IMAGE', '小猫', 'a' * 64 + '.png'))
    view.show_choices('mine', [])
    assert not view.apply_button.isEnabled()
    view.back_button.click()
    assert view.apply_button.isEnabled()


def test_secondary_resource_pages_share_the_appearance_navigation(hub):
    _, panel = hub
    bar = panel.navigation.bar
    assert bar.count() == 7 and len(panel.sections) == 9
    for key in ('resources', 'upload'):
        panel.open_section(key)
        assert panel.navigation.current_key == key
        assert bar.tabData(bar.currentIndex()) == 'appearance'
        panel.collapse_section(key)
        assert panel.navigation.current_key == 'appearance'


@pytest.mark.parametrize('size', [(720, 560), (520, 480)])
@pytest.mark.parametrize('state', ['preview', 'busy', 'choices'])
def test_primary_action_remains_visible_in_compact_window(hub, size, state):
    view, panel = hub
    panel.resize(*size)
    if state == 'busy':
        view.set_busy(True, cancellable=True)
    elif state == 'choices':
        view.show_choices('online', [{'id': 'fixture', 'kind': 'IMAGE', 'name': '小猫'}])
    for _ in range(3):
        QApplication.processEvents()
    section = panel.sections['appearance']
    bounds = QRect(view.apply_button.mapTo(section.viewport(), QPoint()), view.apply_button.size())
    assert section.viewport().rect().contains(bounds)
    assert section.horizontalScrollBar().maximum() == 0
