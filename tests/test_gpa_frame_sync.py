from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from threading import Event

import numpy as np
import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import QEventLoop, QThreadPool, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from diffeoforge.desktop import surface_rendering
from diffeoforge.desktop.display_proxy import DisplayProxy
from diffeoforge.desktop.gpa_visualization import GpaAlignedWireframe, GpaAlignmentVisual
from diffeoforge.desktop.gpa_visualization_widget import (
    GpaAlignmentCanvas3D,
    cohort_overlay_color,
)
from diffeoforge.desktop.mesh_preview import MeshPreviewModel


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    application = QApplication.instance() or QApplication(["gpa-frame-sync-test"])
    yield application
    assert QThreadPool.globalInstance().waitForDone(5000)
    application.processEvents()


def wait(app, condition, canvas=None):
    # A tight QTest.qWait/repaint loop can starve the Python render worker.
    # Use the application's native event loop, with the same bounded deadline.
    del app
    loop = QEventLoop()
    timer = QTimer()
    timeout = QTimer()
    timeout.setSingleShot(True)
    timeout.timeout.connect(loop.quit)

    def poll():
        if canvas is not None:
            canvas.grab()
        if condition():
            loop.quit()

    if canvas is not None:
        canvas.grab()
    if condition():
        return
    timer.timeout.connect(poll)
    timer.start(20)
    timeout.start(10000)
    loop.exec()
    timer.stop()
    timeout.stop()
    assert condition()


def ready(canvas):
    return canvas._frames.ready(canvas._frames._wanted)


def tessellated_triangle(base, subdivisions=91):
    # Exceed the proxy threshold with a real tiling, not thousands of identical
    # screen-filling faces (which made this synchronization test an overdraw test).
    points = [(i, j) for i in range(subdivisions + 1)
              for j in range(subdivisions + 1 - i)]
    lookup = {point: index for index, point in enumerate(points)}
    vertices = np.array([
        base[0] + (i * (base[1] - base[0]) + j * (base[2] - base[0])) / subdivisions
        for i, j in points
    ])
    faces = []
    for i in range(subdivisions):
        for j in range(subdivisions - i):
            faces.append((lookup[i, j], lookup[i + 1, j], lookup[i, j + 1]))
            if i + j < subdivisions - 1:
                faces.append((lookup[i + 1, j], lookup[i + 1, j + 1], lookup[i, j + 1]))
    triangles = np.array(faces)
    edges = np.unique(np.sort(np.concatenate((
        triangles[:, (0, 1)], triangles[:, (1, 2)], triangles[:, (2, 0)],
    )), axis=1), axis=0)
    return vertices, triangles, edges


def test_original_frame_fixture_preserves_surface_and_exceeds_proxy_budget():
    base = np.array(((-1., -1., 0.), (1., -1., 0.), (0., 1., 0.)))
    vertices, triangles, _edges = tessellated_triangle(base)
    assert len(triangles) == 8281 > 8000
    assert len(np.unique(np.sort(triangles, axis=1), axis=0)) == len(triangles)
    normals = np.cross(vertices[triangles[:, 1]] - vertices[triangles[:, 0]],
                       vertices[triangles[:, 2]] - vertices[triangles[:, 0]])
    assert np.all(normals[:, 2] > 0)
    assert np.sum(normals[:, 2]) / 2 == pytest.approx(2.0)


@pytest.fixture
def canvas(app):
    vertices = np.array(((-1., -1., 0.), (1., -1., 0.), (0., 1., 0.)))
    triangles = np.array(((0, 1, 2),))
    edges = np.array(((0, 1), (1, 2), (0, 2)))
    full_vertices, full_triangles, full_edges = tessellated_triangle(vertices)
    proxy = DisplayProxy(vertices, triangles, edges, len(full_triangles), 8000, "synthetic proxy")
    detail = MeshPreviewModel(
        Path("synthetic.obj"), "0" * 64, full_vertices,
        full_triangles, full_edges, (-1, 1, -1, 1, -1, 1), proxy,
    )
    meshes = tuple(
        GpaAlignedWireframe(
            f"synthetic-{index}.obj", "0" * 64, "obj", vertices, triangles,
            edges, np.array((point,)), 0.1, 1, len(full_vertices), len(full_triangles),
        )
        for index, point in enumerate(((-0.6, -0.45, 0.4), (0.2, 0.1, -0.15)))
    )
    visual = GpaAlignmentVisual(
        "0" * 64, meshes, ("LM1",),
        np.mean([mesh.landmarks for mesh in meshes], axis=0),
        (-1, 1, -1, 1, -1, 1), detail, 6, 2 * len(full_edges), 2 * len(full_triangles), 8000,
    )
    widget = GpaAlignmentCanvas3D()
    widget.resize(800, 650)
    widget.set_visual(visual)
    widget.set_selected_detail(0, detail)
    widget.set_view_preset("front")
    yield widget
    widget._frames.clear()
    widget.close()


