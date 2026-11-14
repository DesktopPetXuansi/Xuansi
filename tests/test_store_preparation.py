"""首次配置的后台进程使用临时数据和凭据替身，不连接外网。"""

import json
import os
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from PySide6.QtCore import QEventLoop, QObject, QTimer, Slot
from PySide6.QtWidgets import QApplication

from pet.ai.credentials import new_ref
from pet.ai.install_plan import InstallPlan
from pet.ai.settings import ModelProfile
from pet.store_preparation import StorePreparation


@pytest.fixture(scope="module")
def application():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


class MemoryVault:
    def __init__(self):
        self.values = {}

    def write(self, reference, key):
        self.values[reference] = key

    def read(self, reference):
        return self.values.get(reference)

    def delete(self, reference):
        self.values.pop(reference, None)


def selection(root):
    profile = ModelProfile(endpoint="https://example.invalid/v1", model="test-model",
                           credential_ref=new_ref("https://example.invalid/v1"),
                           capabilities=("text", "image", "tools", "stream", "cancel"))
    profile = replace(profile, verified_at="2026-10-29", verified_capabilities=profile.capabilities,
                      verification_fingerprint=profile.fingerprint())
    plan = InstallPlan(mode="api", policy="online_first", app_dir=str(root), model_dir=str(root / "models"),
                       provider_profile_id=profile.fingerprint(), credential_ref=profile.credential_ref)
    return plan, profile


def run_preparation(manager, plan, profile, key, trigger=None):
    loop = QEventLoop()
    received = []
    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(loop.quit)
    def on_finished(ok, message):
        received.append((ok, message))
        loop.quit()

    manager.finished.connect(on_finished)
    timer.start(15000)
    # Qt 在启动失败时可能同步发送错误信号，调用前先连接接收者。
    manager.start(plan, profile, key)
    cancel_timer = QTimer()
    cancel_timer.setSingleShot(True)
    if trigger:
        cancel_timer.timeout.connect(trigger)
        cancel_timer.start(100)
    if not received:
        loop.exec()
    timer.stop()
    cancel_timer.stop()
    manager.finished.disconnect(on_finished)
    assert received, "后台准备进程没有及时结束"
    return received[0]


def test_successful_api_preparation_keeps_credentials_and_saves_configuration(application, tmp_path):
    root = tmp_path / "商店用户 data"
    plan, profile = selection(root)
    vault = MemoryVault()
    manager = StorePreparation(root, credential_store=vault)
    messages = []
    manager.progress.connect(messages.append)
    ok, _ = run_preparation(manager, plan, profile, "private-key-123")

    assert ok
    saved = json.loads((root / "data/settings.json").read_text(encoding="utf-8"))
    assert saved["ai"]["profile"]["credential_ref"] == profile.credential_ref
    assert vault.values == {profile.credential_ref: "private-key-123"}
    assert "private-key-123" not in (root / "data/settings.json").read_text(encoding="utf-8")
    assert "private-key-123" not in "".join(messages)
    assert not list((root / "data").glob(".store-request-*"))


@pytest.mark.parametrize("cancel", [False, True])
def test_failure_or_cancellation_preserves_old_settings_and_removes_new_credentials(application, tmp_path, cancel):
    root = tmp_path / "user"
    data = root / "data"
    data.mkdir(parents=True)
    original = b'{"name":"previous settings"}'
    (data / "settings.json").write_bytes(original)
    worker = tmp_path / "worker.py"
    worker.write_text("import time\ntime.sleep(10)\n" if cancel else "raise SystemExit(7)\n", encoding="utf-8")
    plan, profile = selection(root)
    vault = MemoryVault()
    manager = StorePreparation(root, credential_store=vault, worker=worker, python=sys.executable)
    ok, _ = run_preparation(manager, plan, profile, "private-key-123", manager.cancel if cancel else None)

    assert not ok
    assert (data / "settings.json").read_bytes() == original
    assert vault.values == {}
    assert not list(data.glob(".store-request-*"))


def test_refuses_plan_for_a_different_root_before_writing_files(application, tmp_path):
    root = tmp_path / "user"
    plan, profile = selection(tmp_path / "other")
    vault = MemoryVault()
    manager = StorePreparation(root, credential_store=vault)

    with pytest.raises(ValueError):
        manager.start(plan, profile, "private-key-123")

    assert not root.exists()
    assert not vault.values


