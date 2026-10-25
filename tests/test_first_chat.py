"""首次文字对话的状态与入口；临时文件隔离，不连接服务或使用真实个人配置。"""

import asyncio
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QObject, QPoint, QRect, Signal
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication

from pet.ai.settings import AISettings, ModelProfile
from pet.config import Settings
from pet.conversation_issues import ConversationIssue
from pet.first_chat import FirstChatFlow
from pet.first_chat_state import check_setup, read_completed, save_completed
from pet.panel import Panel


def test_completion_stores_only_version_and_success(tmp_path):
    path = tmp_path / 'first-chat.json'
    assert not read_completed(path)
    save_completed(path)
    assert read_completed(path)
    assert json.loads(path.read_text(encoding='utf-8')) == {'version': 1, 'completed': True}


@pytest.mark.parametrize('raw', ['invalid', '[]', '{"version":2,"completed":true}',
                                 '{"version":1,"completed":"true"}'])
def test_invalid_completion_is_not_success_and_keeps_original(tmp_path, raw):
    path = tmp_path / 'first-chat.json'
    path.write_text(raw, encoding='utf-8')
    assert not read_completed(path)
    assert path.read_text(encoding='utf-8') == raw


def test_file_presence_is_not_model_readiness(tmp_path):
    model, projector = tmp_path / 'model.gguf', tmp_path / 'projector.gguf'
    settings = replace(Settings(), model_path=str(model), projector_path=str(projector))
    assert '未找到' in check_setup(settings)
    model.touch()
    projector.touch()
    assert '待对话确认' in check_setup(settings)


def test_online_hint_distinguishes_missing_configuration_and_potential_fees():
    settings = replace(Settings(), ai=AISettings(policy='online_first'))
    assert '尚未填完整' in check_setup(settings)
    profile = ModelProfile(endpoint='https://example.invalid/v1', model='example', credential_ref='saved-ref')
    hint = check_setup(replace(settings, ai=replace(settings.ai, profile=profile)))
    assert '待对话确认' in hint and '费用' in hint
    assert 'example.invalid' not in hint and 'saved-ref' not in hint


class RuntimeStub(QObject):
    chat_succeeded = Signal(int)
    request_issue = Signal(int, object)

    def __init__(self):
        super().__init__()
        self.epoch = 1
        self.pending = []

    def schedule(self, coroutine):
        self.pending.append(coroutine)

    def drain(self):
        while self.pending:
            asyncio.run(self.pending.pop(0))


@pytest.fixture
def setup_flow(monkeypatch, tmp_path):
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    application = QApplication.instance() or QApplication([])
    panel = Panel(Settings())
    panel.logs.path = tmp_path / 'test.log'
    owner = SimpleNamespace(panel=panel, settings=panel.settings, runtime=RuntimeStub(), busy=False,
                            paused=False)
    path = tmp_path / 'first-chat.json'
    flow = FirstChatFlow(owner, path=path)
    panel.show()
    owner.runtime.drain()
    application.processEvents()
    yield owner, flow, path
    flow.close()
    owner.runtime.drain()
    panel.hide()
    panel.deleteLater()
    application.processEvents()


def test_example_keeps_draft_and_requires_explicit_send(setup_flow):
    owner, flow, path = setup_flow
    sent = QSignalSpy(owner.panel.send_requested)
    owner.panel.first_chat.example.click()
    assert owner.panel.input.text()
    assert sent.count() == 0 and not path.exists()
    owner.panel.input.setText('我的草稿')
    owner.panel.first_chat.example.click()
    assert owner.panel.input.text() == '我的草稿'
    assert sent.count() == 0


def test_only_current_final_chat_completes_and_late_check_does_not_reopen(setup_flow):
    owner, flow, path = setup_flow
    owner.runtime.chat_succeeded.emit(0)
    assert not path.exists() and not flow.completed
    generation = flow.generation
    owner.runtime.chat_succeeded.emit(1)
    owner.runtime.drain()
    assert read_completed(path) and flow.completed
    assert not owner.panel.first_chat.toggle.isChecked()
    flow.checked.emit(generation, False, '迟到的旧检查')
    assert flow.completed and not owner.panel.first_chat.toggle.isChecked()


def test_model_draft_blocks_send_without_losing_input(setup_flow):
    owner, flow, path = setup_flow
    owner.panel.model_page.model.setText('new-model.gguf')
    owner.panel.input.setText('你好')
    sent = QSignalSpy(owner.panel.send_requested)
    owner.panel._send()
    assert sent.count() == 0
    assert owner.panel.input.text() == '你好'
    assert owner.panel.navigation.current_key == 'model'
    assert '保存' in owner.panel.first_chat.note.text()
    assert not path.exists()


def test_saved_configuration_uses_existing_send_signal(setup_flow):
    owner, flow, path = setup_flow
    owner.panel.input.setText('你好')
    sent = QSignalSpy(owner.panel.send_requested)
    owner.panel._send()
    assert sent.count() == 1 and sent.at(0) == ['你好', False]
    assert not owner.panel.input.text() and not path.exists()


