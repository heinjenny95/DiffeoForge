from __future__ import annotations

import json
import time
from dataclasses import replace
from pathlib import Path
from threading import Event, get_ident

import numpy as np
import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from diffeoforge.desktop.display_proxy import DisplayProxy
from diffeoforge.desktop.landmark_3d_widget import InteractiveMeshCanvas3D
from diffeoforge.desktop.mesh_preview import MeshPreviewModel


@pytest.fixture
def application(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication(["proxy-landmark-test"])
    yield app
    app.processEvents()


def _wait(application, condition, canvas=None):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        application.processEvents()
        if canvas is not None:
            canvas.grab()
        if condition():
            return
        QTest.qWait(5)
    assert condition()


def _model():
    n = 64
    vertices = np.array(
        [(x, y, 0.0) for y in np.linspace(-1, 1, n + 1) for x in np.linspace(-1, 1, n + 1)]
    )
    faces = []
    for y in range(n):
        for x in range(n):
            a = y * (n + 1) + x
            faces.extend(((a, a + 1, a + n + 1), (a + 1, a + n + 2, a + n + 1)))
    # Deliberately off the original plane: emitting a proxy coordinate is wrong.
    proxy = DisplayProxy(
        np.array(((-1.0, -1, 0.1), (1, -1, 0.1), (0, 1, 0.1))),
        np.array(((0, 1, 2),)),
        np.array(((0, 1), (1, 2), (0, 2))),
        len(faces),
        8000,
        "synthetic displaced proxy",
    )
    return MeshPreviewModel(
        Path("synthetic-grid.obj"),
        "0" * 64,
        vertices,
        np.array(faces),
        (),
        (-1, 1, -1, 1, 0, 0),
        proxy,
    )


def _canvas(application):
    canvas = InteractiveMeshCanvas3D()
    canvas.resize(500, 500)
    canvas.set_model(_model())
    canvas.set_view_preset("front")
    canvas.show()
    _wait(application, lambda: canvas.picking_ready, canvas)
    return canvas


def _click(canvas):
    QTest.mouseClick(
        canvas, Qt.MouseButton.LeftButton, pos=QPoint(canvas.width() // 2, canvas.height() // 2)
    )


def test_reduced_click_transfers_in_background_and_next_mesh_needs_no_toggle(
    application,
    monkeypatch,
):
    import diffeoforge.desktop.landmark_3d_widget as widget

    original = widget.closest_surface_point
    threads = []

    def traced(*args, **kwargs):
        threads.append(get_ident())
        return original(*args, **kwargs)

    monkeypatch.setattr(widget, "closest_surface_point", traced)
    canvas = _canvas(application)
    points = []
    canvas.surfacePointPicked.connect(points.append)
    for index in range(2):
        assert not canvas.original_detail.isChecked()
        assert not canvas.full_resolution_ready
        assert len(canvas._display_geometry()[1]) == 1
        _click(canvas)
        _wait(application, lambda index=index: len(points) == index + 1)
        assert points[-1] == pytest.approx((0, 0, 0))
        if index == 0:
            canvas.set_model(replace(_model(), path=Path("second.obj")))
            _wait(application, lambda: canvas.picking_ready, canvas)
    assert all(thread != get_ident() for thread in threads)
    canvas.close()


@pytest.mark.parametrize("change", ["label", "mesh", "close", "disable", "resolution"])
def test_pending_transfer_cannot_escape_changed_context(application, monkeypatch, change):
    import diffeoforge.desktop.landmark_3d_widget as widget

    started, release = Event(), Event()

    def delayed(*args, **kwargs):
        started.set()
        assert release.wait(5)
        return (0.0, 0.0, 0.0)  # Even an operation ignoring cancellation must be discarded.

    monkeypatch.setattr(widget, "closest_surface_point", delayed)
    canvas = _canvas(application)
    points = []
    canvas.surfacePointPicked.connect(points.append)
    try:
        _click(canvas)
        _wait(application, started.is_set)
        assert canvas._pick_pending
        if change == "label":
            canvas.set_markers({})
        elif change == "mesh":
            canvas.set_model(_model())
        elif change == "close":
            canvas.close()
        elif change == "disable":
            canvas.set_picking_enabled(False)
        else:
            canvas.original_detail.setChecked(True)
    finally:
        release.set()
    _wait(application, lambda: canvas._pick_loader._active is None)
    assert points == []
    canvas.close()


def test_proxy_stale_frame_and_proxy_only_model_remain_unpickable(application):
    canvas = _canvas(application)
    points = []
    canvas.surfacePointPicked.connect(points.append)
    canvas.rotate_view(12.0, 0.0)
    _click(canvas)
    assert not canvas._pick_pending
    canvas.set_model(replace(_model(), geometry_is_proxy=True))
    _wait(application, lambda: canvas._frames.ready(canvas._frame_key()), canvas)
    assert not canvas.picking_ready
    _click(canvas)
    assert points == []
    canvas.close()


def test_transfer_error_is_visible_without_emitting_proxy_coordinate(application, monkeypatch):
    import diffeoforge.desktop.landmark_3d_widget as widget

    def fail(*args, **kwargs):
        raise ValueError("test transfer failure")

    monkeypatch.setattr(widget, "closest_surface_point", fail)
    canvas = _canvas(application)
    points = []
    canvas.surfacePointPicked.connect(points.append)
    _click(canvas)
    _wait(application, lambda: bool(canvas._pick_error))
    assert "Landmark not placed" in canvas._pick_error
    assert points == []
    canvas.close()


def test_reduced_editor_clicks_autosave_advance_and_export_original_coordinates(
    application,
    tmp_path,
):
    from diffeoforge.analysis.landmarks import read_landmark_csv
    from diffeoforge.desktop.landmark_editor import LandmarkEditorDialog

    model = _model()
    paths = []
    for index in range(2):
        path = tmp_path / f"grid-{index}.obj"
        path.write_text(
            "".join(f"v {x} {y} {z + index}\n" for x, y, z in model.vertices)
            + "".join(f"f {a + 1} {b + 1} {c + 1}\n" for a, b, c in model.triangles),
            encoding="utf-8",
        )
        paths.append(path)
    originals = [path.read_bytes() for path in paths]
    output = tmp_path / "landmarks.csv"
    dialog = LandmarkEditorDialog(tuple(paths), output, auto_advance_mesh=True)
    dialog.canvas.set_view_preset("front")
    dialog.show()
    canvas = dialog.canvas
    for mesh in range(2):
        for label, (dx, dy) in enumerate(((-35, -30), (35, -30), (0, 35))):
            _wait(application, lambda: canvas.picking_ready, canvas)
            assert not canvas.original_detail.isChecked()
            assert not canvas.full_resolution_ready
            QTest.mouseClick(
                canvas,
                Qt.MouseButton.LeftButton,
                pos=QPoint(canvas.width() // 2 + dx, canvas.height() // 2 + dy),
            )
            _wait(
                application,
                lambda mesh=mesh, label=label: (
                    len(dialog.placements[paths[mesh].name]) == label + 1
                ),
            )
            placed = dialog.placements[paths[mesh].name][f"LM{label + 1}"]
            assert placed[2] == pytest.approx(mesh)
    draft = json.loads(dialog.draft_path.read_text(encoding="utf-8"))
    assert sum(len(points) for points in draft["placements"].values()) == 6
    canvas._pick_pending = True
    dialog._save_and_accept()
    assert not output.exists()
    assert "Transferring the last landmark" in dialog.status_label.text()
    canvas._pick_pending = False
    dialog._save_and_accept()
    labels, values = read_landmark_csv(output, tuple(path.name for path in paths))
    assert labels == ("LM1", "LM2", "LM3")
    assert values[:, :, 2] == pytest.approx(np.array(((0, 0, 0), (1, 1, 1))))
    assert [path.read_bytes() for path in paths] == originals
    dialog.close()
