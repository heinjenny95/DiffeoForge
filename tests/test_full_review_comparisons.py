"""Private actual-Qt switching/full-frame policy tests; no owner data or fits."""

import time
from dataclasses import replace
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
def case(tmp_path, monkeypatch, request):
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
    common_case = getattr(request, "param", None)
    if common_case in {"common", "same_reference", "no_seed", "unreviewed_seed"}:
        seed = (reference if common_case == "same_reference" else
                None if common_case == "no_seed" else dict(reference, candidate_id="seed"))
        choices = [replace(choices[0], rating_reference=reference),
                   replace(choices[1], rating_reference=(
                       None if common_case == "unreviewed_seed" else seed))]
        context.update(require_fit_decision=True, common_review=dict(
            current_label="Test 3", seed_label="Test 1", current_distances="",
            approved_individual=reference, numerical_seed=seed, context_directory=str(tmp_path)))
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
        common_model=common_case == "legacy_saved_common",
    )
    viewer.resize(1250, 850)
    viewer.show()
    main_models = (
        model(original, pair.original_sha256, proxy=True),
        model(current, pair.reconstruction_sha256, proxy=True),
    )
    viewer._pair_loaded(0, main_models)
    wait(app, lambda: viewer.canvas.comparison_ready)
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


def deliver(case, index, *, proxy=True, path=None):
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
    wait(case.app, lambda: case.v.canvas.comparison_ready)
    assert case.v.complete_button.isEnabled()  # single-fit suitability remains scoped to current
    assert case.requests[-1][1][1] == (case.pair.original_path, case.choices[0].reconstruction_path)
    assert case.requests[-1][2]["pilot_cache"] == case.v._preview_cache
    case.saved.choice.setCurrentIndex(1)
    assert case.saved.canvas.reconstruction_model is None
    deliver(case, 0)  # late previous selection must never appear below the new label
    assert case.saved.canvas.reconstruction_model is None and not relative_enabled(case)
    deliver(case, 1)
    wait(case.app, lambda: case.saved.full_comparison_ready and case.v.canvas.comparison_ready)
    assert relative_enabled(case)
    case.v.guided_feedback.outcomes["better"].click()
    assert case.v.guided_feedback_decision is not None
    case.saved.choice.setCurrentIndex(0)
    assert not any(b.isChecked() for b in case.v.guided_feedback.outcomes.values())
    assert not relative_enabled(case) and case.v.guided_feedback_decision is None
    case.saved.toggle.setChecked(False)
    wait(case.app, lambda: case.v.canvas.comparison_ready)
    assert relative_enabled(case) and not case.v.review_recorded


def test_preview_comparison_can_qualify_but_wrong_selected_source_cannot(case):
    case.saved.toggle.setChecked(True)
    deliver(case, 0, proxy=True)
    wait(case.app, lambda: case.saved.full_comparison_ready and case.v.canvas.comparison_ready)
    assert relative_enabled(case)
    assert not case.saved.canvas.full_resolution_ready
    case.saved.choice.setCurrentIndex(1)
    deliver(case, 1, path=case.choices[0].reconstruction_path)
    assert not case.saved.full_comparison_ready and not relative_enabled(case)
    assert case.saved.retry_button.isVisible() and case.saved.canvas.reconstruction_model is None
    before = len(case.requests)
    case.saved.retry_button.click()
    assert len(case.requests) == before + 1 and not case.saved.retry_button.isVisible()
    deliver(case, 1)
    wait(case.app, lambda: case.saved.full_comparison_ready and case.v.canvas.comparison_ready)
    assert relative_enabled(case) and not case.v.review_recorded
    assert case.saved.canvas.reconstruction_model.sha256 == case.choices[1].reconstruction_sha256


def test_comparison_navigation_blocks_relative_feedback_but_preserves_its_bound_choice(case):
    case.saved.toggle.setChecked(True)
    deliver(case, 0)
    wait(case.app, lambda: case.saved.full_comparison_ready and case.v.canvas.comparison_ready)
    case.v.guided_feedback.outcomes["same"].click()
    assert case.v.guided_feedback_decision["comparison_displayed"] is True
    case.saved.canvas._interacting = True
    case.saved.canvas._emit_camera()
    case.saved.canvas.update()
    wait(case.app, lambda: not case.saved.canvas.comparison_ready)
    case.v._update_review_progress()
    assert not relative_enabled(case) and case.v.guided_feedback_decision is None
    case.saved.canvas._interacting = False
    case.saved.canvas._emit_camera()
    case.saved.canvas.update()
    wait(
        case.app,
        lambda: (
            case.saved.full_comparison_ready
            and case.v.canvas.comparison_ready
            and relative_enabled(case)
        ),
    )
    assert relative_enabled(case) and case.v.guided_feedback.outcomes["same"].isChecked()
    assert not case.v.review_recorded


