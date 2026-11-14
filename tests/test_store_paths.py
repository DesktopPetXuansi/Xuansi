"""在独立进程中验证商店可写根目录，不触碰现有安装的数据或模型。"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def run_isolated(code, writable_root=None):
    environment = dict(os.environ, PYTHONUTF8="1")
    environment.pop("XUANSI_WRITABLE_ROOT", None)
    if writable_root is not None:
        environment["XUANSI_WRITABLE_ROOT"] = str(writable_root)
    return subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, env=environment,
        capture_output=True, text=True, encoding="utf-8", timeout=30,
    )


def test_default_paths_keep_existing_installation_layout():
    result = run_isolated("""
import hashlib
from pathlib import Path
from pet import config
from pet import instance
assert config.ROOT == Path.cwd()
assert config.DATA == config.ROOT / 'data'
assert config.RUNTIME == config.ROOT / 'runtime'
assert instance.NAME == 'neko-local-' + hashlib.sha256(str(config.ROOT).encode()).hexdigest()[:16]
""")
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("writable", [ROOT, str(ROOT).lower(), ROOT / ".." / ROOT.name])
def test_explicit_source_directory_keeps_legacy_notification_name(writable):
    result = run_isolated("""
import hashlib
from pet import config, instance
assert instance.NAME == 'neko-local-' + hashlib.sha256(str(config.ROOT).encode()).hexdigest()[:16]
""", writable)
    assert result.returncode == 0, result.stdout + result.stderr


def test_writable_directory_aliases_share_pipe_and_other_directories_are_isolated(tmp_path):
    writable = tmp_path / "商店数据"
    aliases = [writable, str(writable).lower(), writable / ".." / writable.name]
    names = []
    for path in [*aliases, tmp_path / "另一份数据"]:
        result = run_isolated("from pet.instance import NAME; print(NAME)", path)
        assert result.returncode == 0, result.stdout + result.stderr
        names.append(result.stdout.strip())
    assert len(set(names[:3])) == 1
    assert names[-1] != names[0]


def test_launch_notification_reaches_same_data_directory_after_code_version_changes(tmp_path):
    result = run_isolated("""
import importlib
import os
import time
from pathlib import Path
from PySide6.QtCore import QCoreApplication
from PySide6.QtNetwork import QLocalSocket
from pet import config

app = QCoreApplication([])
writable = Path(os.environ['XUANSI_WRITABLE_ROOT'])
config.ROOT = writable.parent / 'package-v1'
from pet import instance
activated = []
server = instance.listen_for_launch(app, lambda: activated.append(True))
assert server.isListening()
try:
    config.ROOT = writable.parent / 'package-v2'
    importlib.reload(instance)
    connection = QLocalSocket()
    connection.connectToServer(instance.NAME)
    assert connection.waitForConnected(500), 'new package cannot notify the running instance'
    connection.close()
    deadline = time.monotonic() + 2
    while not activated and time.monotonic() < deadline:
        app.processEvents()
    assert activated == [True]
finally:
    server.close()
""", tmp_path / "商店数据")
    assert result.returncode == 0, result.stdout + result.stderr


def test_writable_root_saves_and_loads_real_settings_without_moving_source(tmp_path):
    writable = tmp_path / "商店用户 with spaces"
    result = run_isolated("""
import os
from pathlib import Path
from pet import config
writable = Path(os.environ['XUANSI_WRITABLE_ROOT'])
assert config.ROOT == Path.cwd()
assert config.DATA == writable / 'data'
assert config.RUNTIME == writable / 'runtime'
assert not config.DATA.exists()
settings = config.Settings(name='商店伙伴', observe=False)
config.save_settings(settings)
assert config.load_settings() == settings
assert (config.DATA / 'settings.json').is_file()
""", writable)
    assert result.returncode == 0, result.stdout + result.stderr
    assert sorted(path.name for path in writable.iterdir()) == ["data"]


@pytest.mark.parametrize("writable", ["relative/path", "C:relative"])
def test_relative_override_is_rejected_before_creating_files(writable):
    result = run_isolated("import pet.config", writable)
    assert result.returncode != 0
    assert "可写根目录必须是绝对路径" in result.stderr


def test_local_engine_launches_binary_from_selected_writable_root(tmp_path):
    writable = tmp_path / "引擎 with spaces"
    executable = writable / "runtime/llama/cpu/release/llama-server.exe"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"synthetic executable, never launched")
    result = run_isolated("""
import asyncio
import os
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock, patch
from pet.config import Settings
from pet.inference import LocalEngine

class LaunchRecorded(Exception):
    pass

async def check():
    writable = Path(os.environ['XUANSI_WRITABLE_ROOT'])
    model = writable / 'synthetic.gguf'
    model.write_bytes(b'synthetic weights')
    settings = Settings(model_path=str(model), projector_path=str(model), gpu_layers=0)
    settings = replace(settings, ai=replace(settings.ai, local_backend='cpu'))
    expected = writable / 'runtime/llama/cpu/release/llama-server.exe'
    async def launch(*arguments, **options):
        assert arguments[0] == str(expected)
        assert arguments[arguments.index('-m') + 1] == str(model)
        assert arguments[arguments.index('--mmproj') + 1] == str(model)
        assert options['cwd'] == expected.parent
        raise LaunchRecorded
    engine = LocalEngine()
    with patch.object(engine, '_check_resources', AsyncMock()), patch(
        'pet.inference.asyncio.create_subprocess_exec', launch
    ):
        try:
            await engine.start(settings)
        except LaunchRecorded:
            return
    raise AssertionError('did not reach isolated process launch')

asyncio.run(check())
""", writable)
    assert result.returncode == 0, result.stdout + result.stderr
