from dataclasses import replace

import pytest
from test_reference_stage_retention import _second_stage

from diffeoforge import reference_calibration_study as study
from diffeoforge import reference_integration_check as integration
from diffeoforge.reference_stage_retention import keep_previous_fit


def _fourth(tmp_path, monkeypatch):
    runner, _, _, second = _second_stage(tmp_path, monkeypatch)
    keep_previous_fit(second.study_directory)
    return runner, keep_previous_fit(second.study_directory)


def test_predeclared_criteria_bind_full_cohort_and_choose_smallest_adequate_count(
    tmp_path, monkeypatch
):
    runner, fourth = _fourth(tmp_path, monkeypatch)
    done = runner.run_current_stage()
    assert done.integration_tolerances
    events = study._load_events(done.study_directory)
    declaration = next(e for e in events if e["event"] == "integration_tolerances_declared")
    assert len(declaration["subjects"]) == done.plan.pilot_subject_count
    assert declaration["sequence"] < min(
        e["sequence"] for e in events
        if e["event"] == "candidate_started" and e["stage_id"] == "timepoints"
    )
    assessment = study.assess_reference_calibration_snapshot(done)
    assert assessment.balanced_candidate_id == fourth.candidates[0].candidate_id
    assert assessment.metric_weights == (("timepoints", 1.0),)
    assert not assessment.candidates[-1].eligible  # No finer reference for the largest.
    assert not done.visual_reviews  # Numerical stability never supplies anatomical QC.
    with pytest.raises(study.ReferenceCalibrationStudyError, match="Every pilot specimen"):
        study.record_reference_calibration_stage_review(
            done.study_directory, selected_candidate_id=assessment.balanced_candidate_id,
            visual_approvals={},
        )
    with pytest.raises(ValueError, match="already bound"):
        integration.declare_tolerances(done, {k: 0.2 for k in integration.DEFAULT_TOLERANCES})


def test_worst_specimen_failure_cannot_be_hidden_by_cohort_average(tmp_path, monkeypatch):
    runner, _ = _fourth(tmp_path, monkeypatch)
    done = runner.run_current_stage()
    first = done.candidates[0]
    metrics = dict(first.metrics)
    metrics["subject_residual_p95"] = dict(metrics["subject_residual_p95"])
    name = next(iter(metrics["subject_residual_p95"]))
    metrics["subject_residual_p95"][name] *= 3
    # Cohort residual and runtime stay identical; only one measured specimen differs.
    changed = replace(done, candidates=(replace(first, metrics=metrics), *done.candidates[1:]))
    assessment = study.assess_reference_calibration_snapshot(changed)
    assert not assessment.candidates[0].eligible
    assert any("residual_relative_difference exceeds" in r
               for r in assessment.candidates[0].rejection_reasons)
    missing = dict(metrics)
    missing["subject_residual_p95"] = {}
    changed = replace(done, candidates=(replace(first, metrics=missing), *done.candidates[1:]))
    assert not study.assess_reference_calibration_snapshot(changed).candidates[0].eligible


def test_invalid_criteria_refused_before_any_execution(tmp_path, monkeypatch):
    _, fourth = _fourth(tmp_path, monkeypatch)
    for value in (0, -1, float("nan"), True, 2):
        values = dict(integration.DEFAULT_TOLERANCES, residual_relative=value)
        with pytest.raises(ValueError, match="finite positive"):
            integration.declare_tolerances(fourth, values)
    assert not study.load_reference_calibration_study(fourth.study_directory).integration_tolerances


def test_legacy_started_comparison_keeps_its_original_meaning(tmp_path, monkeypatch):
    runner, fourth = _fourth(tmp_path, monkeypatch)
    monkeypatch.setattr(integration, "declare_tolerances", lambda snapshot, _values: snapshot)
    done = runner.run_current_stage()
    assert not done.integration_tolerances
    monkeypatch.undo()
    assert integration.declare_tolerances(done) == done
    with pytest.raises(ValueError, match="before running"):
        integration.declare_tolerances(done, integration.DEFAULT_TOLERANCES)
