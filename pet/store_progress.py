"""首次资源准备的进度窗口；关闭前等待后台进程退出。"""

import logging

from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtWidgets import QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout

from .store_preparation import StorePreparation
from .store_setup_widgets import resource_summary
from .theme import ThemedDialog

LOG = logging.getLogger(__name__)


class StoreProgressDialog(ThemedDialog):
    def __init__(self, root, selection, parent=None, *, preparation=None):
        super().__init__(parent)
        self._selection = selection
        self._running = False
        self._close_requested = False
        self._started = False
        self.preparation = preparation if preparation is not None else StorePreparation(root, parent=self)
        self.setWindowTitle("准备玄司")
        self.setMinimumWidth(480)
        self.resize(600, 330)
        layout = QVBoxLayout(self)
        title = QLabel("正在准备你的桌面伙伴")
        title.setObjectName("title")
        layout.addWidget(title)
        summary = QLabel(resource_summary(selection.plan, prepared=True))
        summary.setTextFormat(Qt.TextFormat.PlainText)
        summary.setWordWrap(True)
        layout.addWidget(summary)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setTextVisible(False)
        layout.addWidget(self.progress_bar)
        self.status = QLabel("即将准备已选择的资源，请保持网络连接。")
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        hint = QLabel("准备过程可能需要一些时间。取消后会保留已下载的文件，稍后可重试。")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        actions = QHBoxLayout()
        actions.addStretch()
        self.retry = QPushButton("重试准备")
        self.retry.setAutoDefault(False)
        self.retry.hide()
        self.cancel = QPushButton("取消")
        self.cancel.setAutoDefault(False)
        actions.addWidget(self.retry)
        actions.addWidget(self.cancel)
        layout.addLayout(actions)
        self.retry.clicked.connect(self._start)
        self.cancel.clicked.connect(self.reject)
        self.preparation.progress.connect(self._progress)
        self.preparation.finished.connect(self._finished)
        # 窗口显示后才启动；使用绑定槽，避免 Qt 父子对象的闭包释放环。
        self._start_timer = QTimer(self)
        self._start_timer.setSingleShot(True)
        self._start_timer.timeout.connect(self._start)

    def showEvent(self, event):
        super().showEvent(event)
        if not self._started and self._selection is not None:
            self._started = True
            self._start_timer.start(0)

    @Slot()
    def _start(self):
        if self._running or self._selection is None or self._close_requested:
            return
        self._running = True
        self.retry.hide()
        self.cancel.setEnabled(True)
        self.progress_bar.setRange(0, 0)
        self.status.setText("正在准备已选择的资源，请保持网络连接。")
        try:
            selection = self._selection
            self.preparation.start(selection.plan, selection.profile, selection.key or "")
            LOG.info("首次配置资源准备已请求")
        except Exception as exc:
            LOG.warning("首次配置资源准备无法开始，类别=%s", type(exc).__name__)
            # 后台若尚未停止，保留窗口，不能在活动进程上执行窗口销毁。
            if self.preparation.process is not None:
                self._close_requested = True
                self.status.setText("正在停止准备，请稍候…")
                self.cancel.setEnabled(False)
                self.preparation.cancel()
            else:
                self._failed()

    @Slot(str)
    def _progress(self, _message):
        if self._running and not self._close_requested:
            # 后台消息不直接透传，用户输入或底层异常不能把密钥带到界面。
            self.status.setText("正在准备已选择的资源，请保持网络连接。")

    @Slot(bool, str)
    def _finished(self, success, _message):
        if not self._running:
            return
        if self.preparation.process is not None:
            LOG.warning("资源准备结果到达时进程仍在运行，等待退出")
            return
        self._running = False
        if self._close_requested:
            self._selection = None
            super().reject()
        elif success:
            self._selection = None
            self.progress_bar.setRange(0, 1)
            self.progress_bar.setValue(1)
            LOG.info("首次配置资源准备已完成")
            super().accept()
        else:
            self._failed()

    def _failed(self):
        self._running = False
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        self.status.setText("准备未完成，请检查网络、可用空间和目录权限后重试。")
        self.retry.show()
        self.retry.setEnabled(True)
        self.cancel.setEnabled(True)

    @Slot()
    def reject(self):
        self._start_timer.stop()
        if self._running or self.preparation.process is not None:
            if not self._close_requested:
                self._close_requested = True
                self.retry.setEnabled(False)
                self.cancel.setEnabled(False)
                self.status.setText("正在取消准备，已下载的文件将保留，请稍候…")
                self.preparation.cancel()
            return
        self._selection = None
        LOG.info("首次配置资源准备窗口已取消")
        super().reject()

    def closeEvent(self, event):
        if self._running or self.preparation.process is not None:
            event.ignore()
            self.reject()
        else:
            super().closeEvent(event)
