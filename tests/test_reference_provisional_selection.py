"""Synthetic evidence only; no engine or private dataset is used."""
import copy
from dataclasses import replace

import pytest
from test_reference_calibration_study import _afk_runner, _approve_for_test

from diffeoforge import reference_calibration_study as study
from diffeoforge.config import load_config
from diffeoforge.reference_stage_retention import keep_previous_fit, verify_reference


def _capped(tmp_path, monkeypatch, **changes):
    runner = _afk_runner(tmp_path, monkeypatch)
    original = study.collect_reference_calibration_run_metrics
    monkeypatch.setattr(study, "collect_reference_calibration_run_metrics", lambda run: replace(
        original(run), converged=False, optimizer_stop_signal="maximum_iterations",
        final_iteration=50, **changes,
    ))
    snapshot = runner.run_current_stage()
    return runner, snapshot, snapshot.candidates[0]


def _choose(snapshot, candidate):
    return study.record_reference_calibration_iteration_limit_selection(
        snapshot.study_directory, selected_candidate_id=candidate.candidate_id,
    )


def test_explicit_capped_choice_preserves_fit_qc_and_ineligibility(tmp_path, monkeypatch):
    _, snapshot, candidate = _capped(tmp_path, monkeypatch)
    original_metrics = dict(candidate.metrics)
    receipts = {p: p.read_bytes() for p in candidate.run_directory.iterdir() if p.is_file()}
    with pytest.raises(study.ReferenceCalibrationStudyError, match="recorded visual QC"):
        _choose(snapshot, candidate)
    _approve_for_test(snapshot.study_directory, candidate.candidate_id)
    with pytest.raises(study.ReferenceCalibrationStudyError, match="not eligible"):
        study.record_reference_calibration_stage_review(
            snapshot.study_directory, selected_candidate_id=candidate.candidate_id,
            visual_approvals={candidate.candidate_id: True},
        )
    second, assessment = _choose(snapshot, candidate)
    assert second.current_stage.order == 2
    assert not assessment.candidates[0].eligible
    assert assessment.balanced_candidate_id is None and not assessment.automatic_selection_allowed
    baseline = second.candidates[-1]
    assert baseline.metrics == original_metrics and not baseline.metrics["converged"]
    assert study.calibration_candidate_run_directory(baseline) == candidate.run_directory
    assert second.visual_reviews[baseline.candidate_id] is True
    assert all(p.read_bytes() == content for p, content in receipts.items())
    event = next(e for e in study._load_events(second.study_directory)
                 if e["event"] == "stage_selected")
    assert event["selection_mode"] == "researcher_iteration_limit_provisional"
    assert (
        event["iteration_limit_provisional"]["binding"]
        == study._candidate_review_binding(candidate)
    )
    assert study.load_reference_calibration_study(second.study_directory).current_stage.order == 2


@pytest.mark.parametrize("changes", [
    {"invalid_face_count": 1}, {"subject_reconstruction_count": 2},
    {"subject_residual_p95": ()}, {"residual_p95": -1},
])
def test_other_failures_cannot_be_bypassed(tmp_path, monkeypatch, changes):
    _, snapshot, candidate = _capped(tmp_path, monkeypatch, **changes)
    _approve_for_test(snapshot.study_directory, candidate.candidate_id)
    with pytest.raises(study.ReferenceCalibrationStudyError, match="Provisional selection"):
        _choose(snapshot, candidate)


@pytest.mark.parametrize("changes", [
    {"fit_scope": "screening"}, {"optimizer_stop_signal": "unknown"},
    {"maximum_iterations": 51}, {"final_iteration": None},
    {"invalid_face_count": False}, {"subject_reconstruction_count": True},
])
def test_ui_predicate_rejects_incomplete_or_wrong_stop_evidence(tmp_path, monkeypatch, changes):
    _, snapshot, candidate = _capped(tmp_path, monkeypatch)
    bad = replace(candidate, metrics={**candidate.metrics, **changes})
    altered = replace(snapshot, candidates=(bad, *snapshot.candidates[1:]))
    assert not study.iteration_limit_selection_available(altered, candidate.candidate_id)
    probe = replace(snapshot, plan=replace(snapshot.plan, execution_scope="single_specimen_probe"))
    assert not study.iteration_limit_selection_available(probe, candidate.candidate_id)


