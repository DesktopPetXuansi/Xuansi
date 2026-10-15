"""浏览器式标签导航：固定内容页，所有入口共用同一切换路径。"""

import logging

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QActionGroup, QKeySequence, QShortcut
from PySide6.QtWidgets import QFrame, QHBoxLayout, QMenu, QStackedWidget, QTabBar, QToolButton

from .control_section import ControlSection

LOG = logging.getLogger(__name__)
TAB_LABELS = ("对话", "人设", "记忆", "语音与行为", "模型设置", "桌宠形象", "官网资源", "模型上传", "运行日志")


class ControlNavigation(QObject):
    opening = Signal(str)

    def __init__(self, sections, parent):
        super().__init__(parent)
        self.header = QFrame(parent)
        self.header.setObjectName("browserTabStrip")
        layout = QHBoxLayout(self.header)
        layout.setContentsMargins(8, 8, 8, 0)
        layout.setSpacing(6)
        self.overflow_button = QToolButton()
        self.overflow_button.setObjectName("tabListButton")
        self.overflow_button.setArrowType(Qt.ArrowType.DownArrow)
        self.overflow_button.setAccessibleName("全部功能标签")
        self.overflow_button.setToolTip("全部功能标签")
        self.overflow_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.menu = QMenu(self.overflow_button)
        self.menu_group = QActionGroup(self.menu)
        self.menu_group.setExclusive(True)
        self.overflow_button.setMenu(self.menu)
        layout.addWidget(self.overflow_button)
        self.bar = QTabBar()
        self.bar.setObjectName("controlTabs")
        self.bar.setAccessibleName("控制中心功能标签")
        self.bar.setExpanding(False)
        self.bar.setUsesScrollButtons(True)
        self.bar.setElideMode(Qt.TextElideMode.ElideRight)
        self.bar.setDocumentMode(True)
        layout.addWidget(self.bar, 1)
        self.stack = QStackedWidget(parent)
        self.stack.setObjectName("controlStack")
        self.pages = {}
        for (key, title), label in zip(sections, TAB_LABELS, strict=True):
            page = ControlSection(key, title)
            self.pages[key] = page
            self.stack.addWidget(page)
            index = self.bar.addTab(label)
            self.bar.setTabData(index, key)
            self.bar.setTabToolTip(index, title)
            action = self.menu.addAction(title)
            action.setData(key)
            action.setCheckable(True)
            # 当前标签再次被点击时也保持勾选，菜单始终只有一个选中项。
            self.menu_group.addAction(action)
            action.triggered.connect(lambda checked=False, index=index: self.bar.setCurrentIndex(index))
        # 首个 addTab 也会触发 currentChanged；映射准备完成后再连接。
        self.bar.currentChanged.connect(self._activate)
        self._activate(0)
        self.shortcuts = []
        for sequence, step in (("Ctrl+Tab", 1), ("Ctrl+Shift+Tab", -1)):
            shortcut = QShortcut(QKeySequence(sequence), parent)
            shortcut.activated.connect(lambda step=step: self._cycle(step))
            self.shortcuts.append(shortcut)

    @property
    def current_key(self):
        return self.bar.tabData(self.bar.currentIndex())

    def select(self, key):
        self.bar.setCurrentIndex(self.stack.indexOf(self.pages[key]))

    def _cycle(self, step):
        self.bar.setCurrentIndex((self.bar.currentIndex() + step) % self.bar.count())

    def _activate(self, index):
        key = self.bar.tabData(index)
        # 先准备预览，再显示目标页；切换只改变显隐，不重新挂载 GL 子控件。
        self.opening.emit(key)
        self.stack.setCurrentIndex(index)
        for position, action in enumerate(self.menu.actions()):
            action.setChecked(position == index)
        LOG.info("控制中心切换标签 key=%s", key)
