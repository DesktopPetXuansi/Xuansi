"""Route wheel gestures over form fields to the enclosing page."""

from PySide6.QtCore import QCoreApplication, QEvent, QObject
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import (
    QAbstractSlider,
    QAbstractSpinBox,
    QComboBox,
    QLineEdit,
    QPlainTextEdit,
    QScrollArea,
    QScrollBar,
    QTextEdit,
    QWidget,
)


class FormWheelFilter(QObject):
    def eventFilter(self, watched, event):
        if event.type() != QEvent.Type.Wheel or not isinstance(watched, QWidget):
            return False

        field = watched
        window = watched.window()
        while field is not None and field.window() == window:
            if isinstance(field, (QPlainTextEdit, QTextEdit)):
                if field.isReadOnly():
                    return False
                break
            if isinstance(field, (QLineEdit, QComboBox, QAbstractSpinBox)):
                break
            if isinstance(field, QAbstractSlider) and not isinstance(field, QScrollBar):
                break
            if isinstance(field, QScrollArea):
                return False
            field = field.parentWidget()
        else:
            return False

        # Preserve both wheel steps and precise touchpad deltas. Consume the original
        # event even at the page boundary so it cannot fall back to a focused field.
        parent = field.parentWidget()
        while parent is not None and parent.window() == window:
            if isinstance(parent, QScrollArea):
                viewport = parent.viewport()
                forwarded = QWheelEvent(
                    viewport.mapFromGlobal(event.globalPosition()), event.globalPosition(),
                    event.pixelDelta(), event.angleDelta(), event.buttons(), event.modifiers(),
                    event.phase(), event.inverted(), event.source(), event.pointingDevice(),
                )
                QCoreApplication.sendEvent(viewport, forwarded)
                break
            parent = parent.parentWidget()
        event.accept()
        return True


def install_form_wheel_filter(application):
    if not hasattr(application, "_form_wheel_filter"):
        application._form_wheel_filter = FormWheelFilter(application)
        application.installEventFilter(application._form_wheel_filter)
