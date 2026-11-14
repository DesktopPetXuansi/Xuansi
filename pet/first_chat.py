"""把首次使用提示接到既有聊天和保存事务；后台 IO，界面只接收当前结果。"""

import asyncio
import logging
from threading import Event

from PySide6.QtCore import QObject, Qt, Signal, Slot
from PySide6.QtWidgets import QCheckBox, QMessageBox

from .ai.local_setup import download_model, inspect_local_setup
from .ai.resource_download import DownloadPaused
from .config import MODELS
from .first_chat_state import check_setup, read_completed, save_completed
from .memory import durable_io

LOG = logging.getLogger(__name__)


class FirstChatFlow(QObject):
    checked = Signal(int, bool, str)
    setup_checked = Signal(int, bool, object, bool)
    setup_progress = Signal(object, str, object, object)
    setup_finished = Signal(object, str)
    stored = Signal(int, str)

    def __init__(self, owner, *, path):
        super().__init__(owner.panel)
        self.owner, self.path = owner, path
        self.completed = False
        self.loaded = False
        self.closed = False
        self.generation = 0
        self.setup_generation = 0
        self.inspected_generation = 0
        self.auto_path = path.with_name('model-auto-download.json')
        self.plan = None
        self.transfer = None
        self.auto = False
        self.auto_loaded = False
        self.auto_attempted = False
        self.auto_write_lock = asyncio.Lock()
        self.approved_plan = None
        self.checked.connect(self._checked)
        self.setup_checked.connect(self._setup_checked)
        self.setup_progress.connect(self._setup_progress)
        self.setup_finished.connect(self._setup_finished)
        self.stored.connect(self._stored)
        owner.runtime.chat_succeeded.connect(self._succeeded)
        owner.runtime.request_issue.connect(self._issue)
        owner.panel.first_chat.action_requested.connect(self._action)
        owner.panel.model_page.prepare_model.clicked.connect(self._open_setup)
        owner.panel.model_page.auto_download.toggled.connect(self._set_auto)
        owner.panel.first_chat.example_requested.connect(self._example)
        owner.panel.configuration_required.connect(self._configuration_required)
        self.refresh()

    def refresh(self):
        if self.closed:
            return
        self.generation += 1
        self.owner.runtime.schedule(self._check(self.generation, self.owner.settings))
        self._refresh_setup()

    def _refresh_setup(self):
        self.setup_generation += 1
        self.owner.runtime.schedule(self._inspect(self.setup_generation, self.owner.settings))

    async def _inspect(self, generation, settings):
        try:
            found, plan, auto = await asyncio.to_thread(
                lambda: (*inspect_local_setup(settings, MODELS), read_completed(self.auto_path)),
            )
        except OSError:
            found, plan, auto = False, None, False
            LOG.warning('本机模型目录检查未完成')
        self.setup_checked.emit(generation, found, plan, auto)

    @Slot(int, bool, object, bool)
    def _setup_checked(self, generation, found, plan, auto):
        if self.closed or generation != self.setup_generation:
            return
        self.inspected_generation = generation
        if self.transfer is not None and plan != self.plan:
            self.transfer.set()
        self.plan = plan
        self.owner.panel.model_setup_required = plan is not None
        if plan is None and self.owner.panel.status.text() == '本机模型待准备，输入内容已保留。':
            self.owner.panel.status.setText('模型文件已找到，可以发送消息。' if found else '模型设置已更新。')
        if not self.auto_loaded:
            self._show_auto(auto)
            self.auto_loaded = True
        card = self.owner.panel.first_chat
        if found:
            self.owner.panel.model_readiness.set_status('本机模型文件已找到', ready=True)
            if card.action_key in ('prepare-model', 'pause-model') or (
                not self.completed and card.action_key == 'model' and card.action.text() == '模型设置'
            ):
                card.set_note('本机模型文件已找到。可以直接发送消息，模型将在首次对话时加载。')
        elif plan is not None and self.transfer is None:
            self.owner.panel.model_readiness.set_status('本机模型待准备')
            self._offer_download()
            if self.auto and not self.auto_attempted:
                self._start_download()
        elif plan is None:
            self.owner.panel.model_readiness.set_status(
                '在线模式' if self.owner.settings.ai.policy == 'online_first' else '检查本机模型设置',
            )
            if card.action_key in ('prepare-model', 'pause-model'):
                card.set_note('请到模型设置检查当前配置。')

    def _offer_download(self, note=None, *, resume=False):
        plan = self.plan
        if plan is None:
            return
        card = self.owner.panel.first_chat
        card.set_note(note or f'未找到可用的 {plan.name} 配套文件。需下载约 {plan.size / 10**9:.2f} GB。',
                      action='prepare-model', label='继续下载' if resume else '准备本机模型')
        card.show()
        card.toggle.setChecked(True)

    @Slot()
    def _open_setup(self):
        panel = self.owner.panel
        page = panel.model_page
        try:
            pending = page.credential_changed() or page.apply(self.owner.settings) != self.owner.settings
        except ValueError:
            pending = True
        if pending or panel.form.saving:
            panel.status.setText('请先保存模型设置，再检查或准备所选模型。')
            return
        if self.transfer is None:
            self._refresh_setup()
            panel.model_readiness.set_status('正在检查模型')
        panel.open_section('chat')
        panel.first_chat.show()
        panel.first_chat.toggle.setChecked(True)

    @Slot(str)
    def _action(self, key):
        if key == 'pause-model':
            if self.transfer is not None:
                self.transfer.set()
                self.owner.panel.first_chat.set_note('正在暂停下载，已下载部分会保留。', action='pause-model',
                                                     label='正在暂停')
            return
        if key != 'prepare-model':
            self.owner.panel.open_section(key)
            return
        plan = self.plan
        if (plan is None or self.transfer is not None
                or self.inspected_generation != self.setup_generation):
            return
        if self.auto or self.approved_plan == plan:
            self._start_download()
            return
        dialog = QMessageBox(self.owner.panel)
        dialog.setWindowTitle('下载本机模型')
        dialog.setTextFormat(Qt.TextFormat.PlainText)
        dialog.setText(f'下载 {plan.name} 的所缺文件？')
        dialog.setInformativeText(f'最多约 {plan.size / 10**9:.2f} GB。校验后即可在本机使用。\n保存到 {plan.root}')
        remember = QCheckBox('以后缺少本机模型时自动补齐', dialog)
        dialog.setCheckBox(remember)
        start = dialog.addButton('开始下载', QMessageBox.ButtonRole.AcceptRole)
        cancel = dialog.addButton('取消', QMessageBox.ButtonRole.RejectRole)
        dialog.setDefaultButton(cancel)
        dialog.exec()
        if (dialog.clickedButton() != start or self.closed or plan != self.plan
                or self.inspected_generation != self.setup_generation):
            return
        self.approved_plan = plan
        if remember.isChecked():
            self._set_auto(True)
        self._start_download()

    def _show_auto(self, enabled):
        self.auto = enabled
        checkbox = self.owner.panel.model_page.auto_download
        checkbox.blockSignals(True)
        checkbox.setChecked(enabled)
        checkbox.blockSignals(False)

    @Slot(bool)
    def _set_auto(self, enabled):
        self.auto_loaded = True
        self._show_auto(enabled)
        self.owner.runtime.schedule(self._save_auto(enabled))

    async def _save_auto(self, enabled):
        try:
            async with self.auto_write_lock:
                if enabled:
                    await durable_io(save_completed, self.auto_path)
                else:
                    await durable_io(self.auto_path.unlink, True)
        except OSError:
            LOG.warning('自动下载偏好未能保存')

    def _start_download(self):
        if self.closed or self.plan is None or self.transfer is not None:
            return
        self.auto_attempted = True
        self.transfer = Event()
        self.owner.panel.first_chat.show()
        self.owner.panel.first_chat.toggle.setChecked(True)
        self._setup_progress(self.transfer, 'download', 0, 0)
        self.owner.runtime.schedule(self._download(self.plan, self.transfer))

    async def _download(self, plan, transfer):
        message = ''
        try:
            await asyncio.to_thread(download_model, plan, transfer,
                                    lambda phase, done, size: self.setup_progress.emit(transfer, phase, done, size))
        except DownloadPaused:
            message = '下载已暂停，已下载部分会保留。'
        except ValueError as exc:
            message = str(exc)
        except OSError as exc:
            LOG.warning('本机模型下载未完成 type=%s', type(exc).__name__)
            message = '下载未完成。请检查网络或磁盘后重试，已下载部分会保留。'
        self.setup_finished.emit(transfer, message)

    @Slot(object, str, object, object)
    def _setup_progress(self, transfer, phase, done, size):
        if self.closed or transfer is not self.transfer or transfer.is_set():
            return
        text = '正在校验模型文件' if phase == 'verify' else '正在下载本机模型'
        self.owner.panel.model_readiness.set_status(text)
        card = self.owner.panel.first_chat
        card.set_note(text + '…', action='pause-model', label='暂停')
        card.download_progress(phase, done, size)

    @Slot(object, str)
    def _setup_finished(self, transfer, message):
        if self.closed or transfer is not self.transfer:
            return
        self.transfer = None
        if message and self.plan is not None:
            self.owner.panel.model_readiness.set_status('本机模型待准备')
            self._offer_download(message, resume=True)
        else:
            self.owner.panel.first_chat.set_note('正在重新检查本机模型…', action='prepare-model', label='正在检查')
            self._refresh_setup()

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
        if self.transfer is not None or card.action_key == 'prepare-model':
            return
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
        if self.transfer is None:
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
        if self.transfer is not None:
            return
        if self.plan is not None and issue.action == 'model' and self.owner.settings.ai.policy == 'local_only':
            self._offer_download()
            return
        card.set_note(issue.message, action=issue.action, label=issue.action_label)
        card.show()
        card.toggle.setChecked(True)

    def close(self):
        self.closed = True
        self.generation += 1
        if self.transfer is not None:
            self.transfer.set()
