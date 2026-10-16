"""观察协议与真实局部看图验收，仅捕获完整覆盖的人工测试窗口。

静默阶段用受控 finish_observation 验证 UI/运行时，不代表真实模型静默语义通过。
自然观察保持产品提示，允许模型评论或结束；随后独立提交显式看图请求。
"""

import ctypes
import json
import logging
import sys
import tempfile
import time
from ctypes import wintypes
from pathlib import Path
from unittest.mock import patch

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
from pet.live2d_session import configure_opengl_sharing
from pet.memory import MemoryStore
from pet.tool_protocol import AssistantReply, ToolCall

LOG = logging.getLogger(__name__)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    configure_opengl_sharing()
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    output = ROOT / "data/verification"
    output.mkdir(parents=True, exist_ok=True)
    picture = Image.new("RGB", (900, 650), "#f8faf5")
    draw = ImageDraw.Draw(picture)
    font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 28)
    draw.text((270, 150), "文件整理工具", font=font, fill="#23442f")
    draw.text((270, 210), "待处理文件：3", font=font, fill="#23442f")
    draw.rounded_rectangle((350, 300, 620, 380), 9, fill="#507758")
    draw.text((390, 320), "开始整理", font=font, fill="white")
    picture.save(output / "observation-source.png")
    fixture = QLabel(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                     | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowDoesNotAcceptFocus)
    fixture.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    pixels = QPixmap(str(output / "observation-source.png"))
    scale = app.primaryScreen().devicePixelRatio()
    pixels.setDevicePixelRatio(scale)
    fixture.setPixmap(pixels)
    fixture.setFixedSize(round(900 / scale), round(650 / scale))
    fixture.move(60, 60)
    settings = Settings(observe=True, speak_replies=False, speak_observations=False,
                        capture_scope="nearby", audio_avoidance=False)
    temporary = tempfile.TemporaryDirectory(prefix="xuansi-observation-")
    # Qt 启动也使用临时记忆，不读取用户资料或启动真实输入监控。
    with patch("pet.runtime.MemoryStore", lambda: MemoryStore(Path(temporary.name) / "memory.json")), \
            patch("pet.runtime.Runtime.load_devices", lambda _: None), \
            patch("pet.runtime.AudioActivity.start", lambda _: None), \
            patch("pet.app.MouseMonitor.start", lambda _: None):
        pet = DesktopPet(app, settings)
    pet.monitor.stop()
    pet.resource_timer.stop()
    report = {"passed": False, "scope": "受控静默协议、真实自然观察、真实显式看图；不启麦、不朗读"}
    phase = "silence_protocol"
    replies, calls, failures, states, quiet_calls = [], [], [], [], []
    started = time.monotonic()
    focus_before = 0
    finished = False
    original_complete = pet.runtime.engine.complete
    original_start = pet.runtime.engine.start
    original_desktop = desktop.desktop_state
    original_app_desktop = app_module.desktop_state
    original_own = app_module.point_is_own_window

    async def quiet_complete(*_args, **_kwargs):
        # 只验证无正文结束协议，不给真实观察强加必须沉默的用户指令。
        quiet_calls.append(True)
        return AssistantReply("", (ToolCall("quiet-check", "finish_observation", "{}"),), "tool_calls")

    async def quiet_start(_settings):
        pass

    async def observed_complete(*args, **kwargs):
        result = await original_complete(*args, **kwargs)
        calls.extend(call.name for call in result.tool_calls)
        return result

    def as_external():
        return desktop.DesktopState(int(fixture.winId()), False, False)

    desktop.desktop_state = app_module.desktop_state = as_external
    app_module.point_is_own_window = lambda x, y: (
        False if desktop.USER32.WindowFromPoint(wintypes.POINT(x, y)) == int(fixture.winId())
        else original_own(x, y)
    )

    def capture_position():
        # 只有裁剪区域全在人工窗口内才允许推理截图，失败后不继续显式看图阶段。
        rect = wintypes.RECT()
        desktop.USER32.GetWindowRect(int(fixture.winId()), ctypes.byref(rect))
        for x, y in ((260, 116), (899, 116), (260, 563), (899, 563), (580, 340)):
            if desktop.USER32.WindowFromPoint(wintypes.POINT(rect.left + x, rect.top + y)) != int(fixture.winId()):
                raise RuntimeError("虚拟窗口未覆盖测试裁剪区域，未截图")
        return rect.left + 580, rect.top + 340

    def finish(error=None):
        nonlocal finished
        if finished:
            return
        finished = True
        timeout.stop()
        if error is not None:
            report["error"] = error
        report["seconds"] = round(time.monotonic() - started, 2)
        report["passed"] = (
            report.get("silence_protocol_passed", False)
            and report.get("natural_observation_passed", False)
            and report.get("explicit_image_passed", False)
            and not failures and error is None
        )
        (output / "observation-native-tools-report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps(report, ensure_ascii=False), flush=True)
        fixture.close()
        pet.quit()

    def trigger_observation():
        nonlocal focus_before
        try:
            focus_before = desktop.USER32.GetForegroundWindow()
            fixture.show()
            QTest.qWait(500)
            x, y = capture_position()
            report["synthetic_window_covers_capture"] = True
            # 原产品鼠标入口与提示保持完整，自然观察允许通过工具静默。
            pet.on_mouse(MouseEvent("click", x, y, time.monotonic()))
        except Exception as exc:
            finish(type(exc).__name__ + ": " + str(exc))

    def trigger_explicit_image():
        try:
            position = capture_position()
            pet._begin()
            pet.runtime.ask(settings, "请回答红圈所在按钮的名称。", kind="chat-screen", position=position)
        except Exception as exc:
            finish(type(exc).__name__ + ": " + str(exc))

    def checked_reply(epoch, text, kind):
        before = desktop.USER32.GetForegroundWindow()
        pet.on_reply(epoch, text, kind)
        replies.append(text)
        report.setdefault("bubble_preserves_focus", []).append(desktop.USER32.GetForegroundWindow() == before)

    def completed(_epoch):
        nonlocal phase
        if finished:
            return
        if phase == "silence_protocol":
            report["silence_protocol_passed"] = (
                quiet_calls == [True] and not replies and not failures
                and bool(states) and states[-1] == "已就绪 · 麦克风关闭"
            )
            report["silence_protocol_source"] = "受控 finish_observation，未调用真实模型"
            if not report["silence_protocol_passed"]:
                finish("受控静默阶段出现正文或错误")
                return
            pet.runtime.engine.start = original_start
            pet.runtime.engine.complete = observed_complete
            phase = "natural_observation"
            QTimer.singleShot(50, trigger_observation)
        elif phase == "natural_observation":
            report["natural_observation_replies"] = list(replies)
            report["natural_observation_tools"] = list(calls)
            report["natural_observation_silent"] = not replies
            report["natural_observation_passed"] = not failures and (bool(replies) or "finish_observation" in calls)
            if not report["natural_observation_passed"]:
                finish("自然观察没有正文，也没有合法结束工具")
                return
            replies.clear()
            calls.clear()
            phase = "explicit_image"
            QTimer.singleShot(50, trigger_explicit_image)
        else:
            report["explicit_image_replies"] = list(replies)
            report["explicit_image_tools"] = list(calls)
            report["explicit_image_passed"] = (
                bool(replies) and "整理" in "".join(replies) and not failures
                and all(report.get("bubble_preserves_focus", []))
            )
            report["focus_preserved"] = desktop.USER32.GetForegroundWindow() == focus_before
            finish()

    pet.runtime.reply.disconnect(pet.on_reply)
    pet.runtime.reply.connect(checked_reply)
    pet.runtime.finished.connect(completed)
    pet.runtime.failed.connect(lambda _epoch, message: failures.append(message))
    pet.runtime.state.connect(lambda _epoch, message: states.append(message))
    pet.runtime.engine.start = quiet_start
    pet.runtime.engine.complete = quiet_complete
    timeout = QTimer()
    timeout.setSingleShot(True)
    timeout.timeout.connect(lambda: finish("观察或显式看图等待超时"))
    timeout.start(120000)
    QTimer.singleShot(200, lambda: pet.runtime.ask(settings, "观察当前状态。", kind="observation"))
    try:
        app.exec()
    finally:
        pet.runtime.engine.start = original_start
        pet.runtime.engine.complete = original_complete
        desktop.desktop_state = original_desktop
        app_module.desktop_state = original_app_desktop
        app_module.point_is_own_window = original_own
        pet.runtime.loop.call_soon_threadsafe(pet.runtime.loop.stop)
        pet.runtime.thread.join(3)
        temporary.cleanup()
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