@pytest.mark.parametrize("case", ["common"], indirect=True)
def test_common_review_switch_binds_the_displayed_reference_and_hidden_view_allows_absolute_qc(
    case,
):
    saved, viewer = case.saved, case.v
    assert saved.toggle.isChecked() and not relative_enabled(case)
    deliver(case, 0)
    wait(case.app, lambda: relative_enabled(case))
    viewer.guided_feedback.outcomes["worse"].click()
    assert (viewer.guided_feedback_decision["comparison"]
            == viewer._common_review["approved_individual"])
    assert viewer.guided_feedback_decision["common_comparison_displayed"]
    viewer.guided_feedback.note.setText("The approved projection is missing.")
    saved.choice.setCurrentIndex(1)
    deliver(case, 0)
    assert not relative_enabled(case) and viewer.guided_feedback_decision is None
    deliver(case, 1)
    wait(case.app, lambda: relative_enabled(case))
    assert not viewer.guided_feedback.note.text()
    assert viewer.guided_feedback_decision is None
    viewer.guided_feedback.outcomes["better"].click()
    assert (saved.choice.currentData().rating_reference
            == viewer._common_review["approved_individual"])
    wait(case.app, lambda: viewer.canvas.comparison_ready)
    assert viewer.guided_feedback_decision["comparison"] == viewer._common_review["numerical_seed"]
    viewer.guided_feedback.edit_progress.click()
    assert saved.choice.currentData().rating_reference == viewer._common_review["numerical_seed"]
    deliver(case, 1)
    wait(case.app, lambda: relative_enabled(case))
    assert viewer.guided_feedback_decision is None
    saved.toggle.setChecked(False)
    wait(case.app, lambda: viewer.canvas.comparison_ready and viewer.fail_button.isEnabled())
    assert not relative_enabled(case) and viewer.guided_feedback_decision is None
    viewer.fail_button.click()
    assert viewer.review_recorded and not viewer.review_passed


@pytest.mark.parametrize("case", ["same_reference", "no_seed"], indirect=True)
def test_review_with_same_reference_or_without_a_start(case):
    viewer = case.v
    deliver(case, 0)
    wait(case.app, lambda: relative_enabled(case))
    if viewer._common_review["numerical_seed"] is not None:
        assert not viewer.fail_button.isEnabled()
        viewer.guided_feedback.outcomes["better"].click()
        assert (viewer.guided_feedback_decision["comparison"]
                == viewer._common_review["numerical_seed"])
        assert case.saved.choice.currentIndex() == 0
    else:
        assert "Optional comparison" in viewer.guided_feedback.title.text()
        assert viewer.guided_feedback_decision is None
    assert viewer.fail_button.isEnabled()
    assert all(button.objectName() == "secondary" and not button.autoDefault()
               for button in (viewer.complete_button, viewer.fail_button))
    viewer.fail_button.click()
    assert viewer.review_recorded and not viewer.review_passed


@pytest.mark.parametrize("case", ["common"], indirect=True)
def test_editing_reviewed_marks_reopens_progress_and_cancel_records_nothing(case):
    viewer, comparison = case.v, case.saved
    name = case.pair.original_path.name
    mark = {"center": [1, 2, 3], "radius": 1}
    viewer._set_reviewed_regions(name, [mark])
    comparison.choice.setCurrentIndex(1)
    deliver(case, 1)
    wait(case.app, lambda: relative_enabled(case))
    viewer.guided_feedback.outcomes["better"].click()
    deliver(case, 0)
    wait(case.app, lambda: viewer.fail_button.isEnabled())
    viewer._set_reviewed_regions(name, [dict(mark)])
    assert viewer.guided_feedback_decision["problem_regions"] == {name: [mark]}
    viewer._clear_regions()
    assert (comparison.choice.currentData().rating_reference
            == viewer._common_review["numerical_seed"])
    assert viewer.guided_feedback_decision is None
    viewer.close_button.click()
    assert not viewer.review_recorded and not viewer._guided_feedback_only


@pytest.mark.parametrize("case", ["unreviewed_seed"], indirect=True)
def test_inspection_only_checkpoint_allows_suitability_without_a_progress_rating(case):
    case.saved.choice.setCurrentIndex(1)
    deliver(case, 1)
    wait(case.app, lambda: case.saved.full_comparison_ready and case.v.fail_button.isEnabled())
    assert not any(button.isVisible() for button in case.v.guided_feedback.outcomes.values())
    assert case.v.guided_feedback_decision is None
    case.v.fail_button.click()
    assert case.v.review_recorded and not case.v.review_passed


