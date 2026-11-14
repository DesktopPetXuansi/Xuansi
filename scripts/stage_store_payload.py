"""从明确提供的源码、Python 和锁定依赖暂存开发期 MSIX 载荷；不联网或安装。"""

import argparse
import csv
import hashlib
import io
import json
import logging
import os
import re
import shutil
from importlib import metadata
from pathlib import Path, PurePosixPath, PureWindowsPath

LOG = logging.getLogger(__name__)
SOURCE_FILES = (
    "VERSION", "LICENSE", "NOTICE", "requirements.lock.txt", "assets-manifest.json",
    "scripts/store_bootstrap.py", "scripts/store_prepare.py", "scripts/preflight.py", "scripts/download_assets.py",
    "scripts/download_realtime.py", "docs/context/THIRD_PARTY.md",
    "docs/context/玄司素材说明.md",
)
ASSET_SUFFIXES = {".png", ".ico", ".json", ".moc3", ".gif", ".apng", ".webp", ".jpg", ".jpeg",
                  ".svg", ".wav", ".mp3", ".txt", ".md"}
DRAFT_ASSETS = {"layers", "layers.json", "blink-mouth-reference.png", "blink-talk-preview.png",
                "neutral-preview.png"}
PYTHON_FILES = {"python.exe", "pythonw.exe", "python3.dll", "python313.dll", "LICENSE.txt"}
# Windows 的 ._pth 解析需要反斜杠，才能准确回到载荷根目录。
PYTHON_PATH = ".\nLib\nDLLs\nLib\\site-packages\n..\\..\nimport site\n"


def _name(value):
    return re.sub(r"[-_.]+", "-", value).lower()


def _root(path):
    if path.is_symlink() or path.is_junction() or not path.is_dir():
        raise ValueError("输入必须是实际存在的普通目录")
    return path.resolve()


def _regular(path, root):
    if (path.is_symlink() or path.is_junction() or not path.resolve().is_relative_to(root)
            or not path.is_file()):
        raise ValueError("载荷文件不得使用链接或引用输入目录之外的文件")
    parent = root
    for part in path.relative_to(root).parts[:-1]:
        parent /= part
        if parent.is_symlink() or parent.is_junction():
            raise ValueError("载荷文件的父目录不得使用链接")
    if path.suffix.lower() in {".pfx", ".p12", ".key"}:
        raise ValueError("载荷不能包含私钥容器")
    if path.suffix.lower() == ".pem" and b"PRIVATE KEY-----" in path.read_bytes():
        raise ValueError("载荷不能包含私钥材料")


def _tree(root, prefix, accept, excluded=("__pycache__",)):
    directory = root / prefix
    if not directory.is_dir() or directory.is_symlink() or directory.is_junction():
        raise ValueError("必要的运行目录缺失或使用链接")
    result = []

    def unreadable(error):
        raise error

    for current, folders, files in os.walk(directory, followlinks=False, onerror=unreadable):
        folders[:] = [name for name in folders if name not in excluded]
        for name in [*folders, *files]:
            path = Path(current) / name
            if path.is_symlink() or path.is_junction():
                raise ValueError("运行目录不能包含符号链接或目录联接")
        for name in files:
            path = Path(current) / name
            relative = path.relative_to(root)
            if accept(relative):
                _regular(path, root)
                result.append((path, relative))
    return result


def _source_files(source):
    result = []
    for name in SOURCE_FILES:
        path = source / name
        _regular(path, source)
        result.append((path, Path(name)))
    result += _tree(source, "pet", lambda path: path.suffix.lower() in {".py", ".json"},
                    excluded=("__pycache__", ".venv", ".git", "data", "models"))
    if not all((source / name).is_file() for name in ("pet/__init__.py", "pet/__main__.py")):
        raise ValueError("源码快照缺少宠物入口")
    for prefix in ("assets/xuansi", "assets/neko", "assets/ui"):
        result += _tree(source, prefix, lambda path: not DRAFT_ASSETS.intersection(path.parts)
                        and (path.name == "LICENSE" or path.suffix.lower() in ASSET_SUFFIXES),
                        excluded=("__pycache__", "layers"))
    for name in ("assets/xuansi/LICENSE", "assets/xuansi/front.png", "assets/xuansi/icon.png",
                 "assets/xuansi/icon.ico", "assets/xuansi/rigging/xuansi.model3.json", "assets/neko/LICENSE"):
        _regular(source / name, source)
    return result


def _python_files(runtime):
    result = []
    for name in PYTHON_FILES:
        path = runtime / name
        _regular(path, runtime)
        result.append((path, Path("runtime/python") / name))
    for path in runtime.glob("vcruntime*.dll"):
        _regular(path, runtime)
        result.append((path, Path("runtime/python") / path.name))
    for prefix in ("Lib", "DLLs"):
        selected = _tree(runtime, prefix, lambda path: path.suffix.lower() != ".pyc"
                         and not ({"site-packages", "test"} & set(path.parts)),
                         excluded=("__pycache__", "site-packages", "test"))
        for path, relative in selected:
            if path.suffix.lower() in {".pth", "._pth"}:
                raise ValueError("提供的 Python 标准库包含未核实的路径配置")
            result.append((path, Path("runtime/python") / relative))
    _regular(runtime / "Lib/os.py", runtime)
    return result


def _locked(source):
    result = {}
    for raw in (source / "requirements.lock.txt").read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([^\s;]+)", line)
        if match is None or _name(match[1]) in result:
            raise ValueError("依赖锁文件必须逐项固定唯一名称和版本")
        result[_name(match[1])] = match[2]
    if not result:
        raise ValueError("依赖锁文件为空")
    return result