def point_pixel(point, scene):
    # Independent projection, including the old viewport during pending resize.
    camera = ((point - scene.center) / scene.scale) @ scene.rotation.T
    factor = 0.9 * (min(scene.width, scene.height) - scene.margin) * scene.zoom
    return np.array((scene.width / 2, scene.height / 2)) + scene.pan + (
        np.array((camera[0], -camera[1])) * factor
    )


def rgb_at(image, point):
    x, y = np.rint(point).astype(int)
    return np.array(image.pixelColor(int(x), int(y)).getRgb()[:3])


def assert_markers(image, canvas, scene):
    visual = canvas._visual
    for point, color in (
        (visual.meshes[canvas.selected_index].landmarks[0], "#d9481c"),
        (visual.mean_landmarks[0], "#54c6a1"),
    ):
        assert np.array_equal(rgb_at(image, point_pixel(point, scene)),
                              QColor(color).getRgb()[:3])
    if canvas.show_cohort and not canvas.show_selected_surface:
        # Small alpha-blended dots for the unselected cohort must be in sync too.
        index = 1 - canvas.selected_index
        color = cohort_overlay_color(index, 2, selected=False)
        alpha = color.alphaF()
        expected = alpha * np.array(color.getRgb()[:3]) + (
            (1 - alpha) * np.array(QColor("#f7f9f9").getRgb()[:3])
        )
        actual = rgb_at(image, point_pixel(visual.meshes[index].landmarks[0], scene))
        assert np.max(np.abs(actual - expected)) < 3


@pytest.mark.parametrize("mode", ["cohort", "selected", "shaded-proxy", "shaded-original"])
@pytest.mark.parametrize("motion", ["rotate", "pan", "zoom", "resize", "preset", "reset"])
def test_gpa_pixels_stay_with_presented_mesh_during_delayed_frame(
    app, canvas, monkeypatch, mode, motion
):
    canvas.set_show_cohort(mode != "selected")
    canvas.set_show_selected_surface(mode.startswith("shaded"))
    if mode == "shaded-original":
        canvas.set_selected_detail(0, canvas._visual.first_detail, original_detail=True)
    canvas.show()
    wait(app, lambda: ready(canvas), canvas)
    old_scene = canvas._frames.image_scene
    assert_markers(canvas.grab().toImage(), canvas, old_scene)
    before = [(mesh.vertices.copy(), mesh.triangles.copy(), mesh.landmarks.copy())
              for mesh in canvas._visual.meshes]
    mean_before = canvas._visual.mean_landmarks.copy()
    entered, release = Event(), Event()
    real = surface_rendering.render_surface_scene

    def delayed(scene, cancelled):
        entered.set()
        assert release.wait(5)
        return real(scene, cancelled)

    monkeypatch.setattr(surface_rendering, "render_surface_scene", delayed)
    try:
        if motion == "rotate":
            canvas._yaw += 1.1
            canvas._pitch += 0.6
            canvas._interacting = True
        elif motion == "pan":
            canvas._pan = (65, -40)
            canvas._interacting = True
        elif motion == "zoom":
            canvas._zoom = 1.7
        elif motion == "resize":
            canvas.resize(940, 730)
        elif motion == "preset":
            canvas.set_view_preset("back")
        else:
            canvas.reset_view()
        pending = canvas.grab().toImage()
        wait(app, entered.is_set)
        assert canvas._frames.image_scene is old_scene
        assert not ready(canvas)
        assert_markers(pending, canvas, old_scene)
    finally:
        release.set()
        canvas._interacting = False
    wait(app, lambda: ready(canvas), canvas)
    final = canvas.grab().toImage()
    scene = canvas._frames.image_scene
    assert scene is not old_scene
    if mode == "shaded-original":
        assert [len(layer.indices) for layer in scene.layers if not layer.wireframe] == [8281]
    assert_markers(final, canvas, scene)
    selected = canvas._visual.meshes[0].landmarks[0]
    assert np.linalg.norm(point_pixel(selected, scene) - point_pixel(selected, old_scene)) > 10
    assert not np.array_equal(rgb_at(final, point_pixel(selected, old_scene)),
                              QColor("#d9481c").getRgb()[:3])
    for mesh, (vertices, triangles, landmarks) in zip(canvas._visual.meshes, before, strict=True):
        assert np.array_equal(mesh.vertices, vertices)
        assert np.array_equal(mesh.triangles, triangles)
        assert np.array_equal(mesh.landmarks, landmarks)
    assert np.array_equal(canvas._visual.mean_landmarks, mean_before)


