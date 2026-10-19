"""把历史接到成功回执；同步复用官网任务及其取消、退出协调。"""

import asyncio
import logging
import threading

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton

from .history_dialog import HistoryDialog
from .history_sync import synchronize
from .history_tasks import HistoryIO
from .model_history import ModelHistory
from .personal_history import AppearanceHistory
from .platform_auth import authorize

LOG = logging.getLogger(__name__)


class PersonalHistory:
    def __init__(self, owner, flow, platform):
        self.owner, self.flow, self.platform = owner, flow, platform
        self.io = HistoryIO(owner.panel)
        self.appearances, self.models = AppearanceHistory(), ModelHistory()
        self.appearance_dialog = self.model_dialog = None
        self.sync_requested = False
        self.enable_cancelled = threading.Event()
        self.sync_cancelled = threading.Event()
        self.closed = False
        self.model_signature = self._model_signature(owner.settings)
        flow.applying.used.connect(self.record_appearance)
        flow.view.history_requested.connect(self.open_appearances)
        owner.panel.model_page.history_requested.connect(self.open_models)
        owner.runtime.settings_saved.connect(self.model_saved)
        platform.operation_completed.connect(self.platform_completed)
        platform.operation_failed.connect(self.platform_failed)
        platform.operation_finished.connect(self.idle)

    @staticmethod
    def _model_signature(settings):
        return settings.ai, settings.model_path, settings.projector_path

    def record_appearance(self, candidate):
        self.io.submit(lambda: self.appearances.record(candidate), self.appearance_recorded)

    def appearance_recorded(self, item, error):
        if error:
            self.flow.view.status.setText('形象已更换，但历史未能保存：' + error)
        elif item['sync'] == 'pending':
            self.sync_requested = True
            self.idle()

    def model_saved(self, settings, error):
        signature = self._model_signature(settings)
        if not error and signature != self.model_signature:
            self.model_signature = signature
            self.io.submit(lambda: self.models.record(*signature), self.model_recorded)

    def model_recorded(self, _result, error):
        if error:
            self.owner.panel.status.setText('设置已保存，但配置历史未能保存：' + error)

    def open_models(self):
        if self.model_dialog is None:
            self.model_dialog = HistoryDialog(self.owner.panel, 'AI 模型配置历史',
                '回选只填入设置草稿。请检查连接与能力后保存设置，当前模型不会立即改变。',
                self.models, self.io, self.models.configuration, '填入配置草稿')
            self.model_dialog.selected.connect(self.owner.panel.model_page.restore_configuration)
        self.model_dialog.present()

    def open_appearances(self):
        if self.appearance_dialog is None:
            dialog = HistoryDialog(self.owner.panel, '形象使用历史',
                '只记录实际使用成功的形象。选中后先预览，再点击“使用这个形象”。移除记录会保留形象文件。',
                self.appearances, self.io, self.appearances.candidate, '预览这个形象')
            dialog.selected.connect(self.preview_appearance)
            dialog.sync_state = QLabel()
            dialog.content_layout.addWidget(dialog.sync_state)
            controls = QHBoxLayout()
            for text, slot in (('连接账号并开启同步', self.enable), ('关闭同步', self.disable), ('重试同步', self.retry)):
                button = QPushButton(text)
                button.clicked.connect(slot)
                controls.addWidget(button)
            dialog.content_layout.addLayout(controls)
            dialog.finished.connect(self.cancel_sync)
            self.appearance_dialog = dialog
        self.appearance_dialog.present()

    def preview_appearance(self, candidate):
        if self.flow.view.busy:
            self.feedback('请先完成当前形象操作，再从历史选择。')
            return
        self.flow.view.show_candidate(candidate)
        self.owner.panel.open_section('appearance')

    def enable(self):
        consent = threading.Event()

        async def operation():
            client = self.platform.api()
            previous = await asyncio.to_thread(client.store.read)
            upload = bool(previous and 'resources:write' in previous.get('scope', '').split())
            tokens = await authorize(client.base_url, upload=upload, history=True)
            if consent.is_set():
                return False
            await asyncio.to_thread(client.store.save, tokens)
            profile = await client.request('GET', '/me')
            return await asyncio.to_thread(self.bind_current, consent, client.base_url, profile['id'])
        if self.start('history-enable', operation):
            self.enable_cancelled = consent

    def bind_current(self, consent, url, user):
        # 检查与提交共用文件锁。关闭立即作废同意，随后排队的关闭写入最后生效；
        # 即使取消 asyncio.to_thread 时磁盘提交已开始，也不会让迟到授权重新开启。
        with self.appearances.lock:
            if consent.is_set():
                return False
            self.appearances.bind(url, user)
            return True

    def disable(self):
        self.sync_requested = False
        self.enable_cancelled.set()
        self.sync_cancelled.set()
        self.cancel_sync()
        self.io.submit(self.appearances.disable, self.disabled)

    def disabled(self, _result, error):
        self.feedback(error or '同步已关闭，本机记录继续保留。')
        self.refresh_sync_state()

    def refresh_sync_state(self):
        if not self.closed and self.appearance_dialog is not None:
            self.io.submit(self.appearances.read, self.appearance_dialog.show_sync_state)

    def cancel_sync(self, *_):
        if self.platform.worker is not None and self.platform.worker.command.startswith('history-'):
            if self.platform.worker.command == 'history-enable':
                self.enable_cancelled.set()
            self.platform.cancel()

    def retry(self):
        self.sync_requested = True
        self.idle()

    def idle(self, *_):
        if self.closed or not self.sync_requested or self.platform.worker is not None:
            return
        cancelled = self.sync_cancelled

        async def operation():
            return await synchronize(self.appearances, self.platform.api(), cancelled=cancelled)
        # 任务退出事件后再开始，沿用平台单任务与取消边界。
        QTimer.singleShot(0, lambda: self.start('history-sync', operation))
        self.sync_requested = False

    def start(self, command, operation):
        if self.closed:
            return False
        if self.platform.start(command, operation):
            return True
        self.feedback('请先等待当前操作完成，再重试。')
        return False

    def platform_completed(self, command, result):
        if command == 'history-enable' and result and not self.enable_cancelled.is_set():
            self.sync_cancelled = threading.Event()
            self.feedback('历史同步已开启；从下一次成功使用形象开始记录。')
            self.refresh_sync_state()
        elif command == 'history-sync':
            self.feedback('待同步记录已处理。')

    def platform_failed(self, command, error):
        if command.startswith('history-'):
            self.feedback('本机记录仍保留。' + error + '；需要时可重新连接账号后重试。')

    def feedback(self, text):
        if not self.closed and self.appearance_dialog is not None:
            self.appearance_dialog.status.setText(text)
        LOG.info('形象历史任务状态已更新')

    def close(self):
        self.closed = True
        self.enable_cancelled.set()
        self.sync_cancelled.set()
        self.io.close()
        for dialog in (self.appearance_dialog, self.model_dialog):
            if dialog:
                dialog.hide()
