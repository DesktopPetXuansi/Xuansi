"""桌面不可用和全屏时都停止资源活动，不访问或激活真实窗口。"""

from types import SimpleNamespace

import pytest

from pet.app import DesktopPet
from pet.desktop import DesktopState


@pytest.mark.parametrize("state", [DesktopState(0, False, False), DesktopState(123, False, True)])
def test_unavailable_or_fullscreen_desktop_releases_model(monkeypatch, state):
    actions = []
    hidden = []
    monkeypatch.setattr("pet.app.desktop_state", lambda: state)
    monkeypatch.setattr("pet.app.psutil.virtual_memory", lambda: SimpleNamespace(available=8 * 2**30))
    label = SimpleNamespace(setText=lambda _: None)
    pet = SimpleNamespace(
        ui=SimpleNamespace(refresh=lambda: None),
        fullscreen=False,
        paused=False,
        busy=False,
        avatar=SimpleNamespace(
            hide=lambda: hidden.append("pet"), bubble=SimpleNamespace(hide=lambda: hidden.append("bubble"))
        ),
        voice=lambda enabled: actions.append(("voice", enabled)),
        runtime=SimpleNamespace(
            cancel=lambda release: actions.append(("release", release)),
            listening=False,
            engine=SimpleNamespace(loaded=None),
        ),
        panel=SimpleNamespace(status=label, footer=label),
    )
    DesktopPet._resources(pet)
    assert pet.fullscreen
    assert hidden == ["pet", "bubble"]
    assert actions == [("voice", False), ("release", True)]
