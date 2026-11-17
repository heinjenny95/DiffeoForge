import json
import time
from types import SimpleNamespace

import numpy as np
import pytest

pytest.importorskip("PySide6")

from diffeoforge.desktop import reference_holdout_review as review
from diffeoforge.mesh import TriangleMesh, sha256_file, write_vtk_polydata
from diffeoforge.reference_holdout_study import ReferenceHoldoutStudySnapshot
from diffeoforge.reference_validation_study import ValidationStudyRunState

_VERTICES = ((0, 0, 0), (1, 0, 0), (0, 1, 0))
_FACES = ((0, 1, 2),)


@pytest.fixture
def holdout(tmp_path, monkeypatch):
    root = tmp_path / "fixed-template-holdout"
    run = root / "run"
    for relative in ("input/template", "input/subjects", "input/control-points", "output"):
        (run / relative).mkdir(parents=True, exist_ok=True)
    original_path = write_vtk_polydata(run / "input/subjects/subject.vtk", _VERTICES, _FACES)
    template_path = write_vtk_polydata(run / "input/template/template.vtk", _VERTICES, _FACES)
    controls = run / "input/control-points/controls.txt"
    controls.write_text("0 0 0\n", encoding="ascii")
    name = "DeterministicAtlas__Reconstruction__surface__subject_subject.vtk.vtk"
    fit_path = write_vtk_polydata(run / "output" / name, _VERTICES, _FACES)
    original_digest = sha256_file(original_path)
    template_digest = sha256_file(template_path)
    controls_digest = sha256_file(controls)
    config_digest = "b" * 64
    design = {
        "runs": [{"run_id": "holdout", "config_sha256": config_digest}],
        "subjects": [{"filename": "subject.vtk", "sha256": original_digest}],
        "trained_models": [{
            "finalist_id": "finalist",
            "template": {"sha256": template_digest},
            "control_points": {"sha256": controls_digest},
        }],
    }
    manifest = root / review.HOLDOUT_MANIFEST
    manifest.write_text(json.dumps(design), encoding="utf-8")
    (root / review.HOLDOUT_DIGEST).write_text(sha256_file(manifest) + "\n", encoding="ascii")
    state = ValidationStudyRunState(
        "holdout", "finalist", "fixed-template-holdout", "completed", run / "atlas.yaml",
        run, 1, None, None,
    )
    snapshot = ReferenceHoldoutStudySnapshot(
        root, "holdout-id", tmp_path, "parent-id", ("subject.vtk",), ("finalist",), "completed",
        (state,), 3, SimpleNamespace(practical_error_margin=0.05, preferred_finalist_id="finalist"),
        None, None,
    )
    report = SimpleNamespace(
        run_directory=run,
        result={"status": "completed"},
        checks=(SimpleNamespace(status="pass"),),
        inventory=({
            "path": name, "bytes": fit_path.stat().st_size, "sha256": sha256_file(fit_path),
        },),
        manifest={
            "source_config": {"sha256": config_digest},
            "effective_config": {
                "optimization": {"freeze_template": True, "freeze_control_points": True},
                "model": {"object_id": "surface"},
            },
            "inputs": [
                {"role": "template", "staged_path": "input/template/template.vtk", "geometry": {
                    "sha256": template_digest,
                }},
                {"role": "subject", "staged_path": "input/subjects/subject.vtk", "geometry": {
                    "sha256": original_digest, "bytes": original_path.stat().st_size,
                }},
            ],
            "protected_artifacts": [{
                "path": "input/control-points/controls.txt", "sha256": controls_digest,
            }],
        },
    )
    monkeypatch.setattr(review, "load_reference_holdout_study", lambda directory: snapshot)
    monkeypatch.setattr(review, "collect_run_report", lambda directory: report)
    monkeypatch.setattr(review, "screen_surface_misses", lambda *args, **kwargs: ())
    return snapshot, report, original_path, fit_path, controls


def _load(snapshot, subject="subject.vtk"):
    return review.load_holdout_overlay(snapshot, "finalist", subject, cancelled=lambda: False)


def test_only_reserved_subject_and_sealed_pair_are_displayed(holdout):
    snapshot, _report, original, fit, _controls = holdout
    previous = (original.read_bytes(), fit.read_bytes())
    overlay = _load(snapshot)
    assert overlay.original.path == original
    assert overlay.reconstruction.path == fit
    assert overlay.flags == ()
    assert overlay.threshold == 0.05
    assert previous == (original.read_bytes(), fit.read_bytes())
    with pytest.raises(ValueError, match="reserved holdout specimen"):
        _load(snapshot, "training.vtk")


def test_ambiguous_or_changed_evidence_bars_overlay(holdout):
    snapshot, report, _original, fit, controls = holdout
    original_inventory = report.inventory
    report.inventory *= 2
    with pytest.raises(ValueError, match="one verified final reconstruction"):
        _load(snapshot)
    report.inventory = original_inventory

    controls.write_text("2 0 0\n", encoding="ascii")
    with pytest.raises(ValueError, match="frozen model bytes changed"):
        _load(snapshot)
    controls.write_text("0 0 0\n", encoding="ascii")

    data = fit.read_bytes()
    fit.write_bytes(data.replace(b"DiffeoForge", b"Wrong bytes", 1))
    with pytest.raises(ValueError, match="changed since the sealed run"):
        _load(snapshot)


def test_coherent_local_miss_is_flagged_but_isolated_sample_is_not(monkeypatch):
    original = TriangleMesh(_VERTICES, _FACES)
    reconstruction = TriangleMesh(tuple((x, y, 1) for x, y, _ in _VERTICES), _FACES)
    points = np.asarray([
        [0, 0, 0], [0.01, 0, 0], [0, 0.01, 0], [0.01, 0.01, 0], [0.9, 0, 0],
    ])
    monkeypatch.setattr(review, "surface_samples", lambda *args, **kwargs: points)
    monkeypatch.setattr(
        review,
        "distances_to_surface",
        lambda points, vertices, faces: (
            np.asarray([0.08, 0.06, 0.09, 0.3, 0.5]) if vertices == reconstruction.vertices
            else np.zeros(len(points))
        ),
    )
    assert review.screen_surface_misses(
        original, reconstruction, 0.05, cancelled=lambda: False,
    ) == (review.SurfaceFlag((0.01, 0.01, 0), "Original surface missed", 0.3, 4),)
    with pytest.raises(InterruptedError):
        review.screen_surface_misses(original, reconstruction, 0.05, cancelled=lambda: True)


def test_review_dialog_only_loads_on_request_and_clears_on_selection(holdout, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    application = QApplication.instance() or QApplication(["holdout-review-test"])
    snapshot, _report, original, fit, _controls = holdout
    dialog = review.ReferenceHoldoutReviewDialog(snapshot)
    try:
        assert dialog.canvas.original_model is None
        dialog.load_button.click()
        deadline = time.monotonic() + 5
        while dialog._worker is not None and time.monotonic() < deadline:
            application.processEvents()
            time.sleep(0.005)
        assert dialog.canvas.original_model.path == original
        assert dialog.canvas.reconstruction_model.path == fit
        assert "no cluster" in dialog.status.text()
        dialog.subject.setCurrentIndex(-1)
        assert dialog.canvas.original_model is None
        assert dialog.canvas.reconstruction_model is None
    finally:
        dialog.close()
