from __future__ import annotations

import numpy as np
import pytest

from diffeoforge.analysis.mesh_scaling import (
    MeshScalingMode,
    mesh_scale_metrics,
    scaling_factor,
)


def _square() -> tuple[np.ndarray, np.ndarray]:
    vertices = np.array(
        [
            [0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
            [1.0, 1.0, 0.0],
            [0.0, 1.0, 0.0],
        ],
        dtype=np.float64,
    )
    triangles = np.array([[0, 1, 2], [0, 2, 3]], dtype=np.int64)
    return vertices, triangles


def _subdivided_square() -> tuple[np.ndarray, np.ndarray]:
    vertices = np.array(
        [
            [0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
            [1.0, 1.0, 0.0],
            [0.0, 1.0, 0.0],
            [2.0 / 3.0, 1.0 / 3.0, 0.0],
            [1.0 / 3.0, 2.0 / 3.0, 0.0],
        ],
        dtype=np.float64,
    )
    triangles = np.array(
        [
            [0, 1, 4],
            [1, 2, 4],
            [2, 0, 4],
            [0, 2, 5],
            [2, 3, 5],
            [3, 0, 5],
        ],
        dtype=np.int64,
    )
    return vertices, triangles


def test_area_weighted_scale_is_invariant_to_surface_subdivision() -> None:
    coarse = mesh_scale_metrics(*_square())
    subdivided = mesh_scale_metrics(*_subdivided_square())

    assert coarse.surface_area == pytest.approx(1.0)
    assert subdivided.surface_area == pytest.approx(1.0)
    assert coarse.area_weighted_centroid == pytest.approx((0.5, 0.5, 0.0))
    assert subdivided.area_weighted_centroid == pytest.approx((0.5, 0.5, 0.0))
    assert coarse.area_weighted_rms_radius == pytest.approx(
        subdivided.area_weighted_rms_radius, rel=1e-14
    )
    assert coarse.vertex_centroid_size != pytest.approx(
        subdivided.vertex_centroid_size
    )


def test_scaling_modes_are_numerically_distinct_and_explicit() -> None:
    metrics = mesh_scale_metrics(*_square())

    assert scaling_factor(
        MeshScalingMode.PRESERVE_SIZE,
        target_size=1.0,
        landmark_centroid_size=4.0,
        mesh_metrics=metrics,
    ) == 1.0
    assert scaling_factor(
        MeshScalingMode.LANDMARK_CENTROID_LEGACY,
        target_size=2.0,
        landmark_centroid_size=4.0,
        mesh_metrics=metrics,
    ) == pytest.approx(0.5)
    assert scaling_factor(
        MeshScalingMode.PAMS_VERTEX_CENTROID,
        target_size=2.0,
        landmark_centroid_size=4.0,
        mesh_metrics=metrics,
    ) == pytest.approx(2.0 / metrics.vertex_centroid_size)
    assert scaling_factor(
        MeshScalingMode.PAMS_AREA_WEIGHTED,
        target_size=2.0,
        landmark_centroid_size=4.0,
        mesh_metrics=metrics,
    ) == pytest.approx(2.0 / metrics.area_weighted_rms_radius)


@pytest.mark.parametrize(
    "vertices,triangles,message",
    (
        (np.zeros((2, 3)), np.array([[0, 1, 1]]), "vertices"),
        (np.zeros((3, 3)), np.array([[0, 1, 3]]), "out-of-range"),
        (np.zeros((3, 3)), np.array([[0, 1, 2]]), "surface"),
    ),
)
def test_scale_metrics_reject_invalid_or_degenerate_geometry(
    vertices: np.ndarray,
    triangles: np.ndarray,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        mesh_scale_metrics(vertices, triangles)
