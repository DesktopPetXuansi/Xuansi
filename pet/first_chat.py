"""把首次使用提示接到既有聊天和保存事务；后台 IO，界面只接收当前结果。"""

import asyncio
import logging

from PySide6.QtCore import QObject, Signal, Slot

from .first_chat_state import check_setup, read_completed, save_completed
from .memory import durable_io

LOG = logging.getLogger(__name__)


class FirstChatFlow(QObject):
    checked = Signal(int, bool, str)
    stored = Signal(int, str)

    def __init__(self, owner, *, path):
        super().__init__(owner.panel)
        self.owner, self.path = owner, path
        self.completed = False
        self.loaded = False
        self.closed = False
        self.generation = 0
        self.checked.connect(self._checked)
        self.stored.connect(self._stored)
        owner.runtime.chat_succeeded.connect(self._succeeded)
        owner.runtime.request_issue.connect(self._issue)
        owner.panel.first_chat.action_requested.connect(owner.panel.open_section)
        owner.panel.first_chat.example_requested.connect(self._example)
        owner.panel.configuration_required.connect(self._configuration_required)
        self.refresh()

    def refresh(self):
        if self.closed:
            return
        self.generation += 1
        self.owner.runtime.schedule(self._check(self.generation, self.owner.settings))

    async def _check(self, generation, settings):
        try:
            completed, note = await asyncio.to_thread(
                lambda: (read_completed(self.path), check_setup(settings)),
            )
        except OSError:
            completed, note = False, '暂时无法检查本地资源，可到模型设置确认后发送一句话。'
            LOG.warning('首次使用资源检查未完成')
        self.checked.emit(generation, completed, note)

    @Slot(int, bool, str)
    def _checked(self, generation, completed, note):
        if self.closed or generation != self.generation:
            return
        initial = not self.loaded
        self.loaded = True
        self.completed = self.completed or completed
        card = self.owner.panel.first_chat
        card.show()
        if self.completed:
            card.complete()
        else:
            card.set_note(note)
            if initial:
                card.toggle.setChecked(True)

    @Slot()
    def _example(self):
        panel = self.owner.panel
        if not panel.input.text().strip():
            panel.input.setText('你好，请用一句话介绍你能怎样陪我。')
        panel.input.setFocus()

    @Slot(int)
    def _succeeded(self, epoch):
        if self.closed or self.owner.paused or epoch != self.owner.runtime.epoch:
            return
        first_success = not self.completed
        self.completed = True
        self.generation += 1  # 拒绝成功之前排队的检查，避免迟到结果重新展开引导。
        self.owner.panel.first_chat.show()
        self.owner.panel.first_chat.complete()
        if first_success:
            self.owner.runtime.schedule(self._store(self.generation))
            LOG.info('首次有效文字对话已完成，引导已收起')

    async def _store(self, generation):
        error = ''
        try:
            await durable_io(save_completed, self.path)
        except OSError:
            error = '本次文字对话已完成，但引导记录未能保存；下次启动可能再次显示，不影响继续聊天。'
            LOG.warning('首次聊天完成标记未能保存，正文已正常交付')
        self.stored.emit(generation, error)

    @Slot(int, str)
    def _stored(self, generation, error):
        if not self.closed and generation == self.generation and error:
            self.owner.panel.first_chat.set_note(error, action='chat', label='继续聊天')

    @Slot()
    def _configuration_required(self):
        self.generation += 1
        self.loaded = True

    @Slot(int, object)
    def _issue(self, epoch, issue):
        if self.closed or self.owner.paused or epoch != self.owner.runtime.epoch:
            return
        # 当前请求的恢复提示优先于更早的文件检查；保存成功会发起新检查。
        self.generation += 1
        self.loaded = True
        card = self.owner.panel.first_chat
        card.set_note(issue.message, action=issue.action, label=issue.action_label)
        card.show()
        card.toggle.setChecked(True)

    def close(self):
        self.closed = True
        self.generation += 1