def test_failed_process_start_removes_new_credentials(application, tmp_path):
    root = tmp_path / "user"
    plan, profile = selection(root)
    vault = MemoryVault()
    manager = StorePreparation(root, credential_store=vault, python=tmp_path / "missing-python.exe")
    ok, _ = run_preparation(manager, plan, profile, "private-key-123")

    assert not ok
    assert vault.values == {}
    assert not list((root / "data").glob(".store-request-*"))


def test_retry_with_same_controller_after_failure_keeps_new_credentials(application, tmp_path):
    root = tmp_path / "user"
    plan, profile = selection(root)
    vault = MemoryVault()
    worker = tmp_path / "worker.py"
    worker.write_text("raise SystemExit(7)\n", encoding="utf-8")
    manager = StorePreparation(root, credential_store=vault, worker=worker)
    ok, _ = run_preparation(manager, plan, profile, "private-key-123")
    assert not ok
    assert vault.values == {}

    manager.worker = Path(__file__).resolve().parents[1] / "scripts/store_prepare.py"
    ok, _ = run_preparation(manager, plan, profile, "private-key-123")

    assert ok
    assert vault.values == {profile.credential_ref: "private-key-123"}
    assert (root / "data/settings.json").is_file()


def test_existing_credential_is_never_overwritten_or_removed(application, tmp_path):
    root = tmp_path / "user"
    plan, profile = selection(root)
    vault = MemoryVault()
    vault.write(profile.credential_ref, "existing-secret")
    manager = StorePreparation(root, credential_store=vault)

    with pytest.raises(ValueError):
        manager.start(plan, profile, "new-secret")

    assert vault.values == {profile.credential_ref: "existing-secret"}
    assert not root.exists()


def test_cancel_after_settings_commit_keeps_referenced_credentials(application, tmp_path):
    """子进程刚提交设置时取消，不能删除设置已经引用的密钥。"""
    root = tmp_path / "user"
    plan, profile = selection(root)
    vault = MemoryVault()
    worker = tmp_path / "worker.py"
    worker.write_text(
        "import json, os, sys, time\nfrom pathlib import Path\n"
        "profile = json.loads(Path(sys.argv[sys.argv.index('--profile') + 1]).read_text(encoding='utf-8'))\n"
        "data = Path(os.environ['XUANSI_WRITABLE_ROOT']) / 'data'\n"
        "(data / 'settings.json').write_text(json.dumps({'ai': {'profile': profile}}), encoding='utf-8')\n"
        "print('committed', flush=True)\ntime.sleep(10)\n", encoding="utf-8"
    )
    manager = StorePreparation(root, credential_store=vault, worker=worker)

    class CancelAfterCommit(QObject):
        @Slot(str)
        def cancel(self, _message):
            if (root / "data/settings.json").is_file():
                manager.cancel()

    receiver = CancelAfterCommit()
    manager.progress.connect(receiver.cancel)
    ok, _ = run_preparation(manager, plan, profile, "private-key-123")
    manager.progress.disconnect(receiver.cancel)

    assert not ok
    saved = json.loads((root / "data/settings.json").read_text(encoding="utf-8"))
    assert saved["ai"]["profile"]["credential_ref"] == profile.credential_ref
    assert vault.values == {profile.credential_ref: "private-key-123"}


@pytest.mark.parametrize("settings", ["{broken", "[]", '{"ai":null}', '{"ai":{"profile":null}}'])
def test_unreadable_or_invalid_settings_leave_new_credential_intact(application, tmp_path, settings):
    root = tmp_path / "user"
    data = root / "data"
    data.mkdir(parents=True)
    (data / "settings.json").write_text(settings, encoding="utf-8")
    worker = tmp_path / "worker.py"
    worker.write_text("raise SystemExit(7)\n", encoding="utf-8")
    plan, profile = selection(root)
    vault = MemoryVault()
    manager = StorePreparation(root, credential_store=vault, worker=worker)

    ok, _ = run_preparation(manager, plan, profile, "private-key-123")

    assert not ok
    assert vault.values == {profile.credential_ref: "private-key-123"}
    assert (data / "settings.json").read_text(encoding="utf-8") == settings
