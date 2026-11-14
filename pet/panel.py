"""自适应控制中心，复用现有表单与保存事务。"""

import logging
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from .config import Settings
from .control_navigation import ControlNavigation
from .panel_chrome import create_footer, create_header, create_inspector
from .panel_content import populate_sections
from .panel_settings import PanelSettings
from .panel_style import style_for
from .panel_window import restore_size, save_size
from .theme import configure_fonts

LOG = logging.getLogger(__name__)
SECTIONS = (
    ("chat", "对话"), ("persona", "人设与提示词"), ("memory", "长期记忆"),
    ("preferences", "语音与行为"), ("model", "模型与快捷键"), ("appearance", "更换形象"),
    ("resources", "官网资源"), ("upload", "上传本地 Live2D"), ("updates", "更新中心"), ("logs", "运行日志"),
)


class Panel(QWidget):
    send_requested = Signal(str, bool)
    voice_requested = Signal(bool)
    look_requested = Signal()
    screen_mode_requested = Signal(str)
    automatic_observation_requested = Signal(bool)
    quiet_requested = Signal(bool)
    sleep_requested = Signal()
    settings_requested = Signal(object)
    memory_requested = Signal(str)
    memory_change_requested = Signal(str, str, int, str)
    preview_requested = Signal(object)
    upload_requested = Signal()
    stop_requested = Signal()
    speech_requested = Signal(bool)
    feedback_requested = Signal()
    configuration_required = Signal()

    def __init__(self, settings: Settings, *, window_state_path: Path | None = None, settings_warning=""):
        super().__init__()
        configure_fonts(QApplication.instance())
        self.settings = settings
        self.model_setup_required = False
        self.setWindowTitle(f"{settings.name} · 控制中心")
        self.window_state_path = window_state_path
        self.setMinimumSize(520, 480)
        restore_size(self, window_state_path)
        self._opening_callbacks = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.navigation = ControlNavigation(SECTIONS, self)
        self.sections = self.navigation.pages
        self.navigation.opening.connect(self._prepare)
        layout.addWidget(create_header(self))
        layout.addWidget(self.navigation.header)
        work_area = QHBoxLayout()
        work_area.setSpacing(0)
        work_area.addWidget(self.navigation.sidebar)
        work_area.addWidget(self.navigation.stack, 1)
        self.inspector = create_inspector(self)
        work_area.addWidget(self.inspector)
        layout.addLayout(work_area, 1)
        populate_sections(self)
        self.form = PanelSettings(self, warning=settings_warning)
        layout.addWidget(create_footer(self))
        self.escape = QShortcut(QKeySequence("Esc"), self)
        self.escape.activated.connect(self.close)
        hints = QApplication.styleHints()
        hints.colorSchemeChanged.connect(self._apply_color_scheme)
        self._apply_color_scheme(hints.colorScheme())
        self._resize_layout()
        LOG.info("控制中心布局已就绪")

    def _apply_color_scheme(self, scheme):
        self.setStyleSheet(style_for(scheme))
        for widget in (self.inspector_avatar, self.model_readiness):
            widget.scheme = scheme
            widget.update()

    def _resize_layout(self):
        self.navigation.resize(self.width())
        self.inspector.setVisible(self.width() >= 980)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'inspector'):
            self._resize_layout()

    def mount_section(self, key, widget, on_open=None):
        self._opening_callbacks[key] = on_open
        self.sections[key].set_widget(widget)

    def _prepare(self, key):
        callback = self._opening_callbacks.get(key)
        if self.isVisible() and callback is not None:
            callback()

    def open_section(self, key):
        self.navigation.select(key)
        self.show()
        self.raise_()
        self.activateWindow()
        LOG.info("打开控制中心标签 key=%s", key)

    def collapse_section(self, key):
        # 内嵌表单的返回/关闭只离开当前标签，退出时不能重新显示主窗口。
        if self.navigation.current_key == key and key != "chat":
            self.navigation.select('appearance' if key in ('resources', 'upload') else 'chat')

    def open_configuration(self):
        self.open_section("model")

    def open_logs(self):
        self.open_section("logs")

    def toggle(self):
        if self.isVisible() and self.isActiveWindow():
            self.close()
        else:
            self.open_section("chat")
            self.input.setFocus(Qt.FocusReason.ShortcutFocusReason)

    def _clear_memory(self):
        if self._confirm_forget("清空全部长期记忆？"):
            self._memory_draft_base = self.memory_entries
            self.memory.clear()
            self.memory_requested.emit("")

    def _confirm_forget(self, question):
        return QMessageBox.question(
            self, "彻底遗忘",
            question + "\n将删除旧修订和迁移副本，并清除当前推理上下文。"
            "已显示的原始聊天仍可在对话页查看。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        ) == QMessageBox.StandardButton.Yes

    def set_memory_entries(self, entries):
        selected = self.memory_items.currentData()
        old_entry = next((item for item in self.memory_entries if item.id == selected), None)
        new_entry = next((item for item in entries if item.id == selected), None)
        previous = "\n".join(item.text for item in self.memory_entries)
        if self.memory.toPlainText() == previous or self.memory.toPlainText() == self._submitted_memory:
            self.memory.setPlainText("\n".join(item.text for item in entries))
            self._memory_draft_base = entries
        self._submitted_memory = None
        self.memory_entries = entries
        self.memory_items.blockSignals(True)
        self.memory_items.clear()
        self.memory_items.addItem("选择要更正的记忆", None)
        for entry in entries:
            self.memory_items.addItem(entry.text[:72] or "空行", entry.id)
        self.memory_items.setCurrentIndex(max(0, self.memory_items.findData(selected)))
        self.memory_items.blockSignals(False)
        if old_entry != new_entry:
            self.memory_correction.clear()

    def _save_memory_draft(self):
        self._submitted_memory = self.memory.toPlainText()
        self.memory_requested.emit(self._submitted_memory)

    def _memory_action(self, action):
        selected = self.memory_items.currentData()
        entry = next((item for item in self.memory_entries if item.id == selected), None)
        if entry is None:
            return
        if action == "forget" and not self._confirm_forget("彻底遗忘所选记忆？"):
            return
        self.memory_change_requested.emit(action, entry.id, entry.revision, self.memory_correction.text())

    def _reload_memory_draft(self):
        self.memory.setPlainText("\n".join(item.text for item in self.memory_entries))
        self._memory_draft_base = self.memory_entries

    def _send(self):
        text = self.input.text().strip()
        if text:
            # 不把模型或 Key 草稿误当成已生效；保留文字，复用原来的保存事务。
            try:
                pending = (self.model_page.credential_changed()
                           or self.model_page.apply(self.settings) != self.settings)
            except ValueError:
                pending = True
            if self.form.saving or pending:
                note = '模型设置正在保存，请稍后回来发送。' if self.form.saving else '模型设置有未保存的修改。请先保存，再回到对话；输入内容已保留。'
                self.first_chat.set_note(note)
                self.first_chat.show()
                self.first_chat.toggle.setChecked(True)
                self.configuration_required.emit()
                self.open_section('model')
                LOG.info('发送前等待模型配置保存，已保留输入草稿')
                return
            if self.model_setup_required and self.settings.ai.policy == 'local_only':
                self.first_chat.show()
                self.first_chat.toggle.setChecked(True)
                self.status.setText('本机模型待准备，输入内容已保留。')
                return
            self.input.clear()
            self.send_requested.emit(text, self.with_screen.isChecked())

    def append(self, speaker: str, text: str):
        self.chat.appendPlainText(f"{speaker}\n{text}\n")
        self.chat.moveCursor(QTextCursor.MoveOperation.End)

    def screen_mode(self, mode):
        enabled = mode == "manual"
        self.screen_readiness.setText("屏幕分享 · 按轮确认" if enabled else "屏幕分享 · 已关闭")
        self.with_screen.setEnabled(enabled)
        self.look_button.setEnabled(enabled)
        self.with_screen.setChecked(False)
        self.screen_status.setText("")

    def take_screen_attachment(self):
        selected = self.with_screen.isEnabled() and self.with_screen.isChecked()
        self.with_screen.setChecked(False)
        return selected

    def voice_state(self, enabled, paused=False):
        self.voice_button.blockSignals(True)
        self.voice_button.setChecked(enabled)
        self.voice_button.setText("连续对话已暂停" if enabled and paused else "关闭连续对话" if enabled else "开启连续对话")
        self.voice_button.setToolTip("休眠期间暂停收音，唤醒后恢复；点击可取消恢复。" if enabled and paused else "")
        self.voice_button.blockSignals(False)

    def _save(self):
        self.form.request()

    def _preview(self):
        try:
            self.preview_requested.emit(self.preferences.apply(self.persona.apply(self.settings)).validate())
        except ValueError as exc:
            self.status.setText(str(exc))

    def saving(self, enabled):
        self.form.saving = enabled
        self.form.refresh()
        for button in (self.save_button, self.persona.save_button, self.preferences.save_button, self.model_page.save_button):
            button.setEnabled(not enabled)

    def showEvent(self, event):
        super().showEvent(event)
        self._prepare(self.navigation.current_key)

    def closeEvent(self, event):
        event.ignore()
        self.form.close()

    def hideEvent(self, event):
        super().hideEvent(event)
        # 配置保存完成、直接收起和退出统一走这里；忽略系统最小化的临时隐藏。
        if not event.spontaneous():
            save_size(self, self.window_state_path)
