"""商店载荷暂存仅使用隔离假目录，不运行解释器或复制本机数据。"""

import csv
import io
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from scripts import stage_store_payload as staging

ROOT = Path(__file__).resolve().parents[1]


def put(root, name, data=b"fixture"):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def distribution(root, name="example", version="1.2.3", extra=()):
    metadata = f"{name}-{version}.dist-info"
    files = [f"{name}/__init__.py", f"{name}/resource.txt", f"{metadata}/METADATA",
             f"{metadata}/WHEEL", f"{metadata}/licenses/LICENSE", *extra]
    for filename in files:
        if not filename.startswith("../"):
            put(root, filename)
    put(root, f"{metadata}/METADATA", f"Name: {name}\nVersion: {version}\n".encode())
    put(root, f"{metadata}/WHEEL", b"Wheel-Version: 1.0\nTag: py3-none-any\n")
    record = io.StringIO(newline="")
    csv.writer(record).writerows((name, "", "") for name in [*files, f"{metadata}/RECORD"])
    put(root, f"{metadata}/RECORD", record.getvalue().encode())
    return root / metadata


@pytest.fixture
def inputs(tmp_path):
    source, runtime, dependencies = (tmp_path / name for name in ("源码快照", "官方运行时", "依赖"))
    for name in ("pet/__init__.py", "pet/__main__.py", "pet/ai/catalog.json", "scripts/store_bootstrap.py",
                 "scripts/store_prepare.py",
                 "scripts/preflight.py", "scripts/download_assets.py", "scripts/download_realtime.py",
                 "VERSION", "LICENSE", "NOTICE", "assets-manifest.json", "assets/xuansi/LICENSE",
                 "assets/xuansi/front.png", "assets/xuansi/icon.png", "assets/xuansi/icon.ico",
                 "assets/xuansi/rigging/xuansi.model3.json", "assets/xuansi/rigging/xuansi.moc3",
                 "assets/xuansi/rigging/xuansi.1024/texture.png", "assets/ui/check.svg",
                 "assets/neko/LICENSE", "docs/context/THIRD_PARTY.md",
                 "docs/context/玄司素材说明.md"):
        put(source, name)
    put(source, "requirements.lock.txt", b"example==1.2.3\n")
    for name in ("python.exe", "pythonw.exe", "python3.dll", "python313.dll", "LICENSE.txt",
                 "vcruntime140.dll", "Lib/os.py", "DLLs/_socket.pyd"):
        put(runtime, name)
    distribution(dependencies, extra=("../../Scripts/example.exe",))
    return source, runtime, dependencies, tmp_path / "输出载荷"


def stage(inputs):
    return staging.stage_payload(source=inputs[0], python_runtime=inputs[1], dependencies=inputs[2], output=inputs[3])


def test_stage_keeps_runtime_assets_and_licenses_without_development_data(inputs):
    source, runtime, dependencies, output = inputs
    for root, names in ((source, ("data/settings.json", ".env", ".venv/pyvenv.cfg", "web/backend/main.go",
                                 "assets/xuansi/rigging/xuansi.cmo3", "assets/xuansi/rigging/layers/part.png",
                                 "assets/xuansi/rigging/layers.json", "assets/xuansi/rigging/draft.psd",
                                 "scripts/capture_private.py", "pet/__pycache__/app.pyc")),
                        (runtime, ("pyvenv.cfg", "Lib/site-packages/private.py", "Lib/test/private.pem")),
                        (dependencies, ("not_locked.py", "example/__pycache__/app.pyc"))):
        for name in names:
            put(root, name)
    stage(inputs)
    assert (output / "pet/__main__.py").read_bytes() == (source / "pet/__main__.py").read_bytes()
    for name in ("assets/xuansi/LICENSE", "assets/xuansi/rigging/xuansi.moc3", "assets/ui/check.svg",
                 "docs/context/THIRD_PARTY.md", "runtime/python/LICENSE.txt",
                 "runtime/python/Lib/site-packages/example-1.2.3.dist-info/licenses/LICENSE"):
        assert (output / name).is_file()
    forbidden = ("data", ".env", ".venv", "web", "runtime/python/pyvenv.cfg",
                 "runtime/python/Lib/site-packages/not_locked.py", "runtime/python/Lib/test",
                 "assets/xuansi/rigging/layers", "assets/xuansi/rigging/layers.json",
                 "assets/xuansi/rigging/draft.psd", "scripts/capture_private.py")
    assert not any((output / name).exists() for name in forbidden)
    configuration = (output / "runtime/python/python313._pth").read_text(encoding="utf-8")
    assert configuration.splitlines() == [".", "Lib", "DLLs", "Lib\\site-packages", "..\\..", "import site"]
    assert str(source) not in configuration
    record = (output / "runtime/python/Lib/site-packages/example-1.2.3.dist-info/RECORD").read_text(encoding="utf-8")
    assert "Scripts" not in record
    evidence = json.loads((output / "store-payload.json").read_text(encoding="utf-8"))
    assert evidence["channel"] == "development-msix-payload"
    assert evidence["dependencies"] == {"example": "1.2.3"}
    assert str(source) not in json.dumps(evidence)


@pytest.mark.parametrize("lock", [b"example>=1.2\n", b"example==9.9.9\n", b"missing==1.0\n"])
def test_dependency_lock_mismatch_fails_before_output_creation(inputs, lock):
    put(inputs[0], "requirements.lock.txt", lock)
    with pytest.raises(ValueError):
        stage(inputs)
    assert not inputs[3].exists()


