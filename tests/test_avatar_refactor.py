"""核对拆分前后的动作时序、预览覆写与模型释放接口，不创建真实 GL 上下文。"""

from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication, QWidget

from pet.appearance_preview import PreviewAvatar
from pet.avatar import ARM_RAISE_BINDING_VERIFIED, Avatar
from pet.avatar_live2d import AvatarLive2D
from pet.live2d_session import Live2DSession


@pytest.mark.parametrize("elapsed, eye_open, finished", [
    (0.0, 1.0, False),
    (0.075, 0.0, False),
    (0.1, 0.0, False),
    (0.16, 0.5, False),
    (0.25, 1.0, True),
])
def test_blink_keeps_close_hold_open_and_finish_timing(elapsed, eye_open, finished):
    """固定时钟推进一次性眨眼，完成后恢复自动眨眼。"""
    auto_blink = []
    owner = SimpleNamespace(
        _motion_name="blink",
        _motion_started=10.0,
        _motion_request_id=None,
        animation="idle",
        _live2d_model=SimpleNamespace(SetAutoBlinkEnable=auto_blink.append),
    )

    values = Avatar._motion_parameter_values(owner, 10.0 + elapsed)

    assert values == {"ParamEyeLOpen": pytest.approx(eye_open), "ParamEyeROpen": pytest.approx(eye_open)}
    assert (owner._motion_name is None) is finished
    assert auto_blink == ([True] if finished else [])


def test_motion_completion_is_published_only_after_successful_draw():
    """时序结束先生成末帧参数，绘制完成后才发送工具完成回执。"""
    receipts = []
    owner = SimpleNamespace(_motion_name='blink', _motion_started=10.0,
                            _motion_request_id='request-1', _motion_completed_request=None,
                            animation='idle', _live2d_model=SimpleNamespace(SetAutoBlinkEnable=lambda _: None),
                            motion_finished=SimpleNamespace(emit=lambda *args: receipts.append(args)))
    Avatar._motion_parameter_values(owner, 10.25)
    assert receipts == []
    Avatar._publish_motion_completion(owner)
    Avatar._publish_motion_completion(owner)
    assert receipts == [('request-1', 'completed')]


def test_interrupted_motion_publishes_cancelled_receipt():
    receipts = []
    owner = SimpleNamespace(_motion_name='blink', _motion_started=10.0,
                            _motion_request_id='request-2', _motion_completed_request=None,
                            animation='idle', update=lambda: None,
                            _live2d_model=SimpleNamespace(SetAutoBlinkEnable=lambda _: None,
                                                         SetParameterValue=lambda *_: None),
                            motion_finished=SimpleNamespace(emit=lambda *args: receipts.append(args)))
    assert Avatar.cancel_motion(owner)
    assert receipts == [('request-2', 'cancelled')]


@pytest.mark.parametrize("stage", ["parameter", "update", "draw"])
@pytest.mark.parametrize("elapsed", [0.04, 0.25])
def test_render_failure_cannot_complete_motion_on_next_frame(monkeypatch, stage, elapsed):
    """中途或末帧失败后，恢复绘制不能拿旧标记冒充动作完成。"""
    receipts = []
    fail_once = True

    def render_step(current_stage):
        nonlocal fail_once
        if fail_once and stage == current_stage:
            fail_once = False
            raise RuntimeError("synthetic render failure")

    model = SimpleNamespace(
        SetAutoBlinkEnable=lambda _: None,
        SetParameterValue=lambda name, _: render_step("parameter") if name == "ParamEyeLOpen" else None,
        Update=lambda: render_step("update"), Draw=lambda: render_step("draw"),
    )
    owner = SimpleNamespace(
        _live2d_active=True, _live2d_model=model,
        _live2d_module=SimpleNamespace(clearBuffer=lambda *_: None),
        _last_render=10.0, _platform_model_version="", animation="idle",
        _gaze_x=0.0, _gaze_y=0.0, _mouth_level=0.0, _mouth_target=0.0,
        _motion_name="blink", _motion_started=10.0,
        _motion_request_id="request-failed", _motion_completed_request=None,
        _idle_blade_visual=lambda _: None, _update_gaze=lambda _: None,
        _update_sway=lambda _: None, _present_idle_blade=lambda _: None,
        motion_finished=SimpleNamespace(emit=lambda *args: receipts.append(args)),
    )
    owner._motion_parameter_values = lambda now: Avatar._motion_parameter_values(owner, now)
    owner._publish_motion_completion = lambda: Avatar._publish_motion_completion(owner)
    owner._report_motion_render_failure = lambda: Avatar._report_motion_render_failure(owner)
    monkeypatch.setattr("pet.avatar_live2d.time.monotonic", lambda: 10.0 + elapsed)

    with pytest.raises(RuntimeError, match="synthetic render failure"):
        AvatarLive2D.paintGL(owner)
    monkeypatch.setattr("pet.avatar_live2d.time.monotonic", lambda: 11.0)
    AvatarLive2D.paintGL(owner)

    assert receipts == [("request-failed", "unknown")]
    assert owner._motion_request_id is None and owner._motion_completed_request is None
    assert owner._motion_name is None


