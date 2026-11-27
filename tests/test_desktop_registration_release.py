from __future__ import annotations

import json
import shutil
from dataclasses import replace
from pathlib import Path

import pytest

from diffeoforge.desktop.reference_result_review import (
    finalize_registration_qc_review,
    load_finalized_registration_qc_review,
    load_registration_qc_draft,
    registration_qc_directory,
    save_registration_qc_draft,
)
from diffeoforge.desktop.registration_release import (
    RELEASE_NAME,
    inspection_binding,
    load_visual_inspections,
    registration_inspection_plan,
    release_registration_results,
    require_registration_release,
    required_registration_inspections,
)
from diffeoforge.desktop.result_review import (
    ModernResultArtifact,
    ModernResultReview,
    ModernResultReviewError,
    RegistrationQCItem,
)
from diffeoforge.mesh import sha256_file
from diffeoforge.registration_screening import inspection_threshold


@pytest.fixture
def visual_review(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    for name in ("manifest.json", "analysis.json"):
        (run / name).write_text("{}\n", encoding="utf-8")
    mesh = Path(__file__).parents[1] / "examples/synthetic/meshes/template.vtk"
    artifacts = []
    items = []
    for index in (1, 2):
        for role in ("original", "reconstruction"):
            path = run / f"{role}-{index}.vtk"
            shutil.copyfile(mesh, path)
            artifacts.append(ModernResultArtifact(
                f"subject-{role}-{index}", path.name, path, "vtk", path.stat().st_size,
                sha256_file(path), "Synthetic overlay fixture",
            ))
        items.append(RegistrationQCItem(
            index, f"subject-{index}", float(3 - index),
            f"subject-original-{index}", f"subject-reconstruction-{index}",
        ))
    return ModernResultReview(
        run, run, "Visual review test", "2026-09-07T00:00:00Z",
        run / "manifest.json", sha256_file(run / "manifest.json"),
        run / "analysis.json", sha256_file(run / "analysis.json"),
        True, "tolerance_threshold", 2, 10, (), (), (), (), tuple(artifacts), (),
        engine_route="deformetrica_reference", registration_qc=tuple(items),
    )


def _approvals(review):
    decisions = {item.subject_name: "pass" for item in review.registration_qc}
    return decisions, {name: inspection_binding(review, name) for name in decisions}


def test_unreviewed_registration_cannot_release_or_exclude(visual_review):
    decisions, inspections = _approvals(visual_review)
    decisions.pop("subject-2")
    with pytest.raises(ModernResultReviewError, match="Results remain locked"):
        release_registration_results(visual_review, decisions, inspections)
    assert not (registration_qc_directory(visual_review) / RELEASE_NAME).exists()
    assert len(visual_review.registration_qc) == 2


@pytest.mark.parametrize("engine", ["deformetrica_reference", "modern"])
@pytest.mark.parametrize("decision", ["uncertain", "fail"])
def test_negative_decision_completes_review_without_changing_or_excluding_data(
    visual_review, engine, decision,
):
    review = replace(visual_review, engine_route=engine)
    decisions, inspections = _approvals(review)
    decisions["subject-2"] = decision
    before = {a.path: sha256_file(a.path) for a in review.artifacts}
    save_registration_qc_draft(review, decisions, visual_inspections=inspections)
    release_registration_results(review, decisions, inspections)
    require_registration_release(
        review, load_registration_qc_draft(review), load_visual_inspections(review)
    )
    final = load_finalized_registration_qc_review(review)
    assert dict(final.decisions) == decisions
    payload = json.loads(final.path.read_text(encoding="utf-8"))
    scope = payload["visual_review_scope"]
    assert scope["required_review_complete"] is True
    assert scope["all_required_plausible"] is False
    assert scope["review_outcome"] == "reviewed_with_concerns"
    assert scope["concern_subjects"] == {"subject-2": decision}
    assert before == {a.path: sha256_file(a.path) for a in review.artifacts}


@pytest.mark.parametrize("decision", ["uncertain", "fail"])
def test_negative_decision_still_requires_bound_visual_inspection(visual_review, decision):
    decisions, inspections = _approvals(visual_review)
    decisions["subject-2"] = decision
    inspections.pop("subject-2")
    with pytest.raises(ModernResultReviewError, match="acknowledgement"):
        release_registration_results(visual_review, decisions, inspections)


@pytest.mark.parametrize("engine", ["deformetrica_reference", "modern"])
def test_visual_approval_survives_reload_without_modifying_meshes(visual_review, engine):
    review = replace(visual_review, engine_route=engine)
    decisions, inspections = _approvals(review)
    before = {a.path: sha256_file(a.path) for a in review.artifacts}
    save_registration_qc_draft(review, decisions, visual_inspections=inspections)
    release_registration_results(review, decisions, inspections)
    require_registration_release(
        review, load_registration_qc_draft(review), load_visual_inspections(review)
    )
    assert before == {a.path: sha256_file(a.path) for a in review.artifacts}
    if engine == "modern":
        assert registration_qc_directory(review).parent == review.run_directory.parent
        assert not (review.run_directory / "reviews").exists()


def test_legacy_finalized_review_does_not_bypass_visual_step(visual_review):
    decisions, inspections = _approvals(visual_review)
    save_registration_qc_draft(visual_review, decisions)
    finalize_registration_qc_review(visual_review, decisions)
    assert load_visual_inspections(visual_review) == {}
    with pytest.raises(ModernResultReviewError, match="acknowledgement"):
        require_registration_release(visual_review, decisions, {})
    with pytest.raises(ModernResultReviewError, match="Step 5"):
        require_registration_release(visual_review, decisions, inspections)


@pytest.mark.parametrize("change", ["decision", "mesh_binding", "manifest", "release", "finalized"])
def test_changed_evidence_or_decisions_relock_results(visual_review, change):
    decisions, inspections = _approvals(visual_review)
    release_registration_results(visual_review, decisions, inspections)
    if change == "decision":
        decisions["subject-2"] = "uncertain"
    elif change == "mesh_binding":
        inspections["subject-2"]["original_sha256"] = "0" * 64
    elif change == "manifest":
        visual_review.workflow_manifest_path.write_text("changed", encoding="utf-8")
    elif change == "release":
        path = registration_qc_directory(visual_review) / RELEASE_NAME
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["source"]["analysis_manifest_sha256"] = "0" * 64
        path.write_text(json.dumps(payload), encoding="utf-8")
    else:
        finalize_registration_qc_review(visual_review, decisions)
    with pytest.raises(ModernResultReviewError):
        require_registration_release(visual_review, decisions, inspections)


@pytest.fixture
def review_window(monkeypatch, visual_review):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from diffeoforge.desktop.widgets import DiffeoForgeWindow

    app = QApplication.instance() or QApplication(["visual-review-test"])
    window = DiffeoForgeWindow()
    monkeypatch.setattr(window, "_load_verified_optimizer_plot", lambda _review: None)
    monkeypatch.setattr(window, "_load_verified_pca_plots", lambda _review: None)
    window._result_review_succeeded(visual_review)
    _wait_for_view(window)
    yield window
    window.close()
    app.processEvents()


@pytest.mark.parametrize(("rule", "ceiling"), [
    ("optimizer_convergence", 479),
    ("iteration_target", 377),
    ("morphospace_stability", 651),
    ("morphospace_stability_unlimited", None),
])
def test_reopened_atlas_continues_from_visual_qc(
    review_window, tmp_path, monkeypatch, rule, ceiling,
):
    from types import SimpleNamespace

    from test_reference_tolerance_continuation import _finish_source, _run_hashes

    from diffeoforge.desktop import widgets
    from diffeoforge.desktop.atlas_continuation_dialog import AtlasContinuationDialog
    from diffeoforge.desktop.completed_results import CompletedResultRun

    window = review_window
    source = _finish_source(tmp_path, monkeypatch)
    source_hashes = _run_hashes(source)
    # Supply the synthetic surface review, exercising the same signal used by the result library.
    review = replace(window._result_review, run_directory=source)
    queued = []
    failures = []
    monkeypatch.setattr(widgets.QMessageBox, "warning", lambda *args: failures.append(args[-1]))
    monkeypatch.setattr(window, "_thread_pool", SimpleNamespace(start=queued.append))
    window._open_completed_result(CompletedResultRun(source, reference=True))
    queued.pop().signals.succeeded.emit(review)
    window._convergence_advice.future.result(timeout=10)
    window._convergence_advice._poll()
    assert window._checkpoint_continuation[0] == source
    assert all(not button.isHidden() for button in window._convergence_advice.checkpoint_buttons)
    assert not window._registration_results_released()

    def choose(dialog):
        assert dialog.source.checkpoint_iteration == 211
        assert dialog.limit.text() == "1600"
        selected = "morphospace_stability" if rule == "morphospace_stability_unlimited" else rule
        dialog.rule.setCurrentIndex(dialog.rule.findData(selected))
        dialog.tolerance.setCurrentText("1e-6")
        if ceiling is None:
            dialog.unlimited.setChecked(True)
        else:
            dialog.limit.setText(str(ceiling))
        assert dialog.review.isEnabled()
        return widgets.QDialog.DialogCode.Accepted

    monkeypatch.setattr(AtlasContinuationDialog, "exec", choose)
    window.qc_checkpoint_button.click()
    assert len(queued) == 1
    worker = queued.pop()
    assert isinstance(worker, widgets._IterationExtensionWorker)
    assert "after_tolerance" not in worker.options
    assert not window.qc_checkpoint_button.isEnabled()
    worker.run()

    assert not failures
    request = window._reference_run_request
    assert request.resume_source == source
    plan = request.quality_continuation or request.tolerance_continuation
    assert plan.checkpoint_iteration == 211 and plan.maximum_iterations == ceiling
    assert window.page_stack.currentIndex() == 3
    budget = "No joint iteration limit" if ceiling is None else f"limit {ceiling}"
    assert budget in window.run_summary_label.text()
    if rule == "optimizer_convergence":
        assert plan.tolerance == 1e-6
        assert "objective at iteration 211" in window.run_boundary_label.text()
        assert "before the new limit" in window.run_boundary_label.text()
    elif rule == "iteration_target":
        assert plan.stage_mode == rule
        assert "continues to the requested iteration" in window.run_boundary_label.text()
        assert "tolerance" not in window.run_summary_label.text().split("New iteration limit")[1]
    else:
        assert "First full comparison at iteration 411" in window.run_boundary_label.text()
    assert window.start_atlas_button.text() == "Start atlas continuation"
    assert window.start_atlas_button.isEnabled()
    assert not queued and not request.destination.exists()
    assert window._checkpoint_continuation is None
    window.start_atlas_button.click()
    assert len(queued) == 1
    assert isinstance(queued[0], widgets._ReferenceAtlasWorker)
    assert queued[0].controller.request == request
    # The pool captured the dispatch. No synthetic solver process was started.
    window._worker = None
    assert _run_hashes(source) == source_hashes


def _wait_for_qt(predicate):
    """Run Qt's native loop so Python workers can acquire the GIL under load."""
    from PySide6.QtCore import QEventLoop, QTimer

    if predicate():
        return
    loop, poll, deadline = QEventLoop(), QTimer(), QTimer()
    poll.setInterval(16)
    poll.timeout.connect(lambda: loop.quit() if predicate() else None)
    deadline.setSingleShot(True)
    deadline.timeout.connect(loop.quit)
    poll.start()
    deadline.start(10_000)
    loop.exec()
    poll.stop()
    deadline.stop()
    assert predicate(), "Background Qt operation did not finish"


def _wait_for_view(window):
    def ready():
        loader = window._result_mesh_loader
        if loader._active is None and loader._pending is None:
            if window._loaded_qc_subject is None:
                return True
            canvas = window.result_registration_qc_canvas
            canvas.grab()
            return canvas.full_resolution_ready
        return False

    _wait_for_qt(ready)


def _decide(window, decision="pass"):
    _wait_for_view(window)
    window.result_qc_inspected_check.setChecked(True)
    window._record_registration_qc_decision(decision)
    _wait_for_view(window)


def test_completed_atlas_enters_visual_review_and_gates_all_result_actions(review_window):
    window = review_window
    assert window.page_stack.count() == 7
    assert window.page_stack.currentIndex() == 4
    assert window._loaded_qc_subject == "subject-1"
    assert window.result_registration_qc_canvas.original_model is not None
    assert window.result_registration_qc_canvas.reconstruction_model is not None
    assert window.result_atlas_mesh_group_combo.findData("summary") == -1
    assert not window.rail_steps[5].isEnabled()
    assert not window.create_scientific_report_button.isEnabled()
    assert not window.result_qc_pass_button.isEnabled()
    window._record_registration_qc_decision("pass")
    assert not window._registration_qc_decisions
    for action in (
        lambda: window._navigate_to_step(5), window._start_shape_space_comparison,
        window._start_reference_pca_deformations, window._create_pca_metadata,
        lambda: window._open_result_artifact("pca-scree"), window._open_run_result,
    ):
        action()
        assert window.page_stack.currentIndex() == 4
        assert window._worker is None
    _decide(window)
    assert window._loaded_qc_subject == "subject-2"
    assert not window.result_qc_inspected_check.isChecked()
    assert not window.result_qc_finalize_button.isEnabled()
    _decide(window)
    assert window.result_qc_finalize_button.isEnabled()
    assert not window.rail_steps[5].isEnabled()
    window._finalize_registration_qc_review()
    assert window.page_stack.currentIndex() == 5
    assert window.rail_steps[5].isEnabled()
    assert window.create_scientific_report_button.isEnabled()
    window._result_review_succeeded(window._result_review)
    assert window.page_stack.currentIndex() == 5


def test_failed_overlay_cannot_be_marked_using_a_stale_previous_mesh(review_window, monkeypatch):
    window = review_window
    window.result_qc_inspected_check.setChecked(True)
    def fail(*_args):
        raise ModernResultReviewError("changed specimen")
    monkeypatch.setattr("diffeoforge.desktop.result_mesh_loader.verify_result_artifact", fail)
    window.result_atlas_mesh_combo.setCurrentIndex(1)
    _wait_for_view(window)
    window.result_qc_inspected_check.setChecked(True)
    window._record_registration_qc_decision("pass")
    assert window._loaded_qc_subject is None
    assert not window.result_qc_pass_button.isEnabled()
    assert not window._registration_qc_decisions


def test_next_specimen_navigates_without_approval_and_stops_at_end(review_window):
    window = review_window
    assert window.result_next_specimen_button.isEnabled()
    window.result_qc_inspected_check.setChecked(True)
    window.result_next_specimen_button.click()
    _wait_for_view(window)
    assert window._loaded_qc_subject == "subject-2"
    assert not window.result_qc_inspected_check.isChecked()
    assert not window._registration_qc_decisions
    assert not window.result_next_specimen_button.isEnabled()
    window._show_next_registration_specimen()
    assert window.result_atlas_mesh_combo.currentIndex() == 1
    window.result_atlas_mesh_search_edit.setText("no-matching-specimen")
    assert not window.result_next_specimen_button.isEnabled()


def test_search_does_not_hide_unresolved_subject_from_release_policy(review_window):
    window = review_window
    _decide(window, "fail")
    _decide(window)
    window.result_atlas_mesh_search_edit.setText("subject-2")
    _wait_for_view(window)
    assert window.result_atlas_mesh_combo.count() == 1
    assert window.result_qc_finalize_button.isEnabled()
    assert "QC warnings" in window.result_qc_finalize_button.text()
    assert "1 implausible" in window.result_qc_warning_label.text()
    assert not window._registration_results_released()
    assert len(window._result_review.registration_qc) == 2
    window._finalize_registration_qc_review()
    assert window.page_stack.currentIndex() == 5
    assert window._registration_qc_decisions["subject-1"] == "fail"
    assert not window.result_qc_warning_label.isHidden()
    window._result_review_succeeded(window._result_review)
    assert window.page_stack.currentIndex() == 5
    assert not window.result_qc_warning_label.isHidden()
    assert window._registration_qc_decisions["subject-1"] == "fail"


def test_pending_camera_or_navigation_preview_cannot_be_approved(review_window):
    window = review_window
    canvas = window.result_registration_qc_canvas
    assert canvas.full_resolution_ready
    canvas._yaw += 0.2
    window.result_qc_inspected_check.setChecked(True)
    window._record_registration_qc_decision("pass")
    assert not window._registration_qc_decisions
    canvas._interacting = True
    canvas.grab()
    assert not canvas.full_resolution_ready
    window._record_registration_qc_decision("pass")
    assert not window._registration_qc_decisions
    canvas._interacting = False
    _wait_for_view(window)
    assert canvas.full_resolution_ready


def test_hidden_overlay_layers_cannot_be_approved(review_window):
    window = review_window
    canvas = window.result_registration_qc_canvas
    for setter in (canvas.set_show_original, canvas.set_show_reconstruction):
        setter(False)
        window.result_qc_inspected_check.setChecked(True)
        window._record_registration_qc_decision("pass")
        assert not canvas.full_resolution_ready
        assert not window._registration_qc_decisions
        setter(True)
    _wait_for_view(window)
    assert canvas.full_resolution_ready


def test_background_loader_discards_old_selection_without_blocking_ui(
    review_window, visual_review, monkeypatch
):
    import threading

    from PySide6.QtCore import QTimer
    from PySide6.QtTest import QTest

    from diffeoforge.desktop import result_mesh_loader as module

    entered, release = threading.Event(), threading.Event()
    threads, received, ticks = [], [], []
    real = module.load_mesh_preview

    def slow(path):
        threads.append(threading.get_ident())
        entered.set()
        release.wait(3)
        return real(path)

    monkeypatch.setattr(module, "load_mesh_preview", slow)
    loader = module.ResultMeshLoader()
    loader.loaded.connect(lambda _review, key, _models: received.append(key))
    timer = QTimer()
    timer.timeout.connect(lambda: ticks.append(1))
    timer.start(5)
    loader.request(visual_review, "registration-qc:subject-1")
    try:
        _wait_for_qt(entered.is_set)
        assert entered.is_set()
        for _ in range(5):
            loader.request(visual_review, "registration-qc:subject-1")
            loader.request(visual_review, "registration-qc:subject-2")
        QTest.qWait(50)
        assert len(ticks) >= 2
        assert not received
    finally:
        release.set()
        timer.stop()
    _wait_for_qt(lambda: loader._active is None and loader._pending is None)
    assert received == ["registration-qc:subject-2"]
    assert all(value != threading.get_ident() for value in threads)


def test_cached_mesh_is_reverified_and_modified_file_is_rejected(review_window):
    window = review_window
    review = window._result_review
    item = review.registration_qc_item(window._loaded_qc_subject)
    review.artifact(item.original_artifact_key).path.write_text("tampered", encoding="utf-8")
    window._load_selected_atlas_mesh(window.result_atlas_mesh_combo.currentIndex())
    _wait_for_view(window)
    assert window._loaded_qc_subject is None
    assert not window.result_qc_inspected_check.isEnabled()
    assert "verification or loading failed" in window.result_atlas_status_label.text()


def test_local_surface_check_marks_selected_pair_without_approval(review_window, monkeypatch):
    from diffeoforge.desktop import registration_surface_review as surface_review

    flag = surface_review.SurfaceFlag((0.1, 0.2, 0.3), "Original surface missed", 0.02, 8)
    monkeypatch.setattr(surface_review, "screen_surface_misses", lambda *args, **kwargs: (flag,))
    window = review_window
    panel = window.result_registration_surface_review
    assert panel.button.isEnabled()
    panel.button.click()
    _wait_for_qt(lambda: panel._worker is None)
    assert panel.canvas._inspection_markers == {"1": flag.center}
    assert "Original surface missed" in panel.status.text()
    assert not window._registration_qc_decisions
    assert not window.result_qc_inspected_check.isChecked()

    active = window._result_review
    subject = active.registration_qc_item(window._loaded_qc_subject)
    active.artifact(subject.original_artifact_key).path.write_text("changed", encoding="ascii")
    panel.button.click()
    _wait_for_qt(lambda: panel._worker is None)
    assert not panel.canvas._inspection_markers
    assert "unavailable" in panel.status.text()


def test_local_surface_check_cannot_mark_a_different_selected_pair(review_window, monkeypatch):
    import threading

    from diffeoforge.desktop import registration_surface_review as surface_review

    entered, release = threading.Event(), threading.Event()
    flag = surface_review.SurfaceFlag((0.1, 0.2, 0.3), "Original surface missed", 0.02, 8)

    def delayed_check(*args, **kwargs):
        entered.set()
        release.wait(5)
        return (flag,)

    monkeypatch.setattr(surface_review, "screen_surface_misses", delayed_check)
    window = review_window
    panel = window.result_registration_surface_review
    panel.button.click()
    try:
        _wait_for_qt(entered.is_set)
        old_subject = window._loaded_qc_subject
        window.result_atlas_mesh_combo.setCurrentIndex(1)
        _wait_for_view(window)
        assert window._loaded_qc_subject != old_subject
    finally:
        release.set()
    _wait_for_qt(lambda: panel._worker is None)
    assert not panel.canvas._inspection_markers
    assert not window._registration_qc_decisions
    assert panel.button.isEnabled()


def test_mesh_changed_after_display_cannot_be_approved(review_window):
    window = review_window
    item = window._result_review.registration_qc_item(window._loaded_qc_subject)
    path = window._result_review.artifact(item.original_artifact_key).path
    path.write_text("changed after display", encoding="utf-8")
    _decide(window)
    assert not window._registration_qc_decisions
    assert not window._registration_visual_inspections
    assert "Nothing changed" in window.result_qc_last_action_label.text()


def test_edit_after_release_relocks_navigation_and_exports(review_window):
    window = review_window
    _decide(window)
    _decide(window)
    window._finalize_registration_qc_review()
    window._navigate_to_step(4)
    _decide(window, "uncertain")
    assert not window.rail_steps[5].isEnabled()
    assert not window.create_shape_space_comparison_button.isEnabled()
    assert not window.create_scientific_report_button.isEnabled()
    assert not window._registration_results_released()


def _with_residuals(review, values):
    items = tuple(
        replace(
            review.registration_qc[index % len(review.registration_qc)],
            rank=index + 1, subject_name=f"subject-{index + 1}", residual_p95=float(value),
        )
        for index, value in enumerate(values)
    )
    return replace(review, registration_qc=items)


@pytest.fixture
def flagged_review(visual_review):
    return _with_residuals(visual_review, [10, 1, 1, 1, 1, 1, 1, 1])


@pytest.fixture
def flagged_window(monkeypatch, flagged_review):
    yield from review_window.__wrapped__(monkeypatch, flagged_review)


def test_screen_uses_report_rule_and_explains_flagged_case(flagged_review):
    from diffeoforge.scientific_report import _inspection_threshold

    plan = registration_inspection_plan(flagged_review)
    assert plan["threshold"] == 1
    assert set(plan["flagged_subjects"]) == {"subject-1"}
    assert "exceeds" in plan["flagged_subjects"]["subject-1"]
    assert _inspection_threshold((0, 1, 2, 3)) == inspection_threshold((0, 1, 2, 3)) == 4.5
    assert inspection_threshold((1, 1, 1, 1)) == 1


def test_optional_specimens_cannot_be_auto_passed(flagged_review):
    decisions = {"subject-1": "pass", "subject-2": "pass"}
    inspections = {"subject-1": inspection_binding(flagged_review, "subject-1")}
    with pytest.raises(ModernResultReviewError, match="without inspection"):
        release_registration_results(flagged_review, decisions, inspections)


def test_legacy_unacknowledged_passes_do_not_force_optional_review(flagged_window):
    window = flagged_window
    review = window._result_review
    decisions = {item.subject_name: "pass" for item in review.registration_qc}
    save_registration_qc_draft(review, decisions)
    window._result_review_succeeded(review)
    assert window._registration_qc_decisions == {}
    assert window.result_atlas_mesh_combo.count() == 1
    _decide(window)
    window._finalize_registration_qc_review()
    assert window._registration_results_released()
    final = load_finalized_registration_qc_review(review)
    assert list(final.decisions.values()).count("unreviewed") == 7


def test_only_flagged_case_is_required_and_others_stay_unreviewed(flagged_window):
    window = flagged_window
    review = window._result_review
    assert window.result_atlas_mesh_group_combo.currentData() == "flagged"
    assert window.result_atlas_mesh_combo.count() == 1
    assert window._loaded_qc_subject == "subject-1"
    assert "exceeds" in window.result_atlas_status_label.text()
    _decide(window)
    assert window._loaded_qc_subject == "subject-1"
    assert window._registration_qc_decisions == {"subject-1": "pass"}
    assert window.result_qc_finalize_button.isEnabled()
    window._finalize_registration_qc_review()
    assert window.page_stack.currentIndex() == 5
    final = load_finalized_registration_qc_review(review)
    assert not final.complete  # Full-cohort manual review was not claimed.
    assert final.decisions["subject-1"] == "pass"
    assert list(final.decisions.values()).count("unreviewed") == 7
    payload = json.loads(final.path.read_text(encoding="utf-8"))
    assert payload["visual_review_scope"]["required_review_complete"] is True
    assert payload["visual_review_scope"]["required_subjects"] == ["subject-1"]
    assert len(payload["visual_review_scope"]["unreviewed_subjects"]) == 7
    window._result_review_succeeded(review)
    assert window.page_stack.currentIndex() == 5
    assert "7 specimens not visually reviewed" in window.registration_release_status_label.text()


def test_no_flags_needs_no_mesh_approval_but_still_requires_explicit_release(
    monkeypatch, visual_review,
):
    review = _with_residuals(visual_review, [100, 100, 100, 100, 100, 100])
    context = review_window.__wrapped__(monkeypatch, review)
    window = next(context)
    try:
        assert window.page_stack.currentIndex() == 4
        assert window.result_atlas_mesh_combo.count() == 0
        assert window._loaded_qc_subject is None
        assert window.result_qc_finalize_button.isEnabled()
        assert not window._registration_results_released()
        assert "no flagged cases" in window.result_qc_finalize_button.text()
        window._finalize_registration_qc_review()
        assert window._registration_results_released()
        assert window._registration_qc_decisions == {}
        assert window._registration_visual_inspections == {}
        final = load_finalized_registration_qc_review(review)
        assert set(final.decisions.values()) == {"unreviewed"}
    finally:
        context.close()


def test_optional_concern_becomes_required_and_cannot_be_hidden(flagged_window):
    window = flagged_window
    _decide(window)
    all_group = window.result_atlas_mesh_group_combo.findData("specimens")
    window.result_atlas_mesh_group_combo.setCurrentIndex(all_group)
    window.result_atlas_mesh_combo.setCurrentIndex(1)
    _decide(window, "uncertain")
    assert set(required_registration_inspections(
        window._result_review, window._registration_qc_decisions
    )) == {"subject-1", "subject-2"}
    assert window.result_qc_finalize_button.isEnabled()
    assert "1 uncertain" in window.result_qc_warning_label.text()
    flagged_group = window.result_atlas_mesh_group_combo.findData("flagged")
    assert window.result_atlas_mesh_group_combo.itemText(flagged_group) == "Required review (2)"
    window.result_atlas_mesh_group_combo.setCurrentIndex(flagged_group)
    window.result_atlas_mesh_search_edit.setText("subject-2")
    _wait_for_view(window)
    assert window.result_atlas_mesh_combo.count() == 1
    assert "Researcher decision is uncertain" in window.result_atlas_status_label.text()
    _decide(window)
    assert window.result_qc_finalize_button.isEnabled()
    assert len(window._registration_qc_decisions) == 2


def test_search_outside_flags_cannot_bypass_required_case(flagged_window):
    flagged_window.result_atlas_mesh_search_edit.setText("subject-8")
    assert flagged_window.result_atlas_mesh_combo.count() == 0
    assert not flagged_window.result_qc_finalize_button.isEnabled()
    assert not flagged_window._registration_results_released()


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1])
def test_invalid_residuals_cannot_produce_an_empty_pass_queue(visual_review, value):
    review = _with_residuals(visual_review, [value, 1, 1, 1])
    with pytest.raises(ModernResultReviewError, match="finite"):
        registration_inspection_plan(review)


