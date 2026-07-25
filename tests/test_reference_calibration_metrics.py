from pathlib import Path

import numpy as np
import pytest

from diffeoforge.mesh import TriangleMesh, write_vtk_polydata
from diffeoforge.reference_calibration_metrics import (
    atlas_rms_distance,
    symmetric_nearest_vertex_distances,
)


def _triangle(offset: float = 0.0) -> TriangleMesh:
    return TriangleMesh(
        vertices=(
            (offset, 0.0, 0.0),
            (offset, 1.0, 0.0),
            (offset, 0.0, 1.0),
        ),
        triangles=((0, 1, 2),),
    )


def test_symmetric_surface_distance_is_deterministic_and_zero_for_identity() -> None:
    mesh = _triangle()

    first = symmetric_nearest_vertex_distances(mesh, mesh)
    second = symmetric_nearest_vertex_distances(mesh, mesh)

    assert np.array_equal(first, second)
    assert first.tolist() == [0.0] * 6


def test_symmetric_surface_distance_reports_known_rigid_offset() -> None:
    distances = symmetric_nearest_vertex_distances(_triangle(), _triangle(2.0))

    assert distances.tolist() == pytest.approx([2.0] * 6)


def test_atlas_rms_uses_ordered_vertex_displacement(tmp_path: Path) -> None:
    first = _triangle()
    second = _triangle(2.0)
    first_path = write_vtk_polydata(
        tmp_path / "first.vtk",
        first.vertices,
        first.triangles,
    )
    second_path = write_vtk_polydata(
        tmp_path / "second.vtk",
        second.vertices,
        second.triangles,
    )

    assert atlas_rms_distance(first_path, second_path) == pytest.approx(2.0)
