"""Windows 注册热键；不安装键盘记录钩子，冲突时保留旧绑定。"""

import ctypes
import logging
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter

LOG = logging.getLogger(__name__)
USER32 = ctypes.WinDLL("user32", use_last_error=True)
USER32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
USER32.RegisterHotKey.restype = wintypes.BOOL
USER32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
USER32.UnregisterHotKey.restype = wintypes.BOOL


def parse_hotkey(text):
    parts = text.upper().split("+")
    modifiers = {"ALT": 1, "CTRL": 2, "SHIFT": 4, "META": 8, "WIN": 8}
    if len(parts) < 3 or len(set(parts)) != len(parts) or any(p not in modifiers for p in parts[:-1]):
        raise ValueError("快捷键需包含至少两个修饰键，例如 Ctrl+Alt+Space")
    flags = 0
    for part in parts[:-1]:
        flags |= modifiers[part]
    if flags.bit_count() < 2:
        raise ValueError("快捷键需包含至少两个不同修饰键")
    key = parts[-1]
    if key == "SPACE":
        code = 0x20
    elif len(key) == 1 and key in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789":
        code = ord(key)
    elif key.startswith("F") and key[1:].isdigit() and 1 <= int(key[1:]) <= 24 and key != "F12":
        code = 0x70 + int(key[1:]) - 1
    else:
        raise ValueError("快捷键末键请选择字母、数字、空格或 F1–F24（F12 为系统保留）")
    return flags | 0x4000, code  # MOD_NOREPEAT：长按只触发一次。


class GlobalHotkey(QAbstractNativeEventFilter):
    def __init__(self, app, callback):
        super().__init__()
        self.app, self.callback = app, callback
        self.active = None
        self.pending = None
        self.sequence = ""
        self.next_id = 0x5100
        app.installNativeEventFilter(self)

    def stage(self, sequence):
        if sequence == self.sequence and self.active is not None:
            return
        self.rollback()
        modifiers, code = parse_hotkey(sequence)
        if self.active is not None and parse_hotkey(self.sequence) == (modifiers, code):
            return  # QKeySequence 可能重排修饰键；等价组合无需再次向 Windows 注册。
        if self.next_id == self.active:
            self.next_id = 0x5100 + (self.next_id - 0x5100 + 1) % 0x100
        identifier = self.next_id
        self.next_id = 0x5100 + (self.next_id - 0x5100 + 1) % 0x100
        if not USER32.RegisterHotKey(None, identifier, modifiers, code):
            LOG.warning("快捷键注册失败 code=%s", ctypes.get_last_error())
            raise ValueError("快捷键已被占用或不可用，请在配置中换一个组合；原设置仍保留。")
        self.pending = (identifier, sequence)

    def commit(self):
        if self.pending is None:
            return
        if self.active is not None:
            USER32.UnregisterHotKey(None, self.active)
        self.active, self.sequence = self.pending
        self.pending = None
        LOG.info("快捷对话热键已注册")

    def rollback(self):
        if self.pending:
            USER32.UnregisterHotKey(None, self.pending[0])
            self.pending = None

    def nativeEventFilter(self, event_type, message):
        if event_type in (b"windows_generic_MSG", b"windows_dispatcher_MSG"):
            event = wintypes.MSG.from_address(int(message))
            if event.message == 0x0312 and event.wParam == self.active:
                self.callback()
                return True, 0
        return False, 0

    def close(self):
        self.rollback()
        if self.active is not None:
            USER32.UnregisterHotKey(None, self.active)
            self.active = None
        self.app.removeNativeEventFilter(self)
