"""Private actual-Qt switching/full-frame policy tests; no owner data or fits."""

import time
from types import SimpleNamespace

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from diffeoforge.desktop.mesh_preview import MeshPreviewModel
from diffeoforge.desktop.preview_mesh_loader import PreviewMeshLoader
from diffeoforge.desktop.reference_calibration_dialog import (
    CalibrationCandidateViewerDialog,
    CalibrationQcPair,
)


def wait(app, condition):
    deadline = time.monotonic() + 15
    while not condition() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.002)
    assert condition()


def model(path, sha, proxy=False):
    n = 3 if proxy else 68
    xy = np.linspace(-1, 1, n)
    x, y = np.meshgrid(xy, xy)
    v = np.c_[x.ravel(), y.ravel(), (0.2 * np.sin(x) * np.cos(y)).ravel()]
    a, b = np.meshgrid(np.arange(n - 1), np.arange(n - 1))
    p = (a * n + b).ravel()
    f = np.vstack((np.c_[p, p + 1, p + n], np.c_[p + 1, p + n + 1, p + n]))
    e = np.unique(np.sort(np.vstack((f[:, :2], f[:, 1:], f[:, [2, 0]])), axis=1), axis=0)
    return MeshPreviewModel(
        path=path,
        sha256=sha,
        vertices=tuple(map(tuple, v)),
        triangles=tuple(map(tuple, f)),
        edges=tuple(map(tuple, e)),
        bounds=(-1, 1, -1, 1, -0.2, 0.2),
        geometry_is_proxy=proxy,
        source_triangle_count=8978,
    )


