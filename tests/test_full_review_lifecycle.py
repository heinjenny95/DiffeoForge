"""Actual Qt review closure releases parent-owned views after result extraction."""

import gc
import weakref
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication, QDialog, QWidget
from test_full_review_comparisons import case as full_comparison_case
from test_full_review_geometry import model, wait

from diffeoforge.desktop.preview_mesh_loader import PreviewMeshLoader
from diffeoforge.desktop.reference_calibration_dialog import (
    CalibrationCandidateViewerDialog,
    CalibrationQcPair,
    ReferenceCalibrationDialog,
)


@pytest.fixture
def compared(tmp_path, monkeypatch):
    yield from full_comparison_case.__wrapped__(tmp_path, monkeypatch)


def test_recorded_feedback_remains_readable_after_done_before_caller_disposal(compared):
    viewer = compared.v
    viewer.guided_feedback.outcomes["same"].click()
    viewer._record_guided_feedback()
    decision = viewer.guided_feedback_decision
    assert decision is not None and decision["outcome"] == "same"
    assert not viewer.display_timer.isActive()
    assert viewer.canvas.original_model is not None
    assert viewer.canvas.reconstruction_model is not None


def test_actual_repeated_readonly_caller_disposes_views_after_reading_results(
    tmp_path, monkeypatch
):
    app = QApplication.instance() or QApplication([])
    parent = QWidget()
    parent._view_closed = parent._review_saving = False
    parent._worker = None
    parent.study_directory = tmp_path
    pair = CalibrationQcPair(
        "one",
        "synthetic",
        tmp_path / "original.vtk",
        tmp_path / "fit.vtk",
        True,
        "0" * 64,
        "0" * 64,
    )
    candidate = SimpleNamespace(
        candidate_id="one",
        status="completed",
        run_directory=tmp_path,
        metrics=dict(invalid_face_count=0),
    )
    snapshot = SimpleNamespace(study_directory=tmp_path)
    monkeypatch.setattr(PreviewMeshLoader, "request_paths", lambda *args, **kwargs: None)
    views, models = [], []

    def review(self):
        full = (model(pair.original_path, False), model(pair.reconstruction_path, False))
        models.extend(weakref.ref(value) for value in full)
        self.show()
        self._pair_loaded((0, "detail"), full)
        wait(app, lambda: self.canvas.full_resolution_ready)
        self.anatomical_notes.setText("Feedback remains readable by the caller")
        self.done(QDialog.DialogCode.Rejected)
        assert not self.display_timer.isActive()
        # Deleting in done()/WA_DeleteOnClose would make this result inaccessible.
        assert self.anatomical_notes.text() == "Feedback remains readable by the caller"
        views.append(weakref.ref(self))
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(CalibrationCandidateViewerDialog, "exec", review)
    try:
        for _ in range(3):
            ReferenceCalibrationDialog._candidate_prepared(
                parent, ("guided-inputs", tmp_path, None), (snapshot, candidate, (pair,))
            )
            QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            app.processEvents()
            gc.collect()
            assert not parent.findChildren(CalibrationCandidateViewerDialog)
        gc.collect()
        assert all(reference() is None for reference in models)
        assert all(reference() is None for reference in views)
    finally:
        parent.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
