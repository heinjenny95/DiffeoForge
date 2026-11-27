"""Desktop notifications for finished work and decisions that need a researcher."""

import weakref

from PySide6.QtCore import QEvent, QObject, Qt, Slot
from PySide6.QtWidgets import QApplication, QMessageBox, QStyle, QSystemTrayIcon, QWidget
from shiboken6 import isValid


class _DecisionPrompts(QObject):
    def eventFilter(self, watched, event):  # noqa: N802
        if (event.type() == QEvent.Type.Show and isinstance(watched, QMessageBox)
                and len(watched.buttons()) > 1):
            notify(watched, "Decision needed", watched.windowTitle())
        return False


def install_decision_notifications(app: QApplication) -> None:
    if not hasattr(app, "_df_decision_prompts"):
        app._df_decision_prompts = _DecisionPrompts(app)
        app.installEventFilter(app._df_decision_prompts)


class _WindowTray(QSystemTrayIcon):
    def __init__(self, owner: QWidget):
        icon = owner.windowIcon()
        if icon.isNull():
            icon = owner.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxInformation)
        super().__init__(icon, owner)
        self.setToolTip("DiffeoForge")
        self.target = weakref.ref(owner)
        self.messageClicked.connect(self.open_window)

    @Slot()
    def open_window(self):
        target = self.target()
        if target is None or not isValid(target) or not target.isVisible():
            target = self.parent()
        modal = QApplication.activeModalWidget()
        if modal is not None:
            target = modal
        if target.isMinimized():
            target.setWindowState(target.windowState() & ~Qt.WindowState.WindowMinimized)
        target.raise_()
        target.activateWindow()


def notify(widget: QWidget, title: str, message: str, *, warning: bool = False):
    """Alert the task's window. Only a click on the system message requests focus."""
    target = widget.window()
    QApplication.alert(target, 0)
    if not QSystemTrayIcon.isSystemTrayAvailable() or not QSystemTrayIcon.supportsMessages():
        return
    owner = target
    while owner.parentWidget() is not None:
        owner = owner.parentWidget().window()
    tray = getattr(owner, "_task_notification_tray", None)
    if tray is None:
        tray = owner._task_notification_tray = _WindowTray(owner)
    tray.target = weakref.ref(target)
    tray.show()
    icon = (QSystemTrayIcon.MessageIcon.Warning if warning
            else QSystemTrayIcon.MessageIcon.Information)
    tray.showMessage(f"DiffeoForge · {title}", message, icon, 10000)
