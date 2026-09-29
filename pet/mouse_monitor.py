"""低负担鼠标事件源；钩子只更新状态并发信号，不运行模型。"""

import ctypes
import logging
import math
import sys
import time

from pynput import mouse
from PySide6.QtCore import QObject, QTimer, Signal

from .desktop import cursor_position
from .events import MouseEvent, MouseTracker

LOG = logging.getLogger(__name__)


class _LASTINPUTINFO(ctypes.Structure):
    """Windows 最后输入结构；只保存系统时间戳，不包含按键或鼠标内容。"""

    _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint32)]


class _SystemInputSampler:
    """低成本读取 Windows 会话的最近键鼠输入时间。"""

    def __init__(self):
        self._library = None
        self._read_last_input = None
        if sys.platform != "win32":
            return

        try:
            self._library = ctypes.WinDLL("user32", use_last_error=True)
            self._read_last_input = self._library.GetLastInputInfo
            self._read_last_input.argtypes = [ctypes.POINTER(_LASTINPUTINFO)]
            self._read_last_input.restype = ctypes.c_bool
        except (AttributeError, OSError):
            LOG.exception("无法初始化系统最后输入检测；久置待机动作已禁用")
            self._read_last_input = None

    @property
    def available(self):
        """供桌宠安全门控确认系统输入状态可用。"""
        return self._read_last_input is not None

    def read(self):
        """返回最后输入的 DWORD 时间戳；失败时禁用后续轮询。"""
        if self._read_last_input is None:
            return None

        info = _LASTINPUTINFO(ctypes.sizeof(_LASTINPUTINFO), 0)
        try:
            if not self._read_last_input(ctypes.byref(info)):
                raise OSError(ctypes.get_last_error(), "GetLastInputInfo 返回失败")
        except (OSError, ValueError):
            LOG.exception("系统最后输入检测失败；久置待机动作已禁用")
            self._read_last_input = None
            return None
        return int(info.dwTime)


class MouseMonitor(QObject):
    event = Signal(object)
    activity = Signal()

    def __init__(self):
        super().__init__()
        self.tracker = MouseTracker()
        self.last_position = cursor_position()
        self.last_move = time.monotonic()
        self.hover_sent = False
        self._system_input = _SystemInputSampler()
        self._last_input_tick = None
        self.input_monitor_available = self._system_input.available
        self.listener = mouse.Listener(on_click=self._click, on_scroll=self._scroll)
        self.timer = QTimer(self)
        self.timer.setInterval(150)
        self.timer.timeout.connect(self._poll)

    def start(self):
        # 建立启动基线；启动前的系统空闲时间不应触发动作。
        self._last_input_tick = self._system_input.read()
        self.input_monitor_available = self._system_input.available and self._last_input_tick is not None
        if not self.input_monitor_available and sys.platform != "win32":
            LOG.info("系统键鼠空闲检测仅支持 Windows；久置待机动作已禁用")
        self.listener.start()
        self.timer.start()
        LOG.info("鼠标事件监听启动")

    def stop(self):
        self.timer.stop()
        self.listener.stop()

    def _click(self, x, y, button, pressed):
        if button != mouse.Button.left:
            return
        now = time.monotonic()
        if pressed:
            self.tracker.press(x, y, now)
        else:
            self.event.emit(self.tracker.release(x, y, now))

    def _scroll(self, x, y, dx, dy):
        self.event.emit(MouseEvent("scroll", x, y, time.monotonic()))

    def _poll(self):
        position, now = cursor_position(), time.monotonic()
        self._poll_system_input()
        if math.dist(position, self.last_position) > 6:
            self.last_position, self.last_move = position, now
            self.hover_sent = False
        elif not self.hover_sent and now - self.last_move >= 1.8:
            self.hover_sent = True
            self.event.emit(MouseEvent("hover", *position, now))

    def _poll_system_input(self):
        """复用现有 150ms 轮询，把系统键鼠输入转换成不带内容的活动信号。"""
        if not self.input_monitor_available:
            return
        tick = self._system_input.read()
        if tick is None:
            self.input_monitor_available = False
            self._last_input_tick = None
            return
        if tick != self._last_input_tick:
            self._last_input_tick = tick
            self.activity.emit()
