"""Record timing milestones without retaining conversation or audio data."""

import time
from contextvars import ContextVar
from dataclasses import dataclass, field


@dataclass
class TurnLatency:
    start: float = field(default_factory=time.monotonic)
    milestones: dict[str, float] = field(default_factory=dict)

    def mark(self, event, timestamp=None):
        timestamp = time.monotonic() if timestamp is None else timestamp
        self.milestones.setdefault(event, timestamp - self.start)

    def summary(self):
        return " ".join(f"{name}={seconds:.3f}s" for name, seconds in self.milestones.items())


turn_latency: ContextVar[TurnLatency | None] = ContextVar("turn_latency", default=None)


def mark_latency(event):
    timing = turn_latency.get()
    if timing is not None:
        timing.mark(event)
