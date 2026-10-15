"""将选择的本地模型运行文件整理为上传包，不读取无关文件或修改源模型。"""

import asyncio
import json
import logging
import os
import stat
import zipfile
from dataclasses import dataclass
from pathlib import Path

from .platform_resources import MAX_BYTES, model_file_references, relative_path

LOG = logging.getLogger(__name__)
MAX_FILES = 2048
MAX_JSON_BYTES = 8 * 1024 * 1024
CHUNK_BYTES = 128 * 1024


@dataclass(frozen=True)
class ModelPackage:
    path: Path
    entrypoint: str
    name: str
    bytes: int


def _check_cancel(cancel):
    if cancel is not None and cancel.is_set():
        raise asyncio.CancelledError


def _entry_file(source, cancel):
    path = Path(source).absolute()
    if path.is_symlink() or path.is_junction():
        raise ValueError("模型入口或文件夹不能使用链接")
    if path.is_dir():
        entries = []
        for directory, folders, filenames in os.walk(path, followlinks=False):
            _check_cancel(cancel)
            # Windows junction 不属于普通 symlink，必须主动剪枝，不能把
            # 目录外的模型变成自动选择的入口；未引用目录也不遍历其内容。
            folders[:] = [name for name in folders if not (Path(directory) / name).is_symlink()
                          and not (Path(directory) / name).is_junction()]
            for filename in filenames:
                if filename.endswith(".model3.json"):
                    entries.append(Path(directory) / filename)
                    if len(entries) > 1:
                        raise ValueError("文件夹包含多个模型，请直接选择要上传的 .model3.json 文件")
        if not entries:
            raise ValueError("文件夹中没有导出的 .model3.json 模型入口")
        path = entries[0]
    if not path.name.endswith(".model3.json"):
        raise ValueError("请选择导出的 .model3.json 文件或包含它的模型文件夹")
    return path


def _safe_file(root, name):
    name = relative_path(name)
    candidate = root / name
    # Windows junction 和普通符号链接都不能把引用变成模型目录外的文件。
    for component in [candidate, *candidate.parents]:
        if component == root:
            break
        if component.is_symlink() or component.is_junction():
            raise ValueError("模型引用不能包含符号链接或目录链接")
    if not candidate.resolve().is_relative_to(root.resolve()):
        raise ValueError("模型引用路径超出所选目录")
    if not candidate.is_file() or not stat.S_ISREG(candidate.stat().st_mode):
        raise ValueError(f"模型引用文件不存在：{name}")
    return candidate


def _model_files(entry):
    root = entry.parent
    entry = _safe_file(root, entry.name)
    if entry.stat().st_size > MAX_JSON_BYTES:
        raise ValueError("模型入口 JSON 大小超过 8 MiB")
    document = json.loads(entry.read_text(encoding="utf-8-sig"))
    references = document.get("FileReferences") if isinstance(document, dict) else None
    declared_references = model_file_references(references)
    files = {entry.name: entry}
    names = {entry.name.casefold(): entry.name}
    for name in declared_references:
        path = _safe_file(root, name)
        if name.casefold() in names and names[name.casefold()] != name:
            raise ValueError("模型引用路径存在大小写冲突")
        files[name] = path
        names[name.casefold()] = name
        if len(files) > MAX_FILES:
            raise ValueError("模型文件数量超过 2048")
    sizes = {name: path.stat() for name, path in files.items()}
    if sum(info.st_size for info in sizes.values()) > MAX_BYTES:
        raise ValueError("模型总大小超过 512 MiB")
    return files, sizes


def build_model_package(source, output, progress=None, cancel=None):
    """后台执行；只打包入口及引用，不将工程、聊天或私人笔记带入上传。"""
    _check_cancel(cancel)
    entry = _entry_file(source, cancel)
    files, snapshots = _model_files(entry)
    total = sum(info.st_size for info in snapshots.values())
    processed = 0
    last_percent = -1
    output = Path(output)
    # PNG 等已压缩资源不重复压缩，减少 CPU 消耗并避免压缩比校验误伤。
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_STORED) as archive:
        for name, path in files.items():
            _check_cancel(cancel)
            snapshot = snapshots[name]
            with path.open("rb") as source_file, archive.open(name, "w") as target:
                while chunk := source_file.read(CHUNK_BYTES):
                    _check_cancel(cancel)
                    processed += len(chunk)
                    if processed > MAX_BYTES:
                        raise ValueError("模型总大小超过 512 MiB")
                    target.write(chunk)
                    percent = min(100, processed * 100 // max(1, total))
                    if progress and percent != last_percent:
                        progress(percent)
                        last_percent = percent
            current = path.stat()
            if (current.st_size, current.st_mtime_ns) != (snapshot.st_size, snapshot.st_mtime_ns):
                raise ValueError("模型文件在整理时发生变化，请保存模型后重新上传")
    size = output.stat().st_size
    if size > MAX_BYTES:
        raise ValueError("模型上传包大小超过 512 MiB")
    LOG.info("本地模型已整理 files=%d bytes=%d", len(files), size)
    return ModelPackage(output, entry.name, entry.name.removesuffix(".model3.json"), size)
