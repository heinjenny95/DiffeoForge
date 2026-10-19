"""Engineering tests must never read or change the user's recording preference."""

import importlib.util

import pytest


@pytest.fixture(autouse=True)
def isolated_recording_preferences(monkeypatch, tmp_path):
    if importlib.util.find_spec("PySide6") is None:
        yield
        return
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication

    import diffeoforge.desktop.appearance as appearance
    import diffeoforge.desktop.process_recorder as recording
    monkeypatch.setattr(
        appearance, 'QSettings',
        lambda: QSettings(str(tmp_path/'appearance.ini'), QSettings.Format.IniFormat),
    )
    app = QApplication.instance()
    existing = {id(w) for w in app.topLevelWidgets()} if app is not None else set()

    monkeypatch.setattr(
        recording,
        "_default_settings",
        lambda: QSettings(str(tmp_path / "recording-preferences.ini"), QSettings.Format.IniFormat),
    )

    yield
    _delete_closed_test_windows(existing)


def _delete_closed_test_windows(existing):
    """Release closed Qt test windows while QApplication and its event loop exist."""
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication
    from shiboken6 import isValid

    app = QApplication.instance()
    if app is None:
        return
    for widget in app.topLevelWidgets():
        if id(widget) not in existing and isValid(widget) and not widget.isVisible():
            widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
