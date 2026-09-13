"""真实 Qt 窗口验收：只保存自身界面，观察关闭，麦克风始终关闭。"""

import ctypes
import json
import sys
import time
from ctypes import wintypes
from pathlib import Path

import psutil
from PySide6.QtCore import QPoint, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit, QVBoxLayout, QWidget

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pet.app as app_module
from pet.app import DesktopPet
from pet.config import ROOT, Settings
from pet.desktop import USER32, desktop_state


def main():
    ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    pet = DesktopPet(app, Settings(observe=False, speak_replies=False))
    output = ROOT / "data/verification"
    output.mkdir(parents=True, exist_ok=True)
    baseline = output / "desktop-focus-limited-baseline.json"
    if (output / "desktop-report.json").exists() and not baseline.exists():
        baseline.write_bytes((output / "desktop-report.json").read_bytes())
    report = {}

    def inspect():
        try:
            pet.open_panel()
            QTest.qWait(350)
            for index, name in enumerate(("chat", "persona", "memory", "preferences")):
                pet.panel.tabs.setCurrentIndex(index)
                QTest.qWait(100)
                pet.panel.grab().save(str(output / f"panel-{name}.png"))
            pet.panel.hide()
            # 虚拟工作窗口作为焦点基准，不接触用户的文档或真实应用。
            fixture = QWidget()
            fixture.setWindowTitle("桌宠验收 · 虚拟输入窗口")
            layout = QVBoxLayout(fixture)
            field = QLineEdit("焦点验收基准：可以继续输入")
            layout.addWidget(field)
            fixture.resize(480, 180)
            fixture.show()
            fixture.activateWindow()
            field.setFocus()
            QTest.qWait(400)
            focus_before = USER32.GetForegroundWindow()
            report["fixture_has_focus"] = int(focus_before or 0) == int(fixture.winId())
            pet.avatar.bubble.present("我在这里陪着你。", pet.avatar)
            QTest.qWait(300)
            report["bubble_preserves_focus"] = USER32.GetForegroundWindow() == focus_before
            QTest.keyClicks(field, " ABC")
            report["typing_continues"] = field.text().endswith(" ABC")

            rect = wintypes.RECT()
            USER32.GetWindowRect(int(pet.avatar.winId()), ctypes.byref(rect))
            scale = (rect.right - rect.left) / pet.avatar.width()
            points = [(x, y) for x in range(pet.avatar.width()) for y in range(pet.avatar.height())]
            solid = next((x, y) for x, y in points if pet.avatar.mask().contains(QPoint(x, y)))
            clear = next((x, y) for x, y in points if not pet.avatar.mask().contains(QPoint(x, y)))

            def window_at(point):
                x, y = point
                return USER32.WindowFromPoint(
                    wintypes.POINT(rect.left + int(x * scale), rect.top + int(y * scale))
                )

            report["solid_pet_hit"] = window_at(solid) == int(pet.avatar.winId())
            report["transparent_pet_passes_through"] = window_at(clear) != int(pet.avatar.winId())

            fixture.showFullScreen()
            QTest.qWait(350)
            report["fullscreen_detected"] = desktop_state(int(fixture.winId())).fullscreen
            # Windows 可拒绝测试窗抢占前景，直接送入其真实几何状态检验暂停逻辑。
            app_module.desktop_state = lambda: desktop_state(int(fixture.winId()))
            pet._resources()
            report["fullscreen_hides_pet"] = not pet.avatar.isVisible()
            fixture.showNormal()
            QTest.qWait(350)
            focus_before = USER32.GetForegroundWindow()
            pet._resources()
            QTest.qWait(200)
            report["restores_without_focus"] = (
                pet.avatar.isVisible() and USER32.GetForegroundWindow() == focus_before
            )
            report["microphone_stays_off"] = not pet.runtime.listening
            app_module.desktop_state = desktop_state
            fixture.close()

            process = psutil.Process()
            before = process.cpu_times()
            started = time.monotonic()
            QTest.qWait(5000)
            after = process.cpu_times()
            report["idle_cpu_one_core_percent"] = round(
                ((after.user + after.system) - (before.user + before.system))
                / (time.monotonic() - started)
                * 100,
                2,
            )
            report["idle_rss_mb"] = round(process.memory_info().rss / 2**20)
            report["outbound_connections"] = [
                str(c.raddr) for c in process.net_connections(kind="inet") if c.raddr
            ]
        except Exception as exc:
            report["error"] = f"{type(exc).__name__}: {exc}"
        finally:
            (output / "desktop-report.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(json.dumps(report, ensure_ascii=False), flush=True)
            pet.quit()

    QTimer.singleShot(200, inspect)
    app.exec()
    pet.runtime.loop.call_soon_threadsafe(pet.runtime.loop.stop)
    pet.runtime.thread.join(2)


if __name__ == "__main__":
    main()
