from __future__ import annotations

import time
from dataclasses import replace
from threading import Event

import numpy as np
import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import QThreadPool
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from diffeoforge.desktop import surface_rendering
from diffeoforge.desktop.display_proxy import DisplayProxy
from diffeoforge.desktop.landmark_3d_widget import InteractiveMeshCanvas3D
from diffeoforge.desktop.mesh_preview import load_mesh_preview


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    application = QApplication.instance() or QApplication(["landmark-frame-sync-test"])
    yield application
    assert QThreadPool.globalInstance().waitForDone(5000)
    application.processEvents()


def wait(app, condition, canvas=None):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        app.processEvents()
        if canvas is not None:
            canvas.grab()
        if condition():
            return
        QTest.qWait(5)
    assert condition()


def marker_pixel(image, point):
    x, y = np.rint(point).astype(int)
    return image.pixelColor(int(x), int(y)).name() == "#d9481c"


@pytest.mark.parametrize("original", [False, True])
@pytest.mark.parametrize("motion", ["rotate", "pan", "zoom", "resize", "preset"])
def test_marker_and_mesh_use_same_presented_camera_during_delayed_render(
    app, monkeypatch, tmp_path, original, motion
):
    # Real rendered pixels, not just a camera formula: hold a frame in flight
    # while the GUI is asked to present a different view.
    path = tmp_path / "synthetic.obj"
    path.write_text("v -1 -1 0\nv 1 -1 0\nv 0 1 0\nf 1 2 3\n", encoding="utf-8")
    canvas = InteractiveMeshCanvas3D()
    canvas.resize(500, 500)
    model = load_mesh_preview(path)
    # A genuinely reduced display backed by a >8k-face original, with the same
    # planar surface so approximation cannot explain any pixel discrepancy.
    triangles = np.tile(np.asarray(model.triangles), (8193, 1))
    proxy = DisplayProxy(
        np.asarray(model.vertices), np.asarray(model.triangles),
        np.array(((0, 1), (1, 2), (0, 2))), len(triangles), 8000,
        "synthetic coincident-face stress surface",
    )
    model = replace(model, triangles=triangles, display_proxy=proxy)
    canvas.set_model(model)
    canvas.original_detail.setChecked(original)
    canvas.set_view_preset("front")
    point = (0.25, -0.25, 0.0)
    canvas.set_markers({"LM1": point})
    canvas.show()
    wait(app, lambda: canvas.picking_ready, canvas)
    before_geometry = (canvas._vertices.copy(), canvas._triangles.copy())
    # Independently project the known world point using the original scene.
    old_pixel = np.array((250, 250)) + np.array((point[0], -point[1])) / 2 * 0.9 * 436
    assert marker_pixel(canvas.grab().toImage(), old_pixel)
    old_scene = canvas._frames.image_scene
    entered, release = Event(), Event()
    real = surface_rendering.render_surface_scene

    def delayed(scene, cancelled):
        entered.set()
        assert release.wait(5)
        return real(scene, cancelled)

    monkeypatch.setattr(surface_rendering, "render_surface_scene", delayed)
    try:
        if motion == "rotate":
            canvas.rotate_view(120.0, 65.0)
            canvas._interacting = True
        elif motion == "pan":
            canvas._pan = (60.0, -35.0)
            canvas._interacting = True
        elif motion == "zoom":
            canvas._zoom = 1.8
            canvas._wheel_timer.start(60000)
        elif motion == "resize":
            canvas.resize(650, 580)
        else:
            canvas.set_view_preset("back")
        pending_image = canvas.grab().toImage()
        wait(app, entered.is_set)
        assert canvas._frames.image_scene is old_scene
        assert marker_pixel(pending_image, old_pixel)
        assert not canvas.picking_ready
        assert not canvas.full_resolution_ready
    finally:
        release.set()
        canvas._interacting = False
        canvas._wheel_timer.stop()
    wait(app, lambda: canvas.picking_ready, canvas)
    final = canvas.grab().toImage()
    scene = canvas._frames.image_scene
    assert scene is not old_scene
    camera = ((np.asarray(point) - scene.center) / scene.scale) @ scene.rotation.T
    factor = 0.9 * (min(scene.width, scene.height) - 64) * scene.zoom
    new_pixel = np.array((scene.width / 2, scene.height / 2)) + scene.pan
    new_pixel += np.array((camera[0], -camera[1])) * factor
    assert np.linalg.norm(new_pixel - old_pixel) > 10
    assert marker_pixel(final, new_pixel)
    assert not marker_pixel(final, old_pixel)
    assert canvas._markers == {"LM1": point}
    assert np.array_equal(canvas._vertices, before_geometry[0])
    assert np.array_equal(canvas._triangles, before_geometry[1])
    canvas.set_model(None)
    assert canvas._frames.image_scene is None
    assert canvas._displayed_marker_positions() == {}
    canvas.close()


def test_camera_snapshot_does_not_advance_on_failed_or_cancelled_frame(app, monkeypatch):
    scene = surface_rendering.SurfaceScene(
        200, 200, np.zeros(3), 1, np.eye(3), 1, (0, 0), ()
    )
    cache = surface_rendering.SurfaceFrameCache()
    cache.request((1,), scene)
    wait(app, lambda: cache.ready((1,)))
    first_image = cache._image
    def fail(*args):
        raise ValueError("delayed failure")

    monkeypatch.setattr(surface_rendering, "render_surface_scene", fail)
    cache.request((2,), replace(scene, zoom=2))
    wait(app, lambda: bool(cache.error))
    assert cache._image is first_image
    assert cache.image_scene is scene
    assert not cache.ready((2,))
    cache.clear()
    assert cache.image_scene is None
    assert cache._image is None
