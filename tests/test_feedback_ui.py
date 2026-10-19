"""反馈表单验证草稿、显式诊断选择和服务端确认，不访问网络或剪贴板。"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from pet.feedback_client import FeedbackReceipt
from pet.feedback_dialog import FeedbackDialog


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def view(app):
    widget = FeedbackDialog()
    widget.show()
    app.processEvents()
    yield widget
    widget.close()
    widget.deleteLater()
    app.processEvents()


def fill(view):
    view.title_input.setText("导入形象失败")
    view.description.setPlainText("点击使用之后显示文件不完整，希望补充提示。")


def test_empty_form_does_not_submit(view):
    requests = []
    view.submit_requested.connect(requests.append)
    QTest.mouseClick(view.submit_button, Qt.MouseButton.LeftButton)
    assert not requests and "标题" in view.status.text()


def test_submit_is_explicit_and_duplicate_clicks_are_blocked(view):
    requests = []
    view.submit_requested.connect(requests.append)
    fill(view)
    assert not requests
    QTest.mouseClick(view.submit_button, Qt.MouseButton.LeftButton)
    QTest.mouseClick(view.submit_button, Qt.MouseButton.LeftButton)
    assert len(requests) == 1 and requests[0].diagnostics is None
    assert not view.submit_button.isEnabled()
    assert "正在提交" in view.submit_button.text()


def test_failure_and_close_keep_the_complete_draft(view):
    fill(view)
    view.contact.setText("自愿填写的联系方式")
    view.set_busy(True)
    view.failed("暂时无法连接服务")
    view.close()
    view.show()
    assert view.title_input.text() == "导入形象失败"
    assert view.description.toPlainText().startswith("点击使用")
    assert view.contact.text() == "自愿填写的联系方式"
    assert view.submit_button.isEnabled()
    assert "无法连接" in view.status.text()


def test_diagnostics_are_only_requested_after_opt_in_and_can_be_previewed(view, app):
    fill(view)
    requests = []
    view.diagnostics_requested.connect(lambda: requests.append(True))
    assert not view.include_diagnostics.isChecked() and not requests
    view.include_diagnostics.setChecked(True)
    assert requests and not view.submit_button.isEnabled()
    view.set_diagnostics({"appVersion": "0.8.0", "system": "Windows 11"})
    view.preview_button.click()
    app.processEvents()
    assert view.preview.isVisible() and "0.8.0" in view.preview.toPlainText()
    assert view.draft().payload()["diagnostics"]["system"] == "Windows 11"
    view.include_diagnostics.setChecked(False)
    assert not view.preview.isVisible() and "diagnostics" not in view.draft().payload()


def test_late_diagnostics_do_not_reenable_opt_in(view):
    fill(view)
    view.include_diagnostics.setChecked(True)
    view.include_diagnostics.setChecked(False)
    view.set_diagnostics({"appVersion": "0.8.0"})
    assert not view.include_diagnostics.isChecked()
    assert view.draft().diagnostics is None and not view.preview.isVisible()


def test_receipt_keeps_copyable_content_until_user_starts_a_new_feedback(view):
    fill(view)
    view.received(FeedbackReceipt("11111111-1111-4111-8111-111111111111", "2026-10-19T16:00:00Z", "NEW"))
    assert "已收到" in view.status.text() and "11111111" in view.status.text()
    assert view.description.toPlainText().startswith("点击使用")
    assert view.submit_button.text() == "再写一条"
    view.submit_button.click()
    assert not view.title_input.text() and not view.description.toPlainText()


@pytest.mark.parametrize("size", [(520, 580), (440, 480)])
def test_small_feedback_window_keeps_primary_action_visible(view, app, size):
    view.resize(*size)
    app.processEvents()
    button = view.submit_button
    assert view.rect().contains(button.mapTo(view, button.rect().topLeft()))
    assert view.rect().contains(button.mapTo(view, button.rect().bottomRight()))
    assert view.scroll.horizontalScrollBar().maximum() == 0
