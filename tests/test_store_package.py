"""只构建和解包临时测试容器，不安装或执行包内程序。"""

import os
import struct
import subprocess
import zlib
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from scripts import build_store_package as builder

ROOT = Path(__file__).resolve().parents[1]
SDK = ROOT / "build/tools/windows-sdk-10.0.28000.2705/bin/10.0.28000.0/x64/makeappx.exe"


def png(size):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    pixels = b"\0" + bytes((20, 40, 60, 255)) * size
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">2I5B", size, size, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(pixels * size)) + chunk(b"IEND", b""))


@pytest.fixture
def payload(tmp_path):
    directory = tmp_path / "载荷 with spaces"
    (directory / "app").mkdir(parents=True)
    (directory / "app/entry.exe").write_bytes(b"test payload, never executed")
    (directory / "app/resources.txt").write_text("resource", encoding="utf-8")
    (directory / "images").mkdir()
    for name, size in (("store.png", 50), ("small.png", 44), ("large.png", 150)):
        (directory / "images" / name).write_bytes(png(size))
    return directory


def arguments(payload, tmp_path):
    # 无 SDK 的机器仍能运行输入验证和失败处理测试；真实打包测试另行指定工具。
    fake_makeappx = tmp_path / "makeappx.exe"
    fake_makeappx.touch(exist_ok=True)
    return dict(payload=payload, output=tmp_path / "output/test.msix", makeappx=fake_makeappx,
                identity="LocalDevelopment.XuansiTest", publisher="CN=LocalDevelopment",
                publisher_display_name="本地容器测试", version="1.0.0.0", executable="app/entry.exe",
                display_name="玄司测试容器", store_logo="images/store.png",
                small_logo="images/small.png", large_logo="images/large.png")