@pytest.mark.parametrize("pth", [b"C:\\Users\\developer\\project\n", b"/private/developer\n",
                                 b"../outside\n", b"import private_loader\n"])
def test_unsafe_pth_is_rejected(inputs, pth):
    distribution(inputs[2], extra=("example.pth",))
    put(inputs[2], "example.pth", pth)
    with pytest.raises(ValueError):
        stage(inputs)
    assert not inputs[3].exists()


def test_relative_pth_inside_the_dependency_root_is_kept(inputs):
    distribution(inputs[2], extra=("example.pth",))
    put(inputs[2], "example.pth", b"example\n")
    stage(inputs)
    assert (inputs[3] / "runtime/python/Lib/site-packages/example.pth").read_bytes() == b"example\n"


def test_local_distribution_origin_is_rejected(inputs):
    distribution(inputs[2], extra=("example-1.2.3.dist-info/direct_url.json",))
    put(inputs[2], "example-1.2.3.dist-info/direct_url.json", b'{"url":"file:///C:/private/developer"}')
    with pytest.raises(ValueError):
        stage(inputs)
    assert not inputs[3].exists()


def test_external_record_file_is_rejected_without_reading_it(inputs):
    distribution(inputs[2], extra=("../private.pem",))
    with pytest.raises(ValueError):
        stage(inputs)
    assert not inputs[3].exists()


def test_existing_output_is_preserved(inputs):
    put(inputs[3], "keep.txt", b"keep")
    with pytest.raises(FileExistsError):
        stage(inputs)
    assert (inputs[3] / "keep.txt").read_bytes() == b"keep"


def test_output_inside_an_input_is_rejected(inputs):
    nested = (*inputs[:3], inputs[0] / "build/output")
    with pytest.raises(ValueError):
        stage(nested)
    assert not nested[3].exists()


def test_selected_source_link_cannot_copy_external_data(inputs, tmp_path):
    private = put(tmp_path, "private.py", b"private")
    try:
        os.symlink(private, inputs[0] / "pet/private.py")
    except OSError:
        pytest.skip("当前用户不能创建符号链接")
    with pytest.raises(ValueError):
        stage(inputs)
    assert not inputs[3].exists()


def test_failed_copy_removes_only_its_new_output(inputs, monkeypatch):
    sibling = put(inputs[3].parent, "unrelated.txt", b"keep")
    monkeypatch.setattr(staging.shutil, "copy2", lambda *_: (_ for _ in ()).throw(OSError("copy failed")))
    with pytest.raises(OSError):
        stage(inputs)
    assert not inputs[3].exists()
    assert sibling.read_bytes() == b"keep"


def test_private_key_material_in_dependency_data_is_rejected(inputs):
    distribution(inputs[2], extra=("example/private.pem",))
    put(inputs[2], "example/private.pem", b"-----BEGIN PRIVATE KEY-----\nfixture\n")
    with pytest.raises(ValueError):
        stage(inputs)
    assert not inputs[3].exists()


def test_linked_distribution_metadata_is_rejected_before_it_is_read(inputs, tmp_path):
    external = put(tmp_path, "metadata.txt", b"Name: example\nVersion: 1.2.3\n")
    original = inputs[2] / "example-1.2.3.dist-info/METADATA"
    original.unlink()
    try:
        os.symlink(external, original)
    except OSError:
        pytest.skip("当前用户不能创建符号链接")
    with pytest.raises(ValueError):
        stage(inputs)
    assert not inputs[3].exists()


def test_missing_bytecode_is_not_needed_for_the_payload(inputs):
    distribution(inputs[2], extra=("example/__pycache__/missing.pyc",))
    (inputs[2] / "example/__pycache__/missing.pyc").unlink()
    stage(inputs)
    assert not (inputs[3] / "runtime/python/Lib/site-packages/example/__pycache__").exists()


def test_missing_store_bootstrap_is_rejected_before_output_creation(inputs):
    (inputs[0] / "scripts/store_bootstrap.py").unlink()
    with pytest.raises(ValueError):
        stage(inputs)
    assert not inputs[3].exists()


def test_isolated_windows_python_finds_payload_root_from_another_working_directory(tmp_path):
    runtime = ROOT / "build/tools/python-3.13.15/tools"
    if not (runtime / "python.exe").is_file():
        pytest.skip("当前机器未提供锁定的 Windows Python 运行时")
    payload = tmp_path / "载荷 with spaces"
    python = payload / "runtime/python"
    python.mkdir(parents=True)
    for name in ("python.exe", "python3.dll", "python313.dll"):
        shutil.copy2(runtime / name, python / name)
    for library in runtime.glob("vcruntime*.dll"):
        shutil.copy2(library, python / library.name)
    shutil.copytree(runtime / "Lib", python / "Lib",
                    ignore=shutil.ignore_patterns("__pycache__", "site-packages", "test", "*.pyc"))
    (python / "python313._pth").write_text(staging.PYTHON_PATH, encoding="utf-8")
    put(payload, "pet/__init__.py", b"VALUE = 'payload'\n")
    result = subprocess.run([str(python / "python.exe"), "-B", "-c", "import pet; print(pet.VALUE)"],
                            cwd=tmp_path, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "payload"
    assert not (payload / "pet/__pycache__").exists()
