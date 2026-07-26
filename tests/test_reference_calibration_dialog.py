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

    assert dialog.pass_check.isEnabled() is False
    assert "1 of 2" in dialog.review_progress.text()
    assert dialog.pass_check.isHidden() is True
    assert dialog.previous_specimen_button.isEnabled() is False
    assert dialog.next_specimen_button.isEnabled() is True

    dialog.next_specimen_button.click()
    application.processEvents()
    assert dialog.pass_check.isEnabled() is True
    assert dialog.pass_check.isHidden() is False
    assert "2 of 2" in dialog.review_progress.text()
    assert dialog.next_specimen_button.isEnabled() is False
    assert dialog.complete_button.isEnabled() is False

    dialog.pass_check.setChecked(True)
    assert dialog.complete_button.isEnabled() is True
    dialog.complete_button.click()
    assert dialog.review_complete is True
    dialog.close()
    application.processEvents()
