"""显式启用的原生 Qt/SDK 验收；普通 CI 不依赖桌面 GPU。"""

import hashlib
import json
import os
import time
import zipfile
from dataclasses import replace
from uuid import uuid4

import pytest

from pet.config import ROOT, Settings, load_settings, save_settings
from pet.platform_resources import SUFFIXES, install_package, read_installed


def test_resource_selection_persists_without_credentials(tmp_path):
    settings = replace(Settings(), platform_model_version=str(uuid4()),
                       platform_expression_version=str(uuid4()), platform_url="https://example.org")
    path = tmp_path / "settings.json"
    save_settings(settings, path)
    assert load_settings(path) == settings
    assert not {"access_token", "refresh_token"} & json.loads(path.read_text("utf-8")).keys()


@pytest.mark.skipif(os.environ.get("PET_PLATFORM_NATIVE") != "1", reason="需显式启用原生 GPU 桌面验收")
def test_native_model_motion_expression_and_offline_restore(tmp_path):
    """临时资源副本安装后加载原生模型、动作和表情，保存后可离线恢复。"""
    from PySide6.QtWidgets import QApplication, QWidget

    from pet.avatar import Avatar
    from pet.live2d_session import configure_opengl_sharing

    def install(files, entrypoint, kind, dependency=None):
        package = tmp_path / f"{uuid4()}.zip"
        with zipfile.ZipFile(package, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, data in files.items():
                archive.writestr(name, data)
        manifest = {"schemaVersion": 1, "resourceId": str(uuid4()), "resourceVersionId": str(uuid4()),
                    "kind": kind, "version": "1.0.0", "minimumClientVersion": "0.5.6",
                    "entrypoint": entrypoint, "dependencies": [dependency] if dependency else [],
                    "files": [{"path": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
                              for name, data in files.items()]}
        authorization = {"bytes": package.stat().st_size,
                         "sha256": hashlib.sha256(package.read_bytes()).hexdigest()}
        install_package(package, manifest, authorization, tmp_path / "resources")
        return manifest, read_installed(manifest["resourceVersionId"], tmp_path / "resources")

    source = ROOT / "assets/xuansi/rigging"
    files = {path.relative_to(source).as_posix(): path.read_bytes() for path in source.rglob("*")
             if path.is_file() and path.suffix.lower() in SUFFIXES}
    model, prepared = install(files, "xuansi.model3.json", "MODEL")
    dependency = {"resourceId": model["resourceId"], "resourceVersionId": model["resourceVersionId"],
                  "kind": "MODEL", "relation": "TARGET_MODEL"}
    motion_data = {"Version": 3, "Meta": {"Duration": 0.2, "Fps": 30, "Loop": False,
                    "AreBeziersRestricted": True, "CurveCount": 1, "TotalSegmentCount": 1, "TotalPointCount": 2,
                    "UserDataCount": 0, "TotalUserDataSize": 0},
                   "Curves": [{"Target": "Parameter", "Id": "ParamEyeLOpen", "Segments": [0, 1, 0, 0.2, 0]}]}
    motion, motion_prepared = install({"test.motion3.json": json.dumps(motion_data, indent=2).encode()},
                                      "test.motion3.json", "MOTION", dependency)
    expression_data = {"Type": "Live2D Expression", "Parameters": [
        {"Id": "ParamEyeLOpen", "Value": 0.3, "Blend": "Overwrite"}]}
    expression, expression_prepared = install({"test.exp3.json": json.dumps(expression_data).encode()},
                                              "test.exp3.json", "EXPRESSION", dependency)
    if QApplication.instance() is None:
        configure_opengl_sharing()
    application = QApplication.instance() or QApplication([])
    window = QWidget()
    avatar = Avatar(224, parent=window)
    window.resize(400, 400)
    window.show()
    def events(seconds=0.2):
        finish = time.monotonic() + seconds
        while time.monotonic() < finish:
            application.processEvents()
            time.sleep(0.01)
    try:
        events()
        assert avatar._live2d_active
        avatar.select_platform_model(model["resourceVersionId"], prepared)
        assert avatar._platform_model_version == model["resourceVersionId"]
        assert not avatar.supports_idle_blade
        avatar.apply_platform_action(motion["resourceVersionId"], motion_prepared)
        assert not avatar._live2d_model.IsMotionFinished()
        events()
        avatar.apply_platform_action(expression["resourceVersionId"], expression_prepared)
        events()
        assert avatar._platform_expression
        assert not avatar.grabFramebuffer().isNull()
        path = tmp_path / "settings.json"
        save_settings(replace(Settings(), platform_model_version=model["resourceVersionId"],
                              platform_expression_version=expression["resourceVersionId"]), path)
        settings = load_settings(path)
        avatar.select_platform_model(settings.platform_model_version,
                                     read_installed(settings.platform_model_version, tmp_path / "resources"))
        avatar.apply_platform_action(settings.platform_expression_version,
                                     read_installed(settings.platform_expression_version, tmp_path / "resources"))
        assert avatar._platform_expression
    finally:
        avatar.clock.stop()
        avatar.render_clock.stop()
        avatar._release_live2d()
        window.close()
        application.processEvents()
