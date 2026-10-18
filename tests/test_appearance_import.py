"""本地形象导入只保存运行副本，不修改来源或旧安装。"""

import asyncio
import json
import os
import threading
import zipfile
from pathlib import Path
from uuid import uuid4

import pytest
from PIL import Image

from pet.appearance_import import import_appearance, installed_candidate
from pet.platform_resources import hash_file, install_package


def model_source(root, *, bom=False):
    root.mkdir()
    (root / "形象.moc3").write_bytes(b"MOC3-test")
    Image.new("RGBA", (8, 8), "red").save(root / "纹理.png")
    entry = root / "小猫.model3.json"
    entry.write_text(json.dumps({"Version": 3, "FileReferences": {
        "Moc": "形象.moc3", "Textures": ["纹理.png"],
    }}, ensure_ascii=False), encoding="utf-8-sig" if bom else "utf-8")
    (root / "私人笔记.txt").write_text("不应导入", encoding="utf-8")
    (root / "工程.cmo3").write_bytes(b"private")
    return entry


def local_import(source, tmp_path, **kwargs):
    return import_appearance(source, image_directory=tmp_path / "images",
                             resource_root=tmp_path / "resources", **kwargs)


@pytest.mark.parametrize("animated", [False, True])
def test_image_and_animation_survive_source_removal(tmp_path, animated):
    source = tmp_path / "形象.gif"
    image = Image.new("RGBA", (8, 8), "red")
    image.save(source, save_all=animated,
               append_images=[Image.new("RGBA", (8, 8), "blue")] if animated else [], duration=100)
    original = source.read_bytes()
    first = local_import(source, tmp_path)
    second = local_import(source, tmp_path)
    assert source.read_bytes() == original
    assert first.kind == ("ANIMATION" if animated else "IMAGE")
    assert first.image_id == second.image_id
    assert first.name == "形象" and first.version_id == ""
    source.unlink()
    assert (tmp_path / "images" / first.image_id).is_file()


@pytest.mark.parametrize("folder", [False, True])
@pytest.mark.parametrize("bom", [False, True])
def test_model_import_is_persistent_and_only_collects_references(tmp_path, folder, bom):
    source = model_source(tmp_path / "source", bom=bom)
    original = {file: file.read_bytes() for file in source.parent.iterdir()}
    candidate = local_import(source.parent if folder else source, tmp_path)
    assert candidate.kind == "MODEL" and candidate.name == "小猫"
    manifest, entry = candidate.prepared
    assert candidate.version_id == manifest["resourceVersionId"]
    assert {item["path"] for item in manifest["files"]} == {source.name, "形象.moc3", "纹理.png"}
    assert all(file.read_bytes() == data for file, data in original.items())
    for file in original:
        file.unlink()
    loaded = installed_candidate(candidate.version_id, resource_root=tmp_path / "resources")
    assert loaded == candidate and entry.is_file()


def test_model_identity_ignores_mtime_but_tracks_content(tmp_path):
    source = model_source(tmp_path / "source")
    first = local_import(source, tmp_path)
    for file in source.parent.iterdir():
        os.utime(file, (1_700_000_000, 1_700_000_000))
    assert local_import(source, tmp_path).version_id == first.version_id
    (source.parent / "形象.moc3").write_bytes(b"changed-content")
    second = local_import(source, tmp_path)
    assert first.version_id != second.version_id
    assert len(list((tmp_path / "resources").iterdir())) == 2


def test_missing_reference_keeps_previous_install(tmp_path):
    source = model_source(tmp_path / "source")
    candidate = local_import(source, tmp_path)
    before = {file: file.read_bytes() for file in (tmp_path / "resources").rglob("*") if file.is_file()}
    (source.parent / "纹理.png").unlink()
    with pytest.raises(ValueError, match="引用文件"):
        local_import(source, tmp_path)
    assert all(file.read_bytes() == data for file, data in before.items())
    assert installed_candidate(candidate.version_id, resource_root=tmp_path / "resources") == candidate


