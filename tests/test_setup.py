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


@pytest.mark.parametrize("valid", [True, False])
def test_setup_uses_plan_and_rejects_it_before_creating_environment(tmp_path, valid):
    """完整执行 PowerShell 与真实计划入口，下载器替身不联网。"""
    from pet.ai.install_plan import InstallPlan, save_plan

    install = tmp_path / "plan install"
    scripts = install / "scripts"
    scripts.mkdir(parents=True)
    shutil.copy2(ROOT / "setup.ps1", install / "setup.ps1")
    shutil.copy2(ROOT / "scripts/preflight.py", scripts / "preflight.py")
    (install / "requirements.lock.txt").write_text("", encoding="utf-8")
    (install / "pet/ai").mkdir(parents=True)
    shutil.copy2(ROOT / "pet/__init__.py", install / "pet/__init__.py")
    for name in ("__init__.py", "assessment.py", "device.py", "catalog.py", "catalog.json", "install_plan.py"):
        shutil.copy2(ROOT / "pet/ai" / name, install / "pet/ai" / name)
    (scripts / "download_assets.py").write_text(
        "import sys\nfrom pathlib import Path\n"
        "assert sys.argv[1] == '--plan'\nPath('selected.checked').touch()\n", encoding="utf-8"
    )
    (scripts / "download_realtime.py").write_text("raise AssertionError('plan resources already handled')\n",
                                                encoding="utf-8")
    plan_path = tmp_path / "plan.json"
    save_plan(InstallPlan(app_dir=str(install), model_dir=str(tmp_path / "models"), backend="cpu"), plan_path)
    if not valid:
        plan_path.write_text('{"api_key":"not-permitted"}', encoding="utf-8")
    result = subprocess.run([
        "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(install / "setup.ps1"),
        "-PythonPath", sys._base_executable, "-InstallPlanPath", str(plan_path), "-SkipShortcuts",
    ], capture_output=True, timeout=90)
    assert (result.returncode == 0) is valid, result.stdout + result.stderr
    assert (install / ".venv").exists() is valid
    assert (install / "selected.checked").exists() is valid
    assert (install / "data/settings.json").exists() is valid
