"""托盘和热键统一唤起控制中心；设置与形象继续经原事务保存。"""

import logging
from dataclasses import replace

from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from .appearance_dialog import AppearanceDialog
from .config import ROOT
from .hotkey import GlobalHotkey
from .platform_dialog import PlatformDialog

LOG = logging.getLogger(__name__)


class CompanionUI:
    def __init__(self, owner):
        self.owner = owner
        self.saving = False
        self.appearance_only = False
        self.hotkey_staged = False
        self.closed = False
        self.hotkey = GlobalHotkey(owner.application, owner.panel.toggle)
        try:
            self.hotkey.stage(owner.settings.chat_hotkey)
            self.hotkey.commit()
        except ValueError as exc:
            owner.panel.status.setText(str(exc))
        owner.panel.settings_requested.connect(self.save)
        owner.panel.audio_avoidance_action.triggered.connect(self.toggle_avoidance)
        owner.runtime.settings_saved.connect(self.saved)
        owner.runtime.speech_changed.connect(self.refresh)
        self.appearance = AppearanceDialog(owner.panel, embedded=True)
        self.appearance.apply_requested.connect(self.save_appearance)
        owner.panel.mount_section("appearance", self.appearance,
                                  on_open=lambda: self.appearance.present(owner.settings.avatar_image))
        self.platform = PlatformDialog(owner, embedded=True)
        owner.panel.mount_section("resources", self.platform, on_open=self.resources_opened)
        owner.panel.upload_requested.connect(self.platform.open_upload)
        # 先显示角色创建 GL 上下文，再异步恢复本机已安装模型。
        from PySide6.QtCore import QTimer

        QTimer.singleShot(250, self.platform.restore_saved)
        self.tray = self._tray()
        self.refresh_icon()
        self.refresh()

    def toggle_avoidance(self, enabled):
        # QAction 的 triggered 才是用户操作；恢复勾选不会再次触发保存。
        self.owner.panel.audio_avoidance_action.setChecked(self.owner.settings.audio_avoidance)
        self.save(replace(self.owner.settings, audio_avoidance=enabled), avoidance_only=True)

    def open_appearance(self):
        self.owner.panel.open_section("appearance")

    def resources_opened(self):
        # 展开和重新显示只刷新空闲资源列表，不抢占上传或正在保存的模型选择。
        if self.platform.worker is None and self.platform.pending_settings is None and not self.platform.shutting_down:
            self.platform.refresh_local()

    def save_appearance(self, identifier):
        if self.saving:
            self.appearance.saved("配置正在保存，请稍后应用形象")
            return
        self.save(replace(self.owner.settings, avatar_image=identifier, platform_model_version="",
                          platform_expression_version=""), appearance_only=True)
        if not self.saving:
            self.appearance.saved(self.owner.panel.status.text())

    def refresh_icon(self):
        if self.owner.settings.avatar_image:
            frames = self.owner.avatar.frames["idle"]
            pixmap = next(pix for pix, region in frames if not region.isEmpty())
            icon = QIcon(pixmap)
        else:
            icon = QIcon(str(ROOT / "assets/xuansi/icon.png"))
        # 任务栏取窗口图标；更新应用默认图标，让已有及随后打开的窗口一起继承。
        self.owner.application.setWindowIcon(icon)
        self.tray.setIcon(icon)
        LOG.info("窗口与托盘图标已同步 custom=%s", bool(self.owner.settings.avatar_image))

    def _tray(self):
        pet = self.owner
        tray = QSystemTrayIcon(QIcon(str(ROOT / "assets/xuansi/icon.png")), pet)
        tray.setToolTip(f"{pet.settings.name} · 本地桌宠")
        menu = QMenu()
        for text, slot in [
            ("打开控制中心", pet.open_panel),
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

    def save(self, settings, appearance_only=False, avoidance_only=False):
        if self.saving:
            return
        try:
            settings.validate()
            if not (appearance_only or avoidance_only):
                self.hotkey.stage(settings.chat_hotkey)
        except ValueError as exc:
            self.owner.panel.form.complete(str(exc))
            return
        self.saving = True
        self.appearance_only = appearance_only
        self.hotkey_staged = not (appearance_only or avoidance_only)
        self.owner.panel.saving(True)
        self.owner.panel.audio_avoidance_action.setEnabled(False)
        self.owner.panel.status.setText("正在保存配置…")
        platform_changes = ({"platform_model_version": settings.platform_model_version,
                             "platform_expression_version": settings.platform_expression_version,
                             "avatar_image": settings.avatar_image}
                            if appearance_only else None)
        self.owner.runtime.persist(settings, validate_models=not (appearance_only or avoidance_only),
                                   platform_changes=platform_changes)

    def saved(self, settings, error):
        if self.closed:
            return
        self.saving = False
        self.owner.panel.saving(False)
        self.owner.panel.audio_avoidance_action.setEnabled(True)
        if self.hotkey_staged:
            if error:
                self.hotkey.rollback()
            else:
                self.hotkey.commit()
        # 保留本次保存的用途，不能仅凭字段差异判断；相同图片仍需重新加载。
        self.owner.apply_settings(settings, error, appearance_only=self.appearance_only)
        self.owner.panel.form.complete(error)
        self.owner.panel.audio_avoidance_action.setChecked(self.owner.settings.audio_avoidance)
        if self.appearance_only:
            self.appearance.saved(error)

    def refresh(self):
        status = self.owner.runtime.audio_activity.status
        enabled = self.owner.runtime.should_speak(self.owner.settings)
        speech = "回复朗读已开启" if enabled else "回复朗读已关闭"
        status = speech + " · " + status
        if self.hotkey.active is None:
            status += " · 热键不可用，请到配置更改"
        self.owner.panel.audio_status.setText(status)
        panel = self.owner.panel
        panel.speech_button.blockSignals(True)
        panel.speech_button.setChecked(enabled)
        panel.speech_button.setText("朗读开启" if enabled else "朗读关闭")
        panel.speech_button.blockSignals(False)
        panel.stop_button.setEnabled(self.owner.busy)

    def close(self):
        self.closed = True
        self.hotkey.close()
        self.owner.panel.logs.hide()
        self.appearance.close()
        self.platform.shutdown()
        self.tray.hide()
        LOG.info("控制中心退出，热键已注销")
