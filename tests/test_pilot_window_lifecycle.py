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
