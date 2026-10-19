"""历史入口和成功回执使用隔离 Qt/文件，不读取真实凭据或启动模型。"""

import time
from dataclasses import replace

from PySide6.QtWidgets import QApplication

from pet.ai.settings import AISettings, ModelProfile
from pet.history_dialog import HistoryDialog
from pet.history_tasks import HistoryIO
from pet.model_history import ModelHistory
from pet.model_page import ModelPage


def wait(app, predicate):
    deadline = time.monotonic() + 4
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    assert predicate()


def test_model_history_fills_draft_without_saving(tmp_path, monkeypatch):
    from pet.config import Settings

    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    app = QApplication.instance() or QApplication([])
    original = Settings()
    page = ModelPage(original)
    snapshot = replace(AISettings(), policy='online_first',
                       profile=ModelProfile(endpoint='https://example.test/v1', model='past-model'))
    store = ModelHistory(tmp_path / 'models.json')
    store.record(snapshot, 'past-model.gguf', 'past-projector.gguf')
    saved = []
    page.save_requested.connect(lambda: saved.append(True))
    page.restore_configuration(store.configuration(store.read()['entries'][0]['id']))
    assert page.apply(original).ai.profile.model == 'past-model'
    assert page.model.text() == 'past-model.gguf'
    assert original.ai.policy == 'local_only' and not saved
    page.close()
    app.processEvents()


def test_history_dialog_reads_and_clears_only_its_file(tmp_path, monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    app = QApplication.instance() or QApplication([])
    store = ModelHistory(tmp_path / 'models.json')
    store.record(AISettings(), 'model.gguf', 'projector.gguf')
    io = HistoryIO()
    dialog = HistoryDialog(None, '配置历史', '只填写草稿', store, io, store.configuration, '填入配置草稿')
    dialog.present()
    wait(app, lambda: dialog.records.count() == 1)
    received = []
    dialog.selected.connect(received.append)
    dialog.select()
    wait(app, lambda: len(received) == 1)
    dialog.present()
    wait(app, lambda: dialog.records.isEnabled())
    dialog.remove(clear=True)
    wait(app, lambda: dialog.records.count() == 0)
    assert store.read()['entries'] == []
    dialog.close()
    io.pool.waitForDone(4000)
    io.close()
