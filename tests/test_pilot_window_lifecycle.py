"""Pilot progress is an independent, minimizable window; computation stays owned."""

from types import SimpleNamespace

import pytest


def test_pilot_minimize_progress_escape_and_idle_close(tmp_path, monkeypatch):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QMessageBox
    from test_reference_calibration_study import _project

    from diffeoforge.desktop.reference_calibration_dialog import ReferenceCalibrationDialog
    from diffeoforge.reference_calibration_study import create_reference_calibration_study

    application = QApplication.instance() or QApplication([])
    snapshot = create_reference_calibration_study(_project(tmp_path), tmp_path / "pilot")
    dialog = ReferenceCalibrationDialog(snapshot.study_directory)
    finished = []
    dialog.finished.connect(finished.append)
    assert dialog.parent() is None
    assert dialog.windowModality() == Qt.WindowModality.NonModal
    assert dialog.windowFlags() & Qt.WindowType.WindowMinimizeButtonHint
    dialog.show()
    application.processEvents()
    for running in (False, True):
        worker = SimpleNamespace() if running else None
        dialog._worker = worker  # No backend or atlas is started by this test.
        dialog.showMinimized()
        application.processEvents()
        assert dialog.isMinimized()
        dialog._event({"event": "candidate_started", "candidate_id": "synthetic"})
        dialog._render()
        application.processEvents()
        assert dialog.isMinimized() and dialog._worker is worker
        if running:
            dialog.reject()
            monkeypatch.setattr(QMessageBox, "information", lambda *args: None)
            dialog.close()
            assert not finished and dialog._worker is worker
        dialog.showNormal()
        application.processEvents()
        assert not dialog.isMinimized()
    dialog._worker = None
    dialog.close()
    assert len(finished) == 1
    application.processEvents()


def test_independent_pilot_retains_main_window_appearance(tmp_path, monkeypatch):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QPalette
    from PySide6.QtWidgets import QApplication, QLabel, QPushButton
    from test_reference_calibration_study import _project

    from diffeoforge.desktop.widgets import DiffeoForgeWindow
    from diffeoforge.reference_calibration_study import create_reference_calibration_study

    application = QApplication.instance() or QApplication([])
    snapshot = create_reference_calibration_study(_project(tmp_path), tmp_path / "pilot")
    window = DiffeoForgeWindow()
    window._review = SimpleNamespace()
    window._reference_readiness = SimpleNamespace(ready=True)
    monkeypatch.setattr(
        window, "_reference_calibration_context", lambda: (snapshot.plan, snapshot.study_directory)
    )
    monkeypatch.setattr(window, "_finish_reference_calibration", lambda _snapshot: None)
    window._open_reference_calibration()
    pilot = window._reference_calibration_dialog
    try:
        application.processEvents()
        assert pilot is not None and pilot.parent() is None
        assert pilot.windowModality() == Qt.WindowModality.NonModal
        assert pilot.windowFlags() & Qt.WindowType.WindowMinimizeButtonHint
        title = pilot.findChild(QLabel, "title")
        assert title.font().pixelSize() == 30
        assert title.palette().color(QPalette.ColorRole.WindowText).name() == "#123b3a"
        primary = next(
            button for button in pilot.findChildren(QPushButton, "primary") if button.isEnabled()
        )
        assert primary.palette().color(QPalette.ColorRole.Button).name() == "#167c6b"
        pilot.showMinimized()
        pilot._render()
        application.processEvents()
        assert pilot.isMinimized()
    finally:
        if pilot is not None:
            pilot.close()
        window.close()
        application.processEvents()
