import time
from pathlib import Path

import pytest

from diffeoforge.reference_calibration_study import CalibrationStudyCandidateState


def _model(path: Path):
    from diffeoforge.desktop.mesh_preview import MeshPreviewModel

    return MeshPreviewModel(
        path=path,
        sha256="0" * 64,
        vertices=(
            (-1.0, -1.0, 0.0),
            (1.0, -1.0, 0.0),
            (0.0, 1.0, 0.0),
            (0.0, 0.0, 0.6),
        ),
        triangles=((0, 1, 2), (0, 1, 3), (1, 2, 3), (0, 2, 3)),
        edges=((0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3)),
        bounds=(-1.0, 1.0, -1.0, 1.0, 0.0, 0.6),
    )


def test_comparison_canvas_binds_both_meshes_and_renders(monkeypatch, tmp_path: Path) -> None:
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from diffeoforge.desktop.calibration_comparison_widget import (
        CalibrationComparisonCanvas3D,
    )

    application = QApplication.instance() or QApplication(["calibration-overlay-test"])
    canvas = CalibrationComparisonCanvas3D()
    canvas.resize(600, 500)
    original = _model(tmp_path / "original.vtk")
    reconstruction = _model(tmp_path / "reconstruction.vtk")

    canvas.set_models(original, reconstruction)
    canvas.show()
    deadline = time.monotonic() + 10
    while not canvas.full_resolution_ready and time.monotonic() < deadline:
        application.processEvents()
        time.sleep(0.005)
    assert canvas.full_resolution_ready
    image = canvas.grab().toImage()

    assert canvas.original_model is original
    assert canvas.reconstruction_model is reconstruction
    assert image.isNull() is False
    assert image.width() == 600
    canvas.close()
    application.processEvents()


def _wait_pair(application, dialog) -> None:
    deadline = time.monotonic() + 10
    while not dialog.canvas.comparison_ready and time.monotonic() < deadline:
        application.processEvents()
        time.sleep(0.005)
    assert dialog.canvas.comparison_ready
    application.processEvents()


