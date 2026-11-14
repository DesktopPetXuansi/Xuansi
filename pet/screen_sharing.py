"""Single-turn screen grants and checks shared by capture and inference."""

from contextvars import ContextVar
from dataclasses import dataclass
from typing import Callable


class ScreenShareError(RuntimeError):
    """A screen grant is missing, expired or tied to another destination."""


@dataclass(frozen=True)
class ScreenGrant:
    version: int
    epoch: int
    position: tuple[int, int]
    scope: str
    hwnd: int
    online_profile: str
    local_model: tuple[str, str, str]
    automatic: bool = False
    eligible: Callable[[], bool] | None = None


@dataclass(frozen=True)
class ScreenTurn:
    runtime: object
    epoch: int
    grant: ScreenGrant

    def current(self):
        if self.epoch != self.runtime.epoch or self.epoch != self.grant.epoch:
            return False
        if self.runtime.screen_version != self.grant.version:
            return False
        if self.grant.automatic:
            return (self.runtime.automatic_observation and not self.runtime.listening
                    and (self.grant.eligible is None or self.grant.eligible()))
        return self.runtime.screen_mode == "manual"

    def check_destination(self, online_profile):
        if (not self.current() or self.grant.online_profile != online_profile
                or (self.grant.automatic and online_profile)):
            raise ScreenShareError("本轮屏幕授权已失效或模型目的地已变更")

    def check_capture(self, foreground):
        self.check_destination(self.grant.online_profile)
        if not self.grant.hwnd or foreground != self.grant.hwnd:
            raise ScreenShareError("屏幕分享前台窗口已变更")


screen_turn: ContextVar[ScreenTurn | None] = ContextVar("screen_turn", default=None)


def check_screen_destination(online_profile=""):
    turn = screen_turn.get()
    if turn is not None:
        turn.check_destination(online_profile)


def online_screen_destination(settings):
    return settings.ai.profile.fingerprint() if settings.ai.policy == "online_first" else ""


def local_screen_destination(settings):
    return settings.ai.local_model, settings.model_path, settings.projector_path