@pytest.mark.parametrize("size", [(960, 640), (1280, 720)])
@pytest.mark.parametrize("case", ["common"], indirect=True)
def test_common_review_keeps_both_meshes_visible_while_scrolling_actions(case, size):
    from PySide6.QtCore import QPoint, QRect

    from diffeoforge.desktop.widgets import _STYLE

    dialog = case.v
    dialog.setStyleSheet(_STYLE)
    dialog.resize(*size)
    def long_specimen(mesh):
        return replace(mesh, vertices=tuple((5 * x, 0.3 * y, z) for x, y, z in mesh.vertices),
                       bounds=(-5, 5, -0.3, 0.3, -0.2, 0.2))

    original, current = map(long_specimen, case.models)
    dialog._pair_loaded(0, (original, current))
    selected = case.saved.choice.currentData()
    reference = long_specimen(model(selected.reconstruction_path, selected.reconstruction_sha256,
                                    proxy=True))
    case.saved._loaded(selected.pair_id, (original, reference))
    wait(case.app, lambda: dialog.canvas.comparison_ready and case.saved.full_comparison_ready)
    assert dialog.width() == size[0] and dialog.height() == size[1]
    scroll = dialog.body_scroll
    viewports = (dialog.canvas, case.saved.canvas)

    def rectangles():
        return tuple(QRect(c.mapTo(dialog, QPoint()), c.size()) for c in viewports)

    for rect, canvas in zip(rectangles(), viewports, strict=True):
        assert dialog.rect().contains(rect)
        assert rect.bottom() < scroll.mapTo(dialog, QPoint()).y()
        assert rect.height() >= 150
        for vertices in (canvas.original_model.vertices, canvas.reconstruction_model.vertices):
            _, points = canvas._project(np.asarray(vertices))
            assert (points >= 0).all()
            assert (points < [canvas.width(), canvas.height()]).all()
            assert np.ptp(points[:, 0]) > canvas.width() / 2
    assert abs(dialog.canvas.width() - case.saved.canvas.width()) <= 2
    assert rectangles()[0].top() == rectangles()[1].top()
    assert dialog.canvas.height() == case.saved.canvas.height()

    dialog.canvas.set_view_preset("left")
    dialog.guided_feedback.note.setText("Better projection, more work needed")
    wait(case.app, lambda: dialog.canvas.comparison_ready and case.saved.full_comparison_ready)
    bounds = rectangles()
    cameras = [canvas.camera_state() for canvas in viewports]
    assert scroll.verticalScrollBar().maximum() > 0
    scroll.ensureWidgetVisible(dialog.fail_button)
    case.app.processEvents()
    button_position = dialog.fail_button.mapTo(scroll.viewport(), QPoint(1, 1))
    assert scroll.viewport().rect().contains(button_position)
    scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum())
    case.app.processEvents()
    assert rectangles() == bounds
    assert [canvas.camera_state() for canvas in viewports] == cameras
    assert dialog.guided_feedback.note.text() == "Better projection, more work needed"
    assert not dialog.review_recorded
    dialog.full_screen_button.click()
    wait(case.app, lambda: dialog.isFullScreen() and case.saved.full_comparison_ready)
    for rect in rectangles():
        assert dialog.rect().contains(rect)
        assert rect.bottom() < scroll.mapTo(dialog, QPoint()).y()
    dialog.full_screen_button.click()
    wait(case.app, lambda: not dialog.isFullScreen() and case.saved.full_comparison_ready)
    assert rectangles() == bounds
    assert [canvas.camera_state() for canvas in viewports] == cameras


@pytest.mark.parametrize("case", ["legacy_saved_common"], indirect=True)
def test_older_common_review_pins_mesh_without_inventing_a_progress_reference(case):
    from PySide6.QtCore import QPoint

    viewer = case.v
    viewer.resize(960, 640)
    wait(case.app, lambda: viewer.canvas.comparison_ready)
    assert not viewer._common_review and not case.saved.toggle.isChecked()
    assert viewer.body_scroll.isAncestorOf(viewer.decision_panel)
    assert not viewer.body_scroll.isAncestorOf(viewer.canvas)
    bottom = viewer.canvas.mapTo(viewer, viewer.canvas.rect().bottomRight()).y()
    assert bottom < viewer.body_scroll.mapTo(viewer, QPoint()).y()


def test_legacy_relative_panel_accepts_matching_preview_and_optional_full_detail(
    tmp_path, monkeypatch
):
    from diffeoforge.desktop.fit_preference_dialog import FitPreferencePanel

    app = QApplication.instance() or QApplication([])
    pending = []
    monkeypatch.setattr(
        PreviewMeshLoader, "request_operation", lambda self, *a, **k: pending.append((a, k))
    )
    panel = FitPreferencePanel(tmp_path)
    panel.show()
    assert not panel.detail.isChecked()
    current = dict(study="now", candidate_id="c")
    ref = dict(study="before", candidate_id="r")
    descriptor = dict(root=str(tmp_path), current=current, best=ref, choices=[ref])
    panel._loaded("choices", descriptor)
    panel.show_comparison.setChecked(True)
    comparison = dict(current=current, reference=ref, best=ref)
    paths = tmp_path / "original.vtk", tmp_path / "current.vtk", tmp_path / "saved.vtk"
    for proxy in (True, False):
        panel.detail.setChecked(not proxy)
        models = [model(p, str(i) * 64, proxy) for i, p in enumerate(paths)]
        panel._loaded("surfaces", (models, comparison))
        wait(
            app,
            lambda: (
                panel.current_canvas.comparison_ready and panel.reference_canvas.comparison_ready
            ),
        )
        assert all(b.isEnabled() for b in panel.feedback_buttons.values())
        if proxy:
            panel._choose("same")
            assert panel.decision is not None and panel.selection_ready
        else:
            assert (
                panel.current_canvas.full_resolution_ready
                and panel.reference_canvas.full_resolution_ready
            )
    panel.shutdown()
    panel.close()
    app.processEvents()
