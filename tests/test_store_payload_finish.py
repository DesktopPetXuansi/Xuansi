"""在隔离载荷中编译入口与缩放图标，不执行应用或安装包。"""

import json
import os
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from scripts import finish_store_payload as finishing

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "installer/store/StoreLauncher.cs"
COMPILER = Path(os.environ.get("WINDIR", "C:/Windows")) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"


@pytest.fixture
def payload(tmp_path):
    root = tmp_path / "商店载荷 with spaces"
    (root / "assets/xuansi").mkdir(parents=True)
    Image.new("RGBA", (256, 256), (20, 50, 80, 127)).save(root / "assets/xuansi/icon.png")
    (root / "store-payload.json").write_text(json.dumps({
        "schema_version": 1, "channel": "development-msix-payload",
        "redistribution_permissions_verified": False,
    }), encoding="utf-8")
    return root


def snapshot(root):
    return {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def test_real_compiler_creates_x64_entry_and_required_png_sizes(payload):
    if not COMPILER.is_file():
        pytest.skip("需要 Windows 自带的 C# 编译器")
    before = snapshot(payload)
    result = finishing.finish_payload(payload=payload, launcher_source=SOURCE, compiler=COMPILER)

    assert result == payload / "Xuansi.exe"
    assert result.read_bytes().startswith(b"MZ")
    for name, size in finishing.ICONS:
        with Image.open(payload / "assets/store" / name) as image:
            assert image.size == (size, size)
            assert image.format == "PNG"
            assert image.mode == "RGBA"
    assert all((payload / name).read_bytes() == data for name, data in before.items())
    assert not list(payload.glob(".xuansi-finish-*"))
    completed = snapshot(payload)
    with pytest.raises(FileExistsError):
        finishing.finish_payload(payload=payload, launcher_source=SOURCE, compiler=COMPILER)
    assert snapshot(payload) == completed


def test_compile_failure_preserves_original_payload(payload, monkeypatch, tmp_path):
    compiler = tmp_path / "compiler.exe"
    compiler.touch()
    before = snapshot(payload)
    monkeypatch.setattr(finishing.subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 7))

    with pytest.raises(RuntimeError, match="7"):
        finishing.finish_payload(payload=payload, launcher_source=SOURCE, compiler=compiler)

    assert snapshot(payload) == before
    assert not (payload / "assets/store").exists()
    assert not list(payload.glob(".xuansi-finish-*"))


def test_invalid_compiler_output_never_publishes_an_entry(payload, monkeypatch, tmp_path):
    compiler = tmp_path / "compiler.exe"
    compiler.touch()

    def invalid(command, **kwargs):
        target = next(argument[5:] for argument in command if argument.startswith("/out:"))
        Path(target).write_bytes(b"not an executable")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(finishing.subprocess, "run", invalid)
    with pytest.raises(ValueError):
        finishing.finish_payload(payload=payload, launcher_source=SOURCE, compiler=compiler)
    assert not (payload / "Xuansi.exe").exists()
    assert not (payload / "assets/store").exists()
    assert not list(payload.glob(".xuansi-finish-*"))


def test_existing_entry_and_icon_directory_are_preserved(payload, tmp_path):
    compiler = tmp_path / "compiler.exe"
    compiler.touch()
    entry = payload / "Xuansi.exe"
    entry.write_bytes(b"existing entry")
    with pytest.raises(FileExistsError):
        finishing.finish_payload(payload=payload, launcher_source=SOURCE, compiler=compiler)
    assert entry.read_bytes() == b"existing entry"
    entry.unlink()
    icons = payload / "assets/store"
    icons.mkdir()
    (icons / "unrelated.txt").write_bytes(b"keep")
    with pytest.raises(FileExistsError):
        finishing.finish_payload(payload=payload, launcher_source=SOURCE, compiler=compiler)
    assert (icons / "unrelated.txt").read_bytes() == b"keep"


@pytest.mark.parametrize("marker", ['{"channel":"production"}', "[]", "null"])
def test_requires_development_payload_marker(payload, tmp_path, marker):
    compiler = tmp_path / "compiler.exe"
    compiler.touch()
    (payload / "store-payload.json").write_text(marker, encoding="utf-8")
    before = snapshot(payload)
    with pytest.raises(ValueError):
        finishing.finish_payload(payload=payload, launcher_source=SOURCE, compiler=compiler)
    assert snapshot(payload) == before


def test_concurrent_entry_is_preserved_and_our_icons_are_rolled_back(payload, monkeypatch):
    if not COMPILER.is_file():
        pytest.skip("需要 Windows 自带的 C# 编译器")
    run = subprocess.run

    def competing(command, **kwargs):
        result = run(command, **kwargs)
        (payload / "Xuansi.exe").write_bytes(b"other complete entry")
        return result

    monkeypatch.setattr(finishing.subprocess, "run", competing)
    with pytest.raises(FileExistsError):
        finishing.finish_payload(payload=payload, launcher_source=SOURCE, compiler=COMPILER)
    assert (payload / "Xuansi.exe").read_bytes() == b"other complete entry"
    assert not (payload / "assets/store").exists()
    assert not list(payload.glob(".xuansi-finish-*"))


def test_partial_icon_publication_rolls_back_only_our_new_files(payload, monkeypatch):
    if not COMPILER.is_file():
        pytest.skip("需要 Windows 自带的 C# 编译器")
    before = snapshot(payload)
    link = os.link

    def fail_second(source, target):
        if Path(target).name == "Square44x44Logo.png":
            raise OSError("synthetic publication failure")
        return link(source, target)

    monkeypatch.setattr(finishing.os, "link", fail_second)
    with pytest.raises(OSError):
        finishing.finish_payload(payload=payload, launcher_source=SOURCE, compiler=COMPILER)
    assert snapshot(payload) == before
    assert not (payload / "assets/store").exists()
    assert not list(payload.glob(".xuansi-finish-*"))


def test_linked_icon_cannot_read_external_file(payload, tmp_path):
    icon = payload / "assets/xuansi/icon.png"
    icon.unlink()
    external = tmp_path / "external.png"
    Image.new("RGBA", (256, 256)).save(external)
    try:
        os.symlink(external, icon)
    except OSError:
        pytest.skip("当前用户不能创建符号链接")
    with pytest.raises(ValueError):
        finishing.finish_payload(payload=payload, launcher_source=SOURCE, compiler=COMPILER)
    assert icon.is_symlink()
    assert not (payload / "Xuansi.exe").exists()
