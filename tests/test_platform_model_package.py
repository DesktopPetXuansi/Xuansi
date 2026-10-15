"""直接上传只收集模型引用；源模型、编辑工程和无关文件不受影响。"""

import asyncio
import json
import threading
import zipfile
from pathlib import Path

import pytest

from pet.platform_model_package import build_model_package


def model_fixture(root):
    root.mkdir()
    (root / "textures").mkdir()
    (root / "pet.moc3").write_bytes(b"MOC3\x01\x00\x00\x00example")
    (root / "textures/texture.png").write_bytes(b"texture-content")
    (root / "pet.model3.json").write_text(json.dumps({
        "Version": 3, "FileReferences": {
            "Moc": "pet.moc3", "Textures": ["textures/texture.png"], "DisplayInfo": "",
        },
    }), encoding="utf-8")
    (root / "project.cmo3").write_bytes(b"editor-source")
    (root / "notes.txt").write_bytes(b"private-notes")
    return root / "pet.model3.json"


@pytest.mark.parametrize("directory", [False, True])
def test_model_file_and_folder_collect_only_references(tmp_path, directory):
    entry = model_fixture(tmp_path / "model")
    original = {file: file.read_bytes() for file in entry.parent.rglob("*") if file.is_file()}
    progress = []
    package = build_model_package(entry.parent if directory else entry, tmp_path / "model.zip",
                                  lambda percent: progress.append(percent))
    assert package.entrypoint == "pet.model3.json" and package.name == "pet"
    assert package.bytes == package.path.stat().st_size
    with zipfile.ZipFile(package.path) as archive:
        assert set(archive.namelist()) == {"pet.model3.json", "pet.moc3", "textures/texture.png"}
        assert archive.read("textures/texture.png") == original[entry.parent / "textures/texture.png"]
    assert all(path.read_bytes() == data for path, data in original.items())
    assert progress[-1] == 100


def test_missing_reference_fails_before_package_is_written(tmp_path):
    entry = model_fixture(tmp_path / "model")
    (entry.parent / "textures/texture.png").unlink()
    with pytest.raises(ValueError, match="引用文件不存在"):
        build_model_package(entry, tmp_path / "model.zip")
    assert not (tmp_path / "model.zip").exists()


def test_unknown_model_fields_never_collect_private_files(tmp_path):
    entry = model_fixture(tmp_path / "model")
    document = json.loads(entry.read_text("utf-8"))
    document["FileReferences"]["UnrelatedMetadata"] = "notes.txt"
    entry.write_text(json.dumps(document), encoding="utf-8")
    package = build_model_package(entry, tmp_path / "model.zip")
    with zipfile.ZipFile(package.path) as archive:
        assert "notes.txt" not in archive.namelist()
        assert b"private-notes" not in b"".join(archive.read(name) for name in archive.namelist())


@pytest.mark.parametrize("reference", ["../secret.png", "/secret.png", "C:/secret.png", "textures\\texture.png"])
def test_reference_cannot_escape_selected_model(tmp_path, reference):
    entry = model_fixture(tmp_path / "model")
    document = json.loads(entry.read_text("utf-8"))
    document["FileReferences"]["Textures"] = [reference]
    entry.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValueError, match="路径"):
        build_model_package(entry, tmp_path / "model.zip")


def test_multiple_entries_require_explicit_file_selection(tmp_path):
    entry = model_fixture(tmp_path / "model")
    (entry.parent / "other.model3.json").write_bytes(entry.read_bytes())
    with pytest.raises(ValueError, match="多个模型"):
        build_model_package(entry.parent, tmp_path / "model.zip")
    assert build_model_package(entry, tmp_path / "model.zip").entrypoint == entry.name


def test_folder_selection_does_not_follow_linked_model_subdirectories(tmp_path, monkeypatch):
    selected = tmp_path / "models"
    selected.mkdir()
    model_fixture(selected / "linked-model")
    original = Path.is_junction
    monkeypatch.setattr(Path, "is_junction", lambda path: path.name == "linked-model" or original(path))
    with pytest.raises(ValueError, match="模型入口|链接"):
        build_model_package(selected, tmp_path / "model.zip")
    assert not (tmp_path / "model.zip").exists()


@pytest.mark.parametrize("link_method", ["is_symlink", "is_junction"])
def test_linked_reference_is_rejected(tmp_path, monkeypatch, link_method):
    entry = model_fixture(tmp_path / "model")
    original = getattr(Path, link_method)
    monkeypatch.setattr(Path, link_method, lambda path: path.name == "texture.png" or original(path))
    with pytest.raises(ValueError, match="链接"):
        build_model_package(entry, tmp_path / "model.zip")


def test_size_limit_is_checked_before_packaging(tmp_path, monkeypatch):
    entry = model_fixture(tmp_path / "model")
    monkeypatch.setattr("pet.platform_model_package.MAX_BYTES", 10)
    with pytest.raises(ValueError, match="大小"):
        build_model_package(entry, tmp_path / "model.zip")
    assert not (tmp_path / "model.zip").exists()


def test_cancelled_packaging_does_not_create_output(tmp_path):
    entry = model_fixture(tmp_path / "model")
    cancellation = threading.Event()
    cancellation.set()
    with pytest.raises(asyncio.CancelledError):
        build_model_package(entry, tmp_path / "model.zip", cancel=cancellation)
    assert not (tmp_path / "model.zip").exists()
