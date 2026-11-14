"""界面只应用当前轮的表情，普通回复不再一律显示高兴状态。"""

from types import SimpleNamespace

from pet.app import DesktopPet
from pet.config import Settings


def test_stale_expression_and_hidden_or_sleeping_desktop_are_ignored():
    applied = []
    pet = SimpleNamespace(
        runtime=SimpleNamespace(epoch=4), paused=False, fullscreen=False,
        avatar=SimpleNamespace(set_reply_expression=applied.append),
    )
    DesktopPet.on_reply_expression(pet, 3, "happy")
    pet.paused = True
    DesktopPet.on_reply_expression(pet, 4, "happy")
    pet.paused = False
    pet.fullscreen = True
    DesktopPet.on_reply_expression(pet, 4, "happy")
    assert applied == []
    pet.fullscreen = False
    DesktopPet.on_reply_expression(pet, 4, "concern")
    assert applied == ["concern"]


def test_plain_reply_keeps_original_text_and_neutral_animation():
    shown, animations = [], []
    avatar = SimpleNamespace(
        bubble=SimpleNamespace(present=lambda text, _avatar: shown.append(("bubble", text))),
        set_animation=animations.append,
    )
    pet = SimpleNamespace(
        runtime=SimpleNamespace(epoch=4), settings=Settings(), paused=False, fullscreen=False, avatar=avatar,
        panel=SimpleNamespace(append=lambda name, text: shown.append((name, text))),
    )
    DesktopPet.on_reply(pet, 4, "  原文。\n", "chat")
    assert shown == [("玄司", "  原文。\n"), ("bubble", "  原文。\n")]
    assert animations == ["idle"]
