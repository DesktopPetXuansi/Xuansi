"""控制中心沿用桌宠的暖白、草绿原生界面，不引入额外样式依赖。"""

STYLE = """
QWidget { background: #f7f8f3; color: #293d33; font: 10pt "Microsoft YaHei UI"; }
QLabel#title { font-size: 20pt; font-weight: 600; }
QLabel#hint { color: #68766c; font-size: 9pt; }
QLabel#status { background: #e7efe5; padding: 9px; border-radius: 6px; }
QFrame#controlSection { background: #ffffff; border: 1px solid #cbd5c8; border-radius: 5px; }
QToolButton#sectionHeader { text-align: left; font-weight: 600; border: 0; padding: 12px; }
QToolButton#sectionHeader:hover { background: #e8ede3; }
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
