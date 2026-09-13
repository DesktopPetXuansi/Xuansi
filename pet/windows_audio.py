"""Core Audio 只读探针；MTA 内维护会话通知，避免频繁重建 COM 图。"""

import os
import threading
import time

import comtypes
from pycaw.api.audioclient import ISimpleAudioVolume
from pycaw.api.audiopolicy import IAudioSessionControl2, IAudioSessionManager2, IAudioSessionNotification
from pycaw.api.endpointvolume import IAudioEndpointVolume, IAudioMeterInformation
from pycaw.utils import AudioUtilities


class SessionChanges(comtypes.COMObject):
    _com_interfaces_ = [IAudioSessionNotification]

    def __init__(self):
        super().__init__()
        self.lock = threading.Lock()
        self.pending = []
        self.closed = False
        self.failed = False

    def OnSessionCreated(self, control):
        # COM 回调与采样线程同属 MTA；只保留引用，后续查询留给采样线程。
        with self.lock:
            if not self.closed:
                try:
                    self.pending.append(control.QueryInterface(IAudioSessionControl2))
                except Exception:
                    self.failed = True
        return 0

    def drain(self):
        with self.lock:
            if self.failed:
                raise RuntimeError("音频会话通知不可用")
            pending, self.pending = self.pending, []
            return pending

    def close(self):
        with self.lock:
            self.closed = True
            self.pending.clear()


class SessionMeter:
    def __init__(self, control):
        self.control = control
        self.pid = control.GetProcessId()
        self.volume = None
        self.meter = None

    def audible(self):
        if self.pid == os.getpid() or self.control.GetState() != 1:
            return False
        if self.volume is None:
            self.volume = self.control.QueryInterface(ISimpleAudioVolume)
            self.meter = self.control.QueryInterface(IAudioMeterInformation)
        return (
            not self.volume.GetMute()
            and self.volume.GetMasterVolume() > 0
            and self.meter.GetPeakValue() > 0.000001
        )


class EndpointMeter:
    def __init__(self, device):
        self.volume = device.Activate(IAudioEndpointVolume._iid_, comtypes.CLSCTX_ALL, None).QueryInterface(
            IAudioEndpointVolume
        )
        self.manager = device.Activate(IAudioSessionManager2._iid_, comtypes.CLSCTX_ALL, None).QueryInterface(
            IAudioSessionManager2
        )
        self.changes = SessionChanges()
        self.sessions = {}
        self.manager.RegisterSessionNotification(self.changes)
        try:
            # GetCount 初始化枚举后，Windows 才开始发送会话通知。
            enumerator = self.manager.GetSessionEnumerator()
            for i in range(enumerator.GetCount()):
                self.add(enumerator.GetSession(i).QueryInterface(IAudioSessionControl2))
        except BaseException:
            self.close()
            raise

    def add(self, control):
        key = control.GetSessionInstanceIdentifier()
        if key not in self.sessions:
            self.sessions[key] = SessionMeter(control)

    def audible(self):
        for control in self.changes.drain():
            self.add(control)
        self.sessions = {key: meter for key, meter in self.sessions.items() if meter.control.GetState() != 2}
        if self.volume.GetMute() or self.volume.GetMasterVolumeLevelScalar() <= 0:
            return False
        return any(meter.audible() for meter in self.sessions.values())

    def close(self):
        self.changes.close()
        try:
            self.manager.UnregisterSessionNotification(self.changes)
        finally:
            self.sessions.clear()


class CoreAudioProbe:
    def __init__(self):
        self.enumerator = AudioUtilities.GetDeviceEnumerator()
        self.endpoints = {}
        self.refreshed = float("-inf")

    def sample(self):
        if time.monotonic() - self.refreshed >= 1:
            self.refresh()
        if not self.endpoints:
            raise RuntimeError("没有可用输出设备")
        # 不短路端点采样，及时处理其他设备上的新会话和过期引用。
        return any([endpoint.audible() for endpoint in self.endpoints.values()])

    def refresh(self):
        devices = self.enumerator.EnumAudioEndpoints(0, 1)  # eRender, DEVICE_STATE_ACTIVE
        current = set()
        for i in range(devices.GetCount()):
            device = devices.Item(i)
            key = device.GetId()
            current.add(key)
            if key not in self.endpoints:
                self.endpoints[key] = EndpointMeter(device)
        for key in set(self.endpoints) - current:
            self.endpoints.pop(key).close()
        self.refreshed = time.monotonic()

    def close(self):
        endpoints, self.endpoints = self.endpoints, {}
        for endpoint in endpoints.values():
            try:
                endpoint.close()
            except Exception:
                pass  # 设备拔出后可能拒绝注销；COM 引用仍由当前 MTA 释放。
