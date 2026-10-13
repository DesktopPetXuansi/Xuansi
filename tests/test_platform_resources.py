"""平台包、授权与外部动作的安全回归。"""

import hashlib
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from pet.platform_auth import callback_code, pkce_pair, website_url
from pet.platform_resources import install_package, read_installed, relative_path, validate_manifest


def fixture_package(tmp_path, files=None, kind="MODEL", dependencies=None):
    files = files or {"pet.model3.json": json.dumps({"FileReferences": {
        "Moc": "pet.moc3", "Textures": ["texture.png"]}}).encode(),
        "pet.moc3": b"model", "texture.png": b"texture"}
    manifest = {"schemaVersion": 1, "resourceId": str(uuid4()), "resourceVersionId": str(uuid4()),
                "kind": kind, "version": "1.0", "minimumClientVersion": "0.5.6",
                "entrypoint": next(iter(files)), "dependencies": dependencies or [],
                "files": [{"path": path, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
                          for path, data in files.items()]}
    package = tmp_path / "package.zip"
    with zipfile.ZipFile(package, "w") as archive:
        for path, data in files.items():
            archive.writestr(path, data)
    authorization = {"bytes": package.stat().st_size,
                     "sha256": hashlib.sha256(package.read_bytes()).hexdigest()}
    return package, manifest, authorization


def test_pkce_and_state():
    verifier, challenge = pkce_pair()
    assert 43 <= len(verifier) <= 128 and len(challenge) == 43
    assert callback_code("/oauth/callback?state=ok&code=abc", "ok") == "abc"
    with pytest.raises(ValueError):
        callback_code("/oauth/callback?state=wrong&code=abc", "ok")
    with pytest.raises(ValueError):
        callback_code("/oauth/callback?state=ok&state=ok&code=abc", "ok")


@pytest.mark.parametrize("url", ["http://example.com", "https://user:pass@example.com", "file:///tmp", "https://example.com/a"])
def test_unsafe_website(url):
    with pytest.raises(ValueError):
        website_url(url)


@pytest.mark.parametrize("path", ["../a.json", "/a.json", "C:/a.json", "a\\b.json", "nul.json", "a.exe", "a/./b.json"])
def test_unsafe_path(path):
    with pytest.raises(ValueError):
        relative_path(path)


def test_atomic_install_and_offline_integrity(tmp_path):
    package, manifest, authorization = fixture_package(tmp_path)
    root = tmp_path / "installed"
    installed = install_package(package, manifest, authorization, root)
    assert read_installed(manifest["resourceVersionId"], root)[1].is_file()
    newer = dict(manifest, resourceVersionId=str(uuid4()))
    package.write_bytes(b"broken")
    with pytest.raises(ValueError):
        install_package(package, newer, authorization, root)
    assert installed.is_dir() and not (root / newer["resourceVersionId"]).exists()
    (installed / "pet.moc3").write_bytes(b"tampered")
    with pytest.raises(ValueError):
        read_installed(manifest["resourceVersionId"], root)


def test_missing_model_reference(tmp_path):
    package, manifest, authorization = fixture_package(tmp_path, {
        "pet.model3.json": b'{"FileReferences":{"Moc":"missing.moc3","Textures":["missing.png"]}}'})
    with pytest.raises(ValueError, match="引用文件缺失"):
        install_package(package, manifest, authorization, tmp_path / "installed")


def test_model_package_keeps_readme_and_license_attachments(tmp_path):
    """后端允许的说明与许可附件可通过清单校验并完整安装到离线模型目录。"""
    files = {"pet.model3.json": b'{"FileReferences":{"Moc":"pet.moc3","Textures":["texture.png"]}}',
             "pet.moc3": b"model", "texture.png": b"texture",
             "README.txt": "模型使用说明，不执行任何脚本。".encode("utf-8"),
             "legal/license.txt": "版权与使用许可。".encode("utf-8")}
    package, manifest, authorization = fixture_package(tmp_path, files)
    assert validate_manifest(manifest) == manifest
    root = tmp_path / "installed"
    installed = install_package(package, manifest, authorization, root)
    loaded, entry = read_installed(manifest["resourceVersionId"], root)
    assert entry.is_file() and loaded == manifest
    for attachment in ("README.txt", "legal/license.txt"):
        assert (installed / attachment).read_bytes() == files[attachment]


def test_unspecified_minimum_version_can_be_installed(tmp_path):
    """官网未声明最低版本时仍允许安全安装，由实际试载决定运行兼容性。"""
    package, manifest, authorization = fixture_package(tmp_path)
    manifest["minimumClientVersion"] = ""
    root = tmp_path / "installed"
    install_package(package, manifest, authorization, root)
    assert read_installed(manifest["resourceVersionId"], root)[0]["minimumClientVersion"] == ""


def test_empty_optional_model_references_are_installable(tmp_path):
    """与Go结构校验一致：未启用的Physics/Pose/Sound不指向文件。"""
    contract = Path(__file__).resolve().parents[1] / "web/contracts/fixtures/model-references.json"
    entry = json.loads(contract.read_text("utf-8"))
    package, manifest, authorization = fixture_package(tmp_path, {
        "pet.model3.json": json.dumps(entry).encode(), "pet.moc3": b"model", "texture.png": b"texture",
        "idle.motion3.json": b'{"Version":3,"Meta":{"Duration":1},"Curves":[]}'})
    install_package(package, manifest, authorization, tmp_path / "installed")
    assert read_installed(manifest["resourceVersionId"], tmp_path / "installed")[1].is_file()


@pytest.mark.parametrize("references", [{"Moc": "", "Textures": ["texture.png"]},
                                      {"Moc": "pet.moc3", "Textures": [""]}])
def test_empty_required_model_reference_is_rejected(tmp_path, references):
    package, manifest, authorization = fixture_package(tmp_path, {
        "pet.model3.json": json.dumps({"FileReferences": references}).encode(),
        "pet.moc3": b"model", "texture.png": b"texture"})
    with pytest.raises(ValueError):
        install_package(package, manifest, authorization, tmp_path / "installed")


@pytest.mark.parametrize("minimum", ["latest", "0.5", "999.0.0"])
def test_invalid_or_newer_minimum_version_is_rejected(tmp_path, minimum):
    _, manifest, _ = fixture_package(tmp_path)
    manifest["minimumClientVersion"] = minimum
    with pytest.raises(ValueError):
        validate_manifest(manifest)


@pytest.mark.parametrize("suffix", [".json", ".moc3", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".wav", ".mp3", ".txt"])
def test_backend_allowed_attachment_suffixes(suffix):
    assert relative_path("attachment" + suffix) == "attachment" + suffix


def test_ogg_attachment_is_not_part_of_backend_contract():
    with pytest.raises(ValueError):
        relative_path("attachment.ogg")


def test_unlisted_zip_file_rejected(tmp_path):
    package, manifest, authorization = fixture_package(tmp_path)
    with zipfile.ZipFile(package, "a") as archive:
        archive.writestr("../outside.json", b"{}")
    authorization.update(bytes=package.stat().st_size, sha256=hashlib.sha256(package.read_bytes()).hexdigest())
    with pytest.raises(ValueError):
        install_package(package, manifest, authorization, tmp_path / "installed")


def test_extra_motion_and_expression_use_sdk(tmp_path, monkeypatch):
    from pet.avatar_live2d import AvatarLive2D
    calls = []
    target = str(uuid4())
    manifest = {"kind": "MOTION", "resourceVersionId": str(uuid4()),
                "dependencies": [{"resourceVersionId": target}]}
    monkeypatch.setattr("pet.platform_resources.read_installed", lambda _: (manifest, tmp_path / "extra.motion3.json"))
    model = SimpleNamespace(LoadExtraMotion=lambda group, path: calls.append((group, path)) or 2,
                            StartMotion=lambda *args: calls.append(args),
                            IsMotionFinished=lambda: False,
                            GetExpressionIds=lambda: [manifest["resourceVersionId"]],
                            LoadExtraExpression=lambda *args: calls.append(args),
                            SetExpression=lambda *args: calls.append(args))
    avatar = SimpleNamespace(_platform_model_version=target, _live2d_model=model,
                             _live2d_active=True, makeCurrent=lambda: None, doneCurrent=lambda: None,
                             cancel_motion=lambda: None, update=lambda: None, _platform_expression=False)
    AvatarLive2D.apply_platform_action(avatar, manifest["resourceVersionId"])
    assert calls[-1] == ("platform", 2, 3)
    manifest["kind"] = "EXPRESSION"
    AvatarLive2D.apply_platform_action(avatar, manifest["resourceVersionId"])
    assert calls[-1] == (manifest["resourceVersionId"],)
    manifest["dependencies"][0]["resourceVersionId"] = str(uuid4())
    with pytest.raises(ValueError):
        AvatarLive2D.apply_platform_action(avatar, manifest["resourceVersionId"])
