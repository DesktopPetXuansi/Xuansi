"""历史列表只负责选择和操作反馈，磁盘任务由串行历史队列执行。"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QListWidget, QPushButton, QVBoxLayout


class HistoryDialog(QDialog):
    selected = Signal(object)

    def __init__(self, parent, title, description, store, io, resolve, select_label):
        super().__init__(parent)
        self.store, self.io, self.resolve = store, io, resolve
        self.setWindowTitle(title)
        self.resize(580, 430)
        self.content_layout = QVBoxLayout(self)
        hint = QLabel(description)
        hint.setWordWrap(True)
        hint.setTextFormat(Qt.TextFormat.PlainText)
        self.content_layout.addWidget(hint)
        self.records = QListWidget()
        self.records.setAccessibleName(title + '列表')
        self.content_layout.addWidget(self.records, 1)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.content_layout.addWidget(self.status)
        actions = QHBoxLayout()
        self.select_button = QPushButton(select_label)
        self.select_button.clicked.connect(self.select)
        self.remove_button = QPushButton('移除记录')
        self.remove_button.clicked.connect(self.remove)
        self.clear_button = QPushButton('清空记录')
        self.clear_button.clicked.connect(lambda: self.remove(clear=True))
        self.refresh_button = QPushButton('刷新')
        self.refresh_button.clicked.connect(self.reload)
        for widget in (self.select_button, self.remove_button, self.clear_button, self.refresh_button):
            actions.addWidget(widget)
        self.content_layout.addLayout(actions)
        self.controls = (self.records, self.select_button, self.remove_button, self.clear_button, self.refresh_button)
        self.sync_state = None

    def busy(self, value):
        for control in self.controls:
            control.setEnabled(not value)

    def present(self):
        self.show()
        self.raise_()
        self.reload()

    def reload(self):
        self.busy(True)
        self.io.submit(self.store.read, self.loaded)

    def loaded(self, result, error):
        self.busy(False)
        if error:
            self.status.setText(error)
            return
        self.records.clear()
        for item in result['entries']:
            date = item['occurredAt'].replace('T', ' ')[:19]
            self.records.addItem(f"{item['name']} · {date} UTC")
            self.records.item(self.records.count() - 1).setData(Qt.ItemDataRole.UserRole, item['id'])
        self.status.setText('选择记录后可再次预览或填写配置。' if result['entries'] else '还没有记录；完成操作后会从这里开始保存。')
        self.show_sync_state(result, '')
        if self.records.count():
            self.records.setCurrentRow(0)

    def show_sync_state(self, result, error):
        if self.sync_state is not None and not error:
            state = result['sync']
            self.sync_state.setText('形象历史同步已开启 · 仅同步此后新记录' if state['enabled'] else '形象历史仅保存在本机')

    def identifier(self):
        item = self.records.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def select(self):
        identifier = self.identifier()
        if not identifier:
            self.status.setText('请先选择一条历史。')
            return
        self.busy(True)
        self.io.submit(lambda: self.resolve(identifier), self.resolved)

    def resolved(self, value, error):
        self.busy(False)
        if error:
            self.status.setText(error)
            return
        self.selected.emit(value)
        self.hide()

    def remove(self, *, clear=False):
        identifier = None if clear else self.identifier()
        if not clear and not identifier:
            return
        self.busy(True)
        self.io.submit(lambda: self.store.remove(identifier), self.removed)

    def removed(self, _result, error):
        if error:
            self.busy(False)
            self.status.setText(error)
        else:
            self.reload()