def test_changed_screening_evidence_requires_new_release(flagged_review):
    decisions = {"subject-1": "pass"}
    inspections = {"subject-1": inspection_binding(flagged_review, "subject-1")}
    release_registration_results(flagged_review, decisions, inspections)
    changed = _with_residuals(flagged_review, [11, 1, 1, 1, 1, 1, 1, 1])
    with pytest.raises(ModernResultReviewError, match="no longer matches"):
        require_registration_release(changed, decisions, inspections)


@pytest.mark.parametrize("scope", [None, [], "invalid"])
def test_malformed_release_scope_is_rejected(flagged_review, scope):
    decisions = {"subject-1": "pass"}
    inspections = {"subject-1": inspection_binding(flagged_review, "subject-1")}
    release_registration_results(flagged_review, decisions, inspections)
    path = registration_qc_directory(flagged_review) / RELEASE_NAME
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["visual_review_scope"] = scope
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ModernResultReviewError):
        require_registration_release(flagged_review, decisions, inspections)


def test_valid_legacy_approval_release_still_opens(visual_review):
    from diffeoforge.desktop.registration_release import LEGACY_POLICY, _visual_review_scope

    decisions, inspections = _approvals(visual_review)
    release_registration_results(visual_review, decisions, inspections)
    path = registration_qc_directory(visual_review) / RELEASE_NAME
    payload = json.loads(path.read_text(encoding="utf-8"))
    scope = _visual_review_scope(visual_review, decisions, inspections, policy=LEGACY_POLICY)
    final = finalize_registration_qc_review(
        visual_review, decisions, allow_incomplete=True, visual_review_scope=scope
    )
    payload.update(schema_version="0.2", policy=LEGACY_POLICY, visual_review_scope=scope,
                   finalized_review_sha256=final.sha256)
    path.write_text(json.dumps(payload), encoding="utf-8")
    require_registration_release(visual_review, decisions, inspections)


