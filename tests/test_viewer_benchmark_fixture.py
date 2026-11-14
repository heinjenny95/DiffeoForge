from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pytest

from diffeoforge.preprocessing import preview_landmark_alignment


@pytest.fixture
def benchmark():
    path = Path(__file__).parents[1] / "tools/benchmark_viewer_matrix.py"
    spec = importlib.util.spec_from_file_location("viewer_benchmark", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_synthetic_viewer_mesh_is_closed_and_non_degenerate(benchmark):
    vertices, faces = benchmark.synthetic_surface(12, 8)
    assert faces.shape == (192, 3)
    points = vertices[faces]
    assert np.all(np.linalg.norm(np.cross(points[:, 1] - points[:, 0],
                                         points[:, 2] - points[:, 0]), axis=1) > 0)
    edges = np.sort(np.concatenate((faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]])),
                    axis=1)
    _, counts = np.unique(edges, axis=0, return_counts=True)
    assert np.all(counts == 2)
    with pytest.raises(ValueError):
        benchmark.synthetic_surface(2, 8)


def test_prepared_fixture_matches_real_gpa_import_and_refuses_overwrite(
    benchmark, monkeypatch, tmp_path,
):
    monkeypatch.setattr(benchmark, "SIZES", {192: (12, 8)})
    folder = tmp_path / "matrix"
    plan = benchmark.prepare(folder)
    assert benchmark.verify_plan(folder) == plan
    assert len(plan["source_hashes"]) == 4
    assert all(benchmark.digest(folder / path) == digest
               for path, digest in plan["source_hashes"].items())
    preview = preview_landmark_alignment(folder / "192/meshes",
                                         landmarks_file=folder / "192/landmarks.csv")
    assert len(preview.alignment.aligned_landmarks) == 3
    with pytest.raises(FileExistsError):
        benchmark.prepare(folder)