@pytest.mark.parametrize("phase", ["before", "packaged"])
def test_cancellation_does_not_install(tmp_path, phase):
    source = model_source(tmp_path / "source")
    cancel = threading.Event()
    if phase == "before":
        cancel.set()
    with pytest.raises(asyncio.CancelledError):
        local_import(source, tmp_path, cancel=cancel, progress=lambda percent: cancel.set())
    assert not (tmp_path / "resources").exists()


@pytest.mark.parametrize("method", ["is_symlink", "is_junction"])
def test_linked_source_parent_is_rejected(tmp_path, monkeypatch, method):
    source = model_source(tmp_path / "source")
    original = getattr(Path, method)
    monkeypatch.setattr(Path, method, lambda path: path == source.parent or original(path))
    with pytest.raises(ValueError, match="链接"):
        local_import(source, tmp_path)
    assert not (tmp_path / "resources").exists()


@pytest.mark.parametrize("filename", ["工程.cmo3", "下载.zip", "未知.txt"])
def test_unsupported_format_explains_accepted_files(tmp_path, filename):
    source = tmp_path / filename
    source.write_bytes(b"unsupported")
    with pytest.raises(ValueError, match="图片|model3"):
        local_import(source, tmp_path)


@pytest.mark.parametrize("animated", [False, True])
def test_downloaded_image_becomes_ready_candidate(tmp_path, animated):
    source = tmp_path / "download.gif"
    Image.new("RGBA", (8, 8), "red").save(
        source, save_all=animated,
        append_images=[Image.new("RGBA", (8, 8), "blue")] if animated else [], duration=100)
    version_id = str(uuid4())
    manifest = {
        "schemaVersion": 1, "resourceId": str(uuid4()), "resourceVersionId": version_id,
        "kind": "ANIMATION" if animated else "IMAGE", "name": "官网小猫", "version": "1",
        "minimumClientVersion": "", "entrypoint": source.name, "dependencies": [],
        "files": [{"path": source.name, "bytes": source.stat().st_size, "sha256": hash_file(source)}],
    }
    package = tmp_path / "download.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.write(source, source.name)
    install_package(package, manifest, {"bytes": package.stat().st_size, "sha256": hash_file(package)},
                    tmp_path / "resources")
    candidate = installed_candidate(version_id, image_directory=tmp_path / "images",
                                    resource_root=tmp_path / "resources")
    assert candidate.name == "官网小猫" and candidate.version_id == version_id
    assert candidate.kind == manifest["kind"]
    assert (tmp_path / "images" / candidate.image_id).is_file()


def test_non_appearance_resource_is_rejected(monkeypatch):
    monkeypatch.setattr("pet.appearance_import.platform_resources.read_installed",
                        lambda *args: ({"kind": "MOTION", "name": "动作"}, Path("pet.motion3.json")))
    with pytest.raises(ValueError, match="动作或表情"):
        installed_candidate(str(uuid4()))


def test_invalid_json_does_not_touch_existing_install(tmp_path):
    source = model_source(tmp_path / "source")
    candidate = local_import(source, tmp_path)
    source.write_text("invalid-json", encoding="utf-8")
    with pytest.raises(ValueError):
        local_import(source, tmp_path)
    assert installed_candidate(candidate.version_id, resource_root=tmp_path / "resources") == candidate
    assert len(list((tmp_path / "resources").iterdir())) == 1


def test_defaults_are_resolved_at_call_time(tmp_path, monkeypatch):
    source = tmp_path / "image.png"
    Image.new("RGBA", (8, 8), "red").save(source)
    monkeypatch.setattr("pet.appearance_import.appearance.DIRECTORY", tmp_path / "new-images")
    candidate = import_appearance(source)
    assert (tmp_path / "new-images" / candidate.image_id).is_file()
