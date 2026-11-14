"""只读 Windows 输出会话电平；所有 COM 接口在同一后台线程创建和释放。"""

import logging
import threading
import time

import comtypes

from .windows_audio import CoreAudioProbe

LOG = logging.getLogger(__name__)
SAMPLE_MAX_AGE = 0.6
FAILURE_GRACE_SECONDS = 3.0
SOUND_HOLD_SECONDS = 1.5


def _close_probe(probe):
    if probe is not None:
        try:
            probe.close()
        except Exception as exc:
            # 设备失效后注销也可能失败，仍需释放引用并继续恢复检测。
            LOG.warning("声音检测探针释放失败 type=%s", type(exc).__name__)


class AudioActivity:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        now = clock()
        self._snapshot = (False, now, float("-inf"), now)
        self._stop = threading.Event()
        self._closed = False
        self.thread = None
        self.enabled = True

    def set_enabled(self, enabled: bool):
        if self.enabled == enabled:
            return
        # 重新开启时重新等待检测，不沿用旧的静音或已降级状态。
        now = self.clock()
        _, _, last_sound, _ = self._snapshot
        self._snapshot = (False, now, last_sound, now)
        self.enabled = enabled
        LOG.info("声音回避开关 enabled=%s", enabled)

    def _state(self):
        if self._closed:
            return "stopped"
        if not self.enabled:
            return "disabled"
        valid, checked, last_sound, unavailable_since = self._snapshot
        now = self.clock()
        if now - last_sound < SOUND_HOLD_SECONDS:
            return "sound"
        if valid:
            if now - checked <= SAMPLE_MAX_AGE:
                return "quiet"
            # 工作线程卡住时，从样本过期时计时，读取状态也能自行降级。
            unavailable_since = checked + SAMPLE_MAX_AGE
        return "checking" if now < unavailable_since + FAILURE_GRACE_SECONDS else "degraded"

    @property
    def blocked(self):
        return self._state() in ("checking", "sound", "stopped")

    @property
    def status(self):
        return {
            "stopped": "声音检测已停止",
            "disabled": "已关闭：朗读可与其他软件同时播放",
            "checking": "暂时无法检测其他声音 · 暂停朗读，等待检测恢复",
            "degraded": "声音检测不可用 · 已暂时放行朗读，可能与其他软件同时播放",
            "sound": "其他软件正在发声 · 只显示文字，不朗读",
            "quiet": "已开启：其他软件发声时暂停朗读",
        }[self._state()]

    def update(self, present, now=None):
        now = self.clock() if now is None else now
        valid, checked, last_sound, unavailable_since = self._snapshot
        if present is None:
            # 连续失败保留第一次失效时间，不能每次重试都延长宽限期。
            if valid:
                unavailable_since = min(now, checked + SAMPLE_MAX_AGE)
        else:
            unavailable_since = now
        self._snapshot = (present is not None, now, now if present else last_sound, unavailable_since)

    def start(self):
        if self._stop.is_set() or (self.thread is not None and self.thread.is_alive()):
            return
        self.thread = threading.Thread(target=self._run, name="pet-audio-activity", daemon=True)
        self.thread.start()

    def _run(self):
        previous = None
        probe = None
        initialized = False
        retry_delay = 0.5
        try:
            while not self._stop.is_set():
                delay = 0.1
                if not self.enabled:
                    # 用户关闭时释放 COM 查询对象，停止轮询音频设备。
                    _close_probe(probe)
                    probe = None
                    retry_delay = 0.5
                else:
                    try:
                        # 初始化失败也走重试，只有成功建立的 MTA 才配对释放。
                        if not initialized:
                            comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
                            initialized = True
                        if probe is None:
                            probe = CoreAudioProbe()
                        self.update(probe.sample())
                    except Exception as exc:
                        self.update(None)
                        _close_probe(probe)
                        probe = None
                        # 健康采样仍为 100ms；重建单独退避，避免 COM 端点风暴。
                        delay = retry_delay
                        retry_delay = min(retry_delay * 2, 5.0)
                        LOG.warning("声音检测失败 type=%s retry_seconds=%s", type(exc).__name__, delay)
                    else:
                        if retry_delay > 0.5:
                            LOG.info("声音检测已恢复")
                        retry_delay = 0.5
                status = self.status
                if status != previous:
                    LOG.info("%s", status)
                    previous = status
                # 关闭会唤醒事件等待，无需等完整的重试间隔。
                self._stop.wait(delay)
        finally:
            _close_probe(probe)
            probe = None
            if initialized:
                comtypes.CoUninitialize()

    def close(self):
        # 主动关闭不能被当作设备故障，超时后也不能重新放行播放。
        self._closed = True
        self._stop.set()
        if self.thread:
            self.thread.join(timeout=2)
        self.update(None)
