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
    application.processEvents()
    image = canvas.grab().toImage()

    assert canvas.original_model is original
    assert canvas.reconstruction_model is reconstruction
    assert image.isNull() is False
    assert image.width() == 600
    canvas.close()
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
    monkeypatch.setattr(dialog_module, "load_mesh_preview", _model)
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
    application.processEvents()

    assert "1 of 2" in dialog.review_progress.text()
    assert dialog.pass_check.isHidden() is True
    assert dialog.previous_specimen_button.isEnabled() is False
    assert dialog.next_specimen_button.isEnabled() is True
    assert dialog.next_specimen_button.objectName() == "primary"
    assert dialog.fail_button.isHidden() is True
    assert dialog.body_scroll.horizontalScrollBarPolicy() == (
        Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    )

    dialog.next_specimen_button.click()
    application.processEvents()
    assert dialog.pass_check.isHidden() is True
    assert "2 of 2" in dialog.review_progress.text()
    assert dialog.next_specimen_button.isEnabled() is False
    assert dialog.complete_button.isEnabled() is True
    assert dialog.complete_button.objectName() == "primary"
    dialog.complete_button.click()
    assert dialog.review_complete is True
    assert dialog.review_recorded is True
    assert dialog.review_passed is True
    dialog.close()
    application.processEvents()


