from threading import Event

import numpy as np
import pytest

from diffeoforge.desktop.surface_snap import closest_surface_point


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ((0.5, 0.5, 3), (0.5, 0.5, 0)),
        ((1.5, 1.5, 1), (1, 1, 0)),
        ((-1, -2, -3), (0, 0, 0)),
        ((1, -2, 1), (1, 0, 0)),
    ],
)
def test_snap_face_edge_and_vertex_without_modifying_source(query, expected):
    vertices = np.array(((0.0, 0, 0), (2, 0, 0), (0, 2, 0)))
    faces = np.array(((0, 1, 2),))
    vertices.setflags(write=False)
    faces.setflags(write=False)
    before = vertices.tobytes(), faces.tobytes()
    assert closest_surface_point(query, vertices, faces) == pytest.approx(expected)
    assert before == (vertices.tobytes(), faces.tobytes())


def test_snap_nearest_layer_not_frontmost_ray_or_nearest_vertex():
    vertices = np.array(((0.0, 0, 0), (2, 0, 0), (0, 2, 0), (0, 0, 3), (2, 0, 3), (0, 2, 3)))
    faces = np.array(((3, 4, 5), (0, 1, 2)))
    for block_size in (1, 2, 32_768):
        assert closest_surface_point(
            (0.5, 0.5, 0.1), vertices, faces, block_size=block_size
        ) == pytest.approx((0.5, 0.5, 0))


@pytest.mark.parametrize("scale", [1e-6, 1, 1000])
def test_snap_oblique_surface_in_source_coordinates(scale):
    vertices = scale * np.array(((0.0, 0, 0), (2, 0, 2), (0, 2, 0)))
    shift = np.array((72.0, -34, 80))
    vertices += shift
    point = shift + scale * np.array((0.5, 0.5, 0.5))
    query = point + scale * np.array((-0.2, 0, 0.2))
    assert closest_surface_point(tuple(query), vertices, np.array(((0, 1, 2),))) == (
        pytest.approx(point)
    )


def test_snap_degenerate_faces_cancellation_and_invalid_inputs():
    vertices = np.array(((0.0, 0, 0), (2, 0, 0)))
    faces = np.array(((0, 0, 0), (0, 1, 1)))
    assert closest_surface_point((0.5, 1, 0), vertices, faces) == (0.5, 0, 0)
    cancelled = Event()
    cancelled.set()
    assert closest_surface_point((0.5, 1, 0), vertices, faces, cancel=cancelled) is None
    with pytest.raises(ValueError, match="triangles are required"):
        closest_surface_point((0, 0, 0), vertices, np.empty((0, 3), dtype=int))
    with pytest.raises(ValueError, match="finite"):
        closest_surface_point((float("nan"), 0, 0), vertices, faces)