def test_arm_binding_stays_disabled_even_if_the_parameter_exists():
    """参数存在不等于经过绑定验收，不能扩大动作白名单。"""
    owner = SimpleNamespace(
        _live2d_active=True,
        _live2d_model=object(),
        _live2d_parameter_ids=frozenset({"ParamEyeLOpen", "ParamEyeROpen", "ParamArmRA"}),
    )

    assert ARM_RAISE_BINDING_VERIFIED is False
    assert Avatar.available_motions.fget(owner) == ("blink",)


@pytest.fixture
def preview(monkeypatch):
    """真实 Qt 构造但不显示窗口，仅验证 Python 覆写和点击蒙版。"""
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    application = QApplication.instance() or QApplication([])
    parent = QWidget()
    renderer = PreviewAvatar(parent)
    yield renderer
    renderer.clock.stop()
    renderer.render_clock.stop()
    parent.deleteLater()
    application.processEvents()


def test_preview_keeps_frame_mask_and_idle_blade_overrides(preview):
    """构造与 resize 仍调用预览覆写，矩形画布不裁切且不加载拔刀素材。"""
    preview.set_size(160)
    preview._frame_mask()

    assert preview.bubble is None
    assert not preview._idle_blade_frames and not preview.supports_idle_blade
    assert preview.mask().isEmpty()
    assert preview._live2d_window_mask().boundingRect() == preview.rect()


def test_preview_initialize_gl_keeps_super_and_mask_overrides(preview):
    """用假模型验证 initializeGL 的继承路径，不访问原生渲染器。"""
    capabilities = []
    preview.motion_capabilities_changed.connect(capabilities.append)
    preview._ensure_live2d = lambda: None
    preview._live2d_model = object()
    preview._live2d_parameter_ids = frozenset({"ParamEyeLOpen", "ParamEyeROpen"})

    preview.initializeGL()

    assert preview._live2d_ready and preview._live2d_active
    assert preview.mask() == preview._live2d_window_mask()
    assert capabilities[-1] == ("blink",)


def test_release_live2d_keeps_owner_interface_and_current_context(monkeypatch):
    """SESSION.shutdown 依赖的接口仍在当前上下文中释放模型并清空状态。"""
    calls = []
    owner = SimpleNamespace(
        _live2d_module=object(),
        _live2d_model=SimpleNamespace(DestroyRenderer=lambda: calls.append("destroy")),
        _live2d_active=True,
        _live2d_parameter_ids=frozenset({"ParamEyeLOpen"}),
        makeCurrent=lambda: calls.append("current"),
        doneCurrent=lambda: calls.append("done"),
        _refresh_motion_capabilities=lambda: calls.append("capabilities"),
    )
    monkeypatch.setattr("pet.avatar.SESSION.release", lambda released: calls.append(released))

    Avatar._release_live2d(owner)

    assert calls == ["current", "destroy", owner, "done", "capabilities"]
    assert owner._live2d_module is None and owner._live2d_model is None
    assert not owner._live2d_active and not owner._live2d_parameter_ids


def test_shutdown_calls_migrated_release_for_two_avatar_instances(monkeypatch, preview):
    """真实 Qt 对象与迁移后的释放方法共同参与退出；原生 SDK 使用替身。"""
    events = []
    session = Live2DSession()
    module = SimpleNamespace(
        enableLog=lambda _: None,
        init=lambda: events.append("init"),
        glInit=lambda: events.append("gl-init"),
        glRelease=lambda: events.append("gl-release"),
        dispose=lambda: events.append("dispose"),
    )
    second = PreviewAvatar(preview.parent())
    owners = (preview, second)
    # 动态替换实现模块的绑定；旧入口再导出只保证导入读取兼容。
    monkeypatch.setattr("pet.avatar_live2d.SESSION", session)
    for index, owner in enumerate(owners):
        owner.clock.stop()
        owner.render_clock.stop()
        monkeypatch.setattr(owner, "context", lambda: None)
        monkeypatch.setattr(owner, "makeCurrent", lambda i=index: events.append(("current", i)))
        monkeypatch.setattr(owner, "doneCurrent", lambda i=index: events.append(("done", i)))
        owner._live2d_module = module
        owner._live2d_model = SimpleNamespace(DestroyRenderer=lambda i=index: events.append(("destroy", i)))
        session.acquire(owner, module)

    session.shutdown()

    assert session.disposed and not session.owners
    assert all(owner._live2d_model is None and owner._live2d_module is None for owner in owners)
    for index in range(2):
        assert events.index(("current", index)) < events.index(("destroy", index))
        assert events.index(("destroy", index)) < events.index("gl-release")
        assert events.index(("destroy", index)) < events.index(("done", index))
    assert events.index("gl-release") < events.index("dispose")
    session.shutdown()
    assert events.count("dispose") == 1
