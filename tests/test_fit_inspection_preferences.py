import time
from dataclasses import replace

import pytest
from test_reference_calibration_dialog import _model


def wait(app, predicate):
    deadline = time.monotonic() + 12
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.005)
    assert predicate()


def inspection(tmp_path, monkeypatch, *, first=False, compare=True):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from diffeoforge.desktop.preview_mesh_loader import PreviewMeshLoader
    from diffeoforge.desktop.reference_calibration_dialog import (
        CalibrationCandidateViewerDialog,
        CalibrationQcPair,
    )
    from diffeoforge.reference_calibration_study import CalibrationStudyCandidateState

    app = QApplication.instance() or QApplication([])
    operations = []
    monkeypatch.setattr(
        PreviewMeshLoader, "request_operation", lambda self, key, op: operations.append((key, op))
    )
    candidate = CalibrationStudyCandidateState(
        candidate_id="fit-specimen", label="Current fit", status="completed",
        config_path=tmp_path / "config.yaml", run_directory=tmp_path / "run",
        attempts=1, metrics={"invalid_face_count": 0}, error=None,
    )
    pair = CalibrationQcPair(
        pair_id="subject:target.vtk", label="Target", original_path=tmp_path / "target.vtk",
        reconstruction_path=tmp_path / "current.vtk", required=True,
        original_sha256="0" * 64, reconstruction_sha256="0" * 64,
    )
    dialog = CalibrationCandidateViewerDialog(
        tmp_path, candidate, pairs=(pair,), allow_plan_b=True, compare_preferences=True
    )
    panel = dialog.fit_preferences
    current = dict(study="current", candidate_id="fit-specimen")
    previous = dict(study="previous", candidate_id="fit-specimen")
    descriptor = dict(
        root=str(tmp_path), current=current, choices=[] if first else [previous], best=None
    )
    panel._loaded("choices", descriptor)
    if compare and not first:
        panel.show_comparison.setChecked(True)
    original, reconstruction = _model(pair.original_path), _model(pair.reconstruction_path)
    dialog._pair_loaded(0, (original, reconstruction))
    comparison = dict(
        current=current, reference=previous if compare and not first else None, best=None,
    )
    models = [original, reconstruction] + (
        [_model(tmp_path / "previous.vtk")] if compare and not first else []
    )
    panel._loaded("surfaces", (models, comparison))
    dialog.resize(1040, 820)
    dialog.show()
    wait(app, lambda: panel.start_button.isEnabled() if first or not compare
         else panel.feedback_buttons["better"].isEnabled())
    return app, dialog, panel, original, reconstruction, candidate


@pytest.mark.parametrize("outcome", ["better", "worse", "same"])
@pytest.mark.parametrize("approved", [True, False])
def test_inspect_then_rank_then_explicit_qc_without_an_early_dispatch(
    tmp_path, monkeypatch, outcome, approved
):
    app, dialog, panel, original, reconstruction, _ = inspection(tmp_path, monkeypatch)
    assert panel.current_canvas is dialog.canvas
    assert dialog.canvas.original_model is original
    assert dialog.canvas.reconstruction_model is reconstruction
    assert panel.feedback_controls.parentWidget() is dialog.decision_panel
    assert not dialog.complete_button.isEnabled() and not dialog.fail_button.isEnabled()
    # Direct slot invocation cannot bypass the first step either.
    dialog._record_visual_qc_pass()
    dialog._record_visual_qc_fail()
    assert not dialog.review_recorded
    panel.feedback_buttons[outcome].click()
    assert dialog.isVisible() and not dialog.review_recorded
    assert dialog.preference_decision[0] == outcome
    assert not list(tmp_path.glob("*.json"))  # Selection alone persists nothing.
    assert dialog.complete_button.isEnabled() and dialog.fail_button.isEnabled()
    if approved:
        dialog.complete_button.click()
    else:
        dialog.fail_button.click()
    assert dialog.review_recorded and dialog.review_passed is approved
    assert dialog.preference_decision[0] == outcome
    assert panel._closed
    app.processEvents()


def test_cancel_after_rating_records_neither_qc_nor_preference(tmp_path, monkeypatch):
    app, dialog, panel, *_ = inspection(tmp_path, monkeypatch)
    panel.feedback_buttons["better"].click()
    dialog.close_button.click()
    assert not dialog.review_recorded and panel._closed
    assert not list(tmp_path.glob("*.json"))
    panel._loaded("surfaces", ([], {}))  # Late deliveries cannot revive it.
    app.processEvents()