def test_cannot_relabel_concerns_as_all_plausible(visual_review):
    decisions, inspections = _approvals(visual_review)
    decisions["subject-2"] = "fail"
    release_registration_results(visual_review, decisions, inspections)
    path = registration_qc_directory(visual_review) / RELEASE_NAME
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["visual_review_scope"]["all_required_plausible"] = True
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ModernResultReviewError):
        require_registration_release(visual_review, decisions, inspections)


def test_disabled_ratings_explain_inspection_requirement(review_window):
    window = review_window
    assert not window.result_qc_fail_button.isEnabled()
    assert "confirm below" in window.result_qc_decision_hint.text()
    window.result_qc_inspected_check.setChecked(True)
    assert window.result_qc_fail_button.isEnabled()
    assert "implausible" in window.result_qc_decision_hint.text()


def test_approved_early_atlas_verifies_resume_outside_gui_callback(review_window, monkeypatch):
    from types import SimpleNamespace

    import diffeoforge.desktop.widgets as widgets

    window = review_window
    result = SimpleNamespace(run_directory=window._result_review.run_directory)
    queued, verified, shown = [], [], []
    request = object()
    monkeypatch.setattr(window, "_thread_pool", SimpleNamespace(start=queued.append))
    monkeypatch.setattr(window, "_show_reference_resume", lambda *values: shown.append(values))
    monkeypatch.setattr(
        widgets, "build_reference_resume_launch_request",
        lambda source, **kwargs: verified.append(source) or request,
    )
    window._approved_early_review_run = result.run_directory
    window._prepare_reference_resume(result)
    assert not verified and not shown
    assert len(queued) == 1
    queued[0].run()
    assert verified == [result.run_directory]
    assert shown == [(request, result)]
    assert window._worker is None


