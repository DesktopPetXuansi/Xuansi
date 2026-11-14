"""资源准备窗口使用异步替身，验证重试和关闭边界，不联网或写凭据。"""

import pytest
from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QApplication, QDialog, QLabel

from pet.ai.install_plan import InstallPlan
from pet.store_progress import StoreProgressDialog
from pet.store_setup_form import SetupSelection


class FakePreparation(QObject):
    progress = Signal(str)
    finished = Signal(bool, str)

    def __init__(self):
        super().__init__()
        self.process = None
        self.starts = []
        self.cancellations = 0
        self.mode = "async"
        self.finish_on_cancel = False

    def start(self, plan, profile, key):
        self.starts.append((plan, profile, key))
        if self.mode == "raise":
            raise OSError("private-test-key")
        self.process = object()
        if self.mode == "sync-failure":
            self.complete(False)

    def cancel(self):
        self.cancellations += 1
        if self.finish_on_cancel:
            self.complete(False)

    def complete(self, success):
        self.process = None
        self.finished.emit(success, "private-test-key")


@pytest.fixture
def progress_dialog(monkeypatch, tmp_path):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    worker = FakePreparation()
    selection = SetupSelection(InstallPlan(mode="api", policy="online_first", app_dir=str(tmp_path),
                                           model_dir=str(tmp_path / "models")), None, "private-test-key")
    dialog = StoreProgressDialog(tmp_path, selection, preparation=worker)
    yield dialog, worker, selection, app
    if worker.process is not None:
        worker.complete(False)
    dialog.reject()
    dialog.deleteLater()
    app.processEvents()


def show_started(dialog, app):
    dialog.open()
    app.processEvents()


def test_show_schedules_background_preparation_and_success_accepts(progress_dialog):
    dialog, worker, selection, app = progress_dialog
    dialog.open()
    assert not worker.starts
    app.processEvents()
    assert worker.starts == [(selection.plan, selection.profile, selection.key)]
    assert dialog.progress_bar.minimum() == dialog.progress_bar.maximum() == 0
    worker.complete(True)
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert not dialog.isVisible()
    assert dialog._selection is None


@pytest.mark.parametrize("mode", ["raise", "sync-failure"])
def test_synchronous_start_failure_is_visible_and_can_retry(progress_dialog, mode, caplog):
    dialog, worker, _, app = progress_dialog
    worker.mode = mode
    show_started(dialog, app)
    assert dialog.isVisible()
    assert dialog.retry.isEnabled() and not dialog.retry.isHidden()
    assert "未完成" in dialog.status.text()
    assert "private-test-key" not in caplog.text
    worker.mode = "async"
    dialog.retry.click()
    assert len(worker.starts) == 2
    worker.complete(True)
    assert dialog.result() == QDialog.DialogCode.Accepted


def test_async_failure_retains_choice_for_retry_and_hides_private_messages(progress_dialog, caplog):
    dialog, worker, selection, app = progress_dialog
    show_started(dialog, app)
    worker.progress.emit("private-test-key")
    worker.complete(False)
    assert dialog.isVisible() and dialog._selection is selection
    assert not dialog.retry.isHidden()
    assert "private-test-key" not in "".join(label.text() for label in dialog.findChildren(QLabel))
    assert "private-test-key" not in caplog.text
    dialog.retry.click()
    assert worker.starts[-1] == (selection.plan, selection.profile, selection.key)
    worker.complete(True)
    assert dialog.result() == QDialog.DialogCode.Accepted


@pytest.mark.parametrize("close_window", [False, True])
def test_cancel_waits_for_worker_before_rejecting(progress_dialog, close_window):
    dialog, worker, _, app = progress_dialog
    show_started(dialog, app)
    if close_window:
        dialog.close()
    else:
        dialog.cancel.click()
    assert worker.cancellations == 1
    assert dialog.isVisible() and worker.process is not None
    assert not dialog.cancel.isEnabled()
    worker.complete(False)
    assert not dialog.isVisible()
    assert dialog.result() == QDialog.DialogCode.Rejected
    assert dialog._selection is None


def test_cancel_before_queued_start_does_not_begin_work(progress_dialog):
    dialog, worker, _, app = progress_dialog
    dialog.open()
    dialog.reject()
    app.processEvents()
    assert not worker.starts
    assert dialog._selection is None


def test_close_handles_synchronous_worker_cancellation(progress_dialog):
    dialog, worker, _, app = progress_dialog
    worker.finish_on_cancel = True
    show_started(dialog, app)
    dialog.close()
    assert worker.cancellations == 1 and worker.process is None
    assert not dialog.isVisible()
    assert dialog.result() == QDialog.DialogCode.Rejected
    assert dialog._selection is None


def test_late_success_does_not_override_user_cancellation(progress_dialog):
    dialog, worker, _, app = progress_dialog
    show_started(dialog, app)
    dialog.reject()
    worker.complete(True)
    assert dialog.result() == QDialog.DialogCode.Rejected
    assert dialog._selection is None


def test_event_loop_keeps_responding_while_preparation_is_running(progress_dialog):
    dialog, worker, _, app = progress_dialog
    show_started(dialog, app)
    heartbeat = []
    QTimer.singleShot(0, lambda: heartbeat.append(True))
    app.processEvents()
    assert heartbeat == [True]
    assert worker.process is not None and dialog.isVisible()
    worker.complete(True)
