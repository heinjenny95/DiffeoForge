from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np
import pytest

from diffeoforge.analysis.landmarks import LANDMARK_COLUMNS
from diffeoforge.config import ConfigurationError
from diffeoforge.mesh import read_vtk_polydata, sha256_file
from diffeoforge.preprocessing import (
    prepare_landmark_aligned_inputs,
    preview_landmark_alignment,
)

ROOT = Path(__file__).parents[1]
MESH_DIRECTORY = ROOT / "examples" / "synthetic" / "meshes"


def _write_landmarks(path: Path) -> Path:
    meshes = [MESH_DIRECTORY / "template.vtk", *sorted(MESH_DIRECTORY.glob("subject-*.vtk"))]
    indices = (0, 40, 80)
    labels = ("anterior", "dorsal", "posterior")
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(LANDMARK_COLUMNS)
        for mesh in meshes:
            points = read_vtk_polydata(mesh).vertices
            for label, point_index in zip(labels, indices, strict=True):
                writer.writerow((mesh.name, label, *points[point_index]))
    return path


def test_procrustes_preprocessing_is_engine_independent_and_preserves_raw_meshes(
    tmp_path: Path,
) -> None:
    sources = (MESH_DIRECTORY / "template.vtk", *sorted(MESH_DIRECTORY.glob("subject-*.vtk")))
    hashes_before = {path: sha256_file(path) for path in sources}
    landmarks = _write_landmarks(tmp_path / "landmarks.csv")

    result = prepare_landmark_aligned_inputs(
        MESH_DIRECTORY,
        project_directory=tmp_path / "project",
        landmarks_file=landmarks,
    )

    assert result.template.name == "template.vtk"
    assert len(result.subjects) == 5
    assert result.directory.name == f"aligned-{result.fingerprint[:16]}"
    assert result.evidence.is_file()
    assert {path: sha256_file(path) for path in sources} == hashes_before
    evidence = json.loads(result.evidence.read_text(encoding="utf-8"))
    assert evidence["method"] == "generalized_procrustes"
    assert evidence["converged"] is True
    assert evidence["landmark_labels"] == ["anterior", "dorsal", "posterior"]
    assert len(evidence["meshes"]) == 6
    assert all(
        Path(result.directory / item["aligned_path"]).is_file()
        for item in evidence["meshes"]
    )
    assert all(
        Path(result.directory / item["raw_copy_path"]).read_bytes()
        == (MESH_DIRECTORY / item["source_filename"]).read_bytes()
        for item in evidence["meshes"]
    )

    aligned_landmarks = []
    for mesh in (result.template, *result.subjects):
        vertices = np.asarray(read_vtk_polydata(mesh).vertices, dtype=np.float64)
        aligned_landmarks.append(vertices[(0, 40, 80), :])
    centroid_sizes = [
        np.linalg.norm(values - np.mean(values, axis=0)) for values in aligned_landmarks
    ]
    assert np.allclose(centroid_sizes, 1.0, rtol=1e-12, atol=1e-12)


def test_procrustes_preview_is_read_only_and_binds_later_publication(
    tmp_path: Path,
) -> None:
    landmarks = _write_landmarks(tmp_path / "landmarks.csv")
    project = tmp_path / "project"
    sources = (MESH_DIRECTORY / "template.vtk", *sorted(MESH_DIRECTORY.glob("subject-*.vtk")))
    before = {path: sha256_file(path) for path in (*sources, landmarks)}

    preview = preview_landmark_alignment(
        MESH_DIRECTORY,
        landmarks_file=landmarks,
    )

    assert preview.alignment.converged is True
    assert preview.landmark_labels == ("anterior", "dorsal", "posterior")
    assert len(preview.subjects) == 5
    assert len(preview.fingerprint) == 64
    assert not project.exists()
    assert {path: sha256_file(path) for path in (*sources, landmarks)} == before

    result = prepare_landmark_aligned_inputs(
        MESH_DIRECTORY,
        project_directory=project,
        landmarks_file=landmarks,
        expected_fingerprint=preview.fingerprint,
    )
    assert result.fingerprint == preview.fingerprint


def test_procrustes_publication_rejects_changed_approved_preview(
    tmp_path: Path,
) -> None:
    landmarks = _write_landmarks(tmp_path / "landmarks.csv")
    preview = preview_landmark_alignment(MESH_DIRECTORY, landmarks_file=landmarks)
    rows = landmarks.read_text(encoding="utf-8").splitlines()
    final = rows[-1].split(",")
    final[2] = str(float(final[2]) + 0.001)
    rows[-1] = ",".join(final)
    landmarks.write_text("\n".join(rows) + "\n", encoding="utf-8")
    project = tmp_path / "project"

    with pytest.raises(ConfigurationError, match="approved preview"):
        prepare_landmark_aligned_inputs(
            MESH_DIRECTORY,
            project_directory=project,
            landmarks_file=landmarks,
            expected_fingerprint=preview.fingerprint,
        )

    assert not project.exists()


def test_procrustes_publication_rejects_source_drift_during_copy_preparation(
    monkeypatch,
    tmp_path: Path,
) -> None:
    landmarks = _write_landmarks(tmp_path / "landmarks.csv")
    project = tmp_path / "project"
    from diffeoforge import preprocessing

    original_write = preprocessing.write_vtk_polydata
    changed = False

    def write_then_change_landmarks(*args, **kwargs) -> None:
        nonlocal changed
        original_write(*args, **kwargs)
        if not changed:
            changed = True
            with landmarks.open("a", encoding="utf-8", newline="") as handle:
                handle.write("\n")

    monkeypatch.setattr(preprocessing, "write_vtk_polydata", write_then_change_landmarks)

    with pytest.raises(ConfigurationError, match="changed while the aligned copies"):
        prepare_landmark_aligned_inputs(
            MESH_DIRECTORY,
            project_directory=project,
            landmarks_file=landmarks,
        )

    preprocessing_root = project / "preprocessing"
    assert list(preprocessing_root.glob("aligned-*")) == []
    assert list(preprocessing_root.glob(".aligning-*")) == []


def test_identical_preprocessing_request_reuses_verified_content_addressed_cohort(
    tmp_path: Path,
) -> None:
    landmarks = _write_landmarks(tmp_path / "landmarks.csv")
    first = prepare_landmark_aligned_inputs(
        MESH_DIRECTORY,
        project_directory=tmp_path / "project",
        landmarks_file=landmarks,
    )
    evidence_before = first.evidence.read_bytes()

    second = prepare_landmark_aligned_inputs(
        MESH_DIRECTORY,
        project_directory=tmp_path / "project",
        landmarks_file=landmarks,
    )

    assert second == first
    assert second.evidence.read_bytes() == evidence_before
    assert list((tmp_path / "project" / "preprocessing").glob(".aligning-*")) == []