@pytest.mark.parametrize("change", ["initial", "cohort", "surface", "proxy", "detail", "visual"])
def test_no_orphan_markers_when_frame_identity_changes(app, canvas, monkeypatch, change):
    canvas.show()
    wait(app, lambda: ready(canvas), canvas)
    old_scene = canvas._frames.image_scene
    old_visual = canvas._visual
    entered, release = Event(), Event()
    real = surface_rendering.render_surface_scene

    def delayed(scene, cancelled):
        entered.set()
        assert release.wait(5)
        return real(scene, cancelled)

    monkeypatch.setattr(surface_rendering, "render_surface_scene", delayed)
    try:
        if change == "initial":
            canvas._frames.clear()
        elif change == "cohort":
            canvas.set_show_cohort(False)
        elif change == "surface":
            canvas.set_show_selected_surface(True)
        elif change == "proxy":
            canvas.set_selected_proxy(1)
        elif change == "detail":
            canvas.set_selected_detail(1, old_visual.first_detail)
        else:
            canvas.set_visual(replace(old_visual, fingerprint="1" * 64))
            assert canvas._detail_vertices.size == 0
            assert canvas._frames.image_scene is None
            canvas.set_selected_proxy(0)
        assert canvas._frames.image_scene is None
        pending = canvas.grab().toImage()
        wait(app, entered.is_set)
        for point in (old_visual.meshes[0].landmarks[0], old_visual.mean_landmarks[0]):
            pixel = np.rint(point_pixel(point, old_scene)).astype(int)
            assert pending.pixelColor(*pixel).name() == "#f7f9f9"
    finally:
        release.set()
    wait(app, lambda: ready(canvas), canvas)
    assert_markers(canvas.grab().toImage(), canvas, canvas._frames.image_scene)


def test_failed_gpa_frame_keeps_previous_mesh_and_markers(app, canvas, monkeypatch):
    canvas.show()
    wait(app, lambda: ready(canvas), canvas)
    old_scene = canvas._frames.image_scene

    def fail(*args):
        raise ValueError("synthetic rendering failure")

    monkeypatch.setattr(surface_rendering, "render_surface_scene", fail)
    canvas.set_view_preset("back")
    wait(app, lambda: bool(canvas._frames.error), canvas)
    assert canvas._frames.image_scene is old_scene
    assert not ready(canvas)
    assert_markers(canvas.grab().toImage(), canvas, old_scene)


def test_superseded_gpa_camera_and_visibility_do_not_move_markers_early(app, canvas, monkeypatch):
    canvas.show()
    wait(app, lambda: ready(canvas), canvas)
    old_scene = canvas._frames.image_scene
    entered, release = Event(), Event()
    real = surface_rendering.render_surface_scene

    def delayed(scene, cancelled):
        entered.set()
        assert release.wait(5)
        return real(scene, cancelled)

    monkeypatch.setattr(surface_rendering, "render_surface_scene", delayed)
    try:
        canvas.set_view_preset("left")
        canvas.grab()
        wait(app, entered.is_set)
        canvas.set_view_preset("right")
        canvas._pan = (50, 30)
        canvas.set_show_landmarks(False)
        hidden = canvas.grab().toImage()
        assert not np.array_equal(
            rgb_at(hidden, point_pixel(canvas._visual.meshes[0].landmarks[0], old_scene)),
            QColor("#d9481c").getRgb()[:3],
        )
        canvas.set_show_landmarks(True)
        assert_markers(canvas.grab().toImage(), canvas, old_scene)
    finally:
        release.set()
    wait(app, lambda: ready(canvas), canvas)
    assert canvas._frames.image_scene.pan == (50, 30)
    assert_markers(canvas.grab().toImage(), canvas, canvas._frames.image_scene)
