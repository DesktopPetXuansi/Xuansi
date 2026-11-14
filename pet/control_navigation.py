"""宽窗口侧栏与窄窗口标签共用页面和选中状态。"""

import logging

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QFrame, QHBoxLayout, QPushButton, QStackedWidget, QTabBar, QVBoxLayout

from .control_section import ControlSection

LOG = logging.getLogger(__name__)
TAB_LABELS = ("对话", "人设", "记忆", "语音与行为", "模型设置", "更换形象", "官网资源", "模型上传", "运行日志")
COMPACT_LABELS = {
    "preferences": "语音", "model": "模型", "appearance": "形象", "logs": "日志",
}


class ControlNavigation(QObject):
    opening = Signal(str)

    def __init__(self, sections, parent):
        super().__init__(parent)
        self.header = QFrame(parent)
        self.header.setObjectName("browserTabStrip")
        layout = QHBoxLayout(self.header)
        layout.setContentsMargins(8, 4, 8, 0)
        self.bar = QTabBar()
        self.bar.setObjectName("controlTabs")
        self.bar.setAccessibleName("控制中心功能标签")
        self.bar.setExpanding(False)
        self.bar.setUsesScrollButtons(True)
        self.bar.setElideMode(Qt.TextElideMode.ElideRight)
        self.bar.setDocumentMode(True)
        layout.addWidget(self.bar, 1)
        self.sidebar = QFrame(parent)
        self.sidebar.setObjectName("controlSidebar")
        self.sidebar.setFixedWidth(166)
        rail = QVBoxLayout(self.sidebar)
        rail.setContentsMargins(12, 16, 12, 12)
        rail.setSpacing(4)
        self.buttons = {}
        self.stack = QStackedWidget(parent)
        self.stack.setObjectName("controlStack")
        self.pages = {}
        for (key, title), label in zip(sections, TAB_LABELS, strict=True):
            page = ControlSection(key, title)
            self.pages[key] = page
            self.stack.addWidget(page)
            # 资源管理与分享是形象页的次级流程，仍保留固定页面和后台任务。
            if key in ('resources', 'upload'):
                continue
            index = self.bar.addTab(COMPACT_LABELS.get(key, label))
            self.bar.setTabData(index, key)
            self.bar.setTabToolTip(index, title)
            button = QPushButton(label)
            button.setObjectName("sidebarItem")
            button.setCheckable(True)
            button.setToolTip(title)
            button.clicked.connect(lambda _checked, key=key: self.select(key))
            self.buttons[key] = button
            rail.addWidget(button)
        rail.addStretch()
        # 首个 addTab 也会触发 currentChanged；映射准备完成后再连接。
        self.bar.currentChanged.connect(self._activate)
        self.bar.tabBarClicked.connect(self._clicked)
        self._activate(0)
        self.shortcuts = []
        for sequence, step in (("Ctrl+Tab", 1), ("Ctrl+Shift+Tab", -1)):
            shortcut = QShortcut(QKeySequence(sequence), parent)
            shortcut.activated.connect(lambda step=step: self._cycle(step))
            self.shortcuts.append(shortcut)

    @property
    def current_key(self):
        return self.stack.currentWidget().key

    def select(self, key):
        parent_key = 'appearance' if key in ('resources', 'upload') else key
        index = next(index for index in range(self.bar.count()) if self.bar.tabData(index) == parent_key)
        if self.current_key == key:
            self.buttons[parent_key].setChecked(True)
            return
        self.bar.blockSignals(True)
        self.bar.setCurrentIndex(index)
        self.bar.blockSignals(False)
        self._show(key)

    def _cycle(self, step):
        self.bar.setCurrentIndex((self.bar.currentIndex() + step) % self.bar.count())

    def _activate(self, index):
        key = self.bar.tabData(index)
        self._show(key)

    def _clicked(self, index):
        # 次页共用形象标签，再点已高亮的标签也能直接回到选择与预览。
        if self.current_key in ('resources', 'upload') and self.bar.tabData(index) == 'appearance':
            self.select('appearance')

    def _show(self, key):
        # 先准备预览，再显示目标页；切换只改变显隐，不重新挂载 GL 子控件。
        self.opening.emit(key)
        self.stack.setCurrentWidget(self.pages[key])
        selected = 'appearance' if key in ('resources', 'upload') else key
        for name, button in self.buttons.items():
            button.setChecked(name == selected)
        LOG.info("控制中心切换标签 key=%s", key)

    def resize(self, width):
        wide = width >= 720
        focus = self.bar.hasFocus() if wide else any(button.hasFocus() for button in self.buttons.values())
        self.header.setVisible(not wide)
        self.sidebar.setVisible(wide)
        if focus:
            target = self.buttons[self.bar.tabData(self.bar.currentIndex())] if wide else self.bar
            target.setFocus(Qt.FocusReason.OtherFocusReason)
