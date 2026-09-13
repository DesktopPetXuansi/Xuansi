"""Windows 原生桌面信息及局部截图；不读取键盘内容或保存截图。"""

import ctypes
import os
import time
from ctypes import wintypes
from dataclasses import dataclass
from io import BytesIO

import mss
from PIL import Image, ImageDraw

from .events import crop_rect

USER32 = ctypes.WinDLL("user32", use_last_error=True)
USER32.GetForegroundWindow.restype = wintypes.HWND
USER32.WindowFromPoint.argtypes = [wintypes.POINT]
USER32.WindowFromPoint.restype = wintypes.HWND
USER32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
USER32.MonitorFromWindow.restype = wintypes.HANDLE
USER32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
USER32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
USER32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]


class MonitorInfo(ctypes.Structure):
    _fields_ = [
        ("size", wintypes.DWORD),
        ("monitor", wintypes.RECT),
        ("work", wintypes.RECT),
        ("flags", wintypes.DWORD),
    ]


USER32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MonitorInfo)]


@dataclass(frozen=True)
class DesktopState:
    hwnd: int
    own_window: bool
    fullscreen: bool


def desktop_state(hwnd=None):
    hwnd = USER32.GetForegroundWindow() if hwnd is None else hwnd
    if not hwnd:
        return DesktopState(0, False, False)
    pid = wintypes.DWORD()
    USER32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    rect = wintypes.RECT()
    info = MonitorInfo()
    info.size = ctypes.sizeof(info)
    name = ctypes.create_unicode_buffer(128)
    USER32.GetClassNameW(hwnd, name, len(name))
    fullscreen = False
    if USER32.GetWindowRect(hwnd, ctypes.byref(rect)) and USER32.GetMonitorInfoW(
        USER32.MonitorFromWindow(hwnd, 2), ctypes.byref(info)
    ):
        screen = info.monitor
        fullscreen = (
            name.value not in ("Progman", "WorkerW", "Shell_TrayWnd")
            and abs(rect.left - screen.left) <= 2
            and abs(rect.top - screen.top) <= 2
            and abs(rect.right - screen.right) <= 2
            and abs(rect.bottom - screen.bottom) <= 2
        )
    return DesktopState(int(hwnd), pid.value == os.getpid(), fullscreen)


def cursor_position():
    point = wintypes.POINT()
    USER32.GetCursorPos(ctypes.byref(point))
    return point.x, point.y


def observation_current(observation):
    if observation is None:
        return True
    hwnd, started = observation
    state = desktop_state()
    return (
        state.hwnd == hwnd
        and not state.own_window
        and not state.fullscreen
        and time.monotonic() - started <= 30
    )


def point_is_own_window(x, y):
    hwnd = USER32.WindowFromPoint(wintypes.POINT(x, y))
    pid = wintypes.DWORD()
    USER32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value == os.getpid()


def capture_near_cursor(x: int, y: int):
    """mss 使用物理坐标，和鼠标钩子一致，跨屏时不混用 Qt 逻辑坐标。"""
    with mss.mss() as grabber:
        monitor = next(
            (
                m
                for m in grabber.monitors[1:]
                if m["left"] <= x < m["left"] + m["width"] and m["top"] <= y < m["top"] + m["height"]
            ),
            grabber.monitors[1],
        )
        bounds = (
            monitor["left"],
            monitor["top"],
            monitor["left"] + monitor["width"],
            monitor["top"] + monitor["height"],
        )
        left, top, right, bottom = crop_rect(x, y, bounds)
        frame = grabber.grab({"left": left, "top": top, "width": right - left, "height": bottom - top})
        picture = Image.frombytes("RGB", frame.size, frame.rgb)
    # 红圈标记鼠标，便于视觉模型区分目标；仅对内存中的局部图像操作。
    draw = ImageDraw.Draw(picture)
    cx, cy = x - left, y - top
    draw.ellipse((cx - 9, cy - 9, cx + 9, cy + 9), outline="#e04d46", width=2)
    with BytesIO() as output:
        picture.save(output, format="JPEG", quality=88)
        return output.getvalue()
