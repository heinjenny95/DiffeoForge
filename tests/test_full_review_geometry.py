"""Private offscreen policy tests; only synthetic geometry/no saved approval."""

import os

os.environ["QT_QPA_PLATFORM"] = "offscreen"
import time
from types import SimpleNamespace

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from diffeoforge.desktop.mesh_preview import MeshPreviewModel
from diffeoforge.desktop.preview_mesh_loader import PreviewMeshLoader
from diffeoforge.desktop.reference_calibration_dialog import (
    CalibrationCandidateViewerDialog as FullGeometryReviewDialog,
)
from diffeoforge.desktop.reference_calibration_dialog import CalibrationQcPair


def wait(app, condition):
    end = time.monotonic() + 10
    while not condition() and time.monotonic() < end:
        app.processEvents()
        time.sleep(0.002)
    assert condition()


def model(path, proxy):
    n = 3 if proxy else 68
    xy = np.linspace(-1, 1, n)
    x, y = np.meshgrid(xy, xy)
    vertices = np.c_[x.ravel(), y.ravel(), (0.2 * np.sin(x * 2) * np.cos(y)).ravel()]
    a, b = np.meshgrid(np.arange(n - 1), np.arange(n - 1))
    p = (a * n + b).ravel()
    faces = np.vstack((np.c_[p, p + 1, p + n], np.c_[p + 1, p + n + 1, p + n]))
    edges = np.unique(
        np.sort(np.vstack((faces[:, :2], faces[:, 1:], faces[:, [2, 0]])), axis=1), axis=0
    )
    return MeshPreviewModel(
        path=path,
        sha256="0" * 64,
        vertices=tuple(map(tuple, vertices)),
        triangles=tuple(map(tuple, faces)),
        edges=tuple(map(tuple, edges)),
        bounds=(-1, 1, -1, 1, -0.2, 0.2),
        geometry_is_proxy=proxy,
        source_triangle_count=8978,
    )


