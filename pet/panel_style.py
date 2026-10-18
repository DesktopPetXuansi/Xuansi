"""桌面主题的唯一 QSS 来源：暖白、草绿与清楚的原生控件状态。"""

from pathlib import Path
from string import Template

# 与 DESIGN.md 共享品牌含义；Qt 独立维护色值，不依赖官网或运行时样式重算。
COLORS = {
    "background": "#f7f5ef",
    "surface": "#fffef9",
    "text": "#28382e",
    "muted": "#5b675a",
    "accent": "#4c654e",
    "hover": "#edf1e8",
    "tabs": "#e3eadf",
    "border": "#d5dcd0",
    "disabled": "#7d8779",
    "danger": "#984735",
}

STYLE = Template("""
QWidget { background: $background; color: $text; font: 10.5pt "Microsoft YaHei UI"; }
QLabel#title { font-size: 16pt; font-weight: 600; }
QLabel#productName { font-size: 15pt; font-weight: 600; }
QLabel#sectionTitle { font-size: 14pt; font-weight: 600; }
QLabel#subsectionTitle { font-weight: 600; }
QLabel#hint { color: $muted; font-size: 9.5pt; }
QLabel#status { color: $muted; font-size: 9.5pt; }
QFrame#panelHeader { border-bottom: 1px solid $border; }
QFrame#panelFooter { border-top: 1px solid $border; }
QFrame#browserTabStrip { background: $tabs; border-bottom: 1px solid $border; }
QTabBar#controlTabs { background: transparent; }
QTabBar#controlTabs::tab { background: $tabs; color: $muted; border: 0;
    border-top-left-radius: 8px; border-top-right-radius: 8px;
    padding: 8px 10px; margin-right: 3px; min-width: 48px; }
QTabBar#controlTabs::tab:hover { background: $hover; color: $text; }
QTabBar#controlTabs::tab:selected { background: $background; color: $accent; font-weight: 600; }
QTabBar#controlTabs::tab:focus { text-decoration: underline; }
QTabBar#controlTabs QToolButton { background: $tabs; border: 0; padding: 6px; }
QTabBar#controlTabs QToolButton:hover { background: $hover; }
QMenu { background: $surface; border: 1px solid $border; padding: 4px; }
QMenu::item { padding: 8px 16px; border-radius: 4px; }
QMenu::item:selected { background: $hover; }
QPushButton, QToolButton#avoidance { background: $background; border: 1px solid $border;
    border-radius: 6px; padding: 6px 10px; min-height: 18px; }
QPushButton:hover, QToolButton#avoidance:hover { background: $hover; }
QPushButton:focus, QToolButton#avoidance:focus { border-color: $accent; background: $hover; }
QPushButton:checked, QToolButton#avoidance:checked { background: $hover; color: $accent; border-color: #91a08a; }
QPushButton:pressed, QToolButton#avoidance:pressed { background: $tabs; }
QPushButton#primary, QPushButton[primary="true"] { background: $accent; color: white; border-color: $accent; }
QPushButton#primary:hover, QPushButton[primary="true"]:hover { background: #405943; }
QPushButton#primary:focus, QPushButton[primary="true"]:focus { border: 2px solid #263e2a; padding: 5px 9px; }
QPushButton#quiet { border-color: transparent; color: $muted; }
QPushButton#quiet:focus { border-color: $accent; }
QPushButton#danger { color: $danger; }
QPushButton#danger:hover, QPushButton#danger:focus { background: #f4e9e3; border-color: $danger; }
QPushButton:disabled, QToolButton#avoidance:disabled,
QPushButton#primary:disabled, QPushButton[primary="true"]:disabled {
    background: #efefe8; color: $disabled; border-color: $border; }
QLineEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox, QKeySequenceEdit, QListWidget {
    background: $surface; border: 1px solid $border; border-radius: 6px;
    padding: 6px; selection-background-color: $accent; selection-color: white; }
QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus,
QComboBox:focus, QKeySequenceEdit:focus, QListWidget:focus { border-color: $accent; }
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled {
    background: #efefe8; color: $disabled; }
QCheckBox { spacing: 8px; padding: 2px 0; }
QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid #8f9b87;
    border-radius: 3px; background: $surface; }
QCheckBox::indicator:checked { background: $accent; border-color: $accent; image: url("$check_icon"); }
QCheckBox::indicator:disabled { background: #e3e7dd; border-color: #b8c2b0; }
QCheckBox:focus { color: $accent; text-decoration: underline; }
QCheckBox:disabled { color: $disabled; }
QGroupBox { border: 1px solid $border; border-radius: 8px; margin-top: 12px; padding-top: 8px; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 4px; color: $accent; }
QScrollArea { border: 0; }
QProgressBar { background: $surface; border: 1px solid $border; border-radius: 5px;
    text-align: center; min-height: 18px; }
QProgressBar::chunk { background: $accent; border-radius: 4px; }
QToolButton#advancedSettings { color: $accent; background: transparent; border: 1px solid transparent;
    border-radius: 6px; padding: 6px; min-height: 18px; }
QToolButton#advancedSettings:hover { background: $hover; }
QToolButton#advancedSettings:focus { border-color: $accent; background: $hover; }
QToolTip { background: $surface; color: $text; border: 1px solid $border; padding: 6px; }
""").substitute(COLORS, check_icon=(Path(__file__).resolve().parents[1] / "assets/ui/check.svg").as_posix())
