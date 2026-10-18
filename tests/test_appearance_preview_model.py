"""用真实 Qt 控件及假 SDK 验证预览状态，不创建原生 GL 或触及桌宠。"""

from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from pet.appearance_preview import AppearancePreview
from pet.avatar import Avatar


@pytest.fixture
def preview(monkeypatch):
    application = QApplication.instance() or QApplication([])
    widget = AppearancePreview(size=160)
    renderer = widget.renderer
    monkeypatch.setattr(renderer, "show", lambda: None)
    monkeypatch.setattr(renderer, "makeCurrent", lambda: None)
    monkeypatch.setattr(renderer, "doneCurrent", lambda: None)

    def release():
        renderer._live2d_model = renderer._live2d_module = None
        renderer._live2d_active = False

    monkeypatch.setattr(renderer, "_release_live2d", release)
    yield widget
    widget.stop()
    renderer.clock.stop()
    renderer.render_clock.stop()
    widget.deleteLater()
    application.processEvents()


def model():
    return {"kind": "MODEL", "resourceVersionId": "test-version"}, Path("synthetic.model3.json")


def fake_select(preview, monkeypatch, calls):
    def select(version, prepared):
        calls.append((version, prepared))
        preview.renderer._platform_model_version = version
        preview.renderer._live2d_model = object()
        preview.renderer._live2d_module = object()
        preview.renderer._live2d_active = True
    monkeypatch.setattr(preview.renderer, "select_platform_model", select)


def test_small_and_legacy_size_are_compatible(preview):
    assert preview.height() == 174 and preview.renderer.height() == 160
    legacy = AppearancePreview()
    assert legacy.height() == 238 and legacy.renderer.height() == 224
    legacy.stop()
    legacy.renderer.clock.stop()
    legacy.deleteLater()


def test_model_waits_for_gl_and_skips_default_load(preview, monkeypatch):
    results, calls, defaults = [], [], []
    preview.load_finished.connect(lambda *result: results.append(result))
    fake_select(preview, monkeypatch, calls)

    def initialize(renderer):
        renderer._live2d_ready = True
        if renderer._live2d_requested:
            defaults.append("default")

    monkeypatch.setattr(Avatar, "initializeGL", initialize)
    preview.set_model(model())
    assert not calls and not results
    preview.renderer.initializeGL()
    assert calls == [("test-version", model())] and not defaults
    assert results[-1][0] is True


def test_failed_custom_model_never_reports_png_success(preview, monkeypatch):
    results = []
    preview.load_finished.connect(lambda *result: results.append(result))
    preview.renderer._live2d_ready = True
    monkeypatch.setattr(preview, "isVisible", lambda: True)
    monkeypatch.setattr(preview.renderer, "select_platform_model",
                        lambda *args: (_ for _ in ()).throw(ValueError("synthetic")))
    preview.set_model(model())
    assert len(results) == 1 and results[0][0] is False
    assert "模型" in results[0][1]
    assert not preview.renderer._live2d_requested


def test_hidden_model_reloads_same_candidate(preview, monkeypatch):
    calls = []
    fake_select(preview, monkeypatch, calls)
    preview.renderer._live2d_ready = True
    monkeypatch.setattr(preview, "isVisible", lambda: True)
    preview.set_model(model())
    preview.stop()
    assert preview.renderer._live2d_model is None
    preview.start()
    assert calls == [("test-version", model()), ("test-version", model())]


def test_model_to_default_forces_clear_and_reload(preview, monkeypatch):
    calls, images = [], []
    fake_select(preview, monkeypatch, calls)
    preview.renderer._live2d_ready = True
    monkeypatch.setattr(preview, "isVisible", lambda: True)
    preview.set_model(model())

    def set_image(identifier, force=False):
        images.append((identifier, force))
        preview.renderer._platform_model_version = ""
        preview.renderer._live2d_model = object()
        preview.renderer._live2d_module = object()
        preview.renderer._live2d_requested = True
        preview.renderer._live2d_active = True

    monkeypatch.setattr(preview.renderer, "set_image", set_image)
    preview.set_image("")
    assert images == [("", True)] and preview.renderer._platform_model_version == ""
    preview.stop()
    monkeypatch.setattr(preview.renderer, "_ensure_live2d", lambda: calls.append("default"))
    preview.start()
    assert calls[-1] == "default"


def test_image_success_and_invalid_image_failure(preview, monkeypatch):
    results = []
    preview.load_finished.connect(lambda *result: results.append(result))
    monkeypatch.setattr("pet.appearance_preview.build_frames",
                        lambda *args, **kwargs: (preview.frames, preview.durations, False))
    preview.set_image("synthetic.png")
    assert results[-1][0] is True
    def broken(*args, **kwargs):
        raise ValueError('合成素材损坏')
    monkeypatch.setattr("pet.appearance_preview.build_frames", broken)
    preview.set_image("missing.png")
    assert results[-1][0] is False
    monkeypatch.setattr(preview.renderer, "resume", lambda: pytest.fail("坏图片不能加载默认模型冒充成功"))
    preview.start()


def test_old_motion_api_remains_forwarded(preview, monkeypatch):
    monkeypatch.setattr(preview.renderer, "play_motion", lambda motion: motion == "blink")
    assert isinstance(preview.available_motions, tuple)
    assert preview.play_motion("blink") is True and preview.play_motion("unknown") is False


def test_context_recreation_never_loads_default_for_custom_model(preview, monkeypatch):
    calls, defaults = [], []
    fake_select(preview, monkeypatch, calls)

    def initialize(renderer):
        renderer._live2d_ready = True
        if renderer._live2d_requested:
            defaults.append("default")

    monkeypatch.setattr(Avatar, "initializeGL", initialize)
    preview.set_model(model())
    preview.renderer.initializeGL()
    preview.renderer._live2d_requested = True
    preview.renderer._release_live2d()
    preview.renderer.initializeGL()
    assert len(calls) == 2 and not defaults


def test_image_then_model_keeps_renderer_and_parent(preview, monkeypatch):
    renderer = preview.renderer
    calls = []
    fake_select(preview, monkeypatch, calls)
    renderer._live2d_ready = True
    monkeypatch.setattr(preview, "isVisible", lambda: True)
    preview.set_model(model())
    monkeypatch.setattr("pet.appearance_preview.build_frames",
                        lambda *args, **kwargs: (preview.frames, preview.durations, False))
    preview.set_image("synthetic.png")
    assert not renderer._platform_model_version and renderer.prepared_model is None
    assert not renderer._live2d_requested and preview.timer.isActive()
    preview.set_model(model())
    assert preview.renderer is renderer and renderer.parent() is preview
    assert not preview.timer.isActive() and len(calls) == 2


def test_default_gl_failure_has_explicit_receipt_without_immediate_retry(preview, monkeypatch):
    results, attempts = [], []
    preview.load_finished.connect(lambda *result: results.append(result))

    def initialize(renderer):
        renderer._live2d_ready = True
        renderer._live2d_active = False
        attempts.append("default-failed")

    monkeypatch.setattr(Avatar, "initializeGL", initialize)
    monkeypatch.setattr(preview.renderer, "_ensure_live2d", lambda: pytest.fail("初始化失败不应立即重试"))
    preview.renderer.initializeGL()
    assert attempts == ["default-failed"]
    assert len(results) == 1 and results[0][0] is False and "默认形象" in results[0][1]