@pytest.fixture
def viewer(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    paths = tmp_path / "original.vtk", tmp_path / "reconstruction.vtk"
    pair = CalibrationQcPair("one", "synthetic", *paths, True, "0" * 64, "0" * 64)
    requests = []
    monkeypatch.setattr(
        PreviewMeshLoader, "request_paths", lambda self, *a, **k: requests.append((a, k))
    )
    candidate = SimpleNamespace(
        candidate_id="capped",
        run_directory=tmp_path,
        status="completed",
        metrics=dict(
            invalid_face_count=0, converged=False, optimizer_stop_signal="maximum_iterations"
        ),
    )
    v = FullGeometryReviewDialog(tmp_path, candidate, pairs=(pair,), compact_review=True)
    scenes = []
    original = v.canvas._frames.request

    def capture(key, scene):
        scenes.append(scene)
        return original(key, scene)

    v.canvas._frames.request = capture
    v.show()
    yield SimpleNamespace(app=app, v=v, paths=paths, requests=requests, scenes=scenes)
    v.close()
    app.processEvents()


def show_proxy(viewer):
    v = viewer.v
    v._pair_loaded(0, tuple(model(p, True) for p in viewer.paths))
    wait(viewer.app, lambda: v.canvas.comparison_ready)
    assert not v.canvas.full_resolution_ready
    assert len(viewer.requests) == 1  # no automatic complete-mesh load
    assert not v.canvas.original_detail.isChecked()
    assert v.complete_button.isEnabled() and v.fail_button.isEnabled()
    assert v.mark_region_button.isEnabled() and not v.review_recorded
    assert v._reviewed_pair_ids == {"one"}
    assert v.display_scopes == {"original.vtk": "preview"}


def show_full(viewer):
    viewer.v._pair_loaded((0, "detail"), tuple(model(p, False) for p in viewer.paths))
    wait(viewer.app, lambda: viewer.v.canvas.full_resolution_ready)
    assert viewer.v.complete_button.isEnabled()
    assert viewer.v.fail_button.isEnabled()
    scene = next(s for s in reversed(viewer.scenes) if not s.navigation)
    assert len(scene.layers[0].indices) == 8978
    assert len(scene.layers[1].indices) > 8000
    assert not viewer.v.canvas.reconstruction_model.geometry_is_proxy


def test_preview_is_sufficient_to_approve_without_loading_full_geometry(viewer):
    show_proxy(viewer)
    assert "Preview ready" in viewer.v.status.text()
    viewer.v.complete_button.click()
    assert viewer.v.review_passed and viewer.v.review_complete


def test_preview_navigation_blocks_decisions_until_selected_image_settles(viewer):
    show_proxy(viewer)
    viewer.v.canvas._interacting = True
    viewer.v.canvas._emit_camera()
    viewer.v.canvas.update()
    wait(viewer.app, lambda: any(s.navigation for s in viewer.scenes))
    assert not viewer.v.canvas.full_resolution_ready
    viewer.v._update_review_progress()
    assert not viewer.v.complete_button.isEnabled()
    viewer.v.canvas._interacting = False
    viewer.v.canvas._emit_camera()
    viewer.v.canvas.update()
    wait(viewer.app, lambda: viewer.v.canvas.comparison_ready)
    assert viewer.v.complete_button.isEnabled() and not viewer.v.review_recorded


def test_optional_full_failure_keeps_usable_preview_and_allows_retry(viewer):
    show_proxy(viewer)
    viewer.v._pair_failed((0, "detail"), "bounded test error")
    wait(viewer.app, lambda: viewer.v.canvas.comparison_ready)
    assert viewer.v.canvas.reconstruction_model is not None
    assert "Optional full detail unavailable" in viewer.v.status.text()
    assert viewer.v.complete_button.isEnabled() and viewer.v.fail_button.isEnabled()
    previous = len(viewer.requests)
    viewer.v.canvas.original_detail.setChecked(True)
    wait(viewer.app, lambda: len(viewer.requests) > previous)
    assert not viewer.v.review_recorded


def test_full_detail_load_is_explicit_and_preview_rejection_remains_available(viewer):
    show_proxy(viewer)
    viewer.v.canvas.original_detail.setChecked(True)
    wait(viewer.app, lambda: len(viewer.requests) == 2)
    assert viewer.requests[-1][0][0] == (0, "detail")
    show_full(viewer)
    assert "Full detail ready" in viewer.v.status.text()
    viewer.v.fail_button.click()
    assert viewer.v.review_recorded and not viewer.v.review_passed


def test_small_full_pair_remains_settled_after_decision_panel_opens(viewer):
    tiny = []
    for path in viewer.paths:
        tiny.append(
            MeshPreviewModel(
                path=path,
                sha256="0" * 64,
                vertices=((-1.0, -1.0, 0.0), (1.0, -1.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 0.6)),
                triangles=((0, 1, 2), (0, 1, 3), (1, 2, 3), (0, 2, 3)),
                edges=((0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3)),
                bounds=(-1.0, 1.0, -1.0, 1.0, 0.0, 0.6),
            )
        )
    viewer.v._pair_loaded(0, tuple(tiny))
    wait(
        viewer.app,
        lambda: viewer.v.canvas.full_resolution_ready and viewer.v.fail_button.isVisible(),
    )
    for _ in range(30):
        viewer.app.processEvents()
        time.sleep(0.01)
    assert viewer.v.canvas.full_resolution_ready and viewer.v.fail_button.isVisible()


@pytest.mark.parametrize("size", [(1080, 930), (900, 720), (1400, 1000)])
@pytest.mark.parametrize("preview", [True, False])
def test_styled_review_stays_ready_without_resizing_and_rerendering_itself(viewer, size, preview):
    from diffeoforge.desktop.widgets import _STYLE

    v = viewer.v
    v.setStyleSheet(_STYLE)
    v.resize(*size)
    (show_proxy if preview else show_full)(viewer)
    # The first ready signal is insufficient: hiding the styled hint used to
    # invalidate it at the following layout pass, indefinitely toggling QC.
    deadline = time.monotonic() + 1.0
    sizes, readiness, render_counts = [], [], []
    while time.monotonic() < deadline:
        viewer.app.processEvents()
        sizes.append((v.canvas.width(), v.canvas.height()))
        readiness.append(v.canvas.comparison_ready)
        render_counts.append(v.canvas._frames.render_count)
        time.sleep(0.005)
    assert len(set(sizes[-30:])) == 1
    assert all(readiness[-30:])
    assert len(set(render_counts[-30:])) == 1
    assert v.complete_button.isEnabled() and v.fail_button.isEnabled()
    assert v.mark_region_button.isEnabled()
    assert not v.review_recorded

    # Actual navigation must still block decisions, with the same viewport on
    # both sides of the full-frame gate.
    settled_size = sizes[-1]
    v.canvas._interacting = True
    v.canvas._emit_camera()
    v.canvas.update()
    viewer.app.processEvents()
    assert not v.complete_button.isEnabled() and not v.mark_region_button.isEnabled()
    assert (v.canvas.width(), v.canvas.height()) == settled_size
    v.canvas._interacting = False
    v.canvas._emit_camera()
    v.canvas.update()
    wait(viewer.app, lambda: v.canvas.comparison_ready)
    deadline = time.monotonic() + 0.4
    while time.monotonic() < deadline:
        viewer.app.processEvents()
        assert v.canvas.comparison_ready
        assert (v.canvas.width(), v.canvas.height()) == settled_size
        time.sleep(0.005)
    assert v.complete_button.isEnabled() and v.mark_region_button.isEnabled()


def test_missing_preview_geometry_cannot_qualify_a_blank_image(viewer):
    # A failed reduction of a large full model must not present an empty image
    # as an adequate preview. The source models alone are insufficient.
    v = viewer.v
    v._pair_loaded(0, tuple(model(p, False) for p in viewer.paths))
    wait(viewer.app, lambda: v.canvas._frames.ready(v.canvas._frame_key()))
    assert not v.canvas.comparison_ready
    assert not v.complete_button.isEnabled() and not v.fail_button.isEnabled()
    v._record_visual_qc_pass()
    assert not v.review_recorded and len(viewer.requests) == 1
