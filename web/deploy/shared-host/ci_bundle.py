"""发布包的固定格式与校验；SSH 接口不解压任意路径，也不执行包内脚本。"""

import hashlib
import json
import re
import shutil
import tarfile
from pathlib import Path

REPOSITORY = "DesktopPetXuansi/Xuansi"
PAYLOAD_FILES = {"api", "worker", "admin", "frontend-image.tar.gz", "release.json"}
BUNDLE_FILES = PAYLOAD_FILES | {"SHA256SUMS"}
MAX_BUNDLE_BYTES = 512 << 20
MAX_EXPANDED_BYTES = 768 << 20


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def validate_manifest(data):
    if data.get("repository") != REPOSITORY or not re.fullmatch(r"[0-9a-f]{40}", str(data.get("commit", ""))):
        raise ValueError("发布来源或提交编号无效")
    for name in ("run_id", "attempt"):
        if type(data.get(name)) is not int or not 0 < data[name] < 10**18:
            raise ValueError("发布流水线编号无效")
    expected_image = "xuansi-frontend:ci-" + data["commit"]
    if data.get("image") != expected_image:
        raise ValueError("前端镜像名称无效")
    return data


def unpack_bundle(archive_path, destination):
    """仅复制六个顶层普通文件，拒绝链接、重复成员和解压炸弹。"""
    destination = Path(destination)
    destination.mkdir(mode=0o700)
    with tarfile.open(archive_path, "r:gz") as archive:
        members = archive.getmembers()
        if len(members) != len(BUNDLE_FILES) or {m.name for m in members} != BUNDLE_FILES:
            raise ValueError("发布包文件集合不匹配")
        if sum(m.size for m in members) > MAX_EXPANDED_BYTES:
            raise ValueError("发布包解压大小超限")
        for member in members:
            if not member.isfile() or member.size <= 0:
                raise ValueError("发布包仅允许非空普通文件")
            with archive.extractfile(member) as source, (destination / member.name).open("xb") as output:
                shutil.copyfileobj(source, output)
            (destination / member.name).chmod(0o600)
    checksums = {}
    for line in (destination / "SHA256SUMS").read_text("utf-8").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  ([A-Za-z0-9_.-]+)", line)
        if not match or match[2] in checksums:
            raise ValueError("发布包摘要格式无效")
        checksums[match[2]] = match[1]
    if set(checksums) != PAYLOAD_FILES or any(digest(destination / name) != value for name, value in checksums.items()):
        raise ValueError("发布包 SHA256 校验失败")
    manifest = validate_manifest(json.loads((destination / "release.json").read_text("utf-8")))
    for name in ("api", "worker", "admin"):
        with (destination / name).open("rb") as stream:
            header = stream.read(20)
        if len(header) < 20 or header[:5] != b"\x7fELF\x02" or header[18:20] != b"\x3e\x00":
            raise ValueError("后端程序必须为 Linux amd64 ELF")
    validate_image_archive(destination / "frontend-image.tar.gz", manifest["image"])
    return manifest


def validate_image_archive(path, expected_image):
    # Docker load 仅可导入本次玄司镜像，不能覆盖主机上其他项目的镜像标签。
    with tarfile.open(path, "r:gz") as archive:
        member = archive.getmember("manifest.json")
        if not member.isfile() or member.size > 65536:
            raise ValueError("Docker 镜像清单无效")
        with archive.extractfile(member) as stream:
            manifests = json.load(stream)
        if len(manifests) != 1 or manifests[0].get("RepoTags") != [expected_image]:
            raise ValueError("Docker 发布包包含非预期镜像")


def release_name(manifest):
    return f"web-ci-{manifest['run_id']}-{manifest['attempt']}-{manifest['commit'][:12]}"
