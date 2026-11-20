"""Desktop result handoffs on complete, synthetic Deformetrica run evidence."""

from dataclasses import replace

import pytest
from test_reference_pca import _completed_reference_run

from diffeoforge.desktop import reference_result_review as results
from diffeoforge.desktop.registration_release import (
    inspection_binding,
    release_registration_results,
    require_registration_release,
    required_registration_inspections,
)
from diffeoforge.desktop.result_review import ModernResultReviewError
from diffeoforge.mesh import sha256_file
from diffeoforge.reference_pca import (
    DEFAULT_REFERENCE_PCA_DIRECTORY,
    load_reference_momenta,
    verify_reference_pca_bundle,
)


@pytest.fixture
def atlas(tmp_path, monkeypatch):
    run = _completed_reference_run(tmp_path, three_components=True)
    inputs = load_reference_momenta(run)
    collect = results._collect_reference_calibration_metrics_from_report
    residuals = dict.fromkeys(inputs.subject_labels, 1.0)

    def metrics(*args, **kwargs):
        return replace(collect(*args, **kwargs), subject_residual_p95=tuple(residuals.items()))

    monkeypatch.setattr(results, "_collect_reference_calibration_metrics_from_report", metrics)
    return inputs, residuals


def _finish(review, decisions):
    inspections = {name: inspection_binding(review, name) for name in decisions}
    results.save_registration_qc_draft(review, decisions, visual_inspections=inspections)
    release_registration_results(review, decisions, inspections)


def test_no_flags_publishes_pca_automatically_and_never_grants_anatomical_approval(atlas):
    inputs, _ = atlas
    run = inputs.run_directory
    review = results.review_desktop_reference_result(run)
    assert not review.pca_pending
    assert not (run / DEFAULT_REFERENCE_PCA_DIRECTORY).exists()
    result = verify_reference_pca_bundle(review.bundle_directory, source_run=run)
    assert result.pca.sample_labels == inputs.subject_labels
    finalized = results.load_finalized_registration_qc_review(review)
    assert finalized is not None and not finalized.complete
    assert set(finalized.decisions.values()) == {"unreviewed"}
    reopened = results.review_current_reference_result(run)
    assert reopened.bundle_directory == review.bundle_directory


def test_flagged_case_waits_then_excludes_only_implausible_from_pca(atlas):
    inputs, residuals = atlas
    first, second, *_ = inputs.subject_labels
    residuals[first] = 100.0
    run = inputs.run_directory
    pending = results.review_desktop_reference_result(run)
    assert pending.pca_pending
    assert set(required_registration_inspections(pending, {})) == {first}
    assert not (run / DEFAULT_REFERENCE_PCA_DIRECTORY).exists()
    assert not list(run.glob("analysis/reference-pca-*"))
    with pytest.raises(ModernResultReviewError, match="inspect each required"):
        results.review_current_reference_result(run)

    decisions = {first: "fail", second: "uncertain"}
    _finish(pending, decisions)
    ready = results.review_desktop_reference_result(run)
    selected = verify_reference_pca_bundle(ready.bundle_directory, source_run=run)
    assert len(ready.registration_qc) == len(inputs.subject_labels)
    assert selected.pca.sample_labels == inputs.subject_labels[1:]
    assert ready.pca_excluded_subjects == (first,)
    assert selected.manifest["qc_cohort"]["decisions"] == decisions

    original_hash = sha256_file(ready.bundle_manifest_path)
    previous_inspections = {name: inspection_binding(ready, name) for name in decisions}
    results.save_registration_qc_draft(
        ready, {first: "pass", second: "uncertain"}, visual_inspections=previous_inspections,
    )
    with pytest.raises(ModernResultReviewError, match="saved visual decisions changed"):
        require_registration_release(ready, decisions, previous_inspections)
    _finish(ready, {first: "pass", second: "uncertain"})
    with pytest.raises(ModernResultReviewError, match="prepare its PCA"):
        results.review_current_reference_result(run)
    revised = results.review_desktop_reference_result(run)
    assert not revised.pca_excluded_subjects
    assert revised.bundle_directory != ready.bundle_directory
    assert sha256_file(ready.bundle_manifest_path) == original_hash


def test_review_with_fewer_than_two_included_stays_available_without_pca(atlas):
    inputs, residuals = atlas
    residuals[inputs.subject_labels[0]] = 100.0
    run = inputs.run_directory
    pending = results.review_desktop_reference_result(run)
    _finish(pending, dict.fromkeys(inputs.subject_labels[:-1], "fail"))
    pending = results.review_desktop_reference_result(run)
    assert pending.pca_pending
    assert len(pending.registration_qc) == len(inputs.subject_labels)
    assert "needs two included specimens" in pending.pca_blocked_reason
    assert not list(run.glob("analysis/reference-pca-*"))


def test_legacy_unacknowledged_optional_pass_does_not_block_empty_flag_queue(atlas):
    inputs, _ = atlas
    legacy = results.review_reference_result(inputs.run_directory)
    subject = inputs.subject_labels[0]
    draft = results.save_registration_qc_draft(legacy, {subject: "pass"})
    old_draft = draft.read_bytes()
    review = results.review_desktop_reference_result(inputs.run_directory)
    assert not review.pca_pending
    assert draft.read_bytes() == old_draft
    assert results.load_finalized_registration_qc_review(review).decisions[subject] == "unreviewed"

    marker = inputs.run_directory / "reviews/registration-qc-pca-workflow.json"
    marker.unlink()
    with pytest.raises(ModernResultReviewError, match="lacks its visual-review workflow"):
        results.review_current_reference_result(inputs.run_directory)


def test_desktop_finish_button_moves_from_required_review_to_filtered_morphospace(
    atlas, monkeypatch, tmp_path,
):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    from diffeoforge.desktop.widgets import DiffeoForgeWindow

    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("DIFFEOFORGE_STATE_HOME", str(tmp_path / "state"))
    app = QApplication.instance() or QApplication(["postqc-test"])
    inputs, residuals = atlas
    first = inputs.subject_labels[0]
    residuals[first] = 100.0
    pending = results.review_desktop_reference_result(inputs.run_directory)
    window = DiffeoForgeWindow()
    monkeypatch.setattr(window, "_sync_reference_pca_deformation_action", lambda _: None)
    monkeypatch.setattr(window, "_populate_atlas_viewer", lambda _: None)
    monkeypatch.setattr(window, "_dispatch_result_review", lambda worker, _: worker.run())
    try:
        window._result_review_succeeded(pending)
        assert window.page_stack.currentIndex() == 4
        assert not window.result_qc_finalize_button.isEnabled()

        decisions = {first: "fail"}
        inspections = {first: inspection_binding(pending, first)}
        results.save_registration_qc_draft(pending, decisions, visual_inspections=inspections)
        window._registration_qc_decisions = decisions
        window._registration_visual_inspections = inspections
        window._update_registration_qc_summary()
        assert window.result_qc_finalize_button.isEnabled()
        assert "compute PCA" in window.result_qc_finalize_button.text()
        window.result_qc_finalize_button.click()
        assert window.page_stack.currentIndex() == 5
        assert window._result_review.pca_excluded_subjects == (first,)
        assert window._registration_results_released()
        assert window.result_pc1_pc2_plot.renderer().isValid()
    finally:
        window.close()
        app.processEvents()
