"""形象导入使用临时图片，覆盖持久副本、透明度及异常输入。"""

from dataclasses import replace
from types import SimpleNamespace

import pytest
from PIL import Image, ImageDraw

from pet.appearance import image_path, import_image
from pet.companion_ui import CompanionUI
from pet.config import Settings, load_settings, save_settings


def test_shape_change_preserves_live_conversation_and_other_settings():
    from pet.app import DesktopPet

    old = replace(Settings(), name="我的伙伴", persona="保留我的人设", temperature=0.3)
    new = replace(old, avatar_image="a" * 64 + ".png")
    applied = []
    owner = SimpleNamespace(
        settings=old,
        panel=SimpleNamespace(settings=old, status=SimpleNamespace(setText=lambda _: None)),
        avatar=SimpleNamespace(set_image=lambda identifier, **_: applied.append(identifier)),
        ui=SimpleNamespace(refresh_icon=lambda: None),
        busy=True,
        runtime=SimpleNamespace(listening=True),
    )  # 没有关闭麦克风/取消推理接口；外观路径不应需要它们。
    DesktopPet.apply_settings(owner, new, "")
    assert owner.settings == new and applied == [new.avatar_image]
    assert owner.runtime.listening and owner.busy


@pytest.mark.parametrize("identifier", ["a" * 64 + ".png", "b" * 64 + ".png", ""])
def test_appearance_save_refreshes_even_same_image_without_resetting_voice(identifier):
    """从形象窗口完成保存；相同标识也刷新，不进入完整配置的停麦路径。"""
    from pet.app import DesktopPet

    old = replace(Settings(), avatar_image="a" * 64 + ".png", persona="保留我的人设")
    applied, icons, completed = [], [], []
    statuses = {"panel": "", "quick": ""}
    panel = SimpleNamespace(
        settings=old,
        saving=lambda _: None,
        status=SimpleNamespace(
            setText=lambda text: statuses.update(panel=text), text=lambda: statuses["panel"],
        ),
        audio_avoidance_action=SimpleNamespace(setEnabled=lambda _: None, setChecked=lambda _: None),
        form=SimpleNamespace(complete=lambda _: None),
    )
    owner = SimpleNamespace(
        settings=old, panel=panel, busy=True, voice_enabled=True, paused=False,
        runtime=SimpleNamespace(listening=True),
        avatar=SimpleNamespace(set_image=lambda image, **kwargs: applied.append((image, kwargs))),
    )  # 不提供关麦和取消接口；任何外观保存都不应调用它们。
    ui = SimpleNamespace(
        owner=owner, saving=True, closed=False, appearance_only=True, hotkey_staged=False,
        quick=SimpleNamespace(
            setWindowTitle=lambda _: None,
            status=SimpleNamespace(setText=lambda text: statuses.update(quick=text)),
        ),
        appearance=SimpleNamespace(saved=completed.append),
        refresh_icon=lambda: icons.append(owner.settings.avatar_image),
    )
    owner.ui = ui
    owner.apply_settings = lambda settings, error, **kwargs: DesktopPet.apply_settings(
        owner, settings, error, **kwargs
    )

    settings = replace(old, avatar_image=identifier)
    CompanionUI.saved(ui, settings, "")

    assert owner.settings == panel.settings == settings
    assert applied == [(identifier, {"force": True})] and icons == [identifier]
    assert completed == [""] and not ui.saving
    assert owner.runtime.listening and owner.busy and owner.voice_enabled
    assert statuses["panel"] == statuses["quick"] and "已应用" in statuses["quick"]


def test_import_keeps_alpha_and_survives_source_removal(tmp_path):
    source = tmp_path / "原图.png"
    image = Image.new("RGBA", (160, 240))
    ImageDraw.Draw(image).ellipse((20, 20, 140, 220), fill="#507b86")
    image.save(source)
    original = source.read_bytes()
    imported = import_image(source, tmp_path / "assets")
    assert source.read_bytes() == original
    source.unlink()
    saved = image_path(imported.identifier, tmp_path / "assets")
    with Image.open(saved) as result:
        assert result.mode == "RGBA"
        assert result.getchannel("A").getextrema() == (0, 255)
    path = tmp_path / "settings.json"
    save_settings(replace(Settings(), avatar_image=imported.identifier), path)
    assert load_settings(path).avatar_image == imported.identifier


def test_large_image_is_bounded_and_identical_import_deduplicates(tmp_path):
    source = tmp_path / "角色.jpg"
    Image.new("RGB", (2000, 3000), "#795945").save(source)
    asset = import_image(source, tmp_path / "assets")
    assert asset.height == 1536 and asset.width == 1024
    assert not asset.transparent
    assert import_image(source, tmp_path / "assets").identifier == asset.identifier
    assert len(list((tmp_path / "assets").iterdir())) == 1


@pytest.mark.parametrize("kind", ["broken", "empty", "oversized", "missing"])
def test_invalid_import_does_not_create_asset(tmp_path, kind):
    source = tmp_path / "input.png"
    if kind == "broken":
        source.write_bytes(b"not an image")
    elif kind == "empty":
        Image.new("RGBA", (30, 40)).save(source)
    elif kind == "oversized":
        Image.new("RGB", (5000, 4000)).save(source)
    with pytest.raises(ValueError):
        import_image(source, tmp_path / "assets")
    assert not (tmp_path / "assets").exists()


@pytest.mark.parametrize("identifier", ["../other.png", "C:/secret.png", "\\\\server\\share\\x.png"])
def test_settings_reject_non_managed_image_paths(identifier):
    with pytest.raises(ValueError):
        replace(Settings(), avatar_image=identifier).validate()
    with pytest.raises(ValueError):
        image_path(identifier)


def test_missing_old_field_uses_default(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text('{"name": "我的伙伴"}', encoding="utf-8")
    assert load_settings(path).avatar_image == ""
    assert load_settings(path).name == "我的伙伴"
