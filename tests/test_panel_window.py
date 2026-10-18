"""窗口尺寸持久化回归；使用临时文件，不接触业务配置或用户数据。"""

import json

import pytest
from PySide6.QtCore import QSize
from PySide6.QtWidgets import QApplication

from pet.config import Settings
from pet.panel import Panel


@pytest.fixture
def windows(monkeypatch, tmp_path):
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    application = QApplication.instance() or QApplication([])
    application.setQuitOnLastWindowClosed(False)
    opened = []
    state = tmp_path / 'panel-window.json'

    def create(path=state):
        window = Panel(Settings(), window_state_path=path)
        window.logs.path = tmp_path / 'panel.log'
        opened.append(window)
        window.show()
        application.processEvents()
        application.processEvents()
        return window

    yield create, state, application
    for window in opened:
        window.hide()
        window.deleteLater()
    application.processEvents()


def test_first_open_uses_compact_size(windows):
    create, state, _ = windows
    window = create()
    assert window.size() == QSize(720, 560)
    assert not state.exists(), '首次展示不需要写入尺寸文件'


@pytest.mark.parametrize('action', ['close', 'hide'])
def test_reopening_restores_size_without_saving_business_settings(windows, action):
    create, state, application = windows
    window = create()
    requested = []
    window.settings_requested.connect(requested.append)
    window.resize(640, 520)
    application.processEvents()
    assert not state.exists(), '拖动窗口期间不反复写磁盘'
    getattr(window, action)()
    application.processEvents()
    assert not window.isVisible()
    assert create().size() == QSize(640, 520)
    assert requested == [] and not window.form.changed()


@pytest.mark.parametrize('content', ['{', '[]', '{"width": true, "height": 540}',
                                      '{"width": -1, "height": 540}'])
def test_invalid_state_falls_back_without_rewriting_it(windows, content):
    create, state, _ = windows
    state.write_text(content, encoding='utf-8')
    assert create().size() == QSize(720, 560)
    assert state.read_text(encoding='utf-8') == content


def test_restore_respects_minimum_window_size(windows):
    create, state, _ = windows
    state.write_text(json.dumps({'width': 1, 'height': 1}), encoding='utf-8')
    assert create().size() == QSize(520, 480)


def test_oversized_state_fits_current_screen(windows):
    create, state, _ = windows
    state.write_text(json.dumps({'width': 5000, 'height': 5000}), encoding='utf-8')
    window = create()
    available = window.screen().availableGeometry().size()
    assert window.width() < available.width()
    assert window.height() < available.height()


@pytest.mark.parametrize('state_method', ['showMaximized', 'showMinimized', 'showFullScreen'])
def test_window_state_preserves_normal_size(windows, state_method):
    create, _, application = windows
    window = create()
    window.resize(640, 520)
    application.processEvents()
    getattr(window, state_method)()
    application.processEvents()
    window.hide()
    application.processEvents()
    restored = create()
    assert restored.size() == QSize(640, 520)
    assert not restored.isMaximized() and not restored.isMinimized() and not restored.isFullScreen()


def test_state_write_failure_does_not_prevent_hiding(windows, tmp_path, caplog):
    create, _, _ = windows
    blocker = tmp_path / 'not-a-directory'
    blocker.write_text('占位文件', encoding='utf-8')
    window = create(blocker / 'panel-window.json')
    window.hide()
    assert not window.isVisible()
    assert '无法保存控制中心窗口大小' in caplog.text
