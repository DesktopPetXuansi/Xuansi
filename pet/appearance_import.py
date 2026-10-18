"""把本地或已下载的形象整理为可预览候选；不切换形象、不执行模型脚本。"""

import asyncio
import hashlib
import json
import logging
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from . import appearance, platform_resources
from .platform_model_package import build_model_package

LOG = logging.getLogger(__name__)
IMAGE_SUFFIXES = {".png", ".apng", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}


@dataclass(frozen=True)
class AppearanceCandidate:
    kind: str
    name: str
    image_id: str = ""
    prepared: tuple | None = None

    @property
    def version_id(self):
        return self.prepared[0]["resourceVersionId"] if self.prepared else ""


def _check_cancel(cancel):
    if cancel is not None and cancel.is_set():
        raise asyncio.CancelledError


def _image_candidate(source, name, image_directory, prepared=None):
    imported = appearance.import_image(source, image_directory)
    return AppearanceCandidate("ANIMATION" if imported.frames > 1 else "IMAGE",
                               name, imported.identifier, prepared)


def _local_manifest(package, cancel):
    """摘要只包含有序文件内容和入口，压缩时间戳变化不产生重复形象。"""
    files = []
    with zipfile.ZipFile(package.path) as archive:
        for item in sorted(archive.infolist(), key=lambda info: info.filename):
            _check_cancel(cancel)
            with archive.open(item) as source:
                digest = hashlib.sha256()
                while chunk := source.read(128 * 1024):
                    _check_cancel(cancel)
                    digest.update(chunk)
            files.append({"path": item.filename, "bytes": item.file_size, "sha256": digest.hexdigest()})
    content = json.dumps({"entrypoint": package.entrypoint, "files": files},
                         sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    version_id = str(uuid5(NAMESPACE_URL, "xuansi:local-model:" + hashlib.sha256(content).hexdigest()))
    return {
        "schemaVersion": 1, "resourceId": version_id, "resourceVersionId": version_id,
        "kind": "MODEL", "name": package.name, "source": "local", "version": "local",
        "minimumClientVersion": "", "capabilities": {}, "entrypoint": package.entrypoint,
        "files": files, "dependencies": [],
    }


def import_appearance(source, progress=None, cancel=None, *, image_directory=None, resource_root=None):
    """后台导入图片、动图或导出模型；失败与取消都不改现用形象。"""
    _check_cancel(cancel)
    path = Path(source).absolute()
    if str(source).startswith(("\\\\", "//")):
        raise ValueError("请选择保存在本机磁盘的形象文件")
    # 同时检查所选路径的父目录，避免目录链接绕过模型打包器的引用边界。
    if any(item.is_symlink() or item.is_junction() for item in (path, *path.parents)):
        raise ValueError("形象文件或文件夹不能使用链接")
    image_directory = Path(image_directory) if image_directory is not None else appearance.DIRECTORY
    resource_root = Path(resource_root) if resource_root is not None else platform_resources.RESOURCE_ROOT
    if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES:
        candidate = _image_candidate(path, path.stem, image_directory)
        LOG.info("本地形象候选已导入 kind=%s", candidate.kind)
        return candidate
    if not path.is_dir() and not path.name.endswith(".model3.json"):
        raise ValueError("请选择图片、动图、导出的 .model3.json 文件或包含唯一模型的文件夹；暂不支持压缩包和工程文件")
    with tempfile.TemporaryDirectory(prefix="xuansi-appearance-") as temporary:
        package = build_model_package(path, Path(temporary) / "model.zip", progress, cancel)
        manifest = _local_manifest(package, cancel)
        authorization = {
            "bytes": package.bytes, "sha256": platform_resources.hash_file(package.path),
        }
        _check_cancel(cancel)
        platform_resources.install_package(package.path, manifest, authorization, resource_root)
    LOG.info("本地形象候选已导入 kind=MODEL version=%s", manifest["resourceVersionId"])
    return installed_candidate(manifest["resourceVersionId"], resource_root=resource_root)


def installed_candidate(version_id, *, image_directory=None, resource_root=None):
    """下载后直接生成候选，保留模型完整性校验并统一识别静图与动图。"""
    image_directory = Path(image_directory) if image_directory is not None else appearance.DIRECTORY
    resource_root = Path(resource_root) if resource_root is not None else platform_resources.RESOURCE_ROOT
    prepared = platform_resources.read_installed(version_id, resource_root)
    manifest, entry = prepared
    name = manifest.get("name") or entry.name.removesuffix(".model3.json")
    if manifest["kind"] in {"IMAGE", "ANIMATION"}:
        return _image_candidate(entry, name, image_directory, prepared)
    if manifest["kind"] != "MODEL":
        raise ValueError("该资源是动作或表情，请选择可更换的桌宠形象")
    return AppearanceCandidate("MODEL", name, prepared=prepared)
