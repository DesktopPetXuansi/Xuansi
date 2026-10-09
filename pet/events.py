"""鼠标事件与观察节流的纯逻辑；时钟由调用者注入，便于验证。"""

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class MouseEvent:
    kind: str
    x: int
    y: int
    when: float
    start: tuple[int, int] | None = None

    def description(self):
        labels = {"click": "点击", "drag": "拖拽结束", "hover": "停留", "scroll": "滚动"}
        return f"鼠标{labels.get(self.kind, self.kind)}；图中红圈标记当前鼠标位置。"


class MouseTracker:
    def __init__(self):
        self.down: tuple[int, int] | None = None

    def press(self, x: int, y: int, when: float):
        self.down = (x, y)

    def release(self, x: int, y: int, when: float):
        start, self.down = self.down, None
        kind = "drag" if start and math.dist(start, (x, y)) > 12 else "click"
        return MouseEvent(kind, x, y, when, start)


@dataclass
class ObservationGate:
    interval: int = 20
    last_sent: float = float("-inf")

    def allowed(self, now: float, event_time: float, blocked: bool):
        return not blocked and 0 <= now - event_time <= 5 and now - self.last_sent >= self.interval

    def mark_sent(self, now: float):
        self.last_sent = now


def crop_rect(x: int, y: int, monitor: tuple[int, int, int, int], width=640, height=448):
    left, top, right, bottom = monitor
    width, height = min(width, right - left), min(height, bottom - top)
    x0 = max(left, min(x - width // 2, right - width))
    y0 = max(top, min(y - height // 2, bottom - height))
    return x0, y0, x0 + width, y0 + height
