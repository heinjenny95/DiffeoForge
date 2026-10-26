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
    wait(viewer.app, lambda: len(viewer.requests) >= 2)
    wait(viewer.app, lambda: v.canvas.comparison_ready)
    assert not v.canvas.full_resolution_ready
    assert not v.complete_button.isEnabled() and not v.fail_button.isEnabled()
    assert not v.mark_region_button.isEnabled() and not v.review_recorded
    v._record_visual_qc_pass()
    v._record_visual_qc_fail()
    v._record_plan_b()
    assert not v.review_recorded and not v.keep_as_plan_b
    assert v._reviewed_pair_ids == set()


def show_full(viewer):
    viewer.v._pair_loaded((0, "detail"), tuple(model(p, False) for p in viewer.paths))
    wait(viewer.app, lambda: viewer.v.canvas.full_resolution_ready)
    assert viewer.v.complete_button.isEnabled()
    assert viewer.v.fail_button.isEnabled()
    scene = next(s for s in reversed(viewer.scenes) if not s.navigation)
    assert len(scene.layers[0].indices) == 8978
    assert len(scene.layers[1].indices) > 8000
    assert not viewer.v.canvas.reconstruction_model.geometry_is_proxy


def test_proxy_waits_for_exact_settled_full_frame_without_convergence_requirement(viewer):
    show_proxy(viewer)
    show_full(viewer)
    assert "Complete comparison ready" in viewer.v.status.text()
    assert viewer.v.canvas.original_detail.isChecked()
    viewer.v.complete_button.click()
    assert viewer.v.review_passed and viewer.v.review_complete


def test_fast_view_and_navigation_block_decisions_until_full_settles_again(viewer):
    show_proxy(viewer)
    show_full(viewer)
    viewer.v.canvas.original_detail.setChecked(False)
    wait(viewer.app, lambda: viewer.v.canvas.comparison_ready)
    assert not viewer.v.canvas.full_resolution_ready and not viewer.v.complete_button.isEnabled()
    assert "Fast preview only" in viewer.v.status.text()
    viewer.v._record_visual_qc_pass()
    assert not viewer.v.review_recorded
    viewer.v.canvas.original_detail.setChecked(True)
    wait(viewer.app, lambda: viewer.v.canvas.full_resolution_ready)
    viewer.v.canvas._interacting = True
    viewer.v.canvas.update()
    wait(viewer.app, lambda: any(s.navigation for s in viewer.scenes))
    assert not viewer.v.canvas.full_resolution_ready
    viewer.v._update_review_progress()
    assert not viewer.v.complete_button.isEnabled()
    viewer.v.canvas._interacting = False
    viewer.v.canvas.update()
    wait(viewer.app, lambda: viewer.v.canvas.full_resolution_ready)
    assert viewer.v.complete_button.isEnabled() and not viewer.v.review_recorded


def test_full_failure_keeps_non_gradeable_preview_and_allows_retry_close(viewer):
    show_proxy(viewer)
    viewer.v._pair_failed((0, "detail"), "bounded test error")
    wait(viewer.app, lambda: viewer.v.canvas.comparison_ready)
    assert viewer.v.canvas.reconstruction_model is not None
    assert "Full geometry unavailable" in viewer.v.status.text()
    assert not viewer.v.complete_button.isEnabled() and not viewer.v.fail_button.isEnabled()
    previous = len(viewer.requests)
    viewer.v.canvas.original_detail.setChecked(True)
    wait(viewer.app, lambda: len(viewer.requests) > previous)
    assert not viewer.v.review_recorded


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
