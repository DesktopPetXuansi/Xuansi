"""本机主动问候的活动门控与持久限频；不读取聊天、记忆或屏幕。"""

import json
import logging
import math
import threading
from datetime import datetime
from pathlib import Path

LOG = logging.getLogger(__name__)
GREETINGS = (
    "如果想换换脑子，我们可以随便聊两句。",
    "要不要歇一小会儿？想安静待着也可以。",
    "想聊点轻松的吗？我在这里。",
    "需要放松一下的话，可以跟我说说今天的小事。",
)


class ProactiveGate:
    """复用资源轮询，只在启动满一小时且最近有真实输入时尝试。"""

    def __init__(self, now):
        self.started = self.last_activity = float(now)
        self.last_attempt = float("-inf")

    def record_activity(self, now):
        self.last_activity = float(now)

    def can_attempt(self, now, *, eligible):
        return bool(eligible and now - self.started >= 3600
                    and 0 <= now - self.last_activity <= 120
                    and now - self.last_attempt >= 300)

    def record_attempt(self, now):
        self.last_attempt = float(now)


class ProactiveLimiter:
    """问候与观察共用限额，持久保存已显示的问候编号和静默日期。"""

    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.Lock()

    def reserve(self, now):
        """预留一次机会；被取消的预留也计数，确保实际展示不会超额。"""
        with self.lock:
            state = self._available(float(now))
            if state is None:
                return None
            day = datetime.fromisoformat(state["day"])
            shown = state["shown"]
            if shown and (day.date() - datetime.fromisoformat(shown["day"]).date()).days > 3:
                shown = {}
            index = (day.toordinal() + state["count"]) % len(GREETINGS)
            if shown.get("index") == index:
                index = (index + 1) % len(GREETINGS)
            return GREETINGS[index] if self._commit(state, now) else None

    def reserve_observation(self, now):
        with self.lock:
            state = self._available(float(now))
            return state is not None and self._commit(state, now)

    def available(self, now):
        with self.lock:
            return self._available(float(now)) is not None

    def _read(self, now):
        if not math.isfinite(now):
            return None
        today = datetime.fromtimestamp(now).date().isoformat()
        state = {"day": today, "last_at": 0.0, "count": 0, "quiet_day": "", "shown": {}}
        try:
            saved = json.loads(self.path.read_text(encoding="utf-8"))
            if (not isinstance(saved, dict) or not {"day", "last_at", "count"} <= saved.keys()
                    or not isinstance(saved["day"], str)
                    or type(saved["last_at"]) not in (int, float)
                    or not math.isfinite(saved["last_at"])
                    or type(saved["count"]) is not int or not 0 <= saved["count"] <= 2):
                raise ValueError("invalid_state")
            datetime.fromisoformat(saved["day"])
            state.update({key: saved[key] for key in state.keys() & saved.keys()})
            if not isinstance(state["quiet_day"], str) or not isinstance(state["shown"], dict):
                raise ValueError("invalid_proactive_state")
            if state["quiet_day"]:
                datetime.fromisoformat(state["quiet_day"])
            if state["shown"]:
                datetime.fromisoformat(state["shown"]["day"])
                if type(state["shown"]["index"]) is not int or state["shown"]["index"] not in range(len(GREETINGS)):
                    raise ValueError("invalid_greeting")
        except FileNotFoundError:
            pass
        except (OSError, ValueError, TypeError, KeyError):
            LOG.warning("主动问候限频记录不可用，保留文件并暂停问候")
            return None
        if state["day"] != today:
            state.update(day=today, count=0)
        return state

    def _available(self, now):
        state = self._read(now)
        if (state is None or state["count"] >= 2 or now - state["last_at"] < 3600
                or state["quiet_day"] >= state["day"]):
            return None
        return state

    def quiet_today(self, now):
        with self.lock:
            state = self._read(now)
            if state is None:
                return False
            state["quiet_day"] = datetime.fromtimestamp(now).date().isoformat()
            return self._write(state)

    def mark_shown(self, text, now=None):
        if text not in GREETINGS:
            return
        now = datetime.now().timestamp() if now is None else now
        with self.lock:
            state = self._read(now)
            if state is not None:
                state["shown"] = {"day": state["day"], "index": GREETINGS.index(text)}
                self._write(state)

    def _commit(self, state, now):
        state.update(last_at=now, count=state["count"] + 1)
        return self._write(state)

    def _write(self, state):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(json.dumps(state), encoding="utf-8")
            temporary.replace(self.path)
        except OSError:
            LOG.warning("主动问候限频写入失败，跳过本次问候")
            return False
        return True
