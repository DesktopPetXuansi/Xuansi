"""单页控制分区使用真实 Qt 层级，不访问账号或加载模型。"""

from types import SimpleNamespace

import pytest
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

from pet.appearance_dialog import AppearanceDialog
from pet.config import Settings
from pet.platform_dialog import PlatformDialog


class Runtime(QObject):
    platform_settings_saved = Signal(object, str)


class Panel(QWidget):
    def __init__(self):
        super().__init__()
        self.sections = {}
        self.callbacks = {}
        self.layout = QVBoxLayout(self)

    def mount_section(self, key, widget, on_open=None):
        self.sections[key] = widget
        self.callbacks[key] = on_open
        widget.setParent(self, Qt.WindowType.Widget)
        self.layout.addWidget(widget)
        widget.hide()

    def open_section(self, key):
        callback = self.callbacks[key]
        if callback:
            callback()
        self.sections[key].show()

    def collapse_section(self, key):
        self.sections[key].hide()


class Preview(QWidget):
    motion_capabilities_changed = Signal(object)
    available_motions = []
    renderer = SimpleNamespace(_live2d_failed=False)

    def __init__(self, parent):
        super().__init__(parent)
        self.images = []
        self.stopped = 0

    def set_image(self, image):
        self.images.append(image)

    def stop(self):
        self.stopped += 1


def test_embedded_sections_keep_one_window_and_ignore_dialog_shortcuts(monkeypatch):
    application = QApplication.instance() or QApplication([])
    monkeypatch.setattr("pet.appearance_dialog.AppearancePreview", Preview)
    panel = Panel()
    owner = SimpleNamespace(panel=panel, settings=Settings(), runtime=Runtime())
    appearance = AppearanceDialog(panel, embedded=True)
    platform = PlatformDialog(owner, embedded=True)
    panel.mount_section("appearance", appearance)
    panel.mount_section("resources", platform, on_open=platform.refresh_local)
    operations = []
    monkeypatch.setattr(platform, "start", lambda command, operation: operations.append(command))
    panel.show()
    panel.open_section("appearance")
    appearance.present("")  # 已挂载并显示时，首次 present 仍必须准备预览。
    assert appearance.preview.images == [""]
    platform.present()
    platform.open_upload()
    upload = platform.upload_dialog
    assert operations == ["local", "upload-connect"]
    platform.worker = SimpleNamespace(command="upload-connect")
    platform.task_failed("首次授权失败")
    platform.worker = None
    platform.set_busy(False)
    assert upload.status.text() == "首次授权失败"
    QTest.keyClick(upload.name, Qt.Key.Key_Return)
    assert operations == ["local", "upload-connect"]
    assert upload.windowModality() == Qt.WindowModality.NonModal
    for widget in (appearance, platform, upload):
        assert not widget.isWindow()
        assert widget.window() is panel
        assert widget.maximumWidth() > 480
        widget.setFocus()
        QTest.keyClick(widget, Qt.Key.Key_Escape)
        QTest.keyClick(widget, Qt.Key.Key_Return)
        widget.accept()
        widget.reject()
        assert widget.isVisible()
    assert operations == ["local", "upload-connect"]
    upload.name.setText("保留的模型名称")
    platform.open_upload()
    assert platform.upload_dialog is upload
    assert upload.name.text() == "保留的模型名称"
    upload.connect_button.click()
    assert operations == ["local", "upload-connect", "upload-connect"]
    upload.cancel_button.click()
    assert not upload.isVisible()
    platform.open_upload()
    assert upload.isVisible() and platform.upload_dialog is upload
    assert len([widget for widget in QApplication.topLevelWidgets()
                if widget.isVisible() and widget in (panel, appearance, platform, upload)]) == 1
    panel.hide()
    assert appearance.preview.stopped >= 1
    panel.show()
    appearance.present("")
    assert len(appearance.preview.images) == 2
    panel.close()
    panel.deleteLater()
    application.processEvents()


