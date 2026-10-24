"""Owner-reported transitions and loading regressions; synthetic data only."""

import csv
import json

import numpy as np
import pytest
from test_guided_pilot import approve, origin, run_batch
from test_preprocessing import MESH_DIRECTORY, _write_landmarks
from test_shape_descriptor import cube

from diffeoforge import preprocessing
from diffeoforge import reference_guided_pilot as guided
from diffeoforge.mesh import sha256_file, write_vtk_polydata
from diffeoforge.pilot_design import suggest_templates
from diffeoforge.template_shape import local_shape_descriptor


def test_refresh_removes_nested_controls_without_waiting_for_deferred_delete(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from pilot_view_helpers import wait_pilot_view
    from PySide6.QtWidgets import QApplication, QComboBox, QFrame, QPushButton

    from diffeoforge.desktop.reference_calibration_dialog import ReferenceCalibrationDialog

    app = QApplication.instance() or QApplication([])
    snapshot = run_batch(guided.prepare(origin(tmp_path).study_directory), monkeypatch)
    dialog = ReferenceCalibrationDialog(snapshot.study_directory)
    dialog.resize(1000, 650)
    dialog.show()
    try:
        wait_pilot_view(dialog)
        prepared = dialog._prepared_view
        opened = []
        monkeypatch.setattr(dialog, "_open_candidate", opened.append)
        for width, height in ((1000, 650), (760, 550), (1500, 950), (1000, 650)):
            dialog.resize(width, height)
            dialog._render(prepared=prepared)
            # Must hold even before deleteLater is processed.
            buttons = [b for b in dialog.content.findChildren(QPushButton)
                       if b.property("pilotCandidate")]
            choices = [c for c in dialog.content.findChildren(QComboBox)
                       if c.accessibleName() == "Fit to inspect"]
            assert len(buttons) == 2 and not choices
            app.processEvents()
            for button, candidate in zip(buttons, snapshot.candidates, strict=True):
                assert not button.isHidden()
                button.click()
                assert opened[-1].candidate_id == candidate.candidate_id
            cards = [c for c in dialog.content.findChildren(QFrame)
                     if c.property("pilotCandidate")]
            assert len(cards) == 2 and not cards[0].geometry().intersects(cards[1].geometry())
        dialog._worker = object()
        dialog._render(prepared=prepared)
        assert not [b for b in dialog.content.findChildren(QPushButton)
                    if b.property("pilotCandidate")]
        assert not dialog.start_button.isEnabled()
        assert dialog.start_button.objectName() == "secondary"
        assert dialog.cancel_button.isEnabled()
        dialog._worker = None
        dialog._render(prepared=prepared)
        decisions = [b for b in dialog.content.findChildren(QPushButton)
                     if b.text().startswith(("Both good", "Both unfit", "Use "))]
        assert all(b.isHidden() for b in decisions)
    finally:
        dialog._worker = None
        dialog.close()
        app.processEvents()


def test_primary_run_and_reviewed_continuation_are_prominent(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from pilot_view_helpers import wait_pilot_view
    from PySide6.QtWidgets import QApplication, QPushButton

    from diffeoforge.desktop.reference_calibration_dialog import ReferenceCalibrationDialog

    app = QApplication.instance() or QApplication([])
    child = guided.prepare(origin(tmp_path).study_directory)
    dialog = ReferenceCalibrationDialog(child.study_directory)
    try:
        wait_pilot_view(dialog)
        assert dialog.start_button.isEnabled()
        assert dialog.start_button.objectName() == "primary"
        done = approve(approve(run_batch(child, monkeypatch), "guided-current"), "guided-varifold")
        dialog._render(done)
        wait_pilot_view(dialog)
        tie = next(b for b in dialog.content.findChildren(QPushButton)
                   if b.text().startswith("No clear preference"))
        assert not tie.isHidden() and tie.isEnabled() and tie.objectName() == "primary"
        assert dialog.start_button.isHidden()
    finally:
        dialog.close()
        app.processEvents()


def test_saved_alignment_reopens_without_mesh_parse_but_checks_current_bytes(tmp_path, monkeypatch):
    landmarks = _write_landmarks(tmp_path / "landmarks.csv")
    kwargs = dict(project_directory=tmp_path / "project", landmarks_file=landmarks)
    cold = preprocessing.prepare_landmark_aligned_inputs(MESH_DIRECTORY, **kwargs)
    cold_hashes = {p.relative_to(cold.directory): sha256_file(p)
                   for p in cold.directory.rglob("*") if p.is_file()}
    monkeypatch.setattr(preprocessing, "load_surface_mesh",
                        lambda *_a: pytest.fail("Reopening parsed a mesh"))
    monkeypatch.setattr(preprocessing, "preview_landmark_alignment",
                        lambda *_a, **_k: pytest.fail("Reopening rebuilt the preview"))
    messages = []
    reopened = preprocessing.prepare_landmark_aligned_inputs(
        MESH_DIRECTORY, **kwargs, progress_callback=lambda _a, _b, p: messages.append(p.name)
    )
    assert reopened == cold
    assert messages[0].startswith("Checking files")
    assert messages[-1] == "Reusing verified alignment"
    assert {p.relative_to(cold.directory): sha256_file(p)
            for p in cold.directory.rglob("*") if p.is_file()} == cold_hashes
    # Corrupt aligned bytes must fail, not be silently re-used or overwritten.
    reopened.template.write_bytes(reopened.template.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="aligned mesh"):
        preprocessing.prepare_landmark_aligned_inputs(MESH_DIRECTORY, **kwargs)


def test_nonvtk_reuse_and_source_and_setting_invalidation(tmp_path, monkeypatch):
    source = tmp_path / "meshes"
    source.mkdir()
    v, f = cube()
    for i in range(3):
        path = source / ("template.obj" if i == 0 else f"subject-{i}.obj")
        path.write_text("\n".join(
            ["v " + " ".join(map(str, p)) for p in v + i]
            + ["f " + " ".join(str(int(j) + 1) for j in face) for face in f]
        ))
    landmarks = tmp_path / "landmarks.csv"
    with landmarks.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(("mesh_file", "landmark", "x", "y", "z"))
        for i, path in enumerate([source / "template.obj", *sorted(source.glob("subject*"))]):
            for label, p in zip(("a", "b", "c"), (v + i)[[0, 2, 5]], strict=True):
                writer.writerow((path.name, label, *p))
    kwargs = dict(project_directory=tmp_path / "project", landmarks_file=landmarks,
                  subject_pattern="*.obj")
    first = preprocessing.prepare_landmark_aligned_inputs(source, **kwargs)
    original_preview = preprocessing.preview_landmark_alignment
    monkeypatch.setattr(preprocessing, "preview_landmark_alignment",
                        lambda *_a, **_k: pytest.fail("Non-VTK input reparsed on reopening"))
    assert preprocessing.prepare_landmark_aligned_inputs(source, **kwargs) == first
    monkeypatch.setattr(preprocessing, "preview_landmark_alignment", original_preview)
    changed = preprocessing.prepare_landmark_aligned_inputs(source, **kwargs, target_size=2)
    assert changed.fingerprint != first.fingerprint
    raw = source / "subject-1.obj"
    raw.write_bytes(raw.read_bytes() + b"\n# changed source bytes\n")
    with pytest.raises(ValueError, match="approved preview"):
        preprocessing.prepare_landmark_aligned_inputs(
            source, **kwargs, expected_fingerprint=first.fingerprint
        )


def test_local_descriptor_detects_indentation_more_than_retriangulation():
    v, f = cube()
    original = np.asarray(local_shape_descriptor(v, f))
    centers = v[f].mean(axis=1)
    subdivided = np.asarray([[face[j], face[(j + 1) % 3], len(v) + i]
                             for i, face in enumerate(f) for j in range(3)])
    dense = np.asarray(local_shape_descriptor(np.vstack((v, centers)), subdivided))
    changed = v.copy()
    changed[6] = [0.2, 0.3, 0.1]
    local = np.asarray(local_shape_descriptor(changed, f))
    assert np.linalg.norm(local - original) > 3 * np.linalg.norm(dense - original)
    assert local_shape_descriptor(v * 3 + 4, f[::-1, ::-1]) == pytest.approx(original)


def test_cold_preview_releases_each_mesh_before_loading_the_next(tmp_path, monkeypatch):
    import weakref

    landmarks = _write_landmarks(tmp_path / "landmarks.csv")
    load = preprocessing.load_surface_mesh
    previous = []

    def checked(path):
        assert not previous or previous[-1]() is None, "Retained full cohort geometry"
        result = load(path)
        previous.append(weakref.ref(result))
        return result

    monkeypatch.setattr(preprocessing, "load_surface_mesh", checked)
    result = preprocessing.preview_landmark_alignment(MESH_DIRECTORY, landmarks_file=landmarks)
    assert len(previous) == len(result.source_paths) and previous[-1]() is None


def test_ranking_retains_contextual_rejection_and_contrasting_alternative(tmp_path):
    v, f = cube()
    paths = []
    for i, factor in enumerate((1, 1.01, 1.02, 3)):
        path = tmp_path / f"mesh-{i}.vtk"
        write_vtk_polydata(path, v * [factor, 1, 1], f, title="Synthetic")
        paths.append(path)
    first = suggest_templates(paths)
    rejected = dict(source_sha256=first["candidates"][0]["sha256"], approved=False,
                    method="current", settings={"noise_std": 1}, targets=[], source_study="test")
    result = suggest_templates(paths, review_evidence=[rejected])
    assert result["candidates"][0]["path"] == first["candidates"][0]["path"]
    assert result["candidates"][0]["previous_reviews"] == [rejected]
    assert len([r for r in result["candidates"] if r["contrasting_alternative"]]) == 1
    assert all("local_distance" in r for r in result["candidates"])
    assert isinstance(result["uncertain"], bool)


def test_previous_template_reviews_verify_decisions_and_skip_changed_evidence(
    tmp_path, monkeypatch
):
    from diffeoforge.template_reviews import previous_template_reviews

    snapshot = approve(run_batch(guided.prepare(origin(tmp_path).study_directory), monkeypatch))
    reviews = previous_template_reviews(tmp_path)
    assert any(r["candidate_id"] == "guided-current" and r["approved"] for r in reviews)
    assert all(r["targets"] and r["settings"] and r["method"] for r in reviews)
    manifest = snapshot.study_directory / "study.json"
    data = json.loads(manifest.read_text())
    data["inputs"]["template"]["sha256"] = "f" * 64
    manifest.write_text(json.dumps(data))
    assert not [r for r in previous_template_reviews(tmp_path)
                if r["source_study"] == str(snapshot.study_directory)]


def test_original_aligned_template_mapping_uses_root_preprocessing_and_checks_hash(tmp_path):
    from diffeoforge.template_reviews import _original_template_hash

    path = tmp_path / "alignment.json"
    path.write_text(json.dumps({"meshes": [
        dict(aligned_sha256="a" * 64, source_sha256="b" * 64),
    ]}))
    manifest = dict(inputs=dict(template=dict(sha256="a" * 64)),
                    source_config=dict(original_path=str(tmp_path / "atlas.yaml")))
    config = dict(preprocessing=dict(procrustes=dict(
        evidence_file=path.name, evidence_sha256=sha256_file(path),
    )))
    assert _original_template_hash(tmp_path, manifest, config) == "b" * 64
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="mapping changed"):
        _original_template_hash(tmp_path, manifest, config)


def test_decisions_hidden_until_first_frame_and_again_on_switch_or_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from test_reference_calibration_dialog import _model, _wait_pair

    from diffeoforge.desktop import reference_calibration_dialog as module
    from diffeoforge.desktop.preview_mesh_loader import PreviewMeshLoader
    from diffeoforge.reference_calibration_study import CalibrationStudyCandidateState

    app = QApplication.instance() or QApplication([])
    pairs = tuple(module.CalibrationQcPair(
        pair_id=f"subject:{i}", label=f"Form {i}", original_path=tmp_path / f"original-{i}.vtk",
        reconstruction_path=tmp_path / f"fit-{i}.vtk", required=True,
    ) for i in range(2))
    monkeypatch.setattr(module, "collect_calibration_qc_pairs", lambda *_a: pairs)
    monkeypatch.setattr(PreviewMeshLoader, "request_paths", lambda *_a, **_k: None)
    candidate = CalibrationStudyCandidateState(
        candidate_id="test", label="Test", status="completed", config_path=tmp_path / "config",
        run_directory=tmp_path / "run", metrics={}, error=None, attempts=1,
    )
    dialog = module.CalibrationCandidateViewerDialog(tmp_path, candidate, compact_review=True)
    dialog.show()
    try:
        app.processEvents()
        assert dialog.decision_panel.isHidden()
        assert dialog.close_button.isVisible()
        dialog._pair_loaded(0, [
            _model(pairs[0].original_path), _model(pairs[0].reconstruction_path),
        ])
        assert dialog.decision_panel.isHidden()  # Geometry assigned, not presented.
        _wait_pair(app, dialog)
        assert dialog.decision_panel.isVisible() and dialog.fail_button.isEnabled()
        dialog.mesh_combo.setCurrentIndex(1)
        assert dialog.decision_panel.isHidden()
        dialog._pair_failed(1, "Synthetic display failure")
        assert dialog.decision_panel.isHidden() and not dialog.review_recorded
        assert dialog.close_button.isVisible()
        assert "display failure" in dialog.status.text()
    finally:
        dialog.close()
        app.processEvents()