def test_retention_carries_warning_but_stage4_stays_strict(tmp_path, monkeypatch):
    runner, snapshot, candidate = _capped(tmp_path, monkeypatch)
    _approve_for_test(snapshot.study_directory, candidate.candidate_id)
    second, _ = _choose(snapshot, candidate)
    trial_directories = set(second.study_directory.rglob("pilot-attempt-*"))
    third = keep_previous_fit(second.study_directory)
    fourth = keep_previous_fit(third.study_directory)
    assert fourth.current_stage.order == 4
    assert set(second.study_directory.rglob("pilot-attempt-*")) == trial_directories
    fourth = runner.run_current_stage()
    cid = fourth.candidates[0].candidate_id
    _approve_for_test(fourth.study_directory, cid)
    with pytest.raises(study.ReferenceCalibrationStudyError, match="Provisional selection"):
        study.record_reference_calibration_iteration_limit_selection(
            fourth.study_directory, selected_candidate_id=cid,
        )
    with pytest.raises(study.ReferenceCalibrationStudyError, match="not eligible"):
        study.record_reference_calibration_stage_review(
            fourth.study_directory, selected_candidate_id=cid, visual_approvals={},
        )


def test_completed_report_discloses_capped_stages_and_no_pilot_field(tmp_path, monkeypatch):
    runner, snapshot, candidate = _capped(tmp_path, monkeypatch)
    _approve_for_test(snapshot.study_directory, candidate.candidate_id)
    second, _ = _choose(snapshot, candidate)
    third = keep_previous_fit(second.study_directory)
    keep_previous_fit(third.study_directory)
    # Calculate a separate, actually converged numerical stage.
    original = study.collect_reference_calibration_run_metrics
    monkeypatch.setattr(study, "collect_reference_calibration_run_metrics", lambda run: replace(
        original(run), converged=True, optimizer_stop_signal="tolerance_threshold",
        final_iteration=12,
    ))
    new = runner.run_current_stage()
    cid = new.candidates[0].candidate_id
    _approve_for_test(new.study_directory, cid)
    final, _ = study.record_reference_calibration_stage_review(
        new.study_directory, selected_candidate_id=cid, visual_approvals={},
    )
    report = study.load_reference_calibration_report(final.study_directory)
    assert any("remain non-converged" in line for line in report["limitations"])
    assert all(item["iteration_limit_provisional"] for item in report["stage_decisions"][:3])
    config = load_config(final.final_config_path)
    result = config["project"]["parameter_provenance"]["recommendation"]["calibration_result"]
    assert len(result["iteration_limit_provisional_selections"]) == 3
    assert config["model"]["deformation"].get("initial_momenta") is None


def test_retained_provisional_record_cannot_drop_warning_or_withdrawn_approval(
    tmp_path, monkeypatch,
):
    _, snapshot, candidate = _capped(tmp_path, monkeypatch)
    _approve_for_test(snapshot.study_directory, candidate.candidate_id)
    second, _ = _choose(snapshot, candidate)
    event = next(
        e for e in study._load_events(second.study_directory) if e["event"] == "stage_retained"
    )
    tampered = copy.deepcopy(event)
    tampered.pop("iteration_limit_provisional")
    with pytest.raises(study.ReferenceCalibrationStudyError, match="approved evidence"):
        verify_reference(second.study_directory, tampered)
    study._append_event(second.study_directory, "candidate_visual_review", dict(
        stage_id="attachment", candidate_id=candidate.candidate_id, approved=False,
        reviewed_subjects=[snapshot.plan.selected_pilot_subjects[0].filename],
        source=study._candidate_review_binding(candidate),
    ))
    with pytest.raises(study.ReferenceCalibrationStudyError, match="withdrawn"):
        keep_previous_fit(second.study_directory)


def test_desktop_explicit_provisional_action_runs_in_worker_without_engine(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from diffeoforge.desktop import reference_calibration_dialog as dialog_module

    app = QApplication.instance() or QApplication([])
    _, snapshot, candidate = _capped(tmp_path, monkeypatch)
    dialog = dialog_module.ReferenceCalibrationDialog(snapshot.study_directory)
    dialog.selection_combo.setCurrentIndex(dialog.selection_combo.findData(candidate.candidate_id))
    assert "provisionally" in dialog.advance_button.text()
    assert not dialog.advance_button.isEnabled()
    _approve_for_test(snapshot.study_directory, candidate.candidate_id)
    dialog._render()
    assert dialog.advance_button.isEnabled()
    assert "Convergence is not established" in dialog.status.text()
    dispatched = []
    monkeypatch.setattr(dialog, "_start_pilot", lambda **kw: dispatched.append(kw))
    dialog._advance()
    assert dispatched == [dict(adaptive=False, provisional_candidate_id=candidate.candidate_id)]
    runner = study.ReferenceCalibrationStudyRunner(snapshot.study_directory)
    monkeypatch.setattr(runner, "run_current_stage", lambda **kw: pytest.fail("No fit should run"))
    worker = dialog_module._CalibrationStageWorker(
        runner, provisional_candidate_id=candidate.candidate_id,
    )
    outcomes = []
    worker.signals.succeeded.connect(outcomes.append)
    worker.run()
    assert worker.is_finished and worker.error_message is None
    assert outcomes[0].current_stage.order == 2
    dialog.close()
    app.processEvents()
