"""Prepare a versioned candidate beside an existing installed 0.9.0."""

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path


def _real_directory(path: Path):
    if not path.is_dir() or path.is_symlink() or path.is_junction():
        raise ValueError("安装目录缺失或为重解析点")
    return path.resolve()


def _reject_links(root: Path):
    for current, directories, files in os.walk(root, followlinks=False):
        for name in (*directories, *files):
            path = Path(current) / name
            if path.is_symlink() or path.is_junction():
                raise ValueError("旧版运行时包含链接，停止桥接")


def prepare(root: Path, version: str):
    root = _real_directory(root)
    old_python = root / ".venv/Scripts/pythonw.exe"
    candidate = _real_directory(root / "versions" / version)
    if candidate.parent != root / "versions" or not old_python.is_file():
        raise ValueError("只支持从既有安装版桥接")
    if (root / "data/app.lock").exists():
        raise ValueError("请先退出旧版玄司")
    _real_directory(root / "data")
    old_runtime = root / "runtime/llama"
    if old_runtime.is_dir():
        _reject_links(old_runtime)
        runtime_target = candidate / "runtime/llama"
        marker = candidate / ".runtime-bridge-ready"
        if runtime_target.exists():
            if not marker.is_file():
                raise FileExistsError("候选版运行时未完整准备，拒绝覆盖")
        else:
            shutil.copytree(old_runtime, runtime_target)
            marker.write_text("copied\n", encoding="ascii")
    base_python = candidate / "runtime/python/python.exe"
    if not base_python.is_file():
        raise FileNotFoundError("桥接载荷缺少 Python")
    environment = os.environ | {
        "XUANSI_WRITABLE_ROOT": str(root),
        "XUANSI_VERSION_RUNTIME_ROOT": str(candidate / "runtime"),
    }
    subprocess.run([str(base_python), "-m", "venv", str(candidate / ".venv")], cwd=candidate, env=environment, check=True)
    subprocess.run(
        [str(candidate / ".venv/Scripts/python.exe"), "-m", "pip", "install", "--disable-pip-version-check", "-r", str(candidate / "requirements.lock.txt")],
        cwd=candidate, env=environment, check=True,
    )
    state_path = root / "update/update-state.json"
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if state.get("current") != version or state.get("pending") is not None:
            raise ValueError("已有其他更新事务，拒绝重新初始化")
    else:
        subprocess.run([str(root / "Xuansi.exe"), "--initialize", version], cwd=root, env=environment, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--version", required=True)
    args = parser.parse_args()
    prepare(args.root, args.version)


if __name__ == "__main__":
    main()
