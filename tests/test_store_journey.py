"""从真实首次选择界面走到隔离后台进程；不联网或访问真实凭据。"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SECRET = "journey-test-secret"

COMMON = r'''
import io
import json
import logging
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

payload, user, worker = map(Path, sys.argv[1:4])
sys.path.insert(0, str(payload))
from PySide6.QtCore import QObject, QTimer, Slot
from PySide6.QtWidgets import QApplication, QDialog
from pet.ai.device import DeviceReport
from pet.ai.settings import ModelProfile
from pet.store_preparation import StorePreparation
from pet.store_progress import StoreProgressDialog
from pet.store_setup_form import StoreSetupDialog

secret = "journey-test-secret"
logs = io.StringIO()
logging.basicConfig(level=logging.INFO, handlers=[logging.StreamHandler(logs)])
app = QApplication([])
app.setQuitOnLastWindowClosed(False)
jobs = []
report = DeviceReport(system="Windows", architecture="AMD64", os_build=26200,
                      avx2=True, memory_available=64 * 2**30,
                      app_free=200 * 2**30, model_free=200 * 2**30,
                      app_volume="test", model_volume="test")

class MemoryVault:
    def __init__(self):
        self.values = {}
    def read(self, reference):
        return self.values.get(reference)
    def write(self, reference, key):
        self.values[reference] = key
    def delete(self, reference):
        self.values.pop(reference, None)

def online_form():
    dialog = StoreSetupDialog(user, user / "models")
    dialog.ai.policy.setCurrentIndex(dialog.ai.policy.findData("online_first"))
    dialog.ai.set_profile(ModelProfile(endpoint="https://example.invalid/v1", model="synthetic",
                                      capabilities=("text", "image", "tools", "stream", "cancel")))
    dialog.ai.key.setText(secret)
    profile = dialog.ai.profile()
    # 这里替换在线能力测试的结果，界面和其余部署步骤仍使用真实实现。
    dialog.ai._validation = SimpleNamespace(request_id="offline", profile=profile)
    verified = replace(profile, verified_at="offline", verified_capabilities=profile.capabilities,
                       verification_fingerprint=profile.fingerprint())
    dialog.ai.validation_complete("offline", verified, "")
    return dialog

probe = SimpleNamespace(globalInstance=lambda: SimpleNamespace(start=jobs.append))
with patch("pet.store_setup_form.QThreadPool", probe), patch(
    "pet.store_setup_form.probe_device", return_value=report
):
    setup = online_form()
'''

WORKER = r'''
import runpy
from pathlib import Path
from unittest.mock import patch

directory = Path(__file__).parent
marker = directory / "attempt-marker"
if FAIL_ONCE and not marker.exists():
    marker.write_text("failed once", encoding="utf-8")
    raise SystemExit(7)

# 即使资源选择发生回归，也不能让这个集成测试访问网络。
with patch("urllib.request.urlopen", side_effect=AssertionError("network forbidden")), patch(
    "socket.create_connection", side_effect=AssertionError("network forbidden")
):
    runpy.run_path(str(directory / "payload/scripts/store_prepare.py"), run_name="__main__")
'''


@pytest.fixture
def journey(tmp_path):
    payload = tmp_path / "payload"
    shutil.copytree(ROOT / "pet", payload / "pet", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    (payload / "scripts").mkdir()
    for name in ("store_prepare.py", "preflight.py", "download_assets.py"):
        shutil.copy2(ROOT / "scripts" / name, payload / "scripts" / name)
    before = {path.relative_to(payload): path.read_bytes() for path in payload.rglob("*") if path.is_file()}
    return tmp_path, payload, before


def run_journey(journey, body, *, fail_once=False):
    directory, payload, before = journey
    user = directory / "用户数据 with spaces"
    worker = directory / "guarded_worker.py"
    worker.write_text("FAIL_ONCE = " + repr(fail_once) + "\n" + WORKER, encoding="utf-8")
    script = directory / "journey.py"
    script.write_text(COMMON + body, encoding="utf-8")
    environment = dict(os.environ, QT_QPA_PLATFORM="offscreen", XUANSI_WRITABLE_ROOT=str(user),
                       PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1")
    result = subprocess.run(
        [sys.executable, "-B", "-X", "utf8", str(script), str(payload), str(user), str(worker)],
        cwd=directory, env=environment, capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "JOURNEY_OK" in result.stdout
    assert SECRET not in result.stdout + result.stderr
    assert {path.relative_to(payload): path.read_bytes() for path in payload.rglob("*") if path.is_file()} == before


def test_confirmed_api_choice_prepares_real_settings_without_network_or_plaintext_key(journey):
    run_journey(journey, r'''
    setup.confirm_selection()
    assert setup.selection is None and len(jobs) == 1 and not user.exists()
    jobs.pop().run()
    assert setup.selection is None and setup.result() != QDialog.DialogCode.Accepted
    setup.confirm_selection()
    assert setup.result() == QDialog.DialogCode.Accepted
    selection = setup.selection
    assert selection.plan.mode == "api" and selection.plan.voice_components == ()
    assert selection.plan.download_bytes == 0 and not user.exists()
    vault = MemoryVault()
    manager = StorePreparation(user, credential_store=vault, worker=worker)
    progress = StoreProgressDialog(user, selection, preparation=manager)
    watchdog = QTimer()
    watchdog.setSingleShot(True)
    watchdog.timeout.connect(progress.reject)
    watchdog.start(15000)
    assert progress.exec() == QDialog.DialogCode.Accepted
    watchdog.stop()
    saved = json.loads((user / "data/settings.json").read_text(encoding="utf-8"))
    assert saved["ai"]["policy"] == "online_first"
    assert saved["ai"]["profile"]["credential_ref"] == selection.profile.credential_ref
    assert saved["model_path"] == saved["projector_path"] == ""
    assert vault.values == {selection.profile.credential_ref: secret}
    assert not (user / "runtime").exists() and not (user / "models").exists()
    assert progress._selection is None
    assert all(secret not in path.read_text(encoding="utf-8") for path in user.rglob("*.json"))
    assert secret not in logs.getvalue()
    assert not list((user / "data").glob(".store-*"))
    print("JOURNEY_OK")
''')


def test_cancelled_choice_and_late_probe_do_not_create_user_or_payload_files(journey):
    run_journey(journey, r'''
    setup.confirm_selection()
    assert len(jobs) == 1 and setup.selection is None
    setup.reject()
    jobs.pop().run()
    assert setup.result() == QDialog.DialogCode.Rejected
    assert setup.selection is None and not setup.ai.key.text()
    assert not user.exists()
    assert secret not in logs.getvalue()
    print("JOURNEY_OK")
''')


def test_failed_real_worker_can_retry_without_overwriting_existing_settings(journey):
    run_journey(journey, r'''
    setup.confirm_selection()
    jobs.pop().run()
    setup.confirm_selection()
    selection = setup.selection
    data = user / "data"
    data.mkdir(parents=True)
    original = b'{"name":"previous companion","persona":"keep me","ai":{}}'
    (data / "settings.json").write_bytes(original)
    vault = MemoryVault()
    manager = StorePreparation(user, credential_store=vault, worker=worker)
    progress = StoreProgressDialog(user, selection, preparation=manager)

    class RetryObserver(QObject):
        def __init__(self):
            super().__init__()
            self.failures = 0
            self.timer = QTimer(self)
            self.timer.setSingleShot(True)
            self.timer.timeout.connect(progress.retry.click)
        @Slot(bool, str)
        def finished(self, success, message):
            if not success:
                self.failures += 1
                assert (data / "settings.json").read_bytes() == original
                assert vault.values == {}
                assert not progress.retry.isHidden()
                self.timer.start(0)

    observer = RetryObserver()
    manager.finished.connect(observer.finished)
    watchdog = QTimer()
    watchdog.setSingleShot(True)
    watchdog.timeout.connect(progress.reject)
    watchdog.start(15000)
    assert progress.exec() == QDialog.DialogCode.Accepted
    watchdog.stop()
    manager.finished.disconnect(observer.finished)
    assert observer.failures == 1
    saved = json.loads((data / "settings.json").read_text(encoding="utf-8"))
    assert saved["name"] == "previous companion" and saved["persona"] == "keep me"
    assert saved["ai"]["policy"] == "online_first"
    backups = list(data.glob("settings.before-install-*.json"))
    assert len(backups) == 1 and json.loads(backups[0].read_text(encoding="utf-8")) == json.loads(original)
    assert vault.values == {selection.profile.credential_ref: secret}
    assert secret not in logs.getvalue()
    assert all(secret not in path.read_text(encoding="utf-8") for path in user.rglob("*.json"))
    print("JOURNEY_OK")
''', fail_once=True)
