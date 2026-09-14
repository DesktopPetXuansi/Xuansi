"""本机形象菜单：后台导入，预览后应用；取消和失败不修改当前形象。"""

import logging

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal
from PySide6.QtWidgets import QDialog, QFileDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from .appearance import image_path, import_image
from .appearance_preview import AppearancePreview

LOG = logging.getLogger(__name__)


class ImportResult(QObject):
    loaded = Signal(int, object, str)


class ImportImage(QRunnable):
    def __init__(self, result, generation, path):
        super().__init__()
        self.result, self.generation, self.path = result, generation, path

    def run(self):
        try:
            asset = import_image(self.path)
            self.result.loaded.emit(self.generation, asset, "")
        except Exception as exc:
            LOG.warning("形象导入失败 type=%s", type(exc).__name__)
            error = str(exc) if isinstance(exc, ValueError) else "导入失败，请检查文件和磁盘空间"
            self.result.loaded.emit(self.generation, None, error)


class AppearanceDialog(QDialog):
    apply_requested = Signal(str)

    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("更换桌宠形象")
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.setFixedWidth(480)
        self.current = self.candidate = ""
        self.generation = 0
        self.loading = self.saving = False
        self.dirty = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        title = QLabel("换一个模样，继续陪你")
        title.setObjectName("title")
        layout.addWidget(title)
        note = QLabel(
            "支持透明 PNG、GIF、WebP、APNG，也可用 JPG / BMP。\n静态图片带轻微身体动作；动图按原帧序循环播放。"
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        self.preview = AppearancePreview(self)
        layout.addWidget(self.preview)
        self.status = QLabel("当前：默认玄司")
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status)
        row = QHBoxLayout()
        self.choose = QPushButton("选择本地图片…")
        self.choose.clicked.connect(self.browse)
        row.addWidget(self.choose)
        self.restore = QPushButton("恢复默认玄司")
        self.restore.clicked.connect(self.use_default)
        row.addWidget(self.restore)
        layout.addLayout(row)
        hint = QLabel(
            "只在本机保存副本，原图移走仍可使用。\n每个文件最多 20 MB、1600 万像素；动图最多 120 帧。"
        )
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        row = QHBoxLayout()
        row.addStretch()
        close = QPushButton("关闭")
        close.clicked.connect(self.close)
        row.addWidget(close)
        self.apply_button = QPushButton("应用形象")
        self.apply_button.setObjectName("primary")
        self.apply_button.clicked.connect(self.apply)
        row.addWidget(self.apply_button)
        layout.addLayout(row)
        self.result = ImportResult(self)
        self.result.loaded.connect(self.imported)
        self.picker = QFileDialog(self, "选择桌宠形象")
        self.picker.setFileMode(QFileDialog.FileMode.ExistingFile)
        self.picker.setNameFilter("图片与透明动图 (*.png *.apng *.gif *.webp *.jpg *.jpeg *.bmp)")
        self.picker.fileSelected.connect(self.import_file)
        self.update_buttons()

    def present(self, identifier):
        if not self.isVisible() and not self.saving:
            self.generation += 1
            self.loading = False
            self.dirty = False
            self.current = self.candidate = identifier
            self.preview.set_image(identifier)
            if identifier and not image_path(identifier).is_file():
                self.status.setText("形象副本已丢失，暂时显示玄司；可重新选择或恢复默认")
            else:
                self.status.setText("当前：自定义形象" if identifier else "当前：默认玄司")
            self.update_buttons()
        self.show()
        self.raise_()
        self.activateWindow()
        LOG.info("打开形象菜单")

    def browse(self):
        self.picker.open()  # 非阻塞文件选择，不暂停主窗口的事件循环。

    def import_file(self, path):
        if not path or self.loading or self.saving:
            return
        self.generation += 1
        self.loading = True
        self.status.setText("正在本机处理图片…")
        self.update_buttons()
        QThreadPool.globalInstance().start(ImportImage(self.result, self.generation, path))

    def imported(self, generation, asset, error):
        if generation != self.generation:
            return
        self.loading = False
        if error:
            self.status.setText(error)
        else:
            self.candidate = asset.identifier
            self.dirty = True
            self.preview.set_image(self.candidate)
            kind = f"动图 · {asset.frames} 帧" if asset.frames > 1 else "静态图片"
            alpha = "透明背景" if asset.transparent else "图片包含底色，不会自动抠图"
            self.status.setText(
                f"{kind} · {asset.width} × {asset.height} · {alpha}\n预览满意后点击“应用形象”。"
            )
        self.update_buttons()

    def use_default(self):
        self.candidate = ""
        self.dirty = self.current != ""
        self.preview.set_image("")
        self.status.setText("默认玄司 · 点击“应用形象”恢复")
        self.update_buttons()

    def apply(self):
        if self.loading or self.saving or not self.dirty:
            return
        self.saving = True
        self.status.setText("正在保存形象…")
        self.update_buttons()
        self.apply_requested.emit(self.candidate)

    def saved(self, error):
        if not self.saving:
            return
        self.saving = False
        if not error:
            self.current = self.candidate
            self.dirty = False
        self.status.setText(error or "形象已应用，重启后会继续使用。")
        self.update_buttons()

    def update_buttons(self):
        free = not self.loading and not self.saving
        self.choose.setEnabled(free)
        self.restore.setEnabled(free)
        self.apply_button.setEnabled(free and self.dirty)

    def closeEvent(self, event):
        self.picker.close()
        super().closeEvent(event)

    def hideEvent(self, event):
        # Esc、关闭按钮和父窗口关闭都拒收迟到导入；已接受的保存事务仍可完成。
        self.generation += 1
        self.preview.timer.stop()
        super().hideEvent(event)