@pytest.fixture
def case(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    original = tmp_path / "original.vtk"
    current = tmp_path / "current.vtk"
    pair = CalibrationQcPair("current", "current", original, current, True, "0" * 64, "1" * 64)
    choices = [
        CalibrationQcPair(
            "alt-" + str(i),
            "alt-" + str(i),
            original,
            tmp_path / ("alt" + str(i) + ".vtk"),
            True,
            "0" * 64,
            str(i + 2) * 64,
        )
        for i in range(2)
    ]
    requests = []
    monkeypatch.setattr(
        PreviewMeshLoader, "request_paths", lambda self, *a, **k: requests.append((self, a, k))
    )
    reference = dict(method="varifold", directory=str(tmp_path), candidate_id="alternative")
    context = dict(
        comparison=reference,
        choices=[dict(reference=reference, label="named starting fit")],
        feedback=None,
        comparison_reconstruction_path=str(choices[0].reconstruction_path),
        comparison_reconstruction_sha256=choices[0].reconstruction_sha256,
    )
    candidate = SimpleNamespace(
        candidate_id="current",
        status="completed",
        run_directory=tmp_path,
        metrics=dict(
            invalid_face_count=0, converged=False, optimizer_stop_signal="maximum_iterations"
        ),
    )
    viewer = CalibrationCandidateViewerDialog(
        tmp_path,
        candidate,
        pairs=(pair,),
        alternative_pairs=tuple((False, "alternative " + str(i), p) for i, p in enumerate(choices)),
        guided_feedback_context=context,
        compact_review=True,
    )
    viewer.resize(1250, 850)
    viewer.show()
    main_models = (
        model(original, pair.original_sha256),
        model(current, pair.reconstruction_sha256),
    )
    viewer._pair_loaded((0, "detail"), main_models)
    wait(app, lambda: viewer.canvas.full_resolution_ready)
    yield SimpleNamespace(
        app=app,
        v=viewer,
        pair=pair,
        choices=choices,
        requests=requests,
        models=main_models,
        saved=viewer.saved_comparison,
    )
    viewer.close()
    app.processEvents()


def relative_enabled(case):
    return all(b.isEnabled() for b in case.v.guided_feedback.outcomes.values())


def deliver(case, index, *, proxy=False, path=None):
    pair = case.choices[index]
    m = (
        model(pair.original_path, pair.original_sha256, proxy),
        model(path or pair.reconstruction_path, pair.reconstruction_sha256, proxy),
    )
    case.saved._loaded(pair.pair_id, m)


def test_alternatives_are_optional_selected_only_and_switches_reject_stale_geometry(case):
    assert relative_enabled(case) and case.v.complete_button.isEnabled()
    assert len(case.requests) == 1  # main pair only; no history/specimen geometry preload
    assert not case.saved.toggle.isChecked()
    case.saved.toggle.setChecked(True)
    assert not relative_enabled(case) and case.v.guided_feedback_decision is None
    wait(case.app, lambda: case.v.canvas.full_resolution_ready)
    assert case.v.complete_button.isEnabled()  # single-fit suitability remains scoped to current
    assert case.requests[-1][1][1] == (case.pair.original_path, case.choices[0].reconstruction_path)
    assert "pilot_cache" not in case.requests[-1][2]
    case.saved.choice.setCurrentIndex(1)
    assert case.saved.canvas.reconstruction_model is None
    deliver(case, 0)  # late previous selection must never appear below the new label
    assert case.saved.canvas.reconstruction_model is None and not relative_enabled(case)
    deliver(case, 1)
    wait(case.app, lambda: case.saved.full_comparison_ready and case.v.canvas.full_resolution_ready)
    assert relative_enabled(case)
    case.v.guided_feedback.outcomes["better"].click()
    assert case.v.guided_feedback_decision is not None
    case.saved.choice.setCurrentIndex(0)
    assert not any(b.isChecked() for b in case.v.guided_feedback.outcomes.values())
    assert not relative_enabled(case) and case.v.guided_feedback_decision is None
    case.saved.toggle.setChecked(False)
    wait(case.app, lambda: case.v.canvas.full_resolution_ready)
    assert relative_enabled(case) and not case.v.review_recorded


def test_proxy_or_wrong_selected_source_cannot_qualify_and_failure_can_retry(case):
    case.saved.toggle.setChecked(True)
    deliver(case, 0, proxy=True)
    assert not case.saved.full_comparison_ready and not relative_enabled(case)
    assert case.saved.retry_button.isVisible() and case.saved.canvas.reconstruction_model is None
    before = len(case.requests)
    case.saved.retry_button.click()
    assert len(case.requests) == before + 1 and not case.saved.retry_button.isVisible()
    deliver(case, 0, path=case.choices[1].reconstruction_path)
    assert not case.saved.full_comparison_ready and case.saved.retry_button.isVisible()
    case.saved.retry_button.click()
    deliver(case, 0)
    wait(case.app, lambda: case.saved.full_comparison_ready and case.v.canvas.full_resolution_ready)
    assert relative_enabled(case) and not case.v.review_recorded
    assert case.saved.canvas.reconstruction_model.sha256 == case.choices[0].reconstruction_sha256


def test_comparison_navigation_blocks_relative_feedback_but_preserves_its_bound_choice(case):
    case.saved.toggle.setChecked(True)
    deliver(case, 0)
    wait(case.app, lambda: case.saved.full_comparison_ready and case.v.canvas.full_resolution_ready)
    case.v.guided_feedback.outcomes["same"].click()
    assert case.v.guided_feedback_decision["comparison_displayed"] is True
    case.saved.canvas._interacting = True
    case.saved.canvas._emit_camera()
    case.saved.canvas.update()
    wait(case.app, lambda: not case.saved.canvas.full_resolution_ready)
    case.v._update_review_progress()
    assert not relative_enabled(case) and case.v.guided_feedback_decision is None
    case.saved.canvas._interacting = False
    case.saved.canvas._emit_camera()
    case.saved.canvas.update()
    wait(
        case.app,
        lambda: (
            case.saved.full_comparison_ready
            and case.v.canvas.full_resolution_ready
            and relative_enabled(case)
        ),
    )
    assert relative_enabled(case) and case.v.guided_feedback.outcomes["same"].isChecked()
    assert not case.v.review_recorded


def test_legacy_relative_panel_requires_full_current_and_selected_reference(tmp_path, monkeypatch):
    from diffeoforge.desktop.fit_preference_dialog import FitPreferencePanel

    app = QApplication.instance() or QApplication([])
    pending = []
    monkeypatch.setattr(
        PreviewMeshLoader, "request_operation", lambda self, *a, **k: pending.append((a, k))
    )
    panel = FitPreferencePanel(tmp_path)
    panel.show()
    assert panel.detail.isChecked()
    current = dict(study="now", candidate_id="c")
    ref = dict(study="before", candidate_id="r")
    descriptor = dict(root=str(tmp_path), current=current, best=ref, choices=[ref])
    panel._loaded("choices", descriptor)
    panel.show_comparison.setChecked(True)
    comparison = dict(current=current, reference=ref, best=ref)
    paths = tmp_path / "original.vtk", tmp_path / "current.vtk", tmp_path / "saved.vtk"
    for proxy in (True, False):
        models = [model(p, str(i) * 64, proxy and i == 2) for i, p in enumerate(paths)]
        panel._loaded("surfaces", (models, comparison))
        wait(
            app,
            lambda: (
                panel.current_canvas.comparison_ready and panel.reference_canvas.comparison_ready
            ),
        )
        assert all(b.isEnabled() for b in panel.feedback_buttons.values()) is (not proxy)
        if proxy:
            panel._choose("same")
            assert panel.decision is None and not panel.selection_ready
        else:
            assert (
                panel.current_canvas.full_resolution_ready
                and panel.reference_canvas.full_resolution_ready
            )
    panel.shutdown()
    panel.close()
    app.processEvents()
