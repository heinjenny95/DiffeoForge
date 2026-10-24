from __future__ import annotations

import threading
import time
from pathlib import Path

import numpy as np
import pytest

from diffeoforge.desktop.display_proxy import build_display_proxy, cached_display_proxy


def grid(n: int = 180) -> tuple[np.ndarray, np.ndarray]:
    x, y = np.meshgrid(np.linspace(-1, 1, n), np.linspace(-1, 1, n))
    vertices = np.column_stack((x.ravel(), y.ravel(), np.zeros(n * n)))
    a = np.arange((n - 1) * n).reshape(n - 1, n)[:, :-1].ravel()
    faces = np.vstack(
        (np.column_stack((a, a + 1, a + n)), np.column_stack((a + 1, a + n + 1, a + n)))
    )
    return vertices, faces


def test_quadric_proxy_is_bounded_deterministic_planar_and_source_immutable() -> None:
    vertices, faces = grid()
    before_vertices, before_faces = vertices.copy(), faces.copy()
    proxy = build_display_proxy(vertices, faces)
    assert 2000 < len(proxy.triangles) <= 8000 < len(faces)
    assert np.allclose(proxy.vertices[:, 2], 0, atol=1e-12)
    assert np.all(proxy.vertices.min(axis=0) >= vertices.min(axis=0) - 1e-12)
    assert np.all(proxy.vertices.max(axis=0) <= vertices.max(axis=0) + 1e-12)
    assert np.isfinite(proxy.vertices).all()
    assert len(np.unique(np.sort(proxy.triangles, axis=1), axis=0)) == len(proxy.triangles)
    assert not proxy.vertices.flags.writeable and not proxy.triangles.flags.writeable
    assert np.array_equal(vertices, before_vertices) and np.array_equal(faces, before_faces)
    again = build_display_proxy(vertices, faces)
    assert np.array_equal(proxy.vertices, again.vertices)
    assert np.array_equal(proxy.triangles, again.triangles)
    # Representatives are geometric approximations, not arbitrarily missing source triangles.
    assert "quadric" in proxy.method


def test_proxy_cache_and_cancel() -> None:
    vertices, faces = grid(15)
    first = cached_display_proxy("test-display-proxy-source", vertices, faces, budget=100)
    assert cached_display_proxy("test-display-proxy-source", vertices, faces, budget=100) is first
    event = threading.Event()
    event.set()
    with pytest.raises(InterruptedError):
        build_display_proxy(vertices, faces, cancelled=event)


def test_large_proxy_cannot_enable_qc_until_original_pixels_are_presented(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from diffeoforge.desktop.calibration_comparison_widget import CalibrationComparisonCanvas3D
    from diffeoforge.desktop.mesh_preview import MeshPreviewModel

    vertices, faces = grid(75)
    proxy = build_display_proxy(vertices, faces)
    model = MeshPreviewModel(
        tmp_path / "synthetic.vtk",
        "a" * 64,
        tuple(map(tuple, vertices)),
        tuple(map(tuple, faces)),
        (),
        (-1, 1, -1, 1, 0, 0),
        display_proxy=proxy,
    )
    app = QApplication.instance() or QApplication([])
    canvas = CalibrationComparisonCanvas3D()
    canvas.resize(600, 450)
    canvas.set_models(model, model)
    canvas.show()

    def wait_for_frame() -> None:
        deadline = time.monotonic() + 10
        while not canvas._frames.ready(canvas._frame_key()) and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.005)
        app.processEvents()
        assert canvas._frames.ready(canvas._frame_key())

    wait_for_frame()
    assert not canvas.full_resolution_ready
    canvas.original_detail.setChecked(True)
    assert not canvas.full_resolution_ready
    wait_for_frame()
    assert canvas.full_resolution_ready
    canvas.set_models(model, model)
    assert not canvas.original_detail.isChecked()
    assert not canvas.full_resolution_ready
    canvas.close()


def test_preview_loader_keeps_only_latest_and_discards_cancelled_results(monkeypatch) -> None:
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from diffeoforge.desktop.preview_mesh_loader import PreviewMeshLoader

    app = QApplication.instance() or QApplication([])
    loader = PreviewMeshLoader()
    gate, started = threading.Event(), threading.Event()
    received, executed = [], []
    loader.loaded.connect(lambda key, value: received.append((key, value)))

    def slow():
        started.set()
        assert gate.wait(5)
        return "stale"

    loader.request_operation("first", slow)
    assert started.wait(5)
    loader.request_operation("skip", lambda: executed.append("skip"))
    loader.request_operation("last", lambda: "current")
    gate.set()
    deadline = time.monotonic() + 5
    while not received and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    assert received == [("last", "current")]
    assert executed == []
    loader.request_operation("cancel", lambda: "ignored")
    loader.cancel()
    deadline = time.monotonic() + 5
    while loader._active is not None and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    assert received == [("last", "current")]
