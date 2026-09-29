"""提供久置待机动作使用的单次空闲计时逻辑。"""


class IdleActionTimer:
    """按单调时钟判断是否已连续空闲，并限制每段空闲只触发一次。"""

    def __init__(self, inactivity_seconds=300):
        self.inactivity_seconds = max(0.0, float(inactivity_seconds))
        self._last_activity = 0.0
        self._eligible = False
        self._triggered = False

    def record_input(self, now):
        """记录键鼠活动并开启新的空闲周期。"""
        self._last_activity = float(now)
        self._triggered = False

    def poll(self, now, eligible):
        """只有进入可用待机后满时限才触发；不可用期间重置计时。"""
        now = float(now)
        if not eligible:
            self._last_activity = now
            self._eligible = False
            self._triggered = False
            return False

        if not self._eligible:
            self._last_activity = now
            self._eligible = True
            self._triggered = False
            return False

        if self._triggered or now - self._last_activity < self.inactivity_seconds:
            return False

        self._triggered = True
        return True