def _check_pth(path, dependencies):
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        target = PureWindowsPath(line)
        if (line.startswith(("import ", "import\t")) or target.drive or target.root
                or Path(line).is_absolute() or not (dependencies / line).resolve().is_relative_to(dependencies)):
            raise ValueError("依赖路径配置包含执行代码、绝对路径或目录外引用")
        if not (dependencies / line).exists():
            raise ValueError("依赖路径配置引用了未提供的目录")


def _dependency_files(dependencies, locked):
    # 读取发行元数据前先排除链接，metadata.distributions 本身不会验证这些边界。
    for entry in dependencies.iterdir():
        if entry.is_symlink() or entry.is_junction():
            raise ValueError("依赖目录不能包含顶层链接")
        if entry.is_dir() and entry.name.endswith((".dist-info", ".egg-info")):
            _tree(dependencies, entry.name, lambda _: False)
    found = {}
    for distribution in metadata.distributions(path=[str(dependencies)]):
        name = _name(distribution.metadata["Name"] or "")
        if name in locked:
            if name in found or distribution.version != locked[name]:
                raise ValueError("依赖的安装版本与锁文件不一致或存在重复元数据")
            found[name] = distribution
    if found.keys() != locked.keys():
        raise ValueError("依赖目录缺少锁文件中的发行包")
    result, rewritten = {}, {}
    for name in sorted(found):
        distribution = found[name]
        if distribution.read_text("WHEEL") is None or distribution.read_text("direct_url.json") is not None:
            raise ValueError("依赖必须来自已安装 wheel，不接受本机来源或可编辑安装")
        record = distribution.read_text("RECORD")
        if record is None:
            raise ValueError("依赖缺少 RECORD，无法确定文件范围")
        rows, record_path = [], None
        for row in csv.reader(io.StringIO(record)):
            if len(row) != 3 or not row[0]:
                raise ValueError("依赖 RECORD 结构无效")
            relative = PurePosixPath(row[0])
            # pip 的控制台封装绑定原解释器；应用通过模块调用，不收入这些外部文件。
            if len(relative.parts) == 4 and relative.parts[:3] == ("..", "..", "Scripts"):
                continue
            windows = PureWindowsPath(row[0])
            if (windows.drive or windows.root or relative.is_absolute() or ".." in relative.parts
                    or "\\" in row[0]):
                raise ValueError("依赖 RECORD 引用了外部目录")
            path = dependencies.joinpath(*relative.parts)
            if path.suffix.lower() == ".pyc" or "__pycache__" in relative.parts:
                continue
            _regular(path, dependencies)
            if relative.name in {"sitecustomize.py", "usercustomize.py"}:
                raise ValueError("依赖不能自动导入未核实的启动定制")
            if path.suffix.lower() == ".pth":
                _check_pth(path, dependencies)
            target = Path("runtime/python/Lib/site-packages").joinpath(*relative.parts)
            result[target] = path
            rows.append(row)
            if relative.name == "RECORD" and relative.parent.name.endswith(".dist-info"):
                record_path = target
                rows[-1] = [row[0], "", ""]
        if record_path is None:
            raise ValueError("依赖 RECORD 未列出自身元数据")
        sanitized = io.StringIO(newline="")
        csv.writer(sanitized, lineterminator="\n").writerows(rows)
        rewritten[record_path] = sanitized.getvalue()
    return [(source, target) for target, source in result.items()], rewritten


def stage_payload(*, source: Path, python_runtime: Path, dependencies: Path, output: Path):
    if output.exists() or output.is_symlink() or output.is_junction():
        raise FileExistsError("暂存目标已存在，保留原目录")
    source, python_runtime, dependencies = map(_root, (source, python_runtime, dependencies))
    output = output.resolve()
    if any(output.is_relative_to(root) or root.is_relative_to(output) for root in
           (source, python_runtime, dependencies)):
        raise ValueError("暂存目标必须与所有输入目录分离")
    locked = _locked(source)
    packages, rewritten = _dependency_files(dependencies, locked)
    files = [*_source_files(source), *_python_files(python_runtime), *packages]
    # 所有输入先完成验证，才创建独立输出；复制失败只回收本次新建目录。
    output.parent.mkdir(parents=True, exist_ok=True)
    output.mkdir()
    created = output.stat()
    try:
        for path, relative in sorted(files, key=lambda item: item[1].as_posix()):
            target = output / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
        for relative, text in rewritten.items():
            (output / relative).write_text(text, encoding="utf-8", newline="\n")
        (output / "runtime/python/python313._pth").write_text(PYTHON_PATH, encoding="utf-8", newline="\n")
        evidence = {"schema_version": 1, "channel": "development-msix-payload", "dependencies": locked,
                    "requirements_sha256": hashlib.sha256((source / "requirements.lock.txt").read_bytes()).hexdigest(),
                    "source": "provided-snapshot", "runtime_origin_verified": False,
                    "redistribution_permissions_verified": False}
        (output / "store-payload.json").write_text(json.dumps(evidence, ensure_ascii=False, sort_keys=True, indent=2),
                                                  encoding="utf-8", newline="\n")
    except BaseException:
        current = output.stat(follow_symlinks=False)
        if (output.is_symlink() or output.is_junction() or (created.st_dev, created.st_ino) !=
                (current.st_dev, current.st_ino)):
            raise RuntimeError("暂存目录身份改变，停止清理") from None
        shutil.rmtree(output)
        raise
    LOG.info("商店开发载荷已暂存，源文件数=%d，依赖数=%d；尚未验证安装与发行许可", len(files), len(locked))
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "python-runtime", "dependencies", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    try:
        stage_payload(**vars(args))
        return 0
    except (ValueError, OSError, RuntimeError) as error:
        LOG.error("载荷暂存未完成，类别=%s", type(error).__name__)
        return 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    raise SystemExit(main())
