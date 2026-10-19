"""反馈任务与Qt生命周期：固定事件循环、合成请求，不发送真实反馈。"""

import asyncio
import os
import threading
import time
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

import pet.feedback_controller as feedback
from pet.feedback import FeedbackDraft
from pet.feedback_client import FeedbackReceipt


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def loop():
    event_loop = asyncio.new_event_loop()
    thread = threading.Thread(target=event_loop.run_forever)
    thread.start()
    while not event_loop.is_running():
        time.sleep(0.001)
    yield event_loop

    async def drain():
        tasks = [task for task in asyncio.all_tasks() if task is not asyncio.current_task()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    asyncio.run_coroutine_threadsafe(drain(), event_loop).result(timeout=2)
    event_loop.call_soon_threadsafe(event_loop.stop)
    thread.join(timeout=2)
    event_loop.close()


@pytest.fixture
def controller(app, loop):
    instance = feedback.FeedbackController(None, lambda: SimpleNamespace(platform_url="http://localhost:3100"), loop)
    yield instance
    instance.shutdown()
    instance.dialog.deleteLater()
    app.processEvents()


def wait_until(app, condition):
    deadline = time.monotonic() + 3
    while not condition() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.001)
    assert condition()


def input_form(controller):
    controller.dialog.title_input.setText("合成反馈")
    controller.dialog.description.setPlainText("仅用于自动验收，不是真实用户的问题。")


def test_open_does_not_collect_or_send(controller, monkeypatch):
    monkeypatch.setattr(feedback, "collect_diagnostics", lambda: pytest.fail("未勾选不应采集"))
    monkeypatch.setattr(feedback, "FeedbackClient", lambda *_: pytest.fail("未提交不应联网"))
    controller.open()
    assert controller.dialog.isVisible() and controller.pending is None


def test_retry_reuses_idempotency_key_but_edited_feedback_gets_new_key(controller, app, monkeypatch):
    calls = []

    class Client:
        def __init__(self, _):
            pass

        async def submit(self, payload, key):
            calls.append((payload, key))
            raise ValueError("合成连接失败，内容已保留。")

    monkeypatch.setattr(feedback, "FeedbackClient", Client)
    input_form(controller)
    for _ in range(2):
        controller.dialog.submit_button.click()
        wait_until(app, lambda: controller.pending is None)
    assert len(calls) == 2 and calls[0][1] == calls[1][1]
    assert controller.dialog.description.toPlainText().startswith("仅用于")
    controller.dialog.title_input.setText("另一条合成反馈")
    controller.dialog.submit_button.click()
    wait_until(app, lambda: controller.pending is None)
    assert calls[-1][1] != calls[0][1]


def test_late_receipt_does_not_reopen_closed_window(controller, app, loop, monkeypatch):
    started, release = threading.Event(), asyncio.Event()

    class Client:
        def __init__(self, _):
            pass

        async def submit(self, payload, key):
            started.set()
            await release.wait()
            return FeedbackReceipt(key, "2026-10-19T16:00:00Z", "NEW")

    monkeypatch.setattr(feedback, "FeedbackClient", Client)
    controller.open()
    input_form(controller)
    controller.dialog.submit_button.click()
    wait_until(app, started.is_set)
    controller.dialog.close()
    loop.call_soon_threadsafe(release.set)
    wait_until(app, lambda: controller.pending is None)
    assert not controller.dialog.isVisible()
    assert "已收到" in controller.dialog.status.text()


def test_new_feedback_after_success_uses_a_new_key_for_identical_content(controller, app, monkeypatch):
    keys = []

    class Client:
        def __init__(self, _):
            pass

        async def submit(self, payload, key):
            keys.append(key)
            return FeedbackReceipt(key, "2026-10-19T16:00:00Z", "NEW")

    monkeypatch.setattr(feedback, "FeedbackClient", Client)
    for turn in range(2):
        if turn:
            controller.dialog.submit_button.click()  # 成功后的“再写一条”开启新反馈。
        input_form(controller)
        controller.dialog.submit_button.click()
        wait_until(app, lambda: controller.pending is None)
        assert "已收到" in controller.dialog.status.text()
    assert len(keys) == 2 and keys[0] != keys[1]


def test_shutdown_cancels_pending_operation_without_showing_receipt(controller, app, monkeypatch):
    started, cancelled = threading.Event(), threading.Event()

    class Client:
        def __init__(self, _):
            pass

        async def submit(self, payload, key):
            started.set()
            try:
                await asyncio.Future()
            finally:
                cancelled.set()

    monkeypatch.setattr(feedback, "FeedbackClient", Client)
    controller.submit(FeedbackDraft("BUG", "合成反馈", "只等待取消"))
    wait_until(app, started.is_set)
    controller.shutdown()
    wait_until(app, cancelled.is_set)
    assert controller.pending.cancelled()
    assert not controller.dialog.isVisible() and "已收到" not in controller.dialog.status.text()


def test_unchecking_during_diagnostic_collection_keeps_it_out_of_submission(controller, app, monkeypatch):
    release = threading.Event()

    def collect():
        release.wait(timeout=2)
        return {"appVersion": "0.8.0"}

    monkeypatch.setattr(feedback, "collect_diagnostics", collect)
    controller.dialog.include_diagnostics.setChecked(True)
    controller.dialog.include_diagnostics.setChecked(False)
    release.set()
    wait_until(app, lambda: controller.diagnostic_job is None)
    assert controller.dialog.draft().diagnostics is None
