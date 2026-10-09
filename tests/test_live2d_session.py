"""用无 GPU 副作用的 SDK 替身验证多个窗口的资源生命周期。"""

from types import SimpleNamespace

import pytest

from pet import live2d_session
from pet.live2d_session import Live2DSession


class Owner:
    def __init__(self, session, context=None):
        self.session = session
        self.released = False
        self.gl_context = context

    def context(self):
        return self.gl_context

    def _release_live2d(self):
        self.released = True
        self.session.release(self)


def sdk(events):
    return SimpleNamespace(
        enableLog=lambda enabled: events.append(("log", enabled)),
        init=lambda: events.append("init"),
        glInit=lambda: events.append("gl-init"),
        glRelease=lambda: events.append("gl-release"),
        dispose=lambda: events.append("dispose"),
    )


def test_closing_one_window_preserves_the_other_and_initializes_once():
    events = []
    session = Live2DSession()
    module = sdk(events)
    desktop, preview = Owner(session), Owner(session)
    session.acquire(desktop, module)
    session.acquire(preview, module)
    preview._release_live2d()
    assert events.count("init") == events.count("gl-init") == 1
    assert "gl-release" not in events and "dispose" not in events
    assert desktop in session.owners and not desktop.released


def test_reopening_the_only_preview_keeps_the_core_available():
    events = []
    session = Live2DSession()
    module = sdk(events)
    first = Owner(session)
    session.acquire(first, module)
    first._release_live2d()
    assert events.count("gl-release") == 1 and "dispose" not in events
    reopened = Owner(session)
    session.acquire(reopened, module)
    assert events.count("init") == 1 and reopened in session.owners
    first._release_live2d()
    assert events.count("gl-release") == 1  # 重复释放不能影响新窗口。


def test_shutdown_releases_every_model_before_disposing_the_core():
    events = []
    session = Live2DSession()
    module = sdk(events)
    owners = [Owner(session), Owner(session)]
    for owner in owners:
        session.acquire(owner, module)
    session.shutdown()
    assert all(owner.released for owner in owners) and not session.owners
    assert events[-2:] == ["gl-release", "dispose"]
    session.shutdown()
    assert events.count("dispose") == 1


@pytest.mark.parametrize("sharing", [True, False])
def test_second_context_must_share_without_disrupting_existing_model(monkeypatch, sharing):
    """独立窗口只可复用共享组，拒绝时不能初始化 SDK 或影响桌宠资源。"""
    monkeypatch.setattr(live2d_session, "QOpenGLContext", SimpleNamespace(areSharing=lambda *_: sharing))
    events = []
    session = Live2DSession()
    module = sdk(events)
    desktop, preview = Owner(session, object()), Owner(session, object())
    session.acquire(desktop, module)
    initial = list(events)

    if sharing:
        session.acquire(preview, module)
        assert preview in session.owners
    else:
        with pytest.raises(RuntimeError, match="未共享"):
            session.acquire(preview, module)
        assert preview not in session.owners

    assert events == initial and desktop in session.owners and not desktop.released