@pytest.mark.parametrize("decision", ["continue", "review", "cancel"])
def test_optional_early_atlas_choice_queues_only_explicit_continuation(
    review_window, monkeypatch, decision
):
    from types import SimpleNamespace

    import diffeoforge.desktop.widgets as widgets
    from diffeoforge.reference_atlas_handoff import EARLY_CHECK

    window = review_window
    assert not window.early_atlas_review_check.isChecked()
    assert not window.initial_fit_review_check.isChecked()
    run = window._result_review.run_directory
    (run / "output").mkdir(exist_ok=True)
    (run / "output" / EARLY_CHECK).write_text("{}", encoding="utf-8")
    result = SimpleNamespace(run_directory=run)
    queued, reviewed, choices = [], [], []
    monkeypatch.setattr(window, "_thread_pool", SimpleNamespace(start=queued.append))
    monkeypatch.setattr(window, "_optional_early_atlas_decision", lambda: decision)
    monkeypatch.setattr(window, "_open_early_atlas_check", reviewed.append)
    monkeypatch.setattr(window, "_show_reference_resume", lambda *_: None)
    monkeypatch.setattr(
        widgets, "build_reference_resume_launch_request", lambda *_a, **_k: object()
    )
    monkeypatch.setattr("diffeoforge.reference_atlas_handoff.record_early_review_choice",
                        lambda path, **kw: choices.append((path, kw)))
    window._prepare_reference_resume(result)
    assert bool(queued) is (decision == "continue")
    assert reviewed == ([run] if decision == "review" else [])
    assert not choices
    if queued:
        queued[0].run()
        assert choices == [(run, {"enabled": False})]


