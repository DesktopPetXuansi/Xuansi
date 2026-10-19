"""历史装配和取消竞态只使用临时文件、合成账号及隔离 Qt 信号。"""

import asyncio
import threading
import time
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication, QLabel, QWidget

from pet.appearance_apply import AppearanceApply
from pet.appearance_import import AppearanceCandidate
from pet.config import Settings
from pet.history_controller import PersonalHistory


class Events(QObject):
    history_requested = Signal()
    settings_saved = Signal(object, str)
    platform_settings_saved = Signal(object, str)
    operation_completed = Signal(str, object)
    operation_failed = Signal(str, str)
    operation_finished = Signal(str)


def drain(app, predicate):
    deadline = time.monotonic() + 4
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    assert predicate()


@pytest.fixture
def history(tmp_path, monkeypatch):
    from pet import config

    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    monkeypatch.setattr(config, 'DATA', tmp_path)
    app = QApplication.instance() or QApplication([])
    panel = QWidget()
    panel.model_page, panel.status = Events(), QLabel()
    runtime, platform = Events(), Events()
    platform.worker = None
    platform.operation = None
    platform.cancel = lambda: None  # 模拟取消请求到达时授权结果已经在途。
    client = SimpleNamespace(base_url='https://example.test', store=Mock(read=lambda: None))

    async def request(*_args):
        return {'id': 'synthetic-account'}

    client.request = request
    platform.api = lambda: client

    def start(_command, operation):
        platform.operation = operation
        return True

    platform.start = start
    owner = SimpleNamespace(panel=panel, settings=Settings(), runtime=runtime, avatar=Mock())
    panel.settings = owner.settings
    applying = AppearanceApply(owner)
    view = Events()
    view.status = QLabel()
    controller = PersonalHistory(owner, SimpleNamespace(applying=applying, view=view), platform)
    yield controller, app, applying, owner
    controller.close()
    controller.io.pool.waitForDone(4000)
    applying.close()
    panel.close()
    app.processEvents()


def test_disabling_during_authorization_rejects_late_consent(history, monkeypatch):
    from pet import history_controller

    controller, app, _applying, _owner = history

    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()

        async def authorize(*_args, **_kwargs):
            entered.set()
            await release.wait()
            return {'scope': 'resources:read history:read history:write'}

        monkeypatch.setattr(history_controller, 'authorize', authorize)
        controller.enable()
        task = asyncio.create_task(controller.platform.operation())
        await asyncio.wait_for(entered.wait(), 2)
        controller.disable()
        drain(app, lambda: controller.appearances.path.is_file())
        assert not controller.appearances.read()['sync']['enabled']
        release.set()
        await asyncio.wait_for(task, 2)
        assert not controller.appearances.read()['sync']['enabled']

    asyncio.run(scenario())


def test_disabling_during_background_bind_finishes_disabled(history, monkeypatch):
    from pet import history_controller

    controller, app, _applying, _owner = history
    entered, release = threading.Event(), threading.Event()
    bind = controller.appearances.bind

    def blocked_bind(*args):
        entered.set()
        assert release.wait(3)
        bind(*args)

    async def authorize(*_args, **_kwargs):
        return {'scope': 'resources:read history:read history:write'}

    monkeypatch.setattr(history_controller, 'authorize', authorize)
    monkeypatch.setattr(controller.appearances, 'bind', blocked_bind)

    async def scenario():
        controller.enable()
        task = asyncio.create_task(controller.platform.operation())
        assert await asyncio.to_thread(entered.wait, 2)
        controller.disable()
        # 允许已经开始的磁盘提交结束；最后一次关闭必须仍然胜出。
        release.set()
        await asyncio.wait_for(task, 3)
        assert await asyncio.to_thread(controller.io.pool.waitForDone, 3000)
        app.processEvents()
        assert not controller.appearances.read()['sync']['enabled']

    asyncio.run(scenario())


def test_successful_appearance_receipt_reaches_local_history(history):
    controller, app, applying, owner = history
    changes = []
    owner.runtime.persist_platform = changes.append
    selected = AppearanceCandidate('DEFAULT', '默认玄司')
    applying.use(selected)
    assert controller.appearances.read()['entries'] == []
    saved = replace(owner.settings, **changes[-1])
    owner.runtime.platform_settings_saved.emit(saved, '')
    drain(app, lambda: controller.appearances.path.is_file())
    assert controller.appearances.read()['entries'][0]['name'] == selected.name
    assert not controller.appearances.read()['sync']['enabled']
