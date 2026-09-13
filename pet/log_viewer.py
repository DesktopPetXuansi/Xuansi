"""有限日志尾部阅读器；打开时异步刷新，隐藏时停止磁盘轮询。"""

import logging
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .config import DATA

LOG = logging.getLogger(__name__)


def read_tail(path: Path, limit=256 * 1024):
    try:
        with path.open("rb") as stream:
            size = stream.seek(0, 2)
            stream.seek(max(0, size - limit))
            data = stream.read(limit)
        if size > limit:
            data = data.split(b"\n", 1)[-1]
        return data.decode("utf-8", errors="replace").splitlines()[-1000:], ""
    except FileNotFoundError:
        return [], "尚无运行日志"
    except OSError:
        return [], "日志暂不可读取，请稍后刷新"


class LogResult(QObject):
    loaded = Signal(object, str)


class ReadLog(QRunnable):
    def __init__(self, result, path):
        super().__init__()
        self.result, self.path = result, path

    def run(self):
        self.result.loaded.emit(*read_tail(self.path))


class LogViewer(QWidget):
    def __init__(self, style, path=DATA / "pet.log"):
        super().__init__()
        self.path = path
        self.lines = []
        self.loading = False
        self.setWindowTitle("运行日志")
        self.resize(780, 490)
        self.setStyleSheet(style)
        layout = QVBoxLayout(self)
        note = QLabel("最近 1000 行 · 仅运行状态、耗时和错误类型，不记录聊天或画面正文")
        note.setWordWrap(True)
        layout.addWidget(note)
        row = QHBoxLayout()
        self.level = QComboBox()
        self.level.addItems(["全部级别", "INFO", "WARNING", "ERROR"])
        self.level.currentIndexChanged.connect(self.render)
        row.addWidget(self.level)
        self.follow = QCheckBox("自动跟随")
        self.follow.setChecked(True)
        row.addWidget(self.follow)
        refresh = QPushButton("刷新")
        refresh.clicked.connect(self.refresh)
        row.addWidget(refresh)
        layout.addLayout(row)
        self.content = QPlainTextEdit()
        self.content.setReadOnly(True)
        self.content.setMaximumBlockCount(1000)
        self.content.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        layout.addWidget(self.content)
        self.status = QLabel()
        layout.addWidget(self.status)
        self.result = LogResult(self)
        self.result.loaded.connect(self.loaded)
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(lambda: self.refresh() if self.follow.isChecked() else None)

    def refresh(self):
        if not self.loading:
            self.loading = True
            QThreadPool.globalInstance().start(ReadLog(self.result, self.path))

    def loaded(self, lines, error):
        self.loading = False
        self.status.setText(error or f"最近 {len(lines)} 行 · 隐藏窗口后停止刷新")
        if lines != self.lines:
            self.lines = lines
            self.render()

    def render(self):
        level = self.level.currentText()
        lines = (
            self.lines
            if self.level.currentIndex() == 0
            else [line for line in self.lines if f" {level} " in line]
        )
        scroll = self.content.verticalScrollBar()
        previous = scroll.value()
        self.content.setPlainText("\n".join(lines))
        scroll.setValue(scroll.maximum() if self.follow.isChecked() else previous)

    def showEvent(self, event):
        self.refresh()
        self.timer.start()
        LOG.info("打开运行日志菜单")
        super().showEvent(event)

    def hideEvent(self, event):
        self.timer.stop()
        super().hideEvent(event)
