"""Keep closed combo selections stable while scrolling any desktop dialog."""

from PySide6.QtCore import QEvent, QObject, QPointF
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication, QComboBox, QScrollArea, QWidget


class _ComboWheelGuard(QObject):
    def eventFilter(self, watched, event):  # noqa: N802 - Qt API
        if event.type() != QEvent.Type.Wheel or not isinstance(watched, QWidget):
            return False
        combo = watched
        while combo is not None and not isinstance(combo, QComboBox):
            combo = combo.parentWidget()
        if combo is None or combo.view().isVisible():
            return False  # An open popup keeps normal scrolling and selection.
        panel = combo.parentWidget()
        while panel is not None and not isinstance(panel, QScrollArea):
            panel = panel.parentWidget()
        if panel is not None:
            viewport = panel.viewport()
            vertical = panel.verticalScrollBar()
            horizontal = panel.horizontalScrollBar()
            before = vertical.value(), horizontal.value()
            forwarded = QWheelEvent(
                QPointF(viewport.mapFromGlobal(event.globalPosition().toPoint())),
                event.globalPosition(), event.pixelDelta(), event.angleDelta(),
                event.buttons(), event.modifiers(), event.phase(), event.inverted(),
            )
            QApplication.sendEvent(viewport, forwarded)
            # Some Windows Qt styles ignore pixel-only touchpad events. Preserve
            # their actual pixel distance when the normal scroll handler did not.
            if not event.pixelDelta().isNull() and before == (vertical.value(), horizontal.value()):
                vertical.setValue(before[0] - event.pixelDelta().y())
                horizontal.setValue(before[1] - event.pixelDelta().x())
        event.accept()
        return True  # Focus alone never makes a closed combo consume selection input.


def install_combo_wheel_guard(application=None):
    """Install once for existing and later-created controls, including modal dialogs."""
    application = application or QApplication.instance()
    if application is None:
        raise RuntimeError("Create QApplication before installing combo wheel behavior")
    guard = getattr(application, "_diffeoforge_combo_wheel_guard", None)
    if guard is None:
        guard = _ComboWheelGuard(application)
        application.installEventFilter(guard)
        application._diffeoforge_combo_wheel_guard = guard
    return guard
