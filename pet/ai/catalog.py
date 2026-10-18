"""安装器与客户端共用的固定资源目录；联网更新不能隐式改变已选资源。"""

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Resource:
    id: str
    url: str
    path: str
    sha256: str
    bytes: int
    kind: str
    location: str = "models"
    archive: str = ""


@dataclass(frozen=True)
class LocalModel:
    id: str
    name: str
    resources: tuple[str, ...]
    model_path: str
    projector_path: str
    verification: str = "unverified"


def load_catalog():
    """只读取随源码发布的版本化目录，不接受计划中的任意下载地址。"""
    raw = json.loads(Path(__file__).with_name("catalog.json").read_text(encoding="utf-8"))
    if raw["schema_version"] != 1:
        raise ValueError("不支持的资源目录版本")
    resources = {item["id"]: Resource(**item) for item in raw["resources"]}
    models = {
        item["id"]: LocalModel(**{**item, "resources": tuple(item["resources"])})
        for item in raw["models"]
    }
    return resources, models


RESOURCES, MODELS = load_catalog()