def test_starting_fit_checkbox_is_bound_when_preparing_the_atlas(review_window, monkeypatch):
    from types import SimpleNamespace

    window = review_window
    config_path = window._result_review.run_directory / "saved-pilot.yaml"
    monkeypatch.setattr(window, "_reference_calibrated_config_path", config_path)
    queued = []
    monkeypatch.setattr(window, "_thread_pool", SimpleNamespace(start=queued.append))
    for checked in (False, True):
        assert not window.initial_fit_review_check.isChecked()
        window.initial_fit_review_check.setChecked(checked)
        window._prepare_preserved_atlas()
        worker = queued[-1]
        assert worker.config_path == config_path
        assert worker.initial_fit_review is checked
        assert worker.early_review is False
        assert worker.direct_start is False
        window._worker = None
    assert len(queued) == 2


def test_direct_pilot_option_requires_review_before_launch(review_window, monkeypatch):
    from dataclasses import replace
    from types import SimpleNamespace

    window = review_window
    review = window._review
    if review is None:
        from diffeoforge.desktop.project_review import ProjectReviewResult
        from diffeoforge.desktop.project_setup import DesktopEngine

        path = window._result_review.run_directory / "saved-pilot.yaml"
        review = ProjectReviewResult(
            DesktopEngine.DEFORMETRICA_REFERENCE, "Pilot study", path, "a" * 64,
            path.with_suffix(".html"), "Report", 7, (), (), (), "",
        )
    review = replace(review, preserved_pilot_atlas=True)
    window._review_succeeded(review)
    window._reference_readiness = SimpleNamespace(ready=True)
    window._run_result = None
    window._result_review = None
    queued = []
    monkeypatch.setattr(window, "_thread_pool", SimpleNamespace(start=queued.append))
    window._sync_ready_state()

    assert not window.pilot_atlas_start_card.isHidden()
    assert window.pilot_atlas_start_combo.currentData() is False
    assert "fixed pilot template" in window.pilot_atlas_start_detail.text()
    assert window._step_is_unlocked(3)
    window.initial_fit_review_check.setChecked(True)
    window.early_atlas_review_check.setChecked(True)
    window.pilot_atlas_start_combo.setCurrentIndex(1)

    assert "undeformed pilot template" in window.pilot_atlas_start_detail.text()
    assert window.initial_fit_review_check.isHidden()
    assert window.early_atlas_review_check.isHidden()
    assert window.show_run_button.text() == "Review selected atlas start"
    assert not window._step_is_unlocked(3)
    window._start_atlas()
    assert not queued
    window._show_run_page()
    window._show_run_page()

    assert len(queued) == 1
    handoff = queued[0]
    assert handoff.config_path == review.config_path
    assert handoff.direct_start is True
    assert handoff.initial_fit_review is False and handoff.early_review is False

    window._review_succeeded(replace(
        review, direct_pilot_atlas=True, pilot_initial_fit_review=True, pilot_early_review=True,
    ))
    assert window.pilot_atlas_start_combo.currentData() is True
    assert not window._pilot_atlas_start_pending()
    window.pilot_atlas_start_combo.setCurrentIndex(0)
    assert window.initial_fit_review_check.isChecked()
    assert window.early_atlas_review_check.isChecked()
    window._review_succeeded(replace(review, preserved_pilot_atlas=False))
    monkeypatch.setattr(window, "_reference_calibrated_config_path", review.config_path)
    window._reference_readiness = SimpleNamespace(ready=True)
    window._sync_ready_state()
    assert window.pilot_atlas_start_combo.currentData() is False
    assert window._pilot_atlas_start_pending()
    window._show_run_page()
    assert len(queued) == 2
    assert queued[-1].direct_start is False
    assert queued[-1].config_path == review.config_path


