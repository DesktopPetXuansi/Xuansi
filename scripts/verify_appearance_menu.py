"""真实 Qt 形象菜单验收；只使用人工动图、临时设置和临时记忆。"""

import ctypes
import json
import logging
import sys
import tempfile
import threading
import time
from ctypes import wintypes
from dataclasses import replace
from pathlib import Path

from PIL import Image, ImageDraw
from PySide6.QtCore import QPoint, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pet.app as app_module
import pet.appearance as assets
import pet.appearance_dialog as dialog_module
import pet.character_frames as character_module
import pet.native_animation as animation_module
import pet.runtime as runtime_module
from pet.app import DesktopPet
from pet.avatar import Avatar
from pet.config import ROOT, Settings, load_settings, save_settings
from pet.desktop import USER32, DesktopState
from pet.memory import MemoryStore


def main():
    logging.basicConfig(level=logging.INFO)
    USER32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    output = ROOT / "data/verification"
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="pet-appearance-") as directory:
        temporary = Path(directory)
        asset_dir = temporary / "assets"
        setting_path = temporary / "settings.json"
        original_path, original_import = assets.image_path, assets.import_image
        assets.image_path = lambda identifier, directory=asset_dir: original_path(identifier, directory)
        character_module.image_path = animation_module.image_path = dialog_module.image_path = (
            assets.image_path
        )
        dialog_module.import_image = lambda path: original_import(path, asset_dir)
        runtime_module.MemoryStore = lambda: MemoryStore(temporary / "memory.json")
        runtime_module.save_settings = lambda settings: save_settings(settings, setting_path)
        app_module.desktop_state = lambda: DesktopState(1, False, False)
        settings = replace(Settings(), observe=False, speak_replies=False, chat_hotkey="Ctrl+Alt+Shift+F24")
        pet = DesktopPet(app, settings)
        report = {}

        def wait_until(predicate, seconds=5):
            end = time.monotonic() + seconds
            while not predicate() and time.monotonic() < end:
                QTest.qWait(20)
            return bool(predicate())

        def inspect():
            restarted = None
            try:
                frames = []
                for offset in (0, 14, 0):
                    frame = Image.new("RGBA", (140, 180))
                    if len(frames) != 2:  # 第三帧完全透明，验证它不会吞掉点击。
                        draw = ImageDraw.Draw(frame)
                        draw.ellipse((35 + offset, 35, 95 + offset, 100), fill="#52786b")
                        draw.rectangle((48, 95, 90, 155), fill="#b79159")
                    frames.append(frame)
                source = temporary / "transparent.png"
                frames[0].save(
                    source, save_all=True, append_images=frames[1:], duration=[80, 160, 100], loop=0
                )
                menu = next(
                    action.menu()
                    for action in pet.panel.layout().menuBar().actions()
                    if action.text() == "形象"
                )
                menu.actions()[0].trigger()
                dialog = pet.ui.appearance
                report["menu_opens_dialog"] = dialog.isVisible()
                dialog.picker.setOption(QFileDialog.Option.DontUseNativeDialog, True)
                dialog.choose.click()
                dialog.picker.selectFile(str(source))
                dialog.picker.accept()
                assert wait_until(lambda: not dialog.loading and bool(dialog.candidate))
                report["picker_imports_animation"] = dialog.candidate.endswith(".apng")
                initial = dialog.preview.index
                report["preview_animates"] = wait_until(lambda: dialog.preview.index != initial)
                report["preview_does_not_apply"] = pet.settings.avatar_image == ""
                dialog.preview.index = 0
                dialog.preview.timer.stop()
                dialog.grab().save(str(output / "appearance-menu.png"))
                avatar_pos = pet.avatar.pos()
                pet.panel.persona.name.setText("未保存的名字")
                dialog.apply_button.click()
                assert wait_until(lambda: not dialog.saving)
                identifier = pet.settings.avatar_image
                assert identifier
                report["live_switch_without_moving"] = (
                    pet.avatar.image_id == identifier and pet.avatar.pos() == avatar_pos
                )
                report["unsaved_persona_preserved"] = (
                    pet.panel.persona.name.text() == "未保存的名字" and pet.settings.name == "玄司"
                )
                report["original_timing_loaded"] = pet.avatar.durations == [80, 160, 100]
                report["settings_persisted"] = load_settings(setting_path).avatar_image == identifier
                dialog.close()
                report["hidden_preview_stops"] = not dialog.preview.timer.isActive()
                source.unlink()
                restarted = Avatar(settings.pet_size, load_settings(setting_path).avatar_image)
                report["reload_without_original"] = restarted.native_animation and restarted.durations == [
                    80,
                    160,
                    100,
                ]
                restarted.hide()

                # 模拟副本丢失后重新导入同一素材，内容标识相同也应能刷新缓存。
                assets.image_path(identifier).unlink()
                restarted.set_image(identifier, force=True)
                report["missing_copy_falls_back"] = not restarted.native_animation
                frames[0].save(
                    source, save_all=True, append_images=frames[1:], duration=[80, 160, 100], loop=0
                )
                pet.ui.open_appearance()
                previous_cache = pet.avatar.frames
                dialog.import_file(str(source))
                assert wait_until(lambda: not dialog.loading)
                assert dialog.candidate == identifier and dialog.apply_button.isEnabled()
                dialog.apply_button.click()
                assert wait_until(lambda: not dialog.saving)
                report["reimport_same_image_refreshes"] = (
                    pet.avatar.native_animation and pet.avatar.frames is not previous_cache
                )
                dialog.close()

                pet.avatar.clock.stop()
                pet.avatar.frame = 2
                pet.avatar._frame_mask()
                QTest.qWait(50)
                rect = wintypes.RECT()
                USER32.GetWindowRect(int(pet.avatar.winId()), ctypes.byref(rect))
                hwnd = USER32.WindowFromPoint(
                    wintypes.POINT((rect.left + rect.right) // 2, (rect.top + rect.bottom) // 2)
                )
                report["fully_transparent_frame_passes_clicks"] = hwnd != int(pet.avatar.winId())
                pet.avatar.frame = 0
                pet.avatar._frame_mask()
                report["next_frame_restores_click_region"] = (
                    not pet.avatar.mask().isEmpty() and not pet.avatar.mask().contains(QPoint(0, 0))
                )
                # 只制造临时设置保存失败，确认当前动图、已存设置都仍然有效。
                pet.ui.open_appearance()
                dialog.use_default()
                normal_save = runtime_module.save_settings
                runtime_module.save_settings = lambda _: (_ for _ in ()).throw(OSError("test disk error"))
                dialog.apply_button.click()
                assert wait_until(lambda: not dialog.saving)
                report["failed_save_keeps_old_shape"] = (
                    pet.settings.avatar_image == identifier
                    and pet.avatar.image_id == identifier
                    and load_settings(setting_path).avatar_image == identifier
                )
                runtime_module.save_settings = normal_save
                dialog.apply_button.click()
                assert wait_until(lambda: not dialog.saving)
                report["restore_default_persists"] = (
                    pet.settings.avatar_image == ""
                    and not pet.avatar.native_animation
                    and load_settings(setting_path).avatar_image == ""
                )
                report["microphone_stays_off"] = not pet.runtime.listening
                dialog.close()
                # 后台导入尚未返回时按 Esc，迟到结果不得替换当前形象。
                delayed = temporary / "late.png"
                frames[0].save(delayed)
                release, completed = threading.Event(), threading.Event()

                def slow_import(path):
                    assert release.wait(2)
                    result = original_import(path, asset_dir)
                    completed.set()
                    return result

                dialog_module.import_image = slow_import
                pet.ui.open_appearance()
                dialog.import_file(str(delayed))
                dialog.reject()
                release.set()
                assert wait_until(completed.is_set)
                QTest.qWait(50)
                report["closed_menu_rejects_late_import"] = (
                    dialog.candidate == "" and pet.settings.avatar_image == ""
                )
                report["all_passed"] = all(report.values())
            except Exception as exc:
                logging.exception("形象菜单验收失败")
                report["error"] = type(exc).__name__
            finally:
                if restarted is not None:
                    restarted.clock.stop()
                    restarted.hide()
                    restarted.bubble.hide()
                pet.quit()
                (output / "appearance-menu-report.json").write_text(
                    json.dumps(report, indent=2), encoding="utf-8"
                )
                print(json.dumps(report, indent=2))

        QTimer.singleShot(300, inspect)
        app.exec()
        pet.runtime.loop.call_soon_threadsafe(pet.runtime.loop.stop)
        pet.runtime.thread.join(2)
        assert report.get("all_passed"), report


if __name__ == "__main__":
    main()
