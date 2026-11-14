"""回复表情的有界插值状态；使用既有绘制时钟，不创建额外计时器。"""

from dataclasses import dataclass, field

from .avatar_motion import BLINK_CLOSE_SECONDS, BLINK_HOLD_SECONDS, BLINK_OPEN_SECONDS, _smoothstep

EXPRESSION_FADE_SECONDS = 0.35
EXPRESSION_HOLD_SECONDS = 4.0

# 默认模型实际绑定了眼睑开合；眉形和微笑参数存在但没有可见网格形变。
EXPRESSION_PARAMETERS = ("ParamEyeLOpen", "ParamEyeROpen")
EXPRESSION_PRESETS = {
    "neutral": (1.0, 1.0),
    "happy": (0.62, 0.62),
    "concern": (0.78, 0.78),
    "curious": (1.0, 0.72),
}


@dataclass
class ReplyExpression:
    """保留当前插值起点；替换、过期和显式清理都不会重播旧表情。"""

    name: str = "neutral"
    started: float | None = None
    origin: tuple[float, ...] = field(default_factory=lambda: EXPRESSION_PRESETS["neutral"])
    pending_reset: bool = False

    def set(self, name, now):
        """从当前值平滑过渡；未知值只回到平静，不承担任何动作协议。"""
        self.origin = self.values(now)
        self.name = name if name in EXPRESSION_PRESETS else "neutral"
        self.started = now
        self.pending_reset = True

    def clear(self):
        """立即丢弃时序，下次绘制只需提交一次中立参数。"""
        self.pending_reset = self.pending_reset or self.started is not None
        self.name = "neutral"
        self.started = None
        self.origin = EXPRESSION_PRESETS["neutral"]

    def values(self, now):
        """按单调时钟计算淡入、保持和淡出，空闲时返回中立值。"""
        neutral = EXPRESSION_PRESETS["neutral"]
        if self.started is None:
            return neutral
        elapsed = max(0.0, now - self.started)
        target = EXPRESSION_PRESETS[self.name]
        if elapsed < EXPRESSION_FADE_SECONDS:
            weight = _smoothstep(elapsed / EXPRESSION_FADE_SECONDS)
            return tuple(start + (end - start) * weight for start, end in zip(self.origin, target))
        if self.name == "neutral":
            self.clear()
            return neutral
        fade_out = EXPRESSION_FADE_SECONDS + EXPRESSION_HOLD_SECONDS
        if elapsed <= fade_out:
            return target
        if elapsed < fade_out + EXPRESSION_FADE_SECONDS:
            weight = 1.0 - _smoothstep((elapsed - fade_out) / EXPRESSION_FADE_SECONDS)
            return tuple(base + (value - base) * weight for base, value in zip(neutral, target))
        self.clear()
        return neutral

    def eye_values(self, now):
        """表情期间叠加短暂眨眼，避免长时间固定眼睑或覆盖语音口型。"""
        values = self.values(now)
        if self.started is None:
            return values
        elapsed = max(0.0, now - self.started)
        if elapsed < 1.6:
            return values
        phase = (elapsed - 1.6) % 3.0
        if phase < BLINK_CLOSE_SECONDS:
            factor = 1.0 - _smoothstep(phase / BLINK_CLOSE_SECONDS)
        elif phase < BLINK_CLOSE_SECONDS + BLINK_HOLD_SECONDS:
            factor = 0.0
        elif phase < BLINK_CLOSE_SECONDS + BLINK_HOLD_SECONDS + BLINK_OPEN_SECONDS:
            factor = _smoothstep((phase - BLINK_CLOSE_SECONDS - BLINK_HOLD_SECONDS) / BLINK_OPEN_SECONDS)
        else:
            factor = 1.0
        return tuple(value * factor for value in values)
