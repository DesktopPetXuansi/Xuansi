"""官网形象缓存只复用同一清单的完整文件；失败时保留目录供用户处理。"""

import json
import logging

from . import platform_resources
from .appearance_import import installed_candidate

LOG = logging.getLogger(__name__)
IDENTITY_FIELDS = (
    "schemaVersion", "resourceId", "resourceVersionId", "kind", "version",
    "minimumClientVersion", "capabilities", "entrypoint", "files", "dependencies",
)
CACHE_FAILURE = "已下载的形象损坏或与当前官网版本不一致，已保留本地文件和当前形象。请选择其他形象，或重新获取完整文件后通过“本地导入”使用。"


def _reject_links(path):
    # Windows junction 与符号链接都可能跳出资源目录，必须在任何读取前拒绝。
    if any(item.is_symlink() or item.is_junction() for item in (path, *path.parents)):
        raise ValueError("形象缓存不能使用链接")


def cache_exists(version_id, resource_root):
    """先验证 UUID 再拼接路径，损坏目录不应当成缓存缺失而被覆盖。"""
    directory = resource_root / platform_resources.identifier(version_id)
    _reject_links(directory)
    return directory.exists()


def _content_identity(manifest):
    identity = {key: manifest.get(key) for key in IDENTITY_FIELDS}
    # 清单文件、依赖的列举顺序不影响内容身份；名称等展示元数据可由官网更新。
    identity["files"] = sorted(manifest["files"], key=lambda item: item["path"])
    identity["dependencies"] = sorted(manifest["dependencies"], key=lambda item: json.dumps(item, sort_keys=True))
    return identity


def cached_candidate(remote, resource, version_id, *, image_directory, resource_root):
    """后台检查当前官网清单、缓存身份、文件摘要，然后才生成可试载候选。"""
    remote = platform_resources.validate_manifest(remote)
    if (remote["resourceId"] != resource["id"] or remote["resourceVersionId"] != version_id
            or remote["kind"] != resource["kind"]):
        raise ValueError("官网返回的形象身份不一致")
    directory = resource_root / platform_resources.identifier(version_id)
    manifest_path = directory / "installed-manifest.json"
    _reject_links(manifest_path)
    local = platform_resources.validate_manifest(json.loads(manifest_path.read_text("utf-8")))
    if _content_identity(local) != _content_identity(remote):
        raise ValueError("缓存与当前官网形象清单不一致")
    for item in local["files"]:
        _reject_links(directory / item["path"])
    candidate = installed_candidate(version_id, image_directory=image_directory, resource_root=resource_root)
    LOG.info("复用已校验的官网形象缓存 version=%s kind=%s", version_id, resource["kind"])
    return candidate
