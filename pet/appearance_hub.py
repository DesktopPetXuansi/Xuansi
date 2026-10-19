"""统一形象选择页：候选只预览，明确点击使用后才交给保存协调器。"""

import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFileDialog, QWidget

from .appearance_import import AppearanceCandidate
from .appearance_layout import build_layout
from .appearance_preview import AppearancePreview

LOG = logging.getLogger(__name__)


def candidate_key(candidate):
    return candidate.kind, candidate.image_id, candidate.version_id


class AppearanceHub(QWidget):
    import_requested = Signal(str)
    online_requested = Signal()
    mine_requested = Signal()
    history_requested = Signal()
    login_requested = Signal()
    default_requested = Signal()
    share_requested = Signal()
    more_requested = Signal()
    cancel_requested = Signal()
    choice_requested = Signal(object)
    use_requested = Signal(object)

    def __init__(self, parent):
        super().__init__(parent)
        self.control_panel = parent
        self.current = self.candidate = AppearanceCandidate('DEFAULT', '默认玄司')
        self.ready = self.busy = self.dirty = False
        self.preview = AppearancePreview(self, size=144)
        build_layout(self)
        self.stack.currentChanged.connect(self.refresh_buttons)
        self.preview.load_finished.connect(self.preview_loaded)
        self.preview.motion_capabilities_changed.connect(self.refresh_buttons)
        self.picker = QFileDialog(self, '选择新的桌宠形象')
        self.picker.setFileMode(QFileDialog.FileMode.ExistingFile)
        self.picker.setNameFilter('形象文件 (*.png *.apng *.gif *.webp *.jpg *.jpeg *.bmp *.model3.json)')
        self.picker.fileSelected.connect(self.import_requested)
        self.folder_picker = QFileDialog(self, '选择模型文件夹')
        self.folder_picker.setFileMode(QFileDialog.FileMode.Directory)
        self.folder_picker.setOption(QFileDialog.Option.ShowDirsOnly)
        self.folder_picker.fileSelected.connect(self.import_requested)
        self.refresh_buttons()
        LOG.info('形象页已就绪，按选择、预览、使用组织操作')

    def browse(self):
        if not self.busy:
            self.picker.open()

    def browse_folder(self):
        if not self.busy:
            self.folder_picker.open()

    def set_current(self, candidate, *, preview=True):
        keep = self.dirty and candidate_key(self.current) == candidate_key(candidate)
        self.current = candidate
        self.current_label.setText('当前使用：' + candidate.name)
        if not preview:
            # 先标出已保存的模型身份，资源缺失时仍允许明确恢复默认形象。
            self.dirty = candidate_key(self.candidate) != candidate_key(candidate)
            self.ready = False
            self.refresh_buttons()
        elif not keep:
            self.show_candidate(candidate)

    def show_candidate(self, candidate):
        self.candidate = candidate
        self.dirty = candidate_key(candidate) != candidate_key(self.current)
        self.ready = False
        self.candidate_label.setText('预览：' + candidate.name)
        self.status.setText('正在准备预览，桌面上的形象保持原样…')
        if candidate.kind == 'MODEL':
            self.preview.set_model(candidate.prepared)
        else:
            self.preview.set_image(candidate.image_id)
        self.stack.setCurrentIndex(0)
        self.refresh_buttons()

    def preview_loaded(self, loaded, error):
        self.ready = loaded
        if not loaded:
            message = error or '预览失败，请重新选择形象。'
        elif self.dirty:
            message = '预览已就绪，喜欢的话点击“使用这个形象”。'
        else:
            message = '这是当前使用的形象。可从本地导入，或在线挑选新的形象。'
        self.status.setText(message)
        self.refresh_buttons()

    def show_choices(self, mode, choices):
        self.choices.clear()
        self.choices_title.setText('在线形象 · 选择后下载预览' if mode == 'online' else '我的形象 · 选择后预览')
        for choice in choices:
            name = choice['name'] if isinstance(choice, dict) else choice.name
            self.choices.addItem(name)
            self.choices.item(self.choices.count() - 1).setData(Qt.ItemDataRole.UserRole, choice)
        self.login_button.setVisible(mode == 'online')
        self.choice_button.setText('下载并预览' if mode == 'online' else '预览所选形象')
        self.stack.setCurrentIndex(1)
        self.status.setText('选择喜欢的形象，再点击下方按钮。' if choices
                            else '暂时没有可用形象，可以从本地导入，或稍后重试在线挑选。')
        self.refresh_buttons()

    def choose_item(self):
        item = self.choices.currentItem()
        if not self.busy and item is not None:
            self.choice_requested.emit(item.data(Qt.ItemDataRole.UserRole))

    def use_candidate(self):
        if self.ready and self.dirty and not self.busy:
            LOG.info('用户确认使用预览形象 kind=%s', self.candidate.kind)
            self.use_requested.emit(self.candidate)

    def set_busy(self, busy, *, cancellable=False):
        self.busy = busy
        self.cancel_button.setVisible(busy and cancellable)
        self.refresh_buttons()

    def refresh_buttons(self, *_):
        for widget in (self.local_button, self.folder_button, self.online_button, self.mine_button, self.history_button,
                       self.default_button, self.share_button, self.more_button, self.login_button):
            widget.setEnabled(not self.busy)
        self.choices.setEnabled(not self.busy)
        self.choice_button.setEnabled(not self.busy and self.choices.currentItem() is not None)
        self.apply_button.setEnabled(self.ready and self.dirty and not self.busy and self.stack.currentIndex() == 0)
        self.motion_button.setEnabled(self.ready and not self.busy and 'blink' in self.preview.available_motions)

    def applied(self, candidate):
        self.current = candidate
        self.dirty = False
        self.current_label.setText('当前使用：' + candidate.name)
        self.status.setText('已更换为“' + candidate.name + '”，选择已自动保存。')
        self.refresh_buttons()

    def saved(self, error):
        # 兼容既有明确的本机图片保存入口；主流程使用独立的形象事务。
        if error:
            self.status.setText(error)
        else:
            self.applied(self.candidate)