@pytest.mark.parametrize("direct", [False, True])
@pytest.mark.parametrize("mode", [
    "diffeoforge_tolerance", "deformetrica_tolerance", "optimizer_convergence",
    "morphospace_stability", "morphospace_stability_unlimited", "iteration_target",
])
def test_atlas_review_dispatches_two_independent_choices(review_window, monkeypatch, direct, mode):
    from types import SimpleNamespace

    from diffeoforge.desktop.project_review import ProjectReviewResult
    from diffeoforge.desktop.project_setup import DesktopEngine

    window = review_window
    path = window._result_review.run_directory / "saved-pilot.yaml"
    review = ProjectReviewResult(
        DesktopEngine.DEFORMETRICA_REFERENCE, "Synthetic atlas", path, "a" * 64,
        path.with_suffix(".html"), "Report", 7, (), (), (), "",
        preserved_pilot_atlas=True, atlas_stop_available=True,
        atlas_project_tolerance=3e-5 if mode == "optimizer_convergence" else 1e-4,
    )
    window._review_succeeded(review)
    initial = mode if mode == "optimizer_convergence" else "diffeoforge_tolerance"
    assert window.atlas_stop_combo.currentData() == initial
    window._reference_readiness = SimpleNamespace(ready=True)
    window._run_result = None
    window._result_review = None
    queued = []
    monkeypatch.setattr(window, "_thread_pool", SimpleNamespace(start=queued.append))
    window.pilot_atlas_start_combo.setCurrentIndex(int(direct))
    window.atlas_stop_combo.setCurrentIndex(window.atlas_stop_combo.findData(mode))
    window._sync_ready_state()
    assert not window.atlas_stop_card.isHidden()
    if mode == "morphospace_stability_unlimited":
        assert "no iteration limit" in window.atlas_stop_detail.text()
    assert window._pilot_atlas_start_pending()
    window._show_run_page()
    assert len(queued) == 1
    assert queued[0].direct_start is direct
    assert queued[0].stop_mode == mode
    window._review_succeeded(replace(review, direct_pilot_atlas=direct, atlas_stop_mode=mode))
    assert window.pilot_atlas_start_combo.currentData() is direct
    assert window.atlas_stop_combo.currentData() == mode
    assert not window._pilot_atlas_start_pending()


