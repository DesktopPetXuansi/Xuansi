"""桌面主题的唯一 QSS 来源：暖白、草绿与清楚的原生控件状态。"""

from pathlib import Path
from string import Template

from PySide6.QtCore import Qt

# 对应控制中心 HTML 原型的 light-dark() 变量。
COLORS = {
    "background": "#fcfbf7",
    "surface": "#f2f3ea",
    "text": "#232c24",
    "muted": "#59655a",
    "accent": "#31583f",
    "on_accent": "#ffffff",
    "selected": "#dde8da",
    "sidebar": "#eeefe7",
    "border": "#dce1d6",
    "art": "#dce6d7",
    "halo": "#ecf0df",
    "amber": "#805b2e",
    "disabled": "#7d8779",
    "danger": "#984735",
    "check_fill": "#31583f",
    "scroll_thumb": "#899b89",
    "scroll_hover": "#647f68",
}

DARK_COLORS = {
    "background": "#202622",
    "surface": "#2b342d",
    "text": "#edf1e7",
    "muted": "#b3c0b4",
    "accent": "#adc9a7",
    "on_accent": "#182a1c",
    "selected": "#3b4c3d",
    "sidebar": "#262e28",
    "border": "#404b42",
    "art": "#36483c",
    "halo": "#526351",
    "amber": "#edbc83",
    "disabled": "#89988c",
    "danger": "#f0a591",
    "check_fill": "#3b4c3d",
    "scroll_thumb": "#748b76",
    "scroll_hover": "#93ab91",
}


def colors_for(scheme):
    return DARK_COLORS if scheme == Qt.ColorScheme.Dark else COLORS


