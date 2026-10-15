"""控制中心沿用桌宠的暖白、草绿原生界面，不引入额外样式依赖。"""

STYLE = """
QWidget { background: #f7f8f3; color: #293d33; font: 10pt "Microsoft YaHei UI"; }
QLabel#title { font-size: 20pt; font-weight: 600; }
QLabel#productName { font-size: 14pt; font-weight: 600; padding-right: 8px; }
QLabel#sectionTitle { font-size: 12pt; font-weight: 600; padding: 4px 0 8px; }
QLabel#hint { color: #68766c; font-size: 9pt; }
QLabel#status { background: #e7efe5; padding: 9px; border-radius: 6px; }
QFrame#browserTabStrip { background: #dce8db; border-bottom: 1px solid #c7d3c3; }
QTabBar#controlTabs { background: transparent; }
QTabBar#controlTabs::tab { background: #dce8db; color: #526858; border: 0;
    border-top-left-radius: 10px; border-top-right-radius: 10px;
    padding: 11px 12px; margin-right: 3px; min-width: 56px; }
QTabBar#controlTabs::tab:hover { background: #cbdcc8; color: #293d33; }
QTabBar#controlTabs::tab:selected { background: #f7f8f3; color: #2f543a; font-weight: 600; }
QTabBar#controlTabs::tab:focus { text-decoration: underline; }
QToolButton#tabListButton, QTabBar#controlTabs QToolButton {
    background: #ccddc9; border: 0; border-radius: 8px; padding: 7px; }
QToolButton#tabListButton:hover, QTabBar#controlTabs QToolButton:hover { background: #bfd3bb; }
QToolButton#tabListButton::menu-indicator { image: none; }
QMenu { background: #f7f8f3; border: 1px solid #c7d3c3; padding: 5px; }
QMenu::item { padding: 7px 18px; border-radius: 4px; }
QMenu::item:selected { background: #dae6d6; }
QPushButton, QToolButton#avoidance { background: #e8ede3; border: 1px solid #c7d3c3;
    border-radius: 5px; padding: 8px 12px; }
QPushButton:hover, QToolButton#avoidance:hover { background: #dae6d6; }
QPushButton:checked, QPushButton#primary, QToolButton#avoidance:checked {
    background: #496e54; color: white; border-color: #496e54; }
QLineEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background: #ffffff; border: 1px solid #cbd5c8; border-radius: 4px;
    padding: 6px; selection-background-color: #709078; }
QLineEdit:focus, QPlainTextEdit:focus { border-color: #577b61; }
QCheckBox { spacing: 8px; padding: 4px 0; }
QCheckBox::indicator { width: 14px; height: 14px; border: 1px solid #8eaa93;
    border-radius: 3px; background: white; }
QCheckBox::indicator:checked { background: #497758; border: 2px solid #2f543a; }
QScrollArea { border: 0; }
"""
