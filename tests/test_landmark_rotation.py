from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from diffeoforge.desktop.landmark_3d_widget import (
    InteractiveMeshCanvas3D,
    camera_rotation,
    screen_drag_rotation,
)
from diffeoforge.desktop.mesh_preview import MeshPreviewModel


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication(["screen-drag-test"])


def drag(canvas, dx, dy, button=Qt.MouseButton.LeftButton):
    start, end = QPointF(240, 250), QPointF(240 + dx, 250 + dy)
    for event_type, position, changed, held in (
        (QEvent.Type.MouseButtonPress, start, button, button),
        (QEvent.Type.MouseMove, end, Qt.MouseButton.NoButton, button),
        (QEvent.Type.MouseButtonRelease, end, button, Qt.MouseButton.NoButton),
    ):
        QApplication.sendEvent(
            canvas, QMouseEvent(event_type, position, position, changed, held,
                                Qt.KeyboardModifier.NoModifier)
        )


def cube_canvas():
    canvas = InteractiveMeshCanvas3D()
    canvas.resize(500, 500)
    vertices = tuple((x, y, z) for x in (-1., 1.) for y in (-1., 1.) for z in (-1., 1.))
    triangles = ((0, 2, 3), (0, 3, 1), (4, 5, 7), (4, 7, 6),
                 (0, 1, 5), (0, 5, 4), (2, 6, 7), (2, 7, 3),
                 (0, 4, 6), (0, 6, 2), (1, 3, 7), (1, 7, 5))
    canvas.set_model(MeshPreviewModel(
        path=Path("synthetic-cube.vtk"), sha256="0" * 64, vertices=vertices,
        triangles=triangles, edges=(), bounds=(-1., 1., -1., 1., -1., 1.),
    ))
    return canvas


@pytest.mark.parametrize("preset", [
    "front", "back", "left", "right", "top", "bottom", "three-quarter",
    "upside-down", "mixed-drags",
])
@pytest.mark.parametrize("dx,dy", [(12, 0), (-12, 0), (0, 12), (0, -12)])
def test_mouse_drag_moves_near_surface_with_cursor_at_every_orientation(app, preset, dx, dy):
    # No angle-sign assertion: follow an actually projected near-side vertex.
    # The upside-down/top cases reproduce the old reversed/degenerate x drag.
    canvas = cube_canvas()
    if preset == "upside-down":
        canvas.set_view_preset("bottom")
        drag(canvas, 0, math.pi / 2 / 0.009)
    elif preset == "mixed-drags":
        for movement in ((130, 65), (-180, 240), (90, -155)):
            drag(canvas, *movement)
    else:
        canvas.set_view_preset(preset)
    before = canvas._surface()
    near = np.argmax(before.camera_vertices[:, 2])
    picked = []
    canvas.surfacePointPicked.connect(picked.append)
    geometry = canvas._vertices.copy(), canvas._triangles.copy()
    canvas.set_markers({"LM1": (0.3, 0.2, 1.0)})
    drag(canvas, dx, dy)
    displacement = canvas._surface().screen_vertices[near] - before.screen_vertices[near]
    if dx:
        assert displacement[0] * dx > 1
    if dy:
        assert displacement[1] * dy > 1
    assert picked == []  # A rotation is never a landmark click.
    assert canvas._markers == {"LM1": (0.3, 0.2, 1.0)}
    np.testing.assert_array_equal(canvas._vertices, geometry[0])
    np.testing.assert_array_equal(canvas._triangles, geometry[1])
    canvas.close()


def test_diagonal_drag_inverse_and_long_sequence_remain_proper_rotations():
    rotation = camera_rotation(-0.55, 0.3)
    for index in range(10000):
        dx, dy = 3 * math.sin(index), 4 * math.cos(index)
        rotation = screen_drag_rotation(dx, dy) @ rotation
    np.testing.assert_allclose(rotation @ rotation.T, np.eye(3), atol=1e-12)
    assert np.linalg.det(rotation) == pytest.approx(1, abs=1e-12)
    delta = screen_drag_rotation(125, -80)
    inverse = screen_drag_rotation(-125, 80)
    np.testing.assert_allclose(inverse @ delta, np.eye(3), atol=1e-14)
    np.testing.assert_array_equal(screen_drag_rotation(0, 0), np.eye(3))


def test_composed_camera_picks_the_original_front_surface(app):
    canvas = cube_canvas()
    for dx, dy in ((120, -70), (-35, 190), (65, 30)):
        drag(canvas, dx, dy)
    # Analytic center ray against a unit cube, independent of triangle picking.
    direction = canvas.rotation.T @ np.array((0., 0., 1.))
    expected = direction / np.max(np.abs(direction))
    point = canvas.pick_at(QPointF(canvas.width() / 2, canvas.height() / 2))
    np.testing.assert_allclose(point, expected, atol=1e-12)
    canvas.set_view_preset("front")
    np.testing.assert_array_equal(canvas.rotation, np.eye(3))
    canvas.close()


@pytest.mark.parametrize("bad", [math.inf, -math.inf, math.nan])
def test_nonfinite_drag_is_rejected(bad):
    with pytest.raises(ValueError, match="finite"):
        screen_drag_rotation(bad, 1)


@pytest.mark.parametrize("button", [Qt.MouseButton.RightButton, Qt.MouseButton.MiddleButton])
def test_pan_still_follows_cursor_without_rotating(app, button):
    canvas = cube_canvas()
    before = canvas.rotation
    drag(canvas, 23, -17, button)
    assert canvas._pan == (23, -17)
    np.testing.assert_array_equal(canvas.rotation, before)
    # Public snapshots cannot mutate the camera or its cache key.
    snapshot = canvas.rotation
    snapshot[:] = 0
    np.testing.assert_array_equal(canvas.rotation, before)
    canvas.rotate_view(70, 30)
    canvas.reset_view()
    np.testing.assert_array_equal(canvas.rotation, camera_rotation(-0.55, 0.3))
    canvas.close()