_TEMPLATE = Template("""
QWidget { background: $background; color: $text; font: 10.5pt "Microsoft YaHei UI"; }
QLabel#title { font-size: 16pt; font-weight: 600; }
QLabel#productName { font-size: 15pt; font-weight: 600; }
QLabel#sectionTitle { font-size: 16pt; font-weight: 600; }
QLabel#subsectionTitle { font-weight: 600; }
QLabel#hint { color: $muted; font-size: 9.5pt; }
QLabel#status { color: $muted; font-size: 9.5pt; }
QFrame#panelHeader { border-bottom: 1px solid $border; }
QFrame#panelFooter { border-top: 1px solid $border; }
QFrame#controlSidebar, QFrame#controlInspector { background: $sidebar; }
QFrame#controlSidebar { border-right: 1px solid $border; }
QFrame#controlInspector { border-left: 1px solid $border; }
QFrame#controlInspector QLabel { background: transparent; }
QFrame#controlInspector QLabel#inspectorPortrait { background: $art; border-radius: 14px; }
QFrame#firstChatCard { background: $surface; border: 1px solid $border; border-radius: 13px; }
QWidget#firstChatBody, QFrame#firstChatCard QLabel { background: transparent; }
QFrame#browserTabStrip { background: $sidebar; border-bottom: 1px solid $border; }
QTabBar#controlTabs { background: transparent; }
QTabBar#controlTabs::tab { background: $sidebar; color: $muted; border: 0;
    border-radius: 7px; padding: 6px 10px; margin: 0 3px 4px 0; min-width: 48px; }
QTabBar#controlTabs::tab:hover { background: $selected; color: $accent; }
QTabBar#controlTabs::tab:selected { background: $selected; color: $accent; font-weight: 600; }
QTabBar#controlTabs::tab:focus { text-decoration: underline; }
QTabBar#controlTabs QToolButton { background: $sidebar; border: 0; padding: 6px; }
QTabBar#controlTabs QToolButton:hover { background: $selected; }
QMenu { background: $surface; border: 1px solid $border; padding: 4px; }
QMenu::item { padding: 8px 16px; border-radius: 4px; }
QMenu::item:selected { background: $selected; }
QPushButton, QToolButton#avoidance { background: $background; border: 1px solid $border;
    border-radius: 6px; padding: 6px 10px; min-height: 18px; }
QPushButton:hover, QToolButton#avoidance:hover { border-color: $accent; }
QPushButton:focus, QToolButton#avoidance:focus { border-color: $accent; }
QPushButton:checked, QToolButton#avoidance:checked { background: $selected; color: $accent; border-color: $border; }
QPushButton:pressed, QToolButton#avoidance:pressed { background: $sidebar; }
QPushButton#sidebarItem { text-align: left; padding: 9px 12px; background: transparent;
    border: 1px solid transparent; color: $muted; }
QPushButton#sidebarItem:hover, QPushButton#sidebarItem:checked { background: $selected; color: $accent; }
QPushButton#sidebarItem:checked { font-weight: 600; }
QPushButton#sidebarItem:focus { border-color: $accent; }
QPushButton#primary, QPushButton[primary="true"] { background: $accent; color: $on_accent; border-color: $accent; }
QPushButton#primary:hover, QPushButton[primary="true"]:hover { border-color: $text; }
QPushButton#primary:focus, QPushButton[primary="true"]:focus { border: 2px solid $text; padding: 5px 9px; }
QPushButton#quiet { border-color: transparent; color: $muted; }
QPushButton#quiet:focus { border-color: $accent; }
QPushButton#danger { color: $danger; }
QPushButton#danger:hover, QPushButton#danger:focus { background: $surface; border-color: $danger; }
QPushButton:disabled, QToolButton#avoidance:disabled,
QPushButton#primary:disabled, QPushButton[primary="true"]:disabled {
    background: $sidebar; color: $disabled; border-color: $border; }
QLineEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox, QKeySequenceEdit, QListWidget {
    background: $surface; border: 1px solid $border; border-radius: 6px;
    padding: 6px; selection-background-color: $accent; selection-color: $on_accent; }
QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus,
QComboBox:focus, QKeySequenceEdit:focus, QListWidget:focus { border-color: $accent; }
QPlainTextEdit#conversationHistory { background: $background; border: 1px solid transparent;
    border-radius: 8px; padding: 8px; placeholder-text-color: $muted; }
QPlainTextEdit#conversationHistory:focus { border-color: $accent; }
QLineEdit#messageComposer { background: $background; border-radius: 8px; padding: 8px 10px;
    placeholder-text-color: $muted; }
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled {
    background: $sidebar; color: $disabled; }
QCheckBox { spacing: 8px; padding: 2px 0; }
QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid $muted;
    border-radius: 3px; background: $surface; }
QCheckBox::indicator:checked { background: $check_fill; border-color: $accent; image: url("$check_icon"); }
QCheckBox::indicator:disabled { background: $selected; border-color: $border; }
QCheckBox:focus { color: $accent; text-decoration: underline; }
QCheckBox:disabled { color: $disabled; }
QGroupBox { border: 1px solid $border; border-radius: 8px; margin-top: 12px; padding-top: 8px; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 4px; color: $accent; }
QScrollArea { border: 0; }
QScrollBar:vertical, QScrollBar:horizontal { background: $surface; border: 0;
    border-radius: 5px; margin: 0; }
QScrollBar:vertical { width: 10px; }
QScrollBar:horizontal { height: 10px; }
QScrollBar::handle:vertical, QScrollBar::handle:horizontal { background: $scroll_thumb;
    border-radius: 4px; }
QScrollBar::handle:vertical { min-height: 30px; margin: 2px 1px; }
QScrollBar::handle:horizontal { min-width: 30px; margin: 1px 2px; }
QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover { background: $scroll_hover; }
QScrollBar::handle:vertical:pressed, QScrollBar::handle:horizontal:pressed { background: $accent; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; border: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
QAbstractScrollArea::corner { background: $surface; }
QProgressBar { background: $surface; border: 1px solid $border; border-radius: 5px;
    text-align: center; min-height: 18px; }
QProgressBar::chunk { background: $accent; border-radius: 4px; }
QToolButton#advancedSettings { color: $accent; background: transparent; border: 1px solid transparent;
    border-radius: 6px; padding: 6px; min-height: 18px; }
QToolButton#advancedSettings:hover { background: $selected; }
QToolButton#advancedSettings:focus { border-color: $accent; background: $selected; }
QToolTip { background: $surface; color: $text; border: 1px solid $border; padding: 6px; }
""")
_CHECK_ICON = (Path(__file__).resolve().parents[1] / "assets/ui/check.svg").as_posix()
STYLE = _TEMPLATE.substitute(COLORS, check_icon=_CHECK_ICON)
DARK_STYLE = _TEMPLATE.substitute(DARK_COLORS, check_icon=_CHECK_ICON)


def style_for(scheme):
    return DARK_STYLE if scheme == Qt.ColorScheme.Dark else STYLE
