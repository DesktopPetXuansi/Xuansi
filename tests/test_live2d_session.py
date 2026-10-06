"""用无 GPU 副作用的 SDK 替身验证多个窗口的资源生命周期。"""

from types import SimpleNamespace

from pet.live2d_session import Live2DSession


class Owner:
    def __init__(self, session):
        self.session = session
        self.released = False

    def context(self):
        return None

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
