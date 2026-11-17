from types import SimpleNamespace

import numpy as np
import pytest

from diffeoforge.desktop import joint_pilot_transfer as transfer
from diffeoforge.desktop.joint_pilot_transfer import measure_transfer
from diffeoforge.desktop.reference_calibration_dialog import CalibrationQcPair
from diffeoforge.mesh import sha256_file


@pytest.mark.parametrize("shift, reverse", [(0.15, "worse"), (1.0, "unavailable")])
def test_localized_joint_regression_and_missing_reverse_are_distinct(shift, reverse):
    vertices = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0],
                         [3, 0, 0], [4, 0, 0], [3, 1, 0]], dtype=float)
    triangles = np.array([[0, 1, 2], [3, 4, 5]])
    original = SimpleNamespace(vertices=vertices, triangles=triangles)
    shared_vertices = vertices.copy()
    shared_vertices[:3, 2] += shift
    shared = SimpleNamespace(vertices=shared_vertices, triangles=triangles)
    regions = [dict(center=vertices[tri].mean(axis=0).tolist(), radius=.25) for tri in triangles]

    rows = measure_transfer(original, original, shared, regions)

    forward, backward = rows[0]["directions"]
    assert forward["change"] == "worse"
    assert forward["shared"] == pytest.approx((shift * 100 / np.sqrt(17),) * 2)
    assert backward["change"] == reverse
    if reverse == "unavailable":
        assert backward["shared"] is None
    assert [finding["change"] for finding in rows[1]["directions"]] == ["unclear", "unclear"]


def test_joint_comparison_verifies_singleton_and_viewed_endpoint(tmp_path, monkeypatch):
    roots = [tmp_path / "individual", tmp_path / "joint"]
    candidates = [SimpleNamespace(candidate_id=name, status="completed")
                  for name in ("singleton", "shared")]
    snapshots, pairs = [], []
    for root, phase, candidate in zip(roots, ("validate", "joint"), candidates, strict=True):
        root.mkdir()
        original = root / "case.vtk"
        original.write_bytes(b"same specimen")
        pairs.append(CalibrationQcPair("subject:case.vtk", "case", original, root / "fit.vtk",
                                      True, sha256_file(original), "fit-hash"))
        snapshots.append(SimpleNamespace(
            study_directory=root, candidates=[candidate], problem_regions={},
            plan=SimpleNamespace(pilot_subject_count=1 if phase == "validate" else 2),
            info=dict(phase=phase, origin=str(tmp_path), pilot_order=["case.vtk"])))
    singleton, joint = snapshots
    original_approval = dict(filename="case.vtk", directory=str(roots[0]),
                             candidate_id="singleton")
    pending = [original_approval]
    approvals_checked = []
    monkeypatch.setattr(transfer.study, "load_reference_calibration_study",
                        dict(zip(roots, snapshots, strict=True)).__getitem__)
    monkeypatch.setattr(transfer.guided, "record", lambda value: value.info)
    monkeypatch.setattr(transfer.guided, "verify_approvals", approvals_checked.extend)
    monkeypatch.setattr(transfer.pilot_form_progress, "marker", lambda _: {"reviews": pending})
    monkeypatch.setattr(transfer, "collect_calibration_qc_pairs",
                        lambda root, _: [pairs[roots.index(root)]])

    individual, shared, evidence = transfer.prepare_joint_transfer(
        joint.study_directory, "shared", pairs[1], [],
    )
    assert (individual, shared, evidence) == (*pairs, [])
    assert approvals_checked == [original_approval]

    with pytest.raises(ValueError, match="shown in the viewer changed"):
        transfer.prepare_joint_transfer(joint.study_directory, "shared", pairs[0], [])
    singleton.info["origin"] = str(tmp_path / "unrelated")
    with pytest.raises(ValueError, match="different pilot"):
        transfer.prepare_joint_transfer(joint.study_directory, "shared", pairs[1], [])


def test_joint_viewer_opens_comparison_for_selected_specimen(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication

    from diffeoforge.desktop.preview_mesh_loader import PreviewMeshLoader
    from diffeoforge.desktop.reference_calibration_dialog import CalibrationCandidateViewerDialog

    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    paths = [tmp_path / name for name in ("first.vtk", "second.vtk", "fit.vtk")]
    pairs = tuple(CalibrationQcPair(f"subject:{path.name}", path.name, path, paths[2], True,
                                    "orig", "fit") for path in paths[:2])
    candidate = SimpleNamespace(candidate_id="shared", status="completed", run_directory=tmp_path,
                                metrics=dict(invalid_face_count=0))
    opened = []

    class Comparison:
        def __init__(self, parent, directory, identifier, pair, marks):
            opened.append((directory, identifier, pair, marks))

        def exec(self):
            return 0

        def deleteLater(self):
            pass

    monkeypatch.setattr(transfer, "JointPilotTransferDialog", Comparison)
    monkeypatch.setattr(PreviewMeshLoader, "request_paths", lambda *a, **k: None)
    dialog = CalibrationCandidateViewerDialog(tmp_path, candidate, pairs=pairs,
                                               compact_review=True, joint_transfer=True)
    try:
        marks = [{"center": [0.0, 0.0, 0.0]}]
        dialog.problem_regions[paths[1].name] = marks
        dialog._navigate_required_specimen(1)
        dialog.joint_transfer_button.click()
        assert opened == [(tmp_path, "shared", pairs[1], marks)]
        assert opened[0][-1] is not marks
        assert not dialog.review_recorded and not dialog.subject_decisions
    finally:
        dialog.close()
        app.processEvents()


def test_closing_comparison_cancels_a_queued_surface_check(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication

    from diffeoforge.desktop.preview_mesh_loader import PreviewMeshLoader

    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    operations = []
    monkeypatch.setattr(PreviewMeshLoader, "request_operation",
                        lambda _loader, _key, work: operations.append(work))
    pair = CalibrationQcPair("subject:case.vtk", "case", tmp_path / "case.vtk",
                             tmp_path / "fit.vtk", True, "original", "fit")
    dialog = transfer.JointPilotTransferDialog(None, tmp_path, "shared", pair, [])
    try:
        dialog.reject()
        with pytest.raises(InterruptedError, match="comparison cancelled"):
            operations[0]()
    finally:
        dialog.close()
        app.processEvents()