def test_real_makeappx_roundtrip_preserves_payload_and_manifest(payload, tmp_path):
    if not SDK.is_file():
        pytest.skip("此机器尚未提供 Windows SDK MakeAppx")
    values = arguments(payload, tmp_path)
    values["makeappx"] = SDK
    before = {path.relative_to(payload): path.read_bytes() for path in payload.rglob("*") if path.is_file()}
    builder.build_package(**values)
    extracted = tmp_path / "extracted"
    result = subprocess.run([str(SDK), "unpack", "/p", str(values["output"]), "/d", str(extracted), "/no"],
                            capture_output=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    namespaces = {"p": builder.NS, "uap": builder.UAP, "rescap": builder.RESCAP}
    manifest = ET.parse(extracted / "AppxManifest.xml")
    identity = manifest.find("p:Identity", namespaces)
    assert identity.attrib == {"Name": values["identity"], "Publisher": values["publisher"],
                               "Version": "1.0.0.0", "ProcessorArchitecture": "x64"}
    application = manifest.find("p:Applications/p:Application", namespaces)
    assert application.attrib["Executable"] == "app\\entry.exe"
    assert application.attrib["EntryPoint"] == "Windows.FullTrustApplication"
    assert manifest.find("p:Capabilities/rescap:Capability", namespaces).attrib["Name"] == "runFullTrust"
    assert manifest.find("p:Dependencies/p:TargetDeviceFamily", namespaces).attrib["MinVersion"] == "10.0.17763.0"
    assert {path.relative_to(payload): path.read_bytes() for path in payload.rglob("*") if path.is_file()} == before
    assert all((extracted / name).read_bytes() == data for name, data in before.items())
    assert not (extracted / "AppxSignature.p7x").exists()


@pytest.mark.parametrize("field,value", [
    ("identity", 'Test\"/><Injected/>'), ("version", "1.0.0.1"), ("version", "0.9.0.0"),
    ("version", "1.65536.0.0"), ("publisher", ""), ("publisher_display_name", ""),
    ("executable", "../entry.exe"), ("executable", "C:/entry.exe"),
    ("executable", "app/missing.exe"), ("small_logo", "images/missing.png"),
])
def test_invalid_inputs_fail_before_output_creation(payload, tmp_path, field, value):
    values = arguments(payload, tmp_path)
    values[field] = value
    with pytest.raises((ValueError, FileNotFoundError)):
        builder.build_package(**values)
    assert not values["output"].parent.exists()


def test_missing_makeappx_fails_before_output_creation(payload, tmp_path):
    values = arguments(payload, tmp_path)
    values["makeappx"] = tmp_path / "missing-makeappx.exe"
    with pytest.raises(FileNotFoundError):
        builder.build_package(**values)
    assert not values["output"].parent.exists()


@pytest.mark.parametrize("inside", [False, True])
def test_output_never_overwrites_or_enters_payload(payload, tmp_path, inside):
    values = arguments(payload, tmp_path)
    values["output"] = payload / "new.msix" if inside else tmp_path / "existing.msix"
    if not inside:
        values["output"].write_bytes(b"keep existing artifact")
    with pytest.raises((ValueError, FileExistsError)):
        builder.build_package(**values)
    if not inside:
        assert values["output"].read_bytes() == b"keep existing artifact"


@pytest.mark.parametrize("name", ["data/settings.json", ".env.production", "AppxManifest.xml"])
def test_unprepared_or_secret_payload_is_rejected(payload, tmp_path, name):
    path = payload / name
    path.parent.mkdir(exist_ok=True)
    path.write_text("do not package", encoding="utf-8")
    with pytest.raises(ValueError):
        builder.build_package(**arguments(payload, tmp_path))
    assert not (tmp_path / "output").exists()


def test_payload_link_cannot_import_external_data(payload, tmp_path):
    external = tmp_path / "private.txt"
    external.write_text("private", encoding="utf-8")
    try:
        os.symlink(external, payload / "external.txt")
    except OSError:
        pytest.skip("当前用户不能创建符号链接")
    with pytest.raises(ValueError):
        builder.build_package(**arguments(payload, tmp_path))


def test_broken_output_link_is_preserved(payload, tmp_path):
    values = arguments(payload, tmp_path)
    target = tmp_path / "missing.msix"
    values["output"].parent.mkdir()
    try:
        os.symlink(target, values["output"])
    except OSError:
        pytest.skip("当前用户不能创建符号链接")
    with pytest.raises(FileExistsError):
        builder.build_package(**values)
    assert values["output"].is_symlink()
    assert not target.exists()


def test_display_values_are_serialized_as_xml_text():
    manifest = builder._manifest("LocalDevelopment.Test", "CN=Name & Company", "Publisher <name>",
                                 "1.0.0.0", "app.exe", "Title </DisplayName><Injected/>",
                                 "store.png", "small.png", "large.png")
    parsed = ET.fromstring(ET.tostring(manifest.getroot()))
    assert parsed.find(f"{{{builder.NS}}}Identity").attrib["Publisher"] == "CN=Name & Company"
    assert parsed.find(f"{{{builder.NS}}}Properties/{{{builder.NS}}}DisplayName").text == "Title </DisplayName><Injected/>"
    assert not any(element.tag.endswith("Injected") for element in parsed.iter())


def test_failed_makeappx_leaves_no_published_artifact(payload, tmp_path, monkeypatch):
    def fail(*args, **kwargs):
        command = args[0]
        Path(command[command.index("/p") + 1]).write_bytes(b"partial package")
        return subprocess.CompletedProcess(args[0], 17, stdout=b"failed", stderr=b"")

    monkeypatch.setattr(builder.subprocess, "run", fail)
    values = arguments(payload, tmp_path)
    with pytest.raises(RuntimeError, match="17"):
        builder.build_package(**values)
    assert not values["output"].exists()
    assert not list(values["output"].parent.iterdir())


def test_output_race_preserves_the_other_artifact(payload, tmp_path, monkeypatch):
    values = arguments(payload, tmp_path)

    def concurrent_output(command, **kwargs):
        Path(command[command.index("/p") + 1]).write_bytes(b"our complete package")
        values["output"].write_bytes(b"other complete package")
        return subprocess.CompletedProcess(command, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(builder.subprocess, "run", concurrent_output)
    with pytest.raises(FileExistsError):
        builder.build_package(**values)
    assert values["output"].read_bytes() == b"other complete package"
    assert list(values["output"].parent.iterdir()) == [values["output"]]


@pytest.mark.skipif(os.name != "nt", reason="Windows 才使用不覆盖目标的重命名")
def test_windows_publishes_complete_package_without_creating_a_second_link(payload, tmp_path, monkeypatch):
    values = arguments(payload, tmp_path)

    def make_package(command, **kwargs):
        Path(command[command.index("/p") + 1]).write_bytes(b"complete package")
        return subprocess.CompletedProcess(command, 0, stdout=b"", stderr=b"")

    def reject_link(*args, **kwargs):
        raise AssertionError("Windows 发布不应创建大型文件硬链接")

    monkeypatch.setattr(builder.subprocess, "run", make_package)
    monkeypatch.setattr(builder.os, "link", reject_link)
    builder.build_package(**values)

    assert values["output"].read_bytes() == b"complete package"
    assert list(values["output"].parent.iterdir()) == [values["output"]]


def test_source_output_is_rejected_outside_build_directories(payload, tmp_path, monkeypatch):
    checkout = tmp_path / "checkout"
    monkeypatch.setattr(builder, "ROOT", checkout)
    values = arguments(payload, tmp_path)
    values["output"] = checkout / "pet/artifact.msix"
    with pytest.raises(ValueError):
        builder.build_package(**values)
    assert not checkout.exists()
