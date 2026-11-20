"""The guided comparison opens two exact saved results without a QC or solver write."""

import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication, QDialog, QWidget

from diffeoforge import guided_feedback, reference_calibration_study, reference_guided_pilot
from diffeoforge.desktop import guided_fit_direction as viewer
from diffeoforge.desktop.guided_working_fit import viewer as working_viewer
from diffeoforge.desktop.reference_calibration_dialog import CalibrationQcPair
from diffeoforge.mesh import sha256_file


def _direction(target, current, alternative):
    return {
        "identifier": "guided-current",
        "target": target,
        "current": dict(directory=str(current), candidate_id="guided-current",
                        method="current", target=target),
        "alternative": dict(directory=str(alternative), candidate_id="guided-varifold",
                            method="varifold", target=target),
        "current_cp": 405, "alternative_cp": 270,
        "current_p95": 10.25, "alternative_p95": 8.25,
        "regions": [dict(cell=[1, 2, 3], current_p95=25.0, alternative_p95=14.0)],
    }


def test_compare_preparation_requires_exact_original_template_and_references(
    tmp_path, monkeypatch,
):
    origin, current, alternative = (
        tmp_path / name for name in ("pilot", "current", "alternative"))
    target = "example.vtk"
    direction = _direction(target, current, alternative)
    snapshots = {}
    manifests = {}
    for name, path, trial, count in (
        ("current", current, 6, 405),
        ("alternative", alternative, 4, 270),
    ):
        ref = direction[name]
        candidate = SimpleNamespace(candidate_id=ref["candidate_id"])
        snapshots[path] = SimpleNamespace(study_directory=path, candidates=[candidate],
            plan=SimpleNamespace(pilot_subject_count=1),
            attachment_comparison={"controls": {"count": count}},
            info={"origin": str(origin), "target": target, "screen_trials_spent": trial,
                  "history": [{"directory": str(alternative)}]})
        manifests[path] = {"inputs": {"template": {"sha256": "2"},
                                      "subjects": [{"filename": target, "sha256": "3"}]}}
    seen = []

    def verify(ref):
        seen.append(ref)
        return snapshots[Path(ref["directory"])]

    monkeypatch.setattr(reference_calibration_study, "load_reference_calibration_study",
                        snapshots.__getitem__)
    monkeypatch.setattr(reference_calibration_study, "_verify_manifest", manifests.__getitem__)
    monkeypatch.setattr(reference_guided_pilot, "record", lambda snap: snap.info)
    monkeypatch.setattr(guided_feedback, "verify_reference", verify)
    monkeypatch.setattr(viewer, "collect_calibration_qc_pairs",
        lambda path, candidate: (CalibrationQcPair(
            "subject", target, path / target, path / "reco.vtk", True,
            manifests[path]["inputs"]["subjects"][0]["sha256"], candidate.candidate_id),))
    (left, right), labels = viewer._prepare(current, direction)
    assert seen == [direction["current"], direction["alternative"]]
    assert labels == ("Current · Test 6 · 405 CP", "Varifold · Test 4 · 270 CP")
    assert left.original_sha256 == right.original_sha256 == "3"
    assert left.reconstruction_path.parent == current
    assert right.reconstruction_path.parent == alternative

    manifests[alternative]["inputs"]["subjects"][0]["sha256"] = "4"
    with pytest.raises(ValueError, match="exact original and template"):
        viewer._prepare(current, direction)
    manifests[alternative]["inputs"]["subjects"][0]["sha256"] = "3"
    manifests[alternative]["inputs"]["template"]["sha256"] = "5"
    with pytest.raises(ValueError, match="exact original and template"):
        viewer._prepare(current, direction)
    direction["alternative"]["directory"] = str(tmp_path / "outside-history")
    with pytest.raises(ValueError, match="do not belong"):
        viewer._prepare(current, direction)


def test_saved_dialog_loads_linked_overlays_and_requires_explicit_work_choice(
    tmp_path, monkeypatch,
):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    window = QWidget()
    example = Path(__file__).resolve().parents[1] / "examples" / "synthetic" / "meshes"
    original, left, right = (example / name for name in (
        "subject-01.vtk", "template.vtk", "subject-02.vtk"))
    original_sha = sha256_file(original)
    pairs = tuple(CalibrationQcPair(name, name, original, fit, True, original_sha, sha256_file(fit))
                  for name, fit in (("left", left), ("right", right)))
    direction = _direction(original.name, tmp_path, tmp_path / "alternative")
    dialog = viewer._ComparisonDialog(window, tmp_path, direction,
        (pairs, ("Current · Test 6 · 405 CP", "Varifold · Test 4 · 270 CP")))
    dialog.show()

    def settled():
        deadline = time.monotonic() + 15
        while not dialog.work.isEnabled() and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(.005)
        assert dialog.work.isEnabled(), dialog.status.text()

    try:
        assert not dialog.work.isEnabled()
        settled()
        canvas, alternative = dialog.canvases
        assert canvas.reconstruction_model.path == left
        assert alternative.reconstruction_model.path == right
        assert canvas.original_model is alternative.original_model
        assert canvas._inspection_markers == alternative._inspection_markers
        assert set(canvas._inspection_markers) == {"Area 1"}
        canvas.set_view_preset("top")
        assert canvas.camera_state() == alternative.camera_state()
        dialog.detail.setChecked(True)
        assert not dialog.work.isEnabled()
        settled()
        assert all(item.original_detail.isChecked() for item in dialog.canvases)
        dialog.work.click()
        assert dialog.result() == QDialog.DialogCode.Accepted
        hint = dialog.working_view
        assert hint["reference"] == direction["alternative"]
        assert hint["hashes"] == (original_sha, sha256_file(right))
        assert hint["camera"] == alternative.camera_state()
        working = working_viewer(window, tmp_path, SimpleNamespace(study_directory=tmp_path),
            SimpleNamespace(run_directory=tmp_path, candidate_id="guided-varifold",
                            status="completed", metrics={"invalid_face_count": 0}),
            (pairs[1],), {}, dict(
                target=original.name, reference=direction["alternative"], label="Saved alternative",
                problem_regions={}, cleared_region_subjects=[], view_hint=hint,
            ))
        try:
            working.show()
            deadline = time.monotonic() + 15
            while not working.canvas.comparison_ready and time.monotonic() < deadline:
                app.processEvents()
                time.sleep(.005)
            assert working.canvas.comparison_ready
            assert working.canvas.camera_state() == hint["camera"]
            assert working.canvas._inspection_markers == dict(hint["markers"])
            assert working.problem_regions == {} and not working.review_recorded
        finally:
            working.close()
    finally:
        dialog.close()
        app.processEvents()
