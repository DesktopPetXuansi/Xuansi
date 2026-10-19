"""把用户反馈交给现有异步循环；收据通过Qt信号回到界面线程。"""

import asyncio
import json
import logging
from concurrent.futures import CancelledError
from uuid import uuid4

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from .feedback import collect_diagnostics
from .feedback_client import FeedbackClient
from .feedback_dialog import FeedbackDialog
from .platform_auth import website_url

LOG = logging.getLogger(__name__)


class FeedbackController(QObject):
    submission_finished = Signal(object, str)
    diagnostics_finished = Signal(object, str)
    connection_requested = Signal()

    def __init__(self, parent, settings_getter, loop):
        super().__init__(parent)
        self.settings_getter, self.loop = settings_getter, loop
        self.dialog = FeedbackDialog(parent)
        self.pending = None
        self.diagnostic_job = None
        self.closed = False
        self.attempt = None
        self.dialog.submit_requested.connect(self.submit)
        self.dialog.diagnostics_requested.connect(self.prepare_diagnostics)
        self.dialog.copy_requested.connect(self.copy)
        self.dialog.connection_requested.connect(self.open_connection)
        self.submission_finished.connect(self._complete)
        self.diagnostics_finished.connect(self._diagnostics_complete)

    def open(self):
        if self.closed:
            return
        if self.pending is None:
            try:
                self.dialog.destination.setText("发送到：" + website_url(self.settings_getter().platform_url))
            except ValueError:
                self.dialog.failed("请先在官网连接中填写正确的网站地址。")
        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()
        LOG.info("打开反馈中心，不自动请求或发送任何内容")

    def submit(self, draft):
        if self.closed:
            return
        if self.pending is not None:
            return
        try:
            payload = draft.payload()
            base = website_url(self.settings_getter().platform_url)
            if not self.loop.is_running():
                raise ValueError("反馈暂时无法提交，内容已保留，请稍后重试。")
        except ValueError as exc:
            self.dialog.failed(str(exc))
            return
        # 同内容、同接收网站的重试使用原请求编号；不保存正文到日志或磁盘。
        identity = json.dumps([base, payload], sort_keys=True, ensure_ascii=False)
        if self.attempt is None or self.attempt[0] != identity:
            self.attempt = (identity, str(uuid4()))
        self.dialog.destination.setText("发送到：" + base)
        self.dialog.set_busy(True)
        self.pending = asyncio.run_coroutine_threadsafe(FeedbackClient(base).submit(payload, self.attempt[1]), self.loop)
        self._watch(self.pending, self.submission_finished)
        LOG.info("用户提交反馈 category=%s diagnostics=%s", draft.category, draft.diagnostics is not None)

    def prepare_diagnostics(self):
        if self.closed or self.diagnostic_job is not None:
            return
        if not self.loop.is_running():
            self.dialog.diagnostics_failed()
            return
        self.diagnostic_job = asyncio.run_coroutine_threadsafe(self._diagnostics(), self.loop)
        self._watch(self.diagnostic_job, self.diagnostics_finished)

    async def _diagnostics(self):
        return await asyncio.to_thread(collect_diagnostics)

    def _watch(self, future, signal):
        def finished(completed):
            try:
                value, error = completed.result(), ""
            except CancelledError:
                return
            except ValueError as exc:
                value, error = None, str(exc)
            except Exception as exc:
                LOG.warning("反馈后台任务未完成 type=%s", type(exc).__name__)
                value, error = None, "反馈暂时无法完成，内容已保留，请稍后重试。"
            if not self.closed:
                signal.emit(value, error)

        future.add_done_callback(finished)

    def _complete(self, receipt, error):
        self.pending = None
        if self.closed:
            return
        if error:
            self.dialog.failed(error)
        else:
            # 确认后结束本次重试；“再写一条”即使同文，也必须创建独立反馈。
            self.attempt = None
            self.dialog.received(receipt)

    def _diagnostics_complete(self, values, error):
        self.diagnostic_job = None
        if self.closed:
            return
        if error:
            self.dialog.diagnostics_failed()
        else:
            self.dialog.set_diagnostics(values)

    def copy(self, text):
        QApplication.clipboard().setText(text)
        self.dialog.status.setText("反馈内容已复制，可保存或通过其他方式提供。")
        LOG.info("用户复制反馈内容")

    def open_connection(self):
        self.dialog.hide()
        self.connection_requested.emit()

    def shutdown(self):
        self.closed = True
        for future in (self.pending, self.diagnostic_job):
            if future is not None:
                future.cancel()
        self.dialog.hide()
        LOG.info("反馈中心已关闭，停止等待后台请求")
