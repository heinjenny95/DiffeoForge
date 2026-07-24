from __future__ import annotations

import csv
import shutil
from pathlib import Path

import numpy as np
import pytest

from diffeoforge.analysis.landmarks import LANDMARK_COLUMNS
from diffeoforge.desktop.gpa_visualization import (
    MAX_EDGES_PER_MESH,
    build_gpa_alignment_visual,
    load_gpa_aligned_detail,
)
from diffeoforge.desktop.mesh_preview import MeshPreviewError
from diffeoforge.mesh import read_vtk_polydata, sha256_file
from diffeoforge.preprocessing import preview_landmark_alignment

ROOT = Path(__file__).parents[1]
MESH_DIRECTORY = ROOT / "examples" / "synthetic" / "meshes"
LANDMARK_INDICES = (0, 40, 80)


def _write_landmarks(
    path: Path,
    mesh_directory: Path = MESH_DIRECTORY,
) -> Path:
    meshes = [
        mesh_directory / "template.vtk",
        *sorted(mesh_directory.glob("subject-*.vtk")),
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(LANDMARK_COLUMNS)
        for mesh in meshes:
            points = read_vtk_polydata(mesh).vertices
            for label, point_index in zip(
                ("anterior", "dorsal", "posterior"),
                LANDMARK_INDICES,
                strict=True,
            ):
                writer.writerow((mesh.name, label, *points[point_index]))
    return path


def test_gpa_visual_is_hash_bound_memory_bounded_and_read_only(
    tmp_path: Path,
) -> None:
    landmarks = _write_landmarks(tmp_path / "landmarks.csv")
    sources = (
        MESH_DIRECTORY / "template.vtk",
        *sorted(MESH_DIRECTORY.glob("subject-*.vtk")),
    )
    before = {path: sha256_file(path) for path in (*sources, landmarks)}
    preview = preview_landmark_alignment(
        MESH_DIRECTORY,
        landmarks_file=landmarks,
    )

    visual = build_gpa_alignment_visual(preview)

    assert visual.fingerprint == preview.fingerprint
    assert len(visual.meshes) == len(sources) == 6
    assert visual.landmark_labels == ("anterior", "dorsal", "posterior")
    assert visual.total_displayed_edges <= len(sources) * MAX_EDGES_PER_MESH
    assert visual.total_displayed_edges <= visual.total_source_edges
    assert all(
        len(mesh.edges) <= MAX_EDGES_PER_MESH for mesh in visual.meshes
    )
    assert all(mesh.vertices.flags.writeable is False for mesh in visual.meshes)
    assert {path: sha256_file(path) for path in (*sources, landmarks)} == before

    detail = load_gpa_aligned_detail(preview, 0)
    detail_vertices = np.asarray(detail.vertices, dtype=np.float64)
    assert np.allclose(
        detail_vertices[list(LANDMARK_INDICES)],
        preview.alignment.aligned_landmarks[0],
        rtol=1e-12,
        atol=1e-12,
    )
    assert visual.first_detail.sha256 == before[sources[0]]


def test_gpa_visual_rejects_mesh_drift_after_numerical_preview(
    tmp_path: Path,
) -> None:
    mesh_directory = tmp_path / "meshes"
    shutil.copytree(MESH_DIRECTORY, mesh_directory)
    landmarks = _write_landmarks(
        tmp_path / "landmarks.csv",
        mesh_directory,
    )
    preview = preview_landmark_alignment(
        mesh_directory,
        landmarks_file=landmarks,
    )
    changed = mesh_directory / "subject-03.vtk"
    changed.write_bytes(changed.read_bytes() + b"\n")

    with pytest.raises(MeshPreviewError, match="changed after"):
        build_gpa_alignment_visual(preview)


def test_gpa_review_dialog_can_inspect_and_complete_exact_visual(
    monkeypatch,
    tmp_path: Path,
) -> None:
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QDialog

    from diffeoforge.desktop.gpa_review_dialog import GpaAlignmentReviewDialog

    application = QApplication.instance() or QApplication(
        ["diffeoforge-gpa-visual-review-test"]
    )
    landmarks = _write_landmarks(tmp_path / "landmarks.csv")
    preview = preview_landmark_alignment(
        MESH_DIRECTORY,
        landmarks_file=landmarks,
    )
    visual = build_gpa_alignment_visual(preview)
    dialog = GpaAlignmentReviewDialog(preview, visual)
    dialog.show()
    application.processEvents()

    assert dialog.mesh_combo.count() == len(visual.meshes)
    assert dialog.canvas.show_cohort is True
    assert dialog.canvas.show_landmarks is True
    assert dialog.viewed_mesh_count == 1
    assert dialog.complete_button.isEnabled() is False
    dialog._select_highest_residual()
    application.processEvents()
    assert dialog.viewed_mesh_count >= 1
    assert "squared landmark residual" in dialog.mesh_status_label.text()
    assert "/" in dialog.inspection_progress_label.text()

    dialog.review_complete_check.setChecked(True)
    assert dialog.complete_button.isEnabled() is True
    dialog.complete_button.click()
    application.processEvents()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.reviewed_fingerprint == preview.fingerprint
    dialog.close()
    application.processEvents()
