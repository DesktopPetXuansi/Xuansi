"""本机历史使用单独串行队列，读写顺序与用户操作保持一致。"""

import logging

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

LOG = logging.getLogger(__name__)


class HistoryResults(QObject):
    completed = Signal(int, object, str)


class HistoryWork(QRunnable):
    def __init__(self, results, identifier, operation):
        super().__init__()
        self.results, self.identifier, self.operation = results, identifier, operation

    def run(self):
        try:
            value, error = self.operation(), ''
        except Exception as exc:
            LOG.warning('本机历史任务未完成 type=%s', type(exc).__name__)
            value = None
            error = str(exc) if isinstance(exc, ValueError) else '历史读写失败，请检查磁盘空间和文件权限后重试。'
        self.results.completed.emit(self.identifier, value, error)


class HistoryIO(QObject):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)
        self.results = HistoryResults()
        self.results.completed.connect(self._complete)
        self.callbacks = {}
        self.sequence = 0
        self.closed = False

    def submit(self, operation, callback):
        if self.closed:
            return
        self.sequence += 1
        self.callbacks[self.sequence] = callback
        self.pool.start(HistoryWork(self.results, self.sequence, operation))

    def _complete(self, identifier, value, error):
        callback = self.callbacks.pop(identifier, None)
        if callback and not self.closed:
            callback(value, error)

    def close(self):
        self.closed = True
        self.callbacks.clear()
