"""托盘、热键和快捷窗口协调；设置保存与热键切换作为一次事务完成。"""

import logging
from dataclasses import replace

from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from .appearance_dialog import AppearanceDialog
from .config import ROOT
from .hotkey import GlobalHotkey
from .panel import STYLE
from .quick_chat import QuickChat

LOG = logging.getLogger(__name__)


class CompanionUI:
    def __init__(self, owner):
        self.owner = owner
        self.saving = False
        self.appearance_only = False
        self.closed = False
        self.quick = QuickChat(owner.settings, STYLE)
        self.quick.send_requested.connect(owner.send)
        self.quick.voice_requested.connect(owner.voice)
        owner.panel.message_added.connect(self.quick.append)
        owner.panel.with_screen.toggled.connect(self.quick.with_screen.setChecked)
        self.quick.with_screen.toggled.connect(owner.panel.with_screen.setChecked)
        self.hotkey = GlobalHotkey(owner.application, self.quick.toggle)
        try:
            self.hotkey.stage(owner.settings.chat_hotkey)
            self.hotkey.commit()
        except ValueError as exc:
            owner.panel.status.setText(str(exc))
        owner.panel.settings_requested.connect(self.save)
        owner.runtime.settings_saved.connect(self.saved)
        self.appearance = AppearanceDialog(owner.panel)
        self.appearance.apply_requested.connect(self.save_appearance)
        owner.panel.appearance_requested.connect(self.open_appearance)
        self.tray = self._tray()
        self.refresh_icon()

    def open_appearance(self):
        self.appearance.present(self.owner.settings.avatar_image)

    def save_appearance(self, identifier):
        if self.saving:
            self.appearance.saved("配置正在保存，请稍后应用形象")
            return
        self.save(replace(self.owner.settings, avatar_image=identifier), appearance_only=True)
        if not self.saving:
            self.appearance.saved(self.owner.panel.status.text())

    def refresh_icon(self):
        if self.owner.settings.avatar_image:
            frames = self.owner.avatar.frames["idle"]
            pixmap = next(pix for pix, region in frames if not region.isEmpty())
            self.tray.setIcon(QIcon(pixmap))
        else:
            self.tray.setIcon(QIcon(str(ROOT / "assets/xuansi/icon.png")))

    def _tray(self):
        pet = self.owner
        tray = QSystemTrayIcon(QIcon(str(ROOT / "assets/xuansi/icon.png")), pet)
        tray.setToolTip(f"{pet.settings.name} · 本地桌宠")
        menu = QMenu()
        for text, slot in [
            ("快捷对话", self.quick.toggle),
            ("打开对话与设置", pet.open_panel),
            ("配置：模型参数与快捷键", pet.panel.open_configuration),
            ("日志：运行日志", pet.panel.open_logs),
            ("形象：更换桌宠形象", self.open_appearance),
            ("开启/关闭连续对话", pet.toggle_voice),
            ("看一眼屏幕", pet.look),
            ("休眠/唤醒", pet.toggle_sleep),
            ("退出", pet.quit),
        ]:
            action = QAction(text, menu)
            action.triggered.connect(slot)
            menu.addAction(action)
        tray.setContextMenu(menu)
        tray.activated.connect(
            lambda reason: (
                pet.open_panel() if reason == QSystemTrayIcon.ActivationReason.DoubleClick else None
            )
        )
        tray.show()
        return tray

    def save(self, settings, appearance_only=False):
        if self.saving:
            return
        try:
            settings.validate()
            if not appearance_only:
                self.hotkey.stage(settings.chat_hotkey)
        except ValueError as exc:
            self.owner.panel.status.setText(str(exc))
            return
        self.saving = True
        self.appearance_only = appearance_only
        self.owner.panel.saving(True)
        self.owner.panel.status.setText("正在保存配置…")
        self.owner.runtime.persist(settings, validate_models=not appearance_only)

    def saved(self, settings, error):
        if self.closed:
            return
        self.saving = False
        self.owner.panel.saving(False)
        if not self.appearance_only:
            if error:
                self.hotkey.rollback()
            else:
                self.hotkey.commit()
        if not error:
            self.quick.setWindowTitle(f"{settings.name} · 快捷对话")
        self.owner.apply_settings(settings, error)
        self.appearance.saved(error)

    def refresh(self):
        status = self.owner.runtime.audio_activity.status
        if self.hotkey.active is None:
            status += " · 热键不可用，请到配置更改"
        self.owner.panel.audio_status.setText(status)
        self.quick.audio_status.setText(status)

    def close(self):
        self.closed = True
        self.hotkey.close()
        self.quick.hide()
        self.owner.panel.logs.hide()
        self.appearance.close()
        self.tray.hide()
        LOG.info("快捷窗口关闭，热键已注销")
