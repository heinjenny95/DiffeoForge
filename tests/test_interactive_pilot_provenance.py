"""Approval reuse and final numerical gates remain independent of preference."""

from dataclasses import replace

import pytest
from test_guided_pilot import approve, run_batch
from test_interactive_pilot import initial
from test_pilot_region_feedback import reject

from diffeoforge import guided_strategy as strategy
from diffeoforge import reference_calibration_study as study
from diffeoforge import reference_guided_pilot as guided


def test_only_exact_historical_approvals_are_reused_after_switching_back(tmp_path, monkeypatch):
    first = run_batch(initial(tmp_path), monkeypatch)
    first = approve(approve(first, "guided-current"), "guided-varifold")
    contrasting = guided.next_action(first.study_directory, "adaptive_confirm", "guided-varifold")
    contrasting = reject(run_batch(contrasting, monkeypatch))
    finer = guided.next_action(contrasting.study_directory, "adaptive_recover", "guided-varifold",
                               goal="goal:detail")
    finer = reject(run_batch(finer, monkeypatch))
    proposed = strategy.trial_proposal(finer, "guided-varifold", "base:other_method")
    assert proposed["available"] and proposed["remaining_checks"] == 1
    switched = guided.next_action(finer.study_directory, "adaptive_recover", "guided-varifold",
                                  goal="base:other_method")
    approved = guided.record(switched)["approved"]
    assert len(approved) == 1 and approved[0]["method"] == "current"
    assert approved[0] == guided._approved_record(first, "guided-current")
    assert not switched.visual_reviews and all(c.attempts == 0 for c in switched.candidates)
    names = [s.filename for s in first.plan.selected_pilot_subjects]
    study.record_reference_calibration_candidate_review(
        first.study_directory, candidate_id="guided-current", approved=False,
        reviewed_subjects=names, subject_decisions={n: "fail" for n in names})
    with pytest.raises(ValueError, match="approve"):
        study.load_reference_calibration_study(switched.study_directory)


def test_preference_never_bypasses_technical_validity_or_joint_approval(tmp_path, monkeypatch):
    snapshot = run_batch(initial(tmp_path), monkeypatch)
    snapshot = reject(snapshot, "guided-varifold")
    bad = next(c for c in snapshot.candidates if c.candidate_id == "guided-varifold")
    invalid = replace(bad, metrics=dict(bad.metrics, invalid_face_count=1))
    invalid_snapshot = replace(snapshot, candidates=tuple(
        invalid if c.candidate_id == invalid.candidate_id else c for c in snapshot.candidates))
    assert not strategy.starting_allowed(invalid_snapshot, "guided-varifold")
    with pytest.raises(ValueError, match="valid fit"):
        strategy.trial_proposal(invalid_snapshot, "guided-varifold", "detail")
    selected = approve(snapshot, "guided-varifold")
    while guided.record(selected)["phase"] != "joint":
        selected = guided.next_action(
            selected.study_directory, "adaptive_confirm", "guided-varifold")
        selected = run_batch(selected, monkeypatch)
        if guided.record(selected)["phase"] != "joint":
            selected = approve(selected, "guided-varifold")
    with pytest.raises(ValueError, match="approve"):
        guided.next_action(selected.study_directory, "finish_joint", "guided-varifold")
    selected = approve(selected, "guided-varifold")
    qualified = guided.next_action(selected.study_directory, "finish_joint", "guided-varifold")
    assert qualified.current_stage.order == 4
    assert not any(c.attempts for c in qualified.candidates if c.status == "pending")