def test_first_fit_can_be_reviewed_without_a_relative_ranking(tmp_path, monkeypatch):
    app, dialog, panel, *_ = inspection(tmp_path, monkeypatch, first=True)
    assert panel.reference_panel.isHidden()
    assert dialog.fail_button.isEnabled()
    assert not dialog.review_recorded
    dialog.fail_button.click()
    assert dialog.preference_decision[0] == "not_compared"
    assert dialog.review_recorded and not dialog.review_passed
    app.processEvents()


def test_default_single_fit_has_optional_comparison_and_no_forced_winner(tmp_path, monkeypatch):
    app, dialog, panel, *_ = inspection(tmp_path, monkeypatch, compare=False)
    assert panel.reference_panel.isHidden()
    assert panel.feedback_controls.isHidden()
    assert not panel.show_comparison.isChecked()
    assert dialog.complete_button.isEnabled() and dialog.fail_button.isEnabled()
    assert dialog.preference_decision[0] == "not_compared"
    dialog.close_button.click()
    assert not dialog.review_recorded
    app.processEvents()


def test_changed_reference_invalidates_rating_and_reuses_the_current_display(tmp_path, monkeypatch):
    app, dialog, panel, original, reconstruction, _ = inspection(tmp_path, monkeypatch)
    panel.feedback_buttons["worse"].click()
    panel._load_comparison()
    assert panel.decision is None and not dialog.fail_button.isEnabled()
    assert dialog.canvas.original_model is original
    assert dialog.canvas.reconstruction_model is reconstruction
    dialog.close()
    app.processEvents()


def test_late_surfaces_cannot_replace_the_current_inspection_identity(tmp_path, monkeypatch):
    app, dialog, panel, original, reconstruction, _ = inspection(tmp_path, monkeypatch)
    comparison = panel._comparison
    panel._loaded("surfaces", (
        [original, _model(tmp_path / "other-current.vtk"), _model(tmp_path / "previous.vtk")],
        comparison,
    ))
    assert dialog.canvas.reconstruction_model is reconstruction
    assert panel.reference_canvas.reconstruction_model is None
    assert "Displayed current specimen changed" in panel.status.text()
    assert not dialog.complete_button.isEnabled() and not dialog.fail_button.isEnabled()
    dialog.close()
    app.processEvents()


def test_invalid_individual_fit_cannot_be_accepted_or_seeded(tmp_path, monkeypatch):
    app, old, _, _, _, candidate = inspection(tmp_path, monkeypatch)
    old.close()
    from diffeoforge.desktop.reference_calibration_dialog import CalibrationCandidateViewerDialog

    dialog = CalibrationCandidateViewerDialog(
        tmp_path, replace(candidate, metrics={"invalid_face_count": 3}),
        pairs=old._pairs, allow_plan_b=True, compare_preferences=True,
    )
    dialog.show()
    dialog._pair_loaded(0, (_model(tmp_path / "target.vtk"), _model(tmp_path / "current.vtk")))
    wait(app, lambda: dialog.canvas.comparison_ready)
    assert dialog.fit_preferences is None
    assert not dialog.complete_button.isEnabled()
    dialog._record_visual_qc_pass()
    assert not dialog.review_recorded
    dialog.fail_button.click()
    assert dialog.review_recorded and not dialog.review_passed
    app.processEvents()


def test_marked_region_notes_are_bound_to_original_without_approving_fit(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QDialog

    from diffeoforge.desktop.landmark_3d_widget import InteractiveMeshCanvas3D

    app, dialog, _, original, *_ = inspection(tmp_path, monkeypatch, first=True, compare=False)

    def mark(region_dialog):
        canvas = region_dialog.findChild(InteractiveMeshCanvas3D)
        assert canvas._model is original
        canvas.surfacePointPicked.emit(original.vertices[0])
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(QDialog, "exec", mark)
    pair = dialog._pairs[0]
    dialog._region_loaded(pair.pair_id, (original,))
    notes = dialog.anatomical_notes.text()
    assert pair.original_path.name in notes and pair.original_sha256 in notes
    assert "xyz=(" in notes
    assert not dialog.review_recorded
    dialog.close()
    app.processEvents()
