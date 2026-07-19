from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np

from diffeoforge.analysis.landmarks import LANDMARK_COLUMNS
from diffeoforge.mesh import read_vtk_polydata, sha256_file
from diffeoforge.preprocessing import prepare_landmark_aligned_inputs

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
    assert all(Path(result.directory / item["filename"]).is_file() for item in evidence["meshes"])

    aligned_landmarks = []
    for mesh in (result.template, *result.subjects):
        vertices = np.asarray(read_vtk_polydata(mesh).vertices, dtype=np.float64)
        aligned_landmarks.append(vertices[(0, 40, 80), :])
    centroid_sizes = [
        np.linalg.norm(values - np.mean(values, axis=0)) for values in aligned_landmarks
    ]
    assert np.allclose(centroid_sizes, 1.0, rtol=1e-12, atol=1e-12)


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
