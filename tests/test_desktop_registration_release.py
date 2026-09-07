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


@pytest.mark.parametrize("decision", [None, "uncertain", "fail"])
def test_unresolved_registration_cannot_release_or_exclude(visual_review, decision):
    decisions, inspections = _approvals(visual_review)
    if decision is None:
        decisions.pop("subject-2")
    else:
        decisions["subject-2"] = decision
    with pytest.raises(ModernResultReviewError, match="Results remain locked"):
        release_registration_results(visual_review, decisions, inspections)
    assert not (registration_qc_directory(visual_review) / RELEASE_NAME).exists()
    assert len(visual_review.registration_qc) == 2


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
    yield window
    window.close()
    app.processEvents()


def _decide(window, decision="pass"):
    window.result_qc_inspected_check.setChecked(True)
    window._record_registration_qc_decision(decision)


def test_completed_atlas_enters_visual_review_and_gates_all_result_actions(review_window):
    window = review_window
    assert window.page_stack.count() == 6
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
    monkeypatch.setattr("diffeoforge.desktop.widgets.verify_result_artifact", fail)
    window.result_atlas_mesh_combo.setCurrentIndex(1)
    window.result_qc_inspected_check.setChecked(True)
    window._record_registration_qc_decision("pass")
    assert window._loaded_qc_subject is None
    assert not window.result_qc_pass_button.isEnabled()
    assert not window._registration_qc_decisions


def test_search_does_not_hide_unresolved_subject_from_release_policy(review_window):
    window = review_window
    _decide(window, "fail")
    _decide(window)
    window.result_atlas_mesh_search_edit.setText("subject-2")
    assert window.result_atlas_mesh_combo.count() == 1
    assert not window.result_qc_finalize_button.isEnabled()
    assert not window._registration_results_released()
    assert len(window._result_review.registration_qc) == 2


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
    assert not window.result_qc_finalize_button.isEnabled()
    flagged_group = window.result_atlas_mesh_group_combo.findData("flagged")
    assert window.result_atlas_mesh_group_combo.itemText(flagged_group) == "Required review (2)"
    window.result_atlas_mesh_group_combo.setCurrentIndex(flagged_group)
    window.result_atlas_mesh_search_edit.setText("subject-2")
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
