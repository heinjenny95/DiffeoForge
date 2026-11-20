"""Verify the paired material point and refuse unbound geometry."""

import json
import time

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from diffeoforge.desktop import atlas_correspondence_dialog as probe
from diffeoforge.desktop.result_review import (
    ModernResultArtifact,
    ModernResultReview,
    ModernResultReviewError,
    RegistrationQCItem,
)
from diffeoforge.mesh import sha256_file, write_vtk_polydata

_VERTICES = ((0, 0, 0), (2, 0, 0), (0, 2, 0), (0, 0, 2))
_FACES = ((0, 1, 2), (0, 3, 1))


def _review(run, *, vertex_z=0.0, template_title="Template", original_title="Original",
            faces=_FACES):
    template = run / "input" / "template" / "template.vtk"
    template.parent.mkdir(parents=True)
    write_vtk_polydata(template, _VERTICES, _FACES, title=template_title)
    manifest = run / "manifest.json"
    manifest.write_text(
        json.dumps({
            "inputs": [{
                "role": "template",
                "staged_path": "input/template/template.vtk",
                "geometry": {"bytes": template.stat().st_size, "sha256": sha256_file(template)},
            }],
        }),
        encoding="utf-8",
    )
    bundle = run / "analysis"
    bundle.mkdir()
    bundle_manifest = bundle / "manifest.json"
    bundle_manifest.write_text("{}", encoding="utf-8")
    points = np.asarray(_VERTICES, dtype=float)
    points[1, 2] = vertex_z
    original = write_vtk_polydata(
        bundle / "original.vtk", _VERTICES, _FACES, title=original_title,
    )
    reconstruction = write_vtk_polydata(bundle / "reconstruction.vtk", points, faces)
    artifacts = tuple(
        ModernResultArtifact(kind, kind, path, "vtk", path.stat().st_size, sha256_file(path), "")
        for kind, path in (("original", original), ("reconstruction", reconstruction))
    )
    return ModernResultReview(
        run_directory=run,
        bundle_directory=bundle,
        project_name="Synthetic correspondence test",
        created_at="",
        workflow_manifest_path=manifest,
        workflow_manifest_sha256=sha256_file(manifest),
        bundle_manifest_path=bundle_manifest,
        bundle_manifest_sha256=sha256_file(bundle_manifest),
        optimizer_converged=True,
        optimizer_termination_reason="",
        optimizer_cycles_completed=0,
        optimizer_max_cycles=0,
        overview=(),
        optimization=(),
        pca=(),
        quality=(),
        artifacts=artifacts,
        scientific_boundaries=(),
        registration_qc=(RegistrationQCItem(1, "one.vtk", 0, "original", "reconstruction"),),
        engine_route="deformetrica_reference",
    )


def _paired_sources(tmp_path, monkeypatch, **second_options):
    paths = tmp_path / "first", tmp_path / "second"
    sources = {
        paths[0]: _review(paths[0], vertex_z=0.25),
        paths[1]: _review(paths[1], vertex_z=0.75, **second_options),
    }

    def read(path, *, create_pca_if_missing):
        assert create_pca_if_missing is False
        return sources[path]

    monkeypatch.setattr(probe, "_review", read)
    return paths, sources


def _wait(app, predicate):
    until = time.monotonic() + 5
    while not predicate() and time.monotonic() < until:
        app.processEvents()
        time.sleep(.01)
    assert predicate()


def test_explicit_material_vertex_reaches_both_linked_overlays(tmp_path, monkeypatch):
    paths, _ = _paired_sources(tmp_path, monkeypatch)
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    dialog = probe.AtlasCorrespondenceDialog(*paths)
    dialog.show()
    try:
        _wait(app, dialog.specimens.isEnabled)
        assert dialog._source.pick_vertex((1.75, .1, 1), (1.75, .1, -1)) == 1
        dialog.specimens.setCurrentIndex(0)
        _wait(app, lambda: dialog.left.original_model is not None)
        dialog.vertex.setValue(1)
        assert dialog.left._inspection_markers == {"1": (2., 0., .25)}
        assert dialog.right._inspection_markers == {"1": (2., 0., .75)}
        assert dialog.left.original_model is dialog.right.original_model
        assert "endpoint distance 0.5" in dialog.status.text()
        dialog.left.set_view_preset("front")
        assert dialog.left.camera_state() == dialog.right.camera_state()
    finally:
        dialog.close()


def test_independent_landmark_distances_follow_the_verified_specimen(tmp_path, monkeypatch):
    paths, _ = _paired_sources(tmp_path, monkeypatch)
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    dialog = probe.AtlasCorrespondenceDialog(*paths)
    dialog.show()
    try:
        _wait(app, dialog.specimens.isEnabled)
        assert not dialog.landmark_input.isEnabled()
        dialog.specimens.setCurrentIndex(0)
        _wait(app, dialog.landmark_input.isEnabled)
        dialog.vertex.setValue(1)
        dialog.landmark_input.setText("2, 0, .375")
        dialog.landmark_apply.click()
        assert dialog.left._inspection_markers["Landmark"] == (2., 0., .375)
        assert dialog.right._inspection_markers["Landmark"] == (2., 0., .375)
        assert "Atlas A 0.125 · Atlas B 0.375" in dialog.landmark_status.text()

        dialog.landmark_input.setText("2 0 nan")
        dialog.landmark_apply.click()
        assert "three finite XYZ" in dialog.landmark_status.text()
        assert "Landmark" not in dialog.left._inspection_markers

        dialog.landmark_input.setText("2 0 .375")
        dialog.landmark_apply.click()
        dialog.specimens.setCurrentIndex(-1)
        assert not dialog.landmark_input.isEnabled()
        assert not dialog.landmark_input.text()
        assert not dialog.landmark_status.text()
        assert not dialog.left._inspection_markers
    finally:
        dialog.close()


@pytest.mark.parametrize(
    ("options", "failure"),
    (
        ({"original_title": "Different aligned original"}, "different aligned original"),
        ({"faces": _FACES[::-1]}, "ordered topology"),
    ),
)
def test_probe_refuses_unbound_subject_geometry(tmp_path, monkeypatch, options, failure):
    paths, _ = _paired_sources(tmp_path, monkeypatch, **options)
    source = probe._load_probe(*paths)
    with pytest.raises(ValueError, match=failure):
        probe._load_specimen(source, "one.vtk")


def test_probe_requires_exact_template_and_reverifies_both_originals(tmp_path, monkeypatch):
    mismatched, _ = _paired_sources(
        tmp_path / "different", monkeypatch, template_title="Another template",
    )
    with pytest.raises(ValueError, match="different verified starting-template bytes"):
        probe._load_probe(*mismatched)
    paired, reviews = _paired_sources(tmp_path / "shared", monkeypatch)
    source = probe._load_probe(*paired)
    reviews[paired[1]].artifact("original").path.write_bytes(b"changed")
    with pytest.raises(ModernResultReviewError, match="changed"):
        probe._load_specimen(source, "one.vtk")
