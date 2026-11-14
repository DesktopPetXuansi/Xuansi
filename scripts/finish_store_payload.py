"""为已暂存的商店开发载荷编译入口并生成图标，不安装或提交应用。"""

import argparse
import json
import logging
import os
import shutil
import struct
import subprocess
import tempfile
from pathlib import Path

from PIL import Image

LOG = logging.getLogger(__name__)
ICONS = (("StoreLogo.png", 50), ("Square44x44Logo.png", 44), ("Square150x150Logo.png", 150))


def _exists(path):
    return path.exists() or path.is_symlink() or path.is_junction()


def _regular(path, root):
    if path.is_symlink() or path.is_junction() or not path.is_file() or not path.resolve().is_relative_to(root):
        raise ValueError("输入文件必须位于指定目录内，且不能使用链接")
    current = root
    for part in path.relative_to(root).parts[:-1]:
        current /= part
        if current.is_symlink() or current.is_junction():
            raise ValueError("输入文件的父目录不能使用链接")


def _identity(path):
    status = path.stat(follow_symlinks=False)
    return status.st_dev, status.st_ino


def _verify_entry(path):
    with path.open("rb") as stream:
        if stream.read(2) != b"MZ":
            raise ValueError("编译输出不是 Windows 可执行文件")
        stream.seek(0x3C)
        offset = stream.read(4)
        if len(offset) != 4:
            raise ValueError("编译输出的 PE 头不完整")
        stream.seek(struct.unpack("<I", offset)[0])
        if stream.read(6) != b"PE\0\0\x64\x86":
            raise ValueError("启动入口必须是 x64 Windows 可执行文件")


def _remove_created(files, directory, directory_identity):
    # 回滚只针对本次独占发布且身份未改变的文件，不覆盖并发写入的产物。
    for path, identity in reversed(files):
        if _exists(path) and not path.is_symlink() and _identity(path) == identity:
            path.unlink()
    if directory_identity is not None and _exists(directory):
        if not directory.is_symlink() and not directory.is_junction() and _identity(directory) == directory_identity:
            try:
                directory.rmdir()
            except OSError:
                LOG.warning("图标目录包含其他文件，已保留该目录")


def finish_payload(*, payload: Path, launcher_source: Path, compiler: Path):
    if payload.is_symlink() or payload.is_junction() or not payload.is_dir():
        raise ValueError("开发载荷必须是普通目录")
    payload = payload.resolve()
    marker, icon = payload / "store-payload.json", payload / "assets/xuansi/icon.png"
    _regular(marker, payload)
    _regular(icon, payload)
    metadata = json.loads(marker.read_text(encoding="utf-8-sig"))
    if (not isinstance(metadata, dict) or metadata.get("schema_version") != 1
            or metadata.get("channel") != "development-msix-payload"):
        raise ValueError("仅允许处理已明确标记的商店开发载荷")
    launcher_source, compiler = Path(launcher_source), Path(compiler)
    if launcher_source.is_symlink() or not launcher_source.is_file() or launcher_source.suffix.lower() != ".cs":
        raise ValueError("请显式提供启动器 C# 源文件")
    if compiler.is_symlink() or not compiler.is_file() or compiler.suffix.lower() != ".exe":
        raise FileNotFoundError("请显式提供 Windows C# 编译器")
    entry, icons = payload / "Xuansi.exe", payload / "assets/store"
    if _exists(entry) or _exists(icons):
        raise FileExistsError("入口或图标目标已存在，保留已有文件")

    temporary = Path(tempfile.mkdtemp(prefix=".xuansi-finish-", dir=payload)).resolve()
    temporary_identity = _identity(temporary)
    published, icons_identity = [], None
    try:
        staged_entry = temporary / "Xuansi.exe"
        command = [str(compiler.resolve()), "/nologo", "/codepage:65001", "/target:winexe", "/platform:x64",
                   "/reference:System.Windows.Forms.dll", "/out:" + str(staged_entry), str(launcher_source.resolve())]
        result = subprocess.run(command, capture_output=True, timeout=60,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if result.returncode != 0 or not staged_entry.is_file():
            raise RuntimeError(f"启动器编译失败，退出码 {result.returncode}")
        _verify_entry(staged_entry)
        staged_icons = temporary / "icons"
        staged_icons.mkdir()
        with Image.open(icon) as original:
            if original.format != "PNG":
                raise ValueError("载荷图标必须是 PNG")
            image = original.convert("RGBA")
            for name, size in ICONS:
                image.resize((size, size), Image.Resampling.LANCZOS).save(staged_icons / name, format="PNG")
        for name, size in ICONS:
            with Image.open(staged_icons / name) as generated:
                if generated.format != "PNG" or generated.size != (size, size):
                    raise ValueError("生成的商店图标尺寸不符")

        # mkdir 与硬链接均以独占方式创建；入口最后发布，失败时不会留下可启动的半成品。
        icons.mkdir()
        icons_identity = _identity(icons)
        for name, _ in ICONS:
            target = icons / name
            os.link(staged_icons / name, target)
            published.append((target, _identity(target)))
        os.link(staged_entry, entry)
        published.append((entry, _identity(entry)))
    except BaseException:
        _remove_created(published, icons, icons_identity)
        raise
    finally:
        # 递归清理前再次核对本次临时目录的路径与身份。
        if (temporary.parent != payload or temporary.resolve().parent != payload
                or not temporary.name.startswith(".xuansi-finish-") or temporary.is_symlink()
                or temporary.is_junction() or _identity(temporary) != temporary_identity):
            raise RuntimeError("临时目录身份改变，停止清理")
        shutil.rmtree(temporary)
    LOG.info("商店开发载荷入口和三个图标已生成；尚未验证 MSIX 安装与发行许可")
    return entry


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("payload", "launcher-source", "compiler"):
        parser.add_argument("--" + name, type=Path, required=True)
    arguments = parser.parse_args(argv)
    try:
        finish_payload(**vars(arguments))
        return 0
    except (ValueError, OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        LOG.error("载荷入口与图标生成未完成，类别=%s", type(error).__name__)
        return 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    raise SystemExit(main())
