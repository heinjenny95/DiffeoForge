from __future__ import annotations

import numpy as np
import pytest

from diffeoforge.mesh import TriangleMesh
from diffeoforge.reference_validation_metrics import (
    directed_vertex_to_surface_distances,
    symmetric_vertex_to_surface_distances,
)


def _triangle(z: float) -> TriangleMesh:
    return TriangleMesh(
        vertices=((0.0, 0.0, z), (1.0, 0.0, z), (0.0, 1.0, z)),
        triangles=((0, 1, 2),),
    )


def test_symmetric_vertex_to_surface_distance_is_exact_for_parallel_triangles() -> None:
    distances = symmetric_vertex_to_surface_distances(_triangle(0.0), _triangle(2.0))

    assert distances.shape == (6,)
    assert np.allclose(distances, 2.0)


def test_directed_metric_uses_triangle_interior_not_only_vertices() -> None:
    source = TriangleMesh(
        vertices=((0.25, 0.25, 1.5), (0.26, 0.25, 1.5), (0.25, 0.26, 1.5)),
        triangles=((0, 1, 2),),
    )

    distances = directed_vertex_to_surface_distances(source, _triangle(0.0))

    assert distances == pytest.approx((1.5, 1.5, 1.5))


def test_directed_metric_handles_projection_outside_triangle_via_edges() -> None:
    source = TriangleMesh(
        vertices=((2.0, 0.0, 0.0), (2.0, 0.1, 0.0), (2.0, 0.0, 0.1)),
        triangles=((0, 1, 2),),
    )

    distances = directed_vertex_to_surface_distances(source, _triangle(0.0))

    assert distances[0] == pytest.approx(1.0)
    assert distances[1] > 1.0
