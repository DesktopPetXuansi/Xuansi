"""Bridge preparation preserves the old application and user data."""

from unittest.mock import patch

from scripts.prepare_update_bridge import prepare


def test_bridge_prepares_candidate_without_modifying_legacy(tmp_path):
    root = tmp_path / "Xuansi"
    candidate = root / "versions/0.9.1"
    for directory in (root / ".venv/Scripts", root / "data", root / "runtime/llama", candidate / "runtime/python"):
        directory.mkdir(parents=True)
    (root / ".venv/Scripts/pythonw.exe").write_bytes(b"legacy")
    (root / "data/settings.json").write_text('{"name":"用户设置"}', encoding="utf-8")
    (root / "runtime/llama/engine.dll").write_bytes(b"runtime")
    (candidate / "runtime/python/python.exe").write_bytes(b"python")
    with patch("scripts.prepare_update_bridge.subprocess.run") as runner:
        prepare(root, "0.9.1")
    assert runner.call_count == 3
    assert (root / "data/settings.json").read_text(encoding="utf-8") == '{"name":"用户设置"}'
    assert (root / ".venv/Scripts/pythonw.exe").read_bytes() == b"legacy"
    assert (candidate / "runtime/llama/engine.dll").read_bytes() == b"runtime"
    assert not (root / "shared").exists()


def test_bridge_refuses_running_legacy(tmp_path):
    root = tmp_path / "Xuansi"
    candidate = root / "versions/0.9.1"
    for directory in (root / ".venv/Scripts", root / "data", candidate / "runtime/python"):
        directory.mkdir(parents=True)
    (root / ".venv/Scripts/pythonw.exe").write_bytes(b"legacy")
    (root / "data/app.lock").write_text("running", encoding="ascii")
    try:
        prepare(root, "0.9.1")
    except ValueError as error:
        assert "退出" in str(error)
    else:
        raise AssertionError("bridge accepted a running legacy process")
