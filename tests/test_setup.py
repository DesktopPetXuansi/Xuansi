"""安装脚本在隔离目录运行，使用真实 Python，不下载模型或修改桌面入口。"""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_upgrade_deletes_only_retired_control_modules():
    """锁定原目录升级的删除边界，防止误删用户数据和其他模块缓存。"""
    installer = (ROOT / "installer/online.iss").read_text(encoding="utf-8-sig")
    section = installer.split("[InstallDelete]", 1)[1].split("[", 1)[0]
    entries = {
        line.strip() for line in section.splitlines()
        if line.strip() and not line.lstrip().startswith(";")
    }
    modules = ("model_control", "model_semantics", "speech_control")
    expected = {
        f'Type: files; Name: "{{app}}\\pet\\{module}.py"' for module in modules
    } | {
        f'Type: files; Name: "{{app}}\\pet\\__pycache__\\{module}.*.pyc"' for module in modules
    }
    assert entries == expected
    assert all(not (ROOT / "pet" / f"{module}.py").exists() for module in modules)


@pytest.mark.parametrize("failure", [None, "models", "shortcuts"])
def test_setup_propagates_errors_and_can_skip_shortcuts(tmp_path, failure):
    install = tmp_path / "安装目录 with spaces"
    scripts = install / "scripts"
    scripts.mkdir(parents=True)
    shutil.copy2(ROOT / "setup.ps1", install / "setup.ps1")
    (install / "requirements.lock.txt").write_text("", encoding="utf-8")
    (scripts / "download_assets.py").write_text(
        "import sys\nsys.exit(23)\n" if failure == "models" else "print('models checked')\n",
        encoding="utf-8",
    )
    (scripts / "download_realtime.py").write_text(
        "from pathlib import Path\nPath('realtime.checked').touch()\n", encoding="utf-8"
    )
    (scripts / "create_shortcuts.ps1").write_text("throw 'shortcut test failure'\n", encoding="utf-8")
    command = [
        "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
        str(install / "setup.ps1"), "-PythonPath", sys._base_executable,
    ]
    if failure != "shortcuts":
        command.append("-SkipShortcuts")
    result = subprocess.run(command, capture_output=True, timeout=90)
    # 下载失败必须中断后续步骤，不能报告成功；中文和空格路径也需要可用。
    assert (result.returncode == 0) == (failure is None), result.stdout + result.stderr
    assert (install / ".venv/Scripts/python.exe").is_file()
    assert (install / "realtime.checked").exists() == (failure != "models")
    log = (install / "data/setup.log").read_text(encoding="utf-8-sig")
    assert ("Setup completed successfully." in log) == (failure is None)
