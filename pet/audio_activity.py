"""只读 Windows 输出会话电平；所有 COM 接口在同一后台线程创建和释放。"""

import logging
import threading
import time

import comtypes

from .windows_audio import CoreAudioProbe

LOG = logging.getLogger(__name__)


class AudioActivity:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self._snapshot = (False, float("-inf"), float("-inf"))
        self._stop = threading.Event()
        self.thread = None

    @property
    def blocked(self):
        valid, checked, last_sound = self._snapshot
        now = self.clock()
        return not valid or now - checked > 0.6 or now - last_sound < 1.5

    @property
    def status(self):
        valid, checked, _ = self._snapshot
        if not valid or self.clock() - checked > 0.6:
            return "声音检测暂不可用 · 仅文字"
        return "其他软件有声音 · 仅文字" if self.blocked else "声音回避已开启"

    def update(self, present, now=None):
        now = self.clock() if now is None else now
        _, _, last = self._snapshot
        self._snapshot = (present is not None, now, now if present else last)

    def start(self):
        if self.thread:
            return
        self.thread = threading.Thread(target=self._run, name="pet-audio-activity", daemon=True)
        self.thread.start()

    def _run(self):
        # 模块在主线程首次导入；此专用工作线程单独初始化 MTA 并配对释放。
        comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
        previous = None
        probe = None
        try:
            while not self._stop.is_set():
                try:
                    if probe is None:
                        probe = CoreAudioProbe()
                    self.update(probe.sample())
                except Exception as exc:
                    self.update(None)
                    if probe:
                        probe.close()
                        probe = None
                    if previous != self.status:
                        LOG.warning("声音检测失败 type=%s", type(exc).__name__)
                status = self.status
                if status != previous:
                    LOG.info("%s", status)
                    previous = status
                self._stop.wait(0.1)
        finally:
            if probe:
                probe.close()
                probe = None
            comtypes.CoUninitialize()

    def close(self):
        self._stop.set()
        if self.thread:
            self.thread.join(timeout=2)
        self.update(None)
