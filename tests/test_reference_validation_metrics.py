from __future__ import annotations

import numpy as np
import pytest

from diffeoforge.config import ConfigurationError
from diffeoforge.mesh import TriangleMesh
from diffeoforge.reference_validation_metrics import (
    _point_triangle_squared_distance,
    _segment_squared_distance,
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


@pytest.mark.parametrize("scale", [1e-100, 1e-12, 1e-6, 1.0, 1e6, 1e100])
def test_triangle_distances_are_scale_equivariant(scale: float) -> None:
    triangle = np.array([[[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]]) * scale
    points = np.array([[0.25, 0.25, 1.5], [2.0, 0.0, 0.0], [0.5, 0.5, 0.0]]) * scale

    with np.errstate(all="raise"):
        distances = np.sqrt(_point_triangle_squared_distance(points, triangle))

    np.testing.assert_allclose(distances / scale, [1.5, 1.0, 0.0], atol=1e-14)


def test_thin_triangle_does_not_lose_its_barycentric_denominator() -> None:
    triangle = np.array([[[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [1.0, 1e-12, 0.0]]])
    points = np.array([[0.75, 0.25e-12, 2e-12], [0.75, 0.25e-12, 0.0]])

    with np.errstate(all="raise"):
        distances = np.sqrt(_point_triangle_squared_distance(points, triangle))

    np.testing.assert_allclose(distances, [2e-12, 0.0], rtol=1e-12, atol=1e-25)


@pytest.mark.parametrize("scale", [1e-12, 1.0, 1e12])
def test_genuinely_collinear_triangles_still_fail(scale: float) -> None:
    triangle = np.array([[[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [2.0, 0.0, 0.0]]]) * scale
    with pytest.raises(ConfigurationError, match="zero-area"):
        _point_triangle_squared_distance(np.zeros((1, 3)), triangle)


def test_genuinely_zero_length_edges_still_fail() -> None:
    with pytest.raises(ConfigurationError, match="zero-length"):
        _segment_squared_distance(np.zeros((1, 3)), np.zeros((1, 3)), np.zeros((1, 3)))


@pytest.mark.parametrize("invalid", [np.nan, np.inf, -np.inf])
def test_nonfinite_coordinates_fail_closed(invalid: float) -> None:
    triangle = np.array([[[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]])
    with pytest.raises(ConfigurationError, match="finite"):
        _point_triangle_squared_distance(np.array([[invalid, 0.0, 0.0]]), triangle)


def test_distance_is_invariant_under_rigid_motion_and_winding() -> None:
    triangle = np.array([[[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]])
    points = np.array([[0.25, 0.25, 1.5], [2.0, 0.0, 0.0], [-0.1, -0.2, 0.5]])
    expected = _point_triangle_squared_distance(points, triangle)
    rotation, _ = np.linalg.qr(np.random.default_rng(902).normal(size=(3, 3)))
    translation = np.array([2.5, -1.2, 4.8])
    actual = _point_triangle_squared_distance(
        points @ rotation + translation,
        triangle[:, ::-1] @ rotation + translation,
    )
    np.testing.assert_allclose(actual, expected, rtol=1e-12, atol=1e-14)