@pytest.mark.parametrize("preserved_pilot", [False, True])
@pytest.mark.parametrize("mode", ["deformetrica_tolerance", "diffeoforge_tolerance",
                                  "morphospace_stability", "morphospace_stability_unlimited"])
def test_atlas_choices_recheck_stays_on_review_page(
    review_window, monkeypatch, preserved_pilot, mode
):
    from types import SimpleNamespace

    from diffeoforge.desktop import widgets
    from diffeoforge.desktop.project_review import ProjectReviewResult
    from diffeoforge.desktop.project_setup import DesktopEngine, ProjectSetupResult

    window = review_window
    directory = window._result_review.run_directory
    path = directory / "atlas.yaml"
    linked = directory / f"atlas-stop-{mode}.yaml"
    engine = DesktopEngine.DEFORMETRICA_REFERENCE
    review = ProjectReviewResult(
        engine, "Synthetic atlas", path, "a" * 64, path.with_suffix(".html"), "Report",
        2, (), (), (), "",
        preserved_pilot_atlas=preserved_pilot, direct_pilot_atlas=preserved_pilot,
        atlas_stop_available=True,
    )
    linked_review = replace(
        review, config_path=linked, config_sha256="b" * 64, atlas_stop_mode=mode,
    )
    linked_setup = ProjectSetupResult(engine, linked, directory / "template.vtk", 2, None, ())
    readiness = SimpleNamespace(
        ready=True, config_path=linked, config_sha256=linked_review.config_sha256,
        workspace=directory, launcher={"type": "container", "engine": "docker", "image": "test"},
        device="cpu", report=SimpleNamespace(status="ready", checks=()),
    )
    queued = []
    refreshes = []
    monkeypatch.setattr(window, "_thread_pool", SimpleNamespace(start=queued.append))
    monkeypatch.setattr(window, "_apply_reference_calibrated_configuration", lambda _path: None)
    monkeypatch.setattr(widgets, "review_project", lambda _path, _engine: linked_review)
    monkeypatch.setattr(widgets, "check_reference_environment", lambda _review: readiness)
    monkeypatch.setattr(window, "_refresh_run_readiness", lambda: refreshes.append(True))
    window._run_result = None
    window._result_review = None
    window._review_succeeded(review)
    assert window.page_stack.currentIndex() == 1
    window._reference_readiness = SimpleNamespace(ready=True)
    window._sync_ready_state()
    window._navigate_to_step(2)
    window.atlas_stop_combo.setCurrentIndex(window.atlas_stop_combo.findData(mode))

    window.show_run_button.click()
    assert len(queued) == 1
    handoff = queued[0]
    assert handoff.config_path == path and handoff.stop_mode == mode
    handoff.signals.succeeded.emit(linked_setup)
    assert len(queued) == 2
    queued[1].run()
    assert len(queued) == 3
    assert window._review is linked_review
    assert window._active_step == window.page_stack.currentIndex() == 2
    assert window.atlas_stop_combo.currentData() == mode
    assert not window.show_run_button.isEnabled()
    assert not window._step_is_unlocked(3)

    queued[2].run()
    assert window._active_step == window.page_stack.currentIndex() == 2
    assert window.show_run_button.text() == "Continue to supervised Deformetrica execution"
    assert window.show_run_button.isEnabled()
    assert not refreshes
    window.show_run_button.click()
    assert window.page_stack.currentIndex() == 3
    assert refreshes == [True] and len(queued) == 3
