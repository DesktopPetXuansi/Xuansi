"""商店脚本只选择用户数据目录，并在启动异常时显示安全提示。"""

import ctypes
import runpy
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]


def test_store_entry_preserves_explicit_data_root(monkeypatch, tmp_path):
    selected = tmp_path / "个人数据"
    monkeypatch.setenv("XUANSI_WRITABLE_ROOT", str(selected))
    monkeypatch.setitem(sys.modules, "pet.store_bootstrap", SimpleNamespace(main=Mock(return_value=0)))
    entry = runpy.run_path(str(ROOT / "scripts/store_bootstrap.py"))

    assert entry["run"]() == 0
    assert entry["os"].environ["XUANSI_WRITABLE_ROOT"] == str(selected)
    assert not selected.exists()


def test_store_entry_reports_failure_without_sensitive_details(monkeypatch, tmp_path, caplog):
    monkeypatch.setenv("XUANSI_WRITABLE_ROOT", str(tmp_path / "personal"))
    monkeypatch.setitem(sys.modules, "pet.store_bootstrap", SimpleNamespace(
        main=Mock(side_effect=RuntimeError("private-secret-content"))))
    message = Mock()
    monkeypatch.setattr(ctypes, "windll", SimpleNamespace(user32=SimpleNamespace(MessageBoxW=message)))
    entry = runpy.run_path(str(ROOT / "scripts/store_bootstrap.py"))

    assert entry["run"]() == 1
    message.assert_called_once()
    assert "玄司" in message.call_args.args[1]
    assert "private-secret-content" not in str(message.call_args)
    assert "private-secret-content" not in caplog.text
