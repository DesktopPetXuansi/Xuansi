"""平台资源严格清单校验、安全安装和离线索引；不执行资源内脚本。"""

import hashlib
import json
import logging
import re
import shutil
import stat
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from uuid import UUID

from .config import DATA, ROOT

LOG = logging.getLogger(__name__)
RESOURCE_ROOT = DATA / "platform-resources"
MAX_BYTES = 512 * 1024 * 1024
KINDS = {"MODEL", "MOTION", "EXPRESSION", "IMAGE", "ANIMATION"}
# 与 Go 资源包 SafePath 白名单一致，许可/说明文本只作为普通附件保存。
SUFFIXES = {".json", ".moc3", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".wav", ".mp3", ".txt"}


def identifier(value):
    if not isinstance(value, str) or str(UUID(value)) != value:
        raise ValueError("资源标识必须为规范 UUID")
    return value


def relative_path(value):
    """拒绝 Windows 路径歧义、设备名、越界和附加数据流。"""
    if not isinstance(value, str) or not value or len(value) > 240:
        raise ValueError("资源路径无效")
    path = PurePosixPath(value)
    if (path.is_absolute() or str(path) != value or re.search(r'[\\:<>"|?*\x00-\x1f]', value)
            or value.casefold() == "installed-manifest.json"
            or any(part in (".", "..") or part.endswith((" ", "."))
                   or re.fullmatch(r"(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])(\..*)?", part)
                   for part in path.parts) or path.suffix.lower() not in SUFFIXES):
        raise ValueError("资源路径不安全或文件类型不允许")
    return value


def validate_manifest(manifest):
    if type(manifest.get("schemaVersion")) is not int or manifest["schemaVersion"] != 1:
        raise ValueError("不支持的资源清单版本")
    identifier(manifest["resourceId"])
    identifier(manifest["resourceVersionId"])
    kind = manifest["kind"]
    if kind not in KINDS:
        raise ValueError("资源类型无效")
    if not isinstance(manifest["version"], str) or not manifest["version"]:
        raise ValueError("资源版本无效")
    minimum = manifest["minimumClientVersion"]
    # 空值表示作者未声明最低版本；运行兼容性仍由客户端实际试载决定。
    if not isinstance(minimum, str) or minimum and not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", minimum):
        raise ValueError("最低客户端版本无效")
    current = (ROOT / "VERSION").read_text("utf-8").strip()
    if minimum and tuple(map(int, minimum.split("."))) > tuple(map(int, current.split("."))):
        raise ValueError("请升级客户端后再安装此资源")
    capabilities = manifest.get("capabilities", {})
    if not isinstance(capabilities, dict):
        raise ValueError("资源能力声明无效")
    parameters = capabilities.get("parameters", {})
    if not isinstance(parameters, dict) or any(not isinstance(key, str) or not isinstance(value, str)
                                               for key, value in parameters.items()):
        raise ValueError("参数映射格式无效")
    entry = relative_path(manifest["entrypoint"])
    files = manifest["files"]
    if not isinstance(files, list) or not 1 <= len(files) <= 2048:
        raise ValueError("文件数量超出范围")
    paths = set()
    total = 0
    for item in files:
        path = relative_path(item["path"])
        if path.casefold() in paths or type(item["bytes"]) is not int or item["bytes"] < 0:
            raise ValueError("清单文件重复或大小无效")
        paths.add(path.casefold())
        if not isinstance(item["sha256"], str) or not re.fullmatch("[a-f0-9]{64}", item["sha256"]):
            raise ValueError("文件摘要无效")
        total += item["bytes"]
    if total > MAX_BYTES or entry.casefold() not in paths:
        raise ValueError("资源过大或入口不存在")
    suffix = {"MODEL": ".model3.json", "MOTION": ".motion3.json", "EXPRESSION": ".exp3.json"}.get(kind)
    if suffix and not entry.endswith(suffix):
        raise ValueError("资源入口与类型不符")
    dependencies = manifest["dependencies"]
    if not isinstance(dependencies, list):
        raise ValueError("依赖格式无效")
    for dependency in dependencies:
        identifier(dependency["resourceId"])
        identifier(dependency["resourceVersionId"])
        if dependency["kind"] != "MODEL" or dependency["relation"] != "TARGET_MODEL":
            raise ValueError("资源依赖类型无效")
    if kind in {"MOTION", "EXPRESSION"} and len(dependencies) != 1:
        raise ValueError("动作或表情必须绑定唯一模型版本")
    return manifest


