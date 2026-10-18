"""显式应用必须真实加载；坏副本和试载失败均保留原形象。"""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PIL import Image
from PySide6.QtWidgets import QApplication

from pet.avatar import Avatar
from pet.avatar_live2d import LIVE2D_PARAMETERS
from pet.character_frames import build_frames


@pytest.fixture
def avatar(monkeypatch):
    application = QApplication.instance() or QApplication([])
    widget = Avatar(160)
    # 测试只验证候选提交边界，不创建原生 GL 上下文或初始化 Cubism。
    monkeypatch.setattr(widget, "makeCurrent", lambda: None)
    monkeypatch.setattr(widget, "doneCurrent", lambda: None)
    monkeypatch.setattr(widget, "_release_live2d", lambda: None)
    old = SimpleNamespace(DestroyRenderer=Mock())
    widget._live2d_model = old
    widget._platform_model_version = "old-version"
    widget._live2d_active = widget._live2d_ready = True
    yield widget
    widget._live2d_model = widget._live2d_module = None
    widget.clock.stop()
    widget.render_clock.stop()
    widget.deleteLater()
    application.processEvents()


@pytest.mark.parametrize("extension", [".png", ".apng"])
@pytest.mark.parametrize("payload", [None, b"broken image"])
def test_strict_missing_or_broken_copy_keeps_old_state(avatar, monkeypatch, tmp_path, extension, payload):
    path = tmp_path / ("a" * 64 + extension)
    if payload is not None:
        path.write_bytes(payload)
    monkeypatch.setattr("pet.character_frames.image_path", lambda _: path)
    monkeypatch.setattr("pet.native_animation.image_path", lambda _: path)
    before = (avatar.image_id, avatar.frames, avatar.durations, avatar._live2d_model)
    avatar._motion_name = "blink"
    with pytest.raises(ValueError, match="重新导入"):
        avatar.set_image(path.name, force=True, strict=True)
    assert (avatar.image_id, avatar.frames, avatar.durations, avatar._live2d_model) == before
    assert avatar._motion_name == "blink" and avatar._platform_model_version == "old-version"
    avatar._live2d_model.DestroyRenderer.assert_not_called()


def test_strict_valid_image_switches_without_default_fallback(avatar, monkeypatch, tmp_path):
    path = tmp_path / ("a" * 64 + ".png")
    Image.new("RGBA", (40, 60), "red").save(path)
    monkeypatch.setattr("pet.character_frames.image_path", lambda _: path)
    old_frames = avatar.frames
    avatar.set_image(path.name, force=True, strict=True)
    assert avatar.image_id == path.name and avatar.frames is not old_frames
    assert not avatar._live2d_requested and not avatar._platform_model_version


def test_strict_fully_transparent_image_preserves_old_avatar(avatar, monkeypatch, tmp_path):
    path = tmp_path / ("a" * 64 + ".png")
    Image.new("RGBA", (40, 60), (0, 0, 0, 0)).save(path)
    monkeypatch.setattr("pet.character_frames.image_path", lambda _: path)
    old = avatar._live2d_model
    with pytest.raises(ValueError, match="没有可见内容"):
        avatar.set_image(path.name, force=True, strict=True)
    assert avatar._live2d_model is old and avatar._platform_model_version == "old-version"


def test_legacy_bad_copy_still_uses_default(monkeypatch, tmp_path):
    monkeypatch.setattr("pet.character_frames.image_path", lambda _: tmp_path / "missing.png")
    frames, durations, native = build_frames(160, "a" * 64 + ".png")
    assert len(frames["idle"]) == len(durations) == 8 and not native


def install_sdk(monkeypatch, *, failure="", parameters=LIVE2D_PARAMETERS):
    import live2d.v3 as sdk

    candidate = Mock()
    candidate.GetParamIds.return_value = parameters
    if failure:
        getattr(candidate, failure).side_effect = ValueError("合成试载失败")
    monkeypatch.setattr(sdk, "LAppModel", lambda: candidate)
    monkeypatch.setattr("pet.avatar_live2d.SESSION.acquire", lambda *_: None)
    monkeypatch.setattr("pet.avatar_live2d.SESSION.release", lambda *_: None)
    return candidate


@pytest.mark.parametrize("failure", ["LoadModelJson", "Update", "Draw"])
def test_strict_default_trial_failure_never_replaces_old_model(avatar, monkeypatch, failure):
    candidate = install_sdk(monkeypatch, failure=failure)
    before = (avatar.image_id, avatar.frames, avatar._live2d_model, avatar._idle_blade_frames)
    with pytest.raises(ValueError, match="合成试载失败"):
        avatar.set_image("", force=True, strict=True)
    assert (avatar.image_id, avatar.frames, avatar._live2d_model, avatar._idle_blade_frames) == before
    assert avatar._platform_model_version == "old-version"
    avatar._live2d_model.DestroyRenderer.assert_not_called()
    candidate.DestroyRenderer.assert_called_once_with()


def test_strict_default_rejects_missing_character_bindings(avatar, monkeypatch):
    old = avatar._live2d_model
    candidate = install_sdk(monkeypatch, parameters=["ParamEyeLOpen"])
    with pytest.raises(ValueError, match="缺少绑定参数"):
        avatar.set_image("", force=True, strict=True)
    assert avatar._live2d_model is old and avatar._platform_model_version == "old-version"
    candidate.Draw.assert_not_called()


def test_strict_default_requires_ready_renderer_even_for_same_identifier(avatar):
    avatar._live2d_ready = False
    old = avatar._live2d_model
    with pytest.raises(ValueError, match="尚未就绪"):
        avatar.set_image("", strict=True)
    assert avatar._live2d_model is old and avatar._platform_model_version == "old-version"


def test_strict_default_restores_character_driver_motion_and_idle_cache(avatar, monkeypatch):
    old = avatar._live2d_model
    candidate = install_sdk(monkeypatch)
    avatar._idle_blade_frames = ()
    avatar.set_image("", force=True, strict=True)
    assert avatar._live2d_model is candidate and avatar._live2d_active
    assert not avatar._platform_model_version and not avatar._platform_parameters
    assert "blink" in avatar.available_motions and avatar.supports_idle_blade
    candidate.Draw.assert_called_once_with()
    old.DestroyRenderer.assert_called_once_with()
