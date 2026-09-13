"""低负担鼠标事件源；钩子只更新状态并发信号，不运行模型。"""

import logging
import math
import time

from pynput import mouse
from PySide6.QtCore import QObject, QTimer, Signal

from .desktop import cursor_position
from .events import MouseEvent, MouseTracker

LOG = logging.getLogger(__name__)


class MouseMonitor(QObject):
    event = Signal(object)

    def __init__(self):
        super().__init__()
        self.tracker = MouseTracker()
        self.last_position = cursor_position()
        self.last_move = time.monotonic()
        self.hover_sent = False
        self.listener = mouse.Listener(on_click=self._click, on_scroll=self._scroll)
        self.timer = QTimer(self)
        self.timer.setInterval(150)
        self.timer.timeout.connect(self._poll)

    def start(self):
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
        if math.dist(position, self.last_position) > 6:
            self.last_position, self.last_move = position, now
            self.hover_sent = False
        elif not self.hover_sent and now - self.last_move >= 1.8:
            self.hover_sent = True
            self.event.emit(MouseEvent("hover", *position, now))