def hash_file(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def model_file_references(references):
    """仅识别 Go/Cubism 契约中的运行文件字段，未知元数据不会触发本地文件读取。"""
    if not isinstance(references, dict):
        raise ValueError("模型缺少有效的文件引用")
    moc, textures = references.get("Moc"), references.get("Textures")
    if (not isinstance(moc, str) or not moc or not isinstance(textures, list) or not textures
            or any(not isinstance(name, str) or not name for name in textures)):
        raise ValueError("模型缺少有效的 MOC 或纹理引用")
    result = [moc, *textures]
    for key in ("Physics", "Pose", "DisplayInfo", "UserData"):
        value = references.get(key)
        if value is not None and not isinstance(value, str):
            raise ValueError("模型可选文件引用无效")
        if value:
            result.append(value)
    expressions, groups = references.get("Expressions") or [], references.get("Motions") or {}
    if not isinstance(expressions, list) or not isinstance(groups, dict):
        raise ValueError("模型动作或表情引用无效")
    actions = list(expressions)
    for motions in groups.values():
        if motions is not None and not isinstance(motions, list):
            raise ValueError("模型动作引用无效")
        actions.extend(motions or [])
    for action in actions:
        if not isinstance(action, dict) or not isinstance(action.get("File"), str) or not action["File"]:
            raise ValueError("模型动作或表情缺少文件引用")
        result.append(action["File"])
    # 表情没有 Sound 字段；只取动作中明确声明的可选声音文件。
    for motions in groups.values():
        for motion in motions or []:
            sound = motion.get("Sound")
            if sound is not None and not isinstance(sound, str):
                raise ValueError("模型声音引用无效")
            if sound:
                result.append(sound)
    return result


def check_references(manifest, directory):
    """校验模型引用存在且位于清单中；JSON 动作/表情也须可解析。"""
    entry = directory / manifest["entrypoint"]
    if manifest["kind"] not in {"MODEL", "MOTION", "EXPRESSION"}:
        return
    document = json.loads(entry.read_text("utf-8-sig"))
    if not isinstance(document, dict):
        raise ValueError("资源入口 JSON 无效")
    if manifest["kind"] == "EXPRESSION":
        if document.get("Type") != "Live2D Expression" or not isinstance(document.get("Parameters"), list):
            raise ValueError("表情 JSON 格式无效")
        for parameter in document["Parameters"]:
            if (not isinstance(parameter, dict) or not isinstance(parameter.get("Id"), str)
                    or type(parameter.get("Value")) not in (int, float)
                    or parameter.get("Blend", "Add") not in {"Add", "Multiply", "Overwrite"}):
                raise ValueError("表情参数无效")
    if manifest["kind"] == "MOTION":
        meta = document.get("Meta", {})
        if (document.get("Version") != 3 or not isinstance(document.get("Curves"), list)
                or not isinstance(meta, dict) or type(meta.get("Duration")) not in (int, float)
                or not 0 < meta["Duration"] <= 3600):
            raise ValueError("动作 JSON 格式无效")
    if manifest["kind"] != "MODEL":
        return
    references = document.get("FileReferences", {})
    declared = {item["path"] for item in manifest["files"]}
    for value in model_file_references(references):
        path = relative_path(value)
        combined = str(PurePosixPath(manifest["entrypoint"]).parent / path)
        if combined not in declared or not (directory / combined).is_file():
            raise ValueError("模型引用文件缺失")


def install_package(package, manifest, authorization, root=RESOURCE_ROOT):
    """暂存验证完整后原子发布新版本；任何失败均不触及旧版本。"""
    validate_manifest(manifest)
    if (type(authorization["bytes"]) is not int or not 0 < authorization["bytes"] <= MAX_BYTES
            or package.stat().st_size != authorization["bytes"]
            or hash_file(package) != authorization["sha256"]):
        raise ValueError("下载包大小或摘要校验失败")
    root.mkdir(parents=True, exist_ok=True)
    destination = root / manifest["resourceVersionId"]
    if destination.exists():
        read_installed(manifest["resourceVersionId"], root)
        return destination
    temporary = Path(tempfile.mkdtemp(prefix=".install-", dir=root))
    try:
        expected = {item["path"]: item for item in manifest["files"]}
        with zipfile.ZipFile(package) as archive:
            seen = set()
            for info in archive.infolist():
                if info.is_dir():
                    continue
                path = relative_path(info.filename)
                mode = info.external_attr >> 16
                if stat.S_ISLNK(mode) or path in seen or path not in expected:
                    raise ValueError("压缩包含未声明文件、重复路径或符号链接")
                seen.add(path)
                if info.file_size != expected[path]["bytes"]:
                    raise ValueError("压缩包文件大小不符")
                target = temporary / path
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as source, target.open("xb") as output:
                    shutil.copyfileobj(source, output, 128 * 1024)
                if hash_file(target) != expected[path]["sha256"]:
                    raise ValueError("解包文件摘要不符")
            if seen != set(expected):
                raise ValueError("压缩包缺少清单文件")
        check_references(manifest, temporary)
        (temporary / "installed-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), "utf-8")
        temporary.rename(destination)
        LOG.info("平台资源已安装 version=%s kind=%s", manifest["resourceVersionId"], manifest["kind"])
        return destination
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def read_installed(version_id, root=RESOURCE_ROOT):
    directory = root / identifier(version_id)
    if directory.is_symlink():
        raise ValueError("资源目录不能使用符号链接")
    manifest = validate_manifest(json.loads((directory / "installed-manifest.json").read_text("utf-8")))
    if manifest["resourceVersionId"] != version_id:
        raise ValueError("已安装资源身份不符")
    for item in manifest["files"]:
        path = directory / item["path"]
        if (any(parent.is_symlink() for parent in (path, *path.parents) if parent != root.parent)
                or not path.is_file() or path.stat().st_size != item["bytes"] or hash_file(path) != item["sha256"]):
            raise ValueError("本地资源已损坏")
    check_references(manifest, directory)
    return manifest, directory / manifest["entrypoint"]


def installed_resources(root=RESOURCE_ROOT):
    result = []
    if root.is_dir():
        for directory in root.iterdir():
            if directory.name.startswith(".") or not directory.is_dir():
                continue
            try:
                result.append(read_installed(directory.name, root)[0])
            except (ValueError, KeyError, OSError, TypeError):
                LOG.warning("忽略已损坏的本地平台资源")
    return result
