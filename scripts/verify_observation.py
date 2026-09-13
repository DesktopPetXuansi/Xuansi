"""鼠标事件→真实局部截图→模型→气泡；窗口内只有人工构造的测试内容。"""

import ctypes
import json
import sys
import time
from ctypes import wintypes
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pet.app as app_module
import pet.desktop as desktop
from pet.app import DesktopPet
from pet.config import ROOT, Settings
from pet.events import MouseEvent


def main():
    ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    output = ROOT / "data/verification"
    # 画面、按钮与计数由人工基准定义。标记位于按钮文字右侧。
    picture = Image.new("RGB", (900, 650), "#f8faf5")
    draw = ImageDraw.Draw(picture)
    font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 28)
    draw.text((270, 150), "文件整理工具", font=font, fill="#23442f")
    draw.text((270, 210), "待处理文件：3", font=font, fill="#23442f")
    draw.rounded_rectangle((350, 300, 620, 380), 9, fill="#507758")
    draw.text((390, 320), "开始整理", font=font, fill="white")
    picture.save(output / "observation-source.png")
    fixture = QLabel(
        None,
        Qt.WindowType.Tool
        | Qt.WindowType.FramelessWindowHint
        | Qt.WindowType.WindowStaysOnTopHint
        | Qt.WindowType.WindowDoesNotAcceptFocus,
    )
    fixture.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    pixels = QPixmap(str(output / "observation-source.png"))
    scale = app.primaryScreen().devicePixelRatio()
    pixels.setDevicePixelRatio(scale)
    fixture.setPixmap(pixels)
    fixture.setFixedSize(round(900 / scale), round(650 / scale))
    fixture.move(60, 60)
    # 此历史测试窗口只覆盖局部区域，显式限制范围，避免默认整屏采集到用户工作。
    pet = DesktopPet(app, Settings(observe=True, speak_replies=False, capture_scope="nearby"))
    pet.monitor.stop()
    original_ask = pet.runtime.ask

    def explicit_test(settings, text, **kwargs):
        # 产品默认可保持安静；验收时明确要求回答，避免采样到“无需回应”。
        return original_ask(
            settings, text + "\n这是明确请求的测试，请回答红圈所在按钮名称，不要返回无需回应。", **kwargs
        )

    pet.runtime.ask = explicit_test
    report = {}
    started = time.monotonic()
    focus_before = 0

    def as_external():
        # 验证脚本模拟用户已点击虚拟窗口，真实前景焦点始终不变。
        return desktop.DesktopState(int(fixture.winId()), False, False)

    desktop.desktop_state = app_module.desktop_state = as_external
    original_own = app_module.point_is_own_window
    app_module.point_is_own_window = lambda x, y: (
        False
        if desktop.USER32.WindowFromPoint(wintypes.POINT(x, y)) == int(fixture.winId())
        else original_own(x, y)
    )

    def trigger():
        nonlocal focus_before
        focus_before = desktop.USER32.GetForegroundWindow()
        fixture.show()
        QTest.qWait(500)
        rect = wintypes.RECT()
        desktop.USER32.GetWindowRect(int(fixture.winId()), ctypes.byref(rect))
        # 只在完整裁剪区域由虚拟窗口覆盖时抓图，避免保存真实工作内容。
        for x, y in ((260, 116), (899, 116), (260, 563), (899, 563), (580, 340)):
            if desktop.USER32.WindowFromPoint(wintypes.POINT(rect.left + x, rect.top + y)) != int(
                fixture.winId()
            ):
                report["error"] = "虚拟窗口未覆盖测试裁剪区域，未截图"
                finish()
                return
        event = MouseEvent("click", rect.left + 580, rect.top + 340, time.monotonic())
        report["synthetic_window_covers_capture"] = True
        pet.on_mouse(event)

    def replied(epoch, text, kind):
        report["reply"] = text
        report["kind"] = kind
        report["seconds"] = round(time.monotonic() - started, 2)
        report["recognized_action"] = "整理" in text
        report["focus_preserved"] = desktop.USER32.GetForegroundWindow() == focus_before
        report["bubble_shown"] = pet.avatar.bubble.isVisible()
        finish()

    def finish():
        timeout.stop()
        report.setdefault("reply", "")
        (output / "observation-report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps(report, ensure_ascii=False), flush=True)
        fixture.close()
        pet.quit()

    pet.runtime.reply.connect(replied)
    # 检查气泡显示这个同步动作，排除等待推理期间用户自行切换窗口的影响。
    pet.runtime.reply.disconnect(pet.on_reply)
    pet.runtime.reply.disconnect(replied)

    def checked_reply(epoch, text, kind):
        before = desktop.USER32.GetForegroundWindow()
        pet.on_reply(epoch, text, kind)
        report["bubble_preserves_focus"] = desktop.USER32.GetForegroundWindow() == before
        replied(epoch, text, kind)

    pet.runtime.reply.connect(checked_reply)
    timeout = QTimer()
    timeout.setSingleShot(True)
    timeout.timeout.connect(finish)
    timeout.start(45000)
    QTimer.singleShot(200, trigger)
    app.exec()
    pet.runtime.loop.call_soon_threadsafe(pet.runtime.loop.stop)
    pet.runtime.thread.join(2)


if __name__ == "__main__":
    main()