def test_visual_qc_pass_is_locked_until_every_subject_pair_was_opened(
    monkeypatch,
    tmp_path: Path,
) -> None:
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    import diffeoforge.desktop.reference_calibration_dialog as dialog_module
    from diffeoforge.desktop.reference_calibration_dialog import (
        CalibrationCandidateViewerDialog,
        CalibrationQcPair,
    )

    application = QApplication.instance() or QApplication(["calibration-review-test"])
    pairs = (
        CalibrationQcPair(
            pair_id="atlas",
            label="Atlas overview",
            original_path=tmp_path / "template.vtk",
            reconstruction_path=tmp_path / "atlas.vtk",
            required=False,
        ),
        CalibrationQcPair(
            pair_id="subject:first.vtk",
            label="First pilot specimen",
            original_path=tmp_path / "first.vtk",
            reconstruction_path=tmp_path / "first-reconstruction.vtk",
            required=True,
        ),
        CalibrationQcPair(
            pair_id="subject:second.vtk",
            label="Second pilot specimen",
            original_path=tmp_path / "second.vtk",
            reconstruction_path=tmp_path / "second-reconstruction.vtk",
            required=True,
        ),
    )
    monkeypatch.setattr(
        dialog_module,
        "collect_calibration_qc_pairs",
        lambda _study, _candidate: pairs,
    )
    monkeypatch.setattr(
        "diffeoforge.desktop.pilot_preview.load_pilot_preview", lambda p, **kw: _model(p)
    )
    candidate = CalibrationStudyCandidateState(
        candidate_id="attachment-01",
        label="center",
        status="completed",
        config_path=tmp_path / "atlas.yaml",
        run_directory=tmp_path / "run",
        metrics={},
        error=None,
        attempts=1,
    )
    dialog = CalibrationCandidateViewerDialog(tmp_path, candidate)
    dialog.show()
    _wait_pair(application, dialog)

    assert "Inspected: 1 / 2" in dialog.review_progress.text()
    assert dialog.pass_check.isHidden() is True
    assert dialog.previous_specimen_button.isEnabled() is False
    assert dialog.next_specimen_button.isEnabled() is True
    assert dialog.next_specimen_button.objectName() == "primary"
    assert dialog.fail_button.isVisible() is True
    assert dialog.body_scroll.horizontalScrollBarPolicy() == (Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

    assert not dialog.complete_button.isEnabled()
    dialog.specimen_decision.setCurrentIndex(dialog.specimen_decision.findData("pass"))
    dialog.next_specimen_button.click()
    _wait_pair(application, dialog)
    assert dialog.pass_check.isHidden() is True
    assert "Inspected: 2 / 2" in dialog.review_progress.text()
    assert dialog.next_specimen_button.isEnabled() is True
    assert dialog.complete_button.isEnabled()
    dialog.specimen_decision.setCurrentIndex(dialog.specimen_decision.findData("pass"))
    assert dialog.complete_button.isEnabled() is True
    assert dialog.complete_button.objectName() == "primary"
    dialog.feature_criterion.setText("Study A: distal prong count")
    dialog.feature_judgement.setCurrentIndex(dialog.feature_judgement.findData("preserved"))
    dialog.original_feature_count.setValue(3)
    assert not dialog.complete_button.isEnabled()  # Incomplete pair, not assumed equal.
    dialog.reconstruction_feature_count.setValue(2)
    assert not dialog.complete_button.isEnabled()
    assert "second.vtk" in dialog.review_gate.text()
    dialog._record_visual_qc_pass()
    assert not dialog.review_recorded
    dialog.previous_specimen_button.click()
    _wait_pair(application, dialog)
    assert dialog.original_feature_count.value() == -1  # Counts belong to one specimen.
    assert dialog.feature_criterion.text() == ""
    assert not dialog.complete_button.isEnabled()  # Other specimen's mismatch remains.
    dialog.mesh_combo.setCurrentIndex(dialog.mesh_combo.findData(1))
    _wait_pair(application, dialog)
    assert dialog.original_feature_count.value() == 3
    assert dialog.feature_criterion.text() == "Study A: distal prong count"
    assert dialog.reconstruction_feature_count.value() == 2
    dialog.reconstruction_feature_count.setValue(3)
    assert dialog.complete_button.isEnabled()
    dialog.complete_button.click()
    assert dialog.review_complete is True
    assert dialog.review_recorded is True
    assert dialog.review_passed is True
    dialog.close()
    application.processEvents()


@pytest.mark.parametrize("criterion", ["Study B: articular surface", "Study C: distal branches"])
def test_visual_qc_can_record_an_explicit_failure_after_every_pair_was_opened(
    monkeypatch,
    tmp_path: Path,
    criterion: str,
) -> None:
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    import diffeoforge.desktop.reference_calibration_dialog as dialog_module
    from diffeoforge.desktop.reference_calibration_dialog import (
        CalibrationCandidateViewerDialog,
        CalibrationQcPair,
    )

    application = QApplication.instance() or QApplication(["calibration-fail-test"])
    pairs = (
        CalibrationQcPair(
            pair_id="subject:only.vtk",
            label="Only pilot specimen",
            original_path=tmp_path / "only.vtk",
            reconstruction_path=tmp_path / "only-reconstruction.vtk",
            required=True,
        ),
    )
    monkeypatch.setattr(
        dialog_module,
        "collect_calibration_qc_pairs",
        lambda _study, _candidate: pairs,
    )
    monkeypatch.setattr(
        "diffeoforge.desktop.pilot_preview.load_pilot_preview", lambda p, **kw: _model(p)
    )
    candidate = CalibrationStudyCandidateState(
        candidate_id="attachment-01",
        label="center",
        status="completed",
        config_path=tmp_path / "atlas.yaml",
        run_directory=tmp_path / "run",
        metrics={},
        error=None,
        attempts=1,
    )

    dialog = CalibrationCandidateViewerDialog(tmp_path, candidate)
    dialog.show()
    _wait_pair(application, dialog)

    assert dialog.fail_button.isVisible() is True
    assert dialog.complete_button.isEnabled() is True
    assert "Approve once" in dialog.review_gate.text()
    dialog.feature_criterion.setText(criterion)
    dialog.feature_judgement.setCurrentIndex(dialog.feature_judgement.findData("not_preserved"))
    assert dialog.original_feature_count.value() == -1  # Qualitative checks need no count.
    assert not dialog.complete_button.isEnabled()
    dialog._record_visual_qc_pass()
    assert not dialog.review_recorded
    dialog.fail_button.click()
    assert dialog.review_recorded is True
    assert dialog.review_passed is False
    assert dialog.review_complete is False
    dialog.close()
    application.processEvents()


def test_staged_calibration_requires_saved_fit_and_can_refine_rejected_center(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from test_reference_calibration_study import _approve_for_test, _review_ready_stage

    import diffeoforge.desktop.reference_calibration_dialog as dialog_module
    import diffeoforge.reference_calibration_study as study

    application = QApplication.instance() or QApplication([])
    runner, snapshot = _review_ready_stage(tmp_path, monkeypatch)
    dialog = dialog_module.ReferenceCalibrationDialog(runner.study_directory)
    dialog.show()
    application.processEvents()
    assert dialog.advanced_mode.isHidden() and dialog.afk_mode.isHidden()
    assert dialog.use_provisional_button.isHidden()
    assert dialog.selection_combo.isVisible()
    cid = snapshot.candidates[0].candidate_id
    dialog.selection_combo.setCurrentIndex(dialog.selection_combo.findData(cid))
    assert not dialog.advance_button.isEnabled()
    assert dialog.review_next_button.isEnabled()
    assert dialog.collect_evidence_button.isEnabled()
    _approve_for_test(runner.study_directory, cid)
    dialog._render()
    assert dialog.advance_button.isEnabled()
    name = snapshot.plan.selected_pilot_subjects[0].filename
    study.record_reference_calibration_candidate_review(
        runner.study_directory,
        candidate_id=cid,
        approved=False,
        reviewed_subjects=(name,),
        subject_decisions={name: "fail"},
    )
    dialog._render()
    assert not dialog.advance_button.isEnabled()
    assert dialog.selection_combo.currentData() == cid  # Rejected center remains inspectable.
    assert dialog.collect_evidence_button.isEnabled()
    starts = []
    monkeypatch.setattr(dialog, "_start_pilot", lambda **kwargs: starts.append(kwargs))
    assert dialog.collect_evidence_button.text() == "Improve fit automatically"
    dialog.selection_combo.setCurrentIndex(0)
    assert dialog.collect_evidence_button.isEnabled()  # No hand-picked center required.
    dialog.collect_evidence_button.click()
    assert starts == [{}]
    assert dialog.adaptive_fit_search.isChecked()
    assert dialog.study_directory == runner.study_directory
    assert dialog.snapshot.visual_reviews[cid] is False
    dialog.close()
    application.processEvents()
