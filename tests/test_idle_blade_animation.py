"""拔刀姿态播放器的时序与透明素材缓存。"""

from pet.idle_blade_animation import (
    IDLE_BLADE_FADE_SECONDS,
    IDLE_BLADE_FRAME_DURATIONS,
    IDLE_BLADE_SEQUENCE,
    IDLE_BLADE_TOTAL_SECONDS,
    idle_blade_opacity,
    idle_blade_pose,
)


def test_pose_sequence_draws_and_returns_the_blade_in_order():
    """关键帧从伸手、握柄、半拔、展示，再反序回到中立。"""
    elapsed = 0.0
    poses = []
    for duration in IDLE_BLADE_FRAME_DURATIONS:
        poses.append(idle_blade_pose(elapsed))
        elapsed += duration

    assert poses == list(IDLE_BLADE_SEQUENCE)
    assert IDLE_BLADE_SEQUENCE == (0, 1, 2, 3, 3, 2, 1, 0)
    assert idle_blade_pose(IDLE_BLADE_TOTAL_SECONDS) is None


def test_pose_sequence_ignores_negative_elapsed_time():
    """时钟边界前不泄露动作姿态。"""
    assert idle_blade_pose(-0.01) is None


def test_pose_fades_over_the_live2d_model_at_both_ends():
    """动作使用短淡入淡出，避免突然盖住或切回 Live2D。"""
    assert idle_blade_opacity(0) == 0
    assert idle_blade_opacity(IDLE_BLADE_FADE_SECONDS) == 1
    assert idle_blade_opacity(IDLE_BLADE_TOTAL_SECONDS - IDLE_BLADE_FADE_SECONDS) == 1
    assert idle_blade_opacity(IDLE_BLADE_TOTAL_SECONDS) == 0


def test_overlay_opacity_is_clamped_outside_the_action():
    """超出动作区间不绘制姿态图层。"""
    assert idle_blade_opacity(-1) == 0
    assert idle_blade_opacity(IDLE_BLADE_TOTAL_SECONDS + 1) == 0