def test_expanded_setup_keeps_small_window_composer_visible(setup_flow):
    owner, flow, path = setup_flow
    panel = owner.panel
    panel.resize(520, 480)
    panel.first_chat.set_note('本地模型未找到。请前往模型设置，确认模型和配套组件，保存后回来发送一句话。')
    panel.first_chat.toggle.setChecked(True)
    application = QApplication.instance()
    application.processEvents()
    application.processEvents()
    viewport = panel.sections['chat'].viewport()
    bounds = QRect(panel.input.mapTo(viewport, QPoint()), panel.input.size())
    assert viewport.rect().contains(bounds)
    assert panel.input.height() >= panel.input.minimumSizeHint().height()
    assert panel.chat.height() >= 64
    assert panel.sections['chat'].verticalScrollBar().maximum() == 0
    card_bounds = QRect(panel.first_chat.mapTo(viewport, QPoint()), panel.first_chat.size())
    assert viewport.rect().contains(card_bounds), '引导卡不能横向溢出视口'
    for button in (panel.first_chat.action, panel.first_chat.example):
        button_bounds = QRect(button.mapTo(panel.first_chat, QPoint()), button.size())
        assert panel.first_chat.rect().contains(button_bounds), '引导操作必须完整显示在卡片内'


def test_closing_cancels_late_ui_updates(setup_flow):
    owner, flow, path = setup_flow
    flow.close()
    owner.runtime.chat_succeeded.emit(1)
    owner.runtime.drain()
    assert not path.exists()


def test_slow_readiness_cannot_replace_current_recovery_hint(setup_flow):
    owner, flow, path = setup_flow
    generation = flow.generation
    issue = ConversationIssue('服务拒绝访问，请检查权限。', 'model', '检查模型设置')
    owner.runtime.request_issue.emit(1, issue)
    flow.checked.emit(generation, False, '迟到的配置检查')
    assert owner.panel.first_chat.note.text() == issue.message
    assert owner.panel.first_chat.toggle.isChecked()


def test_completion_write_failure_does_not_undo_delivered_text(setup_flow, monkeypatch):
    owner, flow, path = setup_flow

    def denied(_path):
        raise PermissionError('synthetic denial')

    monkeypatch.setattr('pet.first_chat.save_completed', denied)
    owner.runtime.chat_succeeded.emit(1)
    owner.runtime.drain()
    assert flow.completed and not path.exists()
    assert '不影响继续聊天' in owner.panel.first_chat.note.text()


def test_success_after_recovery_clears_old_error_without_rewriting_marker(setup_flow, monkeypatch):
    owner, flow, path = setup_flow
    owner.runtime.chat_succeeded.emit(1)
    owner.runtime.drain()
    issue = ConversationIssue('本轮服务不可用', 'model', '模型设置')
    owner.runtime.request_issue.emit(1, issue)
    assert owner.panel.first_chat.toggle.isChecked()
    owner.runtime.epoch = 2
    owner.runtime.chat_succeeded.emit(2)
    assert not owner.panel.first_chat.toggle.isChecked()
    assert '本轮服务不可用' not in owner.panel.first_chat.note.text()
    assert not owner.runtime.pending


def test_model_draft_hint_rejects_slow_readiness(setup_flow):
    owner, flow, path = setup_flow
    generation = flow.generation
    owner.panel.model_page.model.setText('new-model.gguf')
    owner.panel.input.setText('你好')
    owner.panel._send()
    flow.checked.emit(generation, False, '迟到检查')
    assert '保存' in owner.panel.first_chat.note.text()


def test_old_marker_write_failure_cannot_replace_new_request_issue(setup_flow):
    owner, flow, path = setup_flow
    owner.runtime.chat_succeeded.emit(1)
    generation = flow.generation
    issue = ConversationIssue('新的网络错误', 'model', '模型设置')
    owner.runtime.request_issue.emit(1, issue)
    flow.stored.emit(generation, '旧写入失败')
    assert owner.panel.first_chat.note.text() == issue.message


def test_recovery_actions_fit_small_viewport_after_completed_chat(setup_flow):
    owner, flow, path = setup_flow
    owner.runtime.chat_succeeded.emit(1)
    owner.runtime.drain()
    owner.runtime.request_issue.emit(1, ConversationIssue('请检查模型权限后保存。', 'model', '检查模型设置'))
    panel = owner.panel
    panel.resize(520, 480)
    application = QApplication.instance()
    application.processEvents()
    application.processEvents()
    viewport = panel.sections['chat'].viewport()
    for widget in (panel.first_chat, panel.first_chat.action, panel.first_chat.example, panel.input):
        assert viewport.rect().contains(QRect(widget.mapTo(viewport, QPoint()), widget.size()))
