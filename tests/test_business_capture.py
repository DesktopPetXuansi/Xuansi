"""截图验收必须识别隐藏预览的 PNG 回退和证据保存失败。"""

from types import SimpleNamespace

import pytest

from scripts import verify_business_integration as verification


def fixture_pet(monkeypatch):
    """只替换窗口和 GPU 边界，仍调用实际截图验收逻辑。"""
    image = SimpleNamespace(
        isNull=lambda: False, save=lambda _: True, width=lambda: 10, height=lambda: 10,
        pixelColor=lambda *_: SimpleNamespace(alpha=lambda: 255),
    )
    desktop = SimpleNamespace(
        _live2d_active=True, _live2d_failed=False, _live2d_model=object(), context=lambda: "desktop",
        grabFramebuffer=lambda: image,
    )
    preview = SimpleNamespace(
        _live2d_active=True, _live2d_failed=False, _live2d_model=object(), context=lambda: "preview",
    )
    panel = SimpleNamespace(
        grab=lambda: image,
        sections={key: SimpleNamespace(expanded=False) for key in ("chat", "appearance")},
        opened=[],
    )

    def open_section(key):
        # 模拟同页展开，不再为截图创建第二个控制窗口。
        panel.sections[key].expanded = True
        panel.opened.append(key)

    panel.open_section = open_section
    pet = SimpleNamespace(
        avatar=desktop, panel=panel,
        ui=SimpleNamespace(appearance=SimpleNamespace(
            preview=SimpleNamespace(renderer=preview), window=lambda: panel,
        )),
    )
    monkeypatch.setattr(verification, "QOpenGLContext", SimpleNamespace(areSharing=lambda *_: True), raising=False)
    return pet, image


def test_valid_window_captures_record_rendering_checks(monkeypatch, tmp_path):
    pet, _ = fixture_pet(monkeypatch)
    report = {"passed": False}

    verification.verify_window_captures(pet, tmp_path / "business-report.json", report)

    assert pet.panel.opened == ["chat", "appearance"]
    assert all(section.expanded for section in pet.panel.sections.values())
    assert report["window_captures_saved"]
    assert report["capture_keeps_both_live2d_models"]
    assert report["capture_contexts_share_resources"]
    assert report["capture_desktop_frame_contains_character"]
    assert not report["passed"]  # 截图成功仍不能提前跳过退出验收。


@pytest.mark.parametrize("name", ["avatar", "preview"])
def test_capture_rejects_png_fallback(monkeypatch, tmp_path, name):
    pet, _ = fixture_pet(monkeypatch)
    renderer = pet.avatar if name == "avatar" else pet.ui.appearance.preview.renderer
    renderer._live2d_failed = True
    renderer._live2d_active = False
    renderer._live2d_model = None
    report = {"passed": False}

    with pytest.raises(AssertionError, match="Live2D"):
        verification.verify_window_captures(pet, tmp_path / "business-report.json", report)

    assert not report["passed"]


@pytest.mark.parametrize("failure", ["empty", "save", "unshared", "blank_frame", "separate_window"])
def test_capture_rejects_missing_evidence_or_unshared_context(monkeypatch, tmp_path, failure):
    pet, image = fixture_pet(monkeypatch)
    if failure == "empty":
        image.isNull = lambda: True
    elif failure == "save":
        image.save = lambda _: False
    elif failure == "unshared":
        monkeypatch.setattr(verification, "QOpenGLContext", SimpleNamespace(areSharing=lambda *_: False))
    elif failure == "separate_window":
        pet.ui.appearance.window = lambda: object()
    else:
        image.pixelColor = lambda *_: SimpleNamespace(alpha=lambda: 0)
    report = {"passed": False}

    with pytest.raises(AssertionError):
        verification.verify_window_captures(pet, tmp_path / "business-report.json", report)

    assert not report["passed"]


@pytest.mark.parametrize("failure", ["wait", "thread", None])
def test_background_shutdown_failure_still_releases_live2d(monkeypatch, failure):
    """后台超时或线程未退出都要继续释放原生资源，并保留失败状态。"""
    pet, _ = fixture_pet(monkeypatch)
    renderers = (pet.avatar, pet.ui.appearance.preview.renderer)
    for view in renderers:
        view._live2d_module = object()
    session = SimpleNamespace(disposed=False, owners={1, 2})

    def shutdown():
        session.disposed = True
        session.owners.clear()
        for view in renderers:
            view._live2d_model = view._live2d_module = None

    def wait(*_):
        if failure == "wait":
            raise AssertionError("后台清理超时")

    session.shutdown = shutdown
    monkeypatch.setattr(verification, "SESSION", session)
    monkeypatch.setattr(verification, "wait_until", wait)
    pet.quit = lambda: None
    pet.runtime = SimpleNamespace(
        loop=SimpleNamespace(call_soon_threadsafe=lambda _: None, stop=lambda: None),
        thread=SimpleNamespace(join=lambda _: None, is_alive=lambda: failure == "thread"),
    )
    closed = SimpleNamespace(is_set=lambda: True)
    report = {"passed": False}

    if failure:
        with pytest.raises(AssertionError, match="后台清理超时|线程仍存活"):
            verification.release_verification_resources(pet, closed, report)
    else:
        verification.release_verification_resources(pet, closed, report)

    assert session.disposed and not session.owners
    assert all(view._live2d_model is None and view._live2d_module is None for view in renderers)
    assert report["shutdown_releases_live2d_session"] and not report["passed"]