def test_embedded_upload_hide_preserves_task_receipt_and_shutdown_waits(monkeypatch):
    application = QApplication.instance() or QApplication([])
    panel = Panel()
    owner = SimpleNamespace(panel=panel, settings=Settings(), runtime=Runtime())
    platform = PlatformDialog(owner, embedded=True)
    panel.mount_section("resources", platform)
    monkeypatch.setattr(platform, "start", lambda *_: None)
    platform.open_upload()
    upload = platform.upload_dialog
    receipt = {"resourceId": "retained-resource"}
    upload.client = SimpleNamespace(base_url=platform.url.text(), pending_model_upload=receipt)
    cancelled = []
    worker = SimpleNamespace(isRunning=lambda: True, cancel=lambda: cancelled.append(True), deleteLater=lambda: None)
    platform.worker = worker
    upload.set_busy(True)
    panel.show()
    panel.hide()
    application.processEvents()
    assert not cancelled
    panel.show()
    upload.cancel_button.click()
    assert cancelled == [True]
    assert upload.client.pending_model_upload is receipt
    platform.worker = None
    upload.set_busy(False)
    platform.open_upload()
    assert platform.upload_dialog is upload
    assert upload.client.pending_model_upload is receipt
    platform.worker = worker
    completed = []
    platform.shutdown_done.connect(lambda: completed.append(True))
    platform.shutdown()
    assert not completed
    platform.task_finished()
    assert completed == [True]
    panel.close()
    panel.deleteLater()
    application.processEvents()


def test_embedded_upload_switching_sites_does_not_reuse_account_or_receipt(monkeypatch):
    application = QApplication.instance() or QApplication([])
    panel = Panel()
    owner = SimpleNamespace(panel=panel, settings=Settings(), runtime=Runtime())
    platform = PlatformDialog(owner, embedded=True)
    panel.mount_section("resources", platform)
    operations = []
    monkeypatch.setattr(platform, "start", lambda command, operation: operations.append(command))
    platform.open_upload()
    first = platform.upload_dialog
    first.client = SimpleNamespace(base_url=platform.url.text(), pending_model_upload={"resourceId": "old"})
    platform.url.setText("https://other.example")
    platform.open_upload()
    assert platform.upload_dialog is not first
    assert platform.upload_dialog.client is None
    assert operations == ["upload-connect", "upload-connect"]
    panel.close()
    panel.deleteLater()
    application.processEvents()


@pytest.mark.parametrize("pending", [False, True])
@pytest.mark.parametrize("changed_url", ["https://other.example", "不是官网地址"])
def test_existing_upload_section_rejects_changed_site_before_submitting(monkeypatch, pending, changed_url):
    application = QApplication.instance() or QApplication([])
    panel = Panel()
    owner = SimpleNamespace(panel=panel, settings=Settings(), runtime=Runtime())
    platform = PlatformDialog(owner, embedded=True)
    panel.mount_section("resources", platform)
    operations = []
    monkeypatch.setattr(platform, "start", lambda command, operation: operations.append(command))
    platform.open_upload()
    upload = platform.upload_dialog
    original_url = platform.url.text()
    receipt = {"resourceId": "original-site-resource"} if pending else None
    upload.client = SimpleNamespace(base_url=original_url, pending_model_upload=receipt)
    upload.connected = True
    upload.source.setText("local.model3.json")
    upload.name.setText("本地模型")
    upload.author.setText("原作者")
    upload.set_busy(False)
    operations.clear()

    # 同页表单仍在，用户从定位导航进入时不会经过 open_upload 的换站逻辑。
    platform.url.setText(changed_url)
    panel.open_section("upload")
    upload.submit_button.click()
    assert operations == []
    assert upload.client.pending_model_upload is receipt
    assert "官网地址" in upload.status.text()

    # 切回原站点后，尾部斜线不应阻止继续上传或恢复原入库回执。
    platform.url.setText(original_url + "/")
    upload.submit_button.click()
    assert operations == ["upload-model"]
    assert upload.client.pending_model_upload is receipt
    panel.close()
    panel.deleteLater()
    application.processEvents()


def test_upload_entry_shows_busy_status_in_resource_section():
    application = QApplication.instance() or QApplication([])
    panel = Panel()
    owner = SimpleNamespace(panel=panel, settings=Settings(), runtime=Runtime())
    platform = PlatformDialog(owner, embedded=True)
    panel.mount_section("resources", platform)
    platform.worker = SimpleNamespace(isRunning=lambda: True)
    panel.show()
    assert not platform.isVisible()
    platform.open_upload()
    assert platform.isVisible()
    assert "等待当前操作" in platform.status.text()
    assert platform.upload_dialog is None
    platform.worker = None
    panel.close()
    panel.deleteLater()
    application.processEvents()