def test_visual_qc_can_record_an_explicit_failure_after_every_pair_was_opened(
    monkeypatch,
    tmp_path: Path,
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
    monkeypatch.setattr(dialog_module, "load_mesh_preview", _model)
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
    application.processEvents()

    assert dialog.fail_button.isVisible() is True
    assert dialog.complete_button.isEnabled() is True
    assert "Next: record your decision" in dialog.review_gate.text()
    dialog.fail_button.click()
    assert dialog.review_recorded is True
    assert dialog.review_passed is False
    assert dialog.review_complete is False
    dialog.close()
    application.processEvents()


def test_staged_calibration_allows_selection_without_visual_qc(
    monkeypatch,
    tmp_path: Path,
) -> None:
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from types import SimpleNamespace

    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtWidgets import QApplication, QLabel

    import diffeoforge.desktop.reference_calibration_dialog as dialog_module
    from diffeoforge.desktop.reference_calibration_dialog import (
        ReferenceCalibrationDialog,
    )
    from diffeoforge.reference_calibration import (
        CalibrationCandidate,
        CalibrationStage,
    )

    application = QApplication.instance() or QApplication(["calibration-guide-test"])
    planned = (
        CalibrationCandidate(
            candidate_id="attachment-01",
            label="center",
            parameter_values=(("attachment_kernel_width", 0.2),),
            rationale="Tests the declared detail scale.",
        ),
        CalibrationCandidate(
            candidate_id="attachment-02",
            label="smoother",
            parameter_values=(("attachment_kernel_width", 0.3),),
            rationale="Tests a smoother comparison.",
        ),
    )
    stage = CalibrationStage(
        stage_id="attachment",
        order=1,
        kind="attachment_width",
        title="Surface-matching detail",
        candidates=planned,
        locked_from_previous_stages=(),
        evidence_required=(),
        reject_when=(),
        decision_rule="Choose by visual anatomy QC.",
    )

    def metrics(offset: float) -> dict[str, object]:
        return {
            "metric_version": "0.1",
            "completed": True,
            "converged": True,
            "optimizer_stop_signal": "tolerance_threshold",
            "stop_interpretation": "completed before cap",
            "final_iteration": 12,
            "maximum_iterations": 50,
            "residual_p95": 0.2 + offset,
            "residual_median": 0.1 + offset,
            "resampling_sensitivity": 0.02 + offset,
            "deformation_energy": 0.4 + offset,
            "attachment_objective_magnitude": 0.5 + offset,
            "distortion_p95": 0.1 + offset,
            "invalid_face_count": 0,
            "runtime_seconds": 10.0 + offset,
            "subject_reconstruction_count": 3,
            "atlas_path": str(tmp_path / f"atlas-{offset}.vtk"),
            "notes": (),
        }

    candidates = tuple(
        CalibrationStudyCandidateState(
            candidate_id=item.candidate_id,
            label=item.label,
            status="completed",
            config_path=tmp_path / f"{item.candidate_id}.yaml",
            run_directory=tmp_path / item.candidate_id,
            metrics=metrics(float(index)),
            error=None,
            attempts=1,
        )
        for index, item in enumerate(planned)
    )
    snapshot = SimpleNamespace(
        study_directory=tmp_path,
        study_id="guided-test",
        plan=SimpleNamespace(
            stages=(stage,),
            coordinate_unit="unitless",
            fingerprint="a" * 64,
        ),
        status="awaiting_review",
        current_stage=stage,
        candidates=candidates,
        selected_values={},
        selected_candidate_ids={},
        event_count=0,
    )
    monkeypatch.setattr(
        dialog_module,
        "load_reference_calibration_study",
        lambda _directory: snapshot,
    )
    information_messages: list[tuple[str, str]] = []
    monkeypatch.setattr(
        dialog_module.QMessageBox,
        "information",
        lambda _parent, title, message: information_messages.append((title, message)),
    )

    dialog = ReferenceCalibrationDialog(tmp_path)
    dialog.show()
    application.processEvents()

    assert dialog.advanced_mode.isChecked() is False
    assert dialog.start_button.isHidden() is True
    assert dialog.use_provisional_button.isVisible() is True
    assert dialog.compare_options_button.isVisible() is True
    assert dialog.collect_evidence_button.isVisible() is True
    assert "Paused checkpoint" in dialog.status.text()
    assert "search range is not bounded" in dialog.status.text()
    dialog.collect_evidence_button.click()
    application.processEvents()
    assert information_messages
    assert information_messages[-1][0] == "Outward pilot evidence required"
    assert "attachment_kernel_width=" in information_messages[-1][1]
    assert "have not been run" in information_messages[-1][1]
    dialog.compare_options_button.click()
    application.processEvents()
    assert dialog.advanced_mode.isChecked() is True
    assert dialog.selection_combo.isVisible() is True
    warning_labels = dialog.findChildren(QLabel, "statusWarning")
    assert any("Evidence grade:" in label.text() for label in warning_labels)

    application.processEvents()
    application.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    application.processEvents()

    from diffeoforge.desktop.info_disclosure import InfoDisclosure

    disclosures = dialog.findChildren(InfoDisclosure)
    disclosure_titles = [item.title for item in disclosures]
    assert "How pilot calibration works" in disclosure_titles
    assert "Decision guidance for this stage" in disclosure_titles
    assert "How to interpret the comparison colors" in disclosure_titles
    assert disclosure_titles.count("About this option") == 2
    assert all(item.panel.isHidden() for item in disclosures)

    review_buttons = list(dialog._review_buttons.values())
    assert len(review_buttons) == 2
    assert [button.objectName() for button in review_buttons] == [
        "secondary",
        "secondary",
    ]
    assert all(
        button.text().startswith("Optional plausibility gate")
        for button in review_buttons
    )
    assert dialog.review_next_button.isHidden() is True
    assert dialog.selection_combo.isVisible() is True
    assert dialog.selection_combo.count() == 3
    assert "evidence and trade-offs" in dialog.selection_combo.itemText(0)
    assert "not performed" in dialog.selection_combo.itemText(1)
    assert dialog.advance_button.isHidden() is True
    favorable = dialog.findChildren(QLabel, "tradeoffFavorable")
    caution = dialog.findChildren(QLabel, "tradeoffCaution")
    unfavorable = dialog.findChildren(QLabel, "tradeoffUnfavorable")
    legends = dialog.findChildren(QLabel, "tradeoffLegend")
    assert len(favorable) == 4
    assert len(caution) == 1
    assert len(unfavorable) == 3
    assert len(legends) == 1
    assert any("Fastest pilot run" in label.text() for label in favorable)
    assert any("Highest deformation cost" in label.text() for label in caution)
    assert any("Largest measured mismatch" in label.text() for label in unfavorable)
    assert all("do not select" in label.text() for label in legends)
    assert all("requiring inspection" not in label.text() for label in legends)
    assert dialog.scroll.horizontalScrollBarPolicy() == (
        Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    )
    assert dialog.advance_button.isEnabled() is False

    assert dialog.selection_combo.objectName() == "primaryChoice"
    assert dialog.selection_combo.isVisible() is True
    assert dialog.review_next_button.isHidden() is True
    assert dialog.advance_button.isEnabled() is False
    assert dialog.advance_button.isHidden() is True
    dialog.selection_combo.setCurrentIndex(1)
    application.processEvents()
    assert dialog.advance_button.isEnabled() is True
    assert dialog.advance_button.isVisible() is True
    assert dialog.advance_button.objectName() == "primary"
    assert "click the green Select option" in dialog.status.text()
    assert "Optional visual QC status" in dialog.status.text()

    dialog._visually_reviewed_candidates.add("attachment-01")
    dialog._render()
    application.processEvents()
    assert dialog.selection_combo.count() == 2
    assert dialog.selection_combo.findData("attachment-01") == -1
    failed_statuses = [
        label
        for label in dialog.findChildren(QLabel, "statusError")
        if "Plausibility gate: failed" in label.text()
    ]
    assert len(failed_statuses) == 1

    dialog._visually_approved_candidates.add("attachment-01")
    dialog._render()
    application.processEvents()
    approved_index = dialog.selection_combo.findData("attachment-01")
    assert approved_index >= 1
    assert "visual QC passed" in dialog.selection_combo.itemText(approved_index)
    dialog.close()
    application.processEvents()
