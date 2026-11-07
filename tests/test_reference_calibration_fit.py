"""Fit-first ranking and mandatory specimen acceptance, with synthetic evidence."""

import math
from dataclasses import replace

import pytest
from test_reference_calibration import _recommendation, _stage_evidence
from test_reference_calibration_study import (
    _CompletedController,
    _review_ready_stage,
)

import diffeoforge.reference_calibration_study as study
from diffeoforge.reference_calibration import (
    assess_calibration_stage,
    bind_calibration_search_extension_plan,
    build_reference_calibration_plan,
    propose_calibration_fit_refinement,
    reference_calibration_plan_from_provenance,
)


def _fit_evidence():
    plan = build_reference_calibration_plan(
        _recommendation(),
        coordinate_unit="unitless",
        requested_pilot_subject_count=3,
    )
    evidence = _stage_evidence(
        plan,
        "noise",
        (
            (0.01, 0.001, 0.001, 1.0),
            (0.06, 100, 100, 10000),
            (0.1, 0.1, 0.1, 2),
            (0.2, 0.1, 0.1, 3),
            (0.3, 0.1, 0.1, 4),
        ),
    )
    names = tuple(s.filename for s in plan.selected_pilot_subjects)
    first = replace(
        evidence[0],
        subject_normalized_residual_p95=tuple(
            zip(
                names,
                (0.001, 0.001, 0.5),
                strict=True,
            )
        ),
    )
    return plan, tuple(replace(e, review_approved=None) for e in (first, *evidence[1:]))


def test_one_bad_specimen_cannot_hide_behind_pooling_speed_or_sampling():
    plan, evidence = _fit_evidence()
    a = assess_calibration_stage(plan, stage_id="noise", evidence=evidence)
    assert a.balanced_candidate_id == evidence[1].candidate_id
    assert a.recommendation_confidence == "needs_visual_review"
    assert not a.automatic_selection_allowed
    # Arbitrarily favorable economy and half-sample metrics cannot reverse fit.
    changed = (
        replace(evidence[0], runtime_seconds=0, resampling_sensitivity=0),
        replace(evidence[1], runtime_seconds=1e12, resampling_sensitivity=1),
        *evidence[2:-1],
        replace(evidence[-1], residual_p95=1e12),
    )
    b = assess_calibration_stage(plan, stage_id="noise", evidence=changed)
    assert b.balanced_candidate_id == a.balanced_candidate_id
    assert set(b.weights) == {"worst_specimen_normalized_p95"}


def test_fit_order_is_unit_invariant_and_preserves_tradeoffs():
    plan, evidence = _fit_evidence()
    a = assess_calibration_stage(plan, stage_id="noise", evidence=evidence)
    changed = tuple(replace(e, residual_p95=e.residual_p95 * 1000) for e in evidence)
    b = assess_calibration_stage(plan, stage_id="noise", evidence=changed)
    assert a.balanced_candidate_id == b.balanced_candidate_id
    assert a.pareto_candidate_ids == b.pareto_candidate_ids


@pytest.mark.parametrize("bad", [(), (("unknown.vtk", 0.1),)])
def test_partial_or_invalid_per_specimen_evidence_is_not_ranked(bad):
    plan, evidence = _fit_evidence()
    invalid = tuple(replace(e, subject_normalized_residual_p95=bad) for e in evidence)
    a = assess_calibration_stage(plan, stage_id="noise", evidence=invalid)
    assert a.status == "no_eligible_candidate"
    assert a.balanced_candidate_id is None
    assert all(not c.eligible for c in a.candidates)


@pytest.mark.parametrize("mode", ["manual", "provisional", "automatic"])
def test_no_selection_api_can_substitute_an_unrecorded_approval(tmp_path, monkeypatch, mode):
    runner, snapshot = _review_ready_stage(tmp_path, monkeypatch)
    before = (snapshot.study_directory / study.STUDY_EVENTS).read_bytes()
    cid = snapshot.candidates[0].candidate_id
    with pytest.raises(study.ReferenceCalibrationStudyError):
        if mode == "automatic":
            study.select_reference_calibration_stage_automatically(snapshot.study_directory)
        else:
            fn = (
                study.record_reference_calibration_stage_review
                if mode == "manual"
                else study.record_reference_calibration_provisional_override
            )
            fn(snapshot.study_directory, selected_candidate_id=cid, visual_approvals={cid: True})
    assert (snapshot.study_directory / study.STUDY_EVENTS).read_bytes() == before


@pytest.mark.parametrize("afk", [False, True])
def test_batch_runner_pauses_without_advancing_and_reuses_results(tmp_path, monkeypatch, afk):
    runner, snapshot = _review_ready_stage(tmp_path, monkeypatch)
    before = (snapshot.study_directory / study.STUDY_EVENTS).read_bytes()
    result = runner.run_complete_automatic_pilot(
        afk=afk, visual_approvals={snapshot.candidates[0].candidate_id: True}
    )
    assert result.status == "awaiting_review"
    assert result.selected_candidate_ids == {}
    assert (snapshot.study_directory / study.STUDY_EVENTS).read_bytes() == before


def test_early_failed_specimen_is_saved_and_blocks_every_selection(tmp_path, monkeypatch):
    runner, snapshot = _review_ready_stage(tmp_path, monkeypatch)
    name = snapshot.plan.selected_pilot_subjects[0].filename
    cid = snapshot.candidates[0].candidate_id
    saved = study.record_reference_calibration_candidate_review(
        runner.study_directory,
        candidate_id=cid,
        approved=False,
        reviewed_subjects=(name,),
        subject_decisions={name: "fail"},
    )
    assert saved.visual_reviews[cid] is False
    assert saved.subject_decisions[cid] == {name: "fail"}
    assert not study.assess_reference_calibration_snapshot(saved).candidates[0].eligible
    with pytest.raises(study.ReferenceCalibrationStudyError, match="Every pilot specimen"):
        study.record_reference_calibration_provisional_override(
            runner.study_directory,
            selected_candidate_id=cid,
            visual_approvals={cid: True},
        )


@pytest.mark.parametrize("decision", ["fail", "uncertain", "unassessed"])
def test_one_unaccepted_specimen_blocks_candidate_approval(tmp_path, monkeypatch, decision):
    runner, snapshot = _review_ready_stage(tmp_path, monkeypatch)
    names = tuple(s.filename for s in snapshot.plan.selected_pilot_subjects)
    decisions = {name: "pass" for name in names}
    decisions[names[-1]] = decision
    with pytest.raises(study.ReferenceCalibrationStudyError, match="every specimen must pass"):
        study.record_reference_calibration_candidate_review(
            runner.study_directory,
            candidate_id=snapshot.candidates[0].candidate_id,
            approved=True,
            reviewed_subjects=names,
            subject_decisions=decisions,
        )


def test_refinement_keeps_rejected_center_and_cohort_and_runs_only_new_options(
    tmp_path, monkeypatch
):
    runner, snapshot = _review_ready_stage(tmp_path, monkeypatch)
    cid = snapshot.candidates[0].candidate_id
    name = snapshot.plan.selected_pilot_subjects[0].filename
    snapshot = study.record_reference_calibration_candidate_review(
        runner.study_directory,
        candidate_id=cid,
        approved=False,
        reviewed_subjects=(name,),
        subject_decisions={name: "fail"},
    )
    source_bytes = (runner.study_directory / study.STUDY_EVENTS).read_bytes()
    assessment = study.assess_reference_calibration_snapshot(snapshot)
    proposal = propose_calibration_fit_refinement(
        snapshot.plan,
        assessment,
        source_candidate_id=cid,
        selected_values=snapshot.selected_values,
    )
    assert 1 <= len(proposal.candidates) <= 8
    assert any(
        c.values["noise_std"] != dict(proposal.fit_center_values)["noise_std"]
        for c in proposal.candidates
    )
    center = dict(proposal.fit_center_values)
    assert all(sum(c.values[k] != v for k, v in center.items()) == 1 for c in proposal.candidates)
    plan = bind_calibration_search_extension_plan(snapshot.plan, assessment, proposal)
    assert reference_calibration_plan_from_provenance(plan.provenance) == plan
    successor = study.create_reference_calibration_search_extension_study(
        runner.study_directory,
        tmp_path / "refined",
        fit_center_candidate_id=cid,
        safety_limits={k: (v / 2, v * 2) for k, v in center.items()},
    )
    assert successor.status == "ready" and not successor.selected_candidate_ids
    assert successor.plan.selected_pilot_subjects == snapshot.plan.selected_pilot_subjects
    assert successor.visual_reviews[cid] is False
    assert successor.subject_decisions[cid] == {name: "fail"}
    assert (
        study.calibration_candidate_run_directory(successor.candidates[0])
        == snapshot.candidates[0].run_directory
    )
    assert (runner.study_directory / study.STUDY_EVENTS).read_bytes() == source_bytes
    count = sum(c.status == "pending" for c in successor.candidates)
    assert count == len(proposal.candidates)
    result = study.ReferenceCalibrationStudyRunner(
        successor.study_directory,
        controller_factory=_CompletedController,
    ).run_complete_automatic_pilot(afk=True)
    assert result.status == "awaiting_review" and not result.selected_candidate_ids
    events = study._load_events(result.study_directory)
    new_started = [
        e
        for e in events
        if e["event"] == "candidate_started" and "imported_source_event_hash" not in e
    ]
    assert len(new_started) == count
    assert result.visual_reviews[cid] is False


def test_missing_original_normalization_fails_closed_without_mutating_evidence(
    tmp_path, monkeypatch
):
    runner, snapshot = _review_ready_stage(tmp_path, monkeypatch)
    before = (runner.study_directory / study.STUDY_EVENTS).read_bytes()
    candidate = snapshot.candidates[0]
    fit = study.normalized_candidate_subject_fit(snapshot, candidate)
    assert set(fit) == {s.filename for s in snapshot.plan.selected_pilot_subjects}
    assert all(math.isfinite(v) and v > 0 for v in fit.values())
    assert (runner.study_directory / study.STUDY_EVENTS).read_bytes() == before
    path = runner.study_directory / "inputs" / "subjects" / next(iter(fit))
    path.write_text("changed", encoding="utf-8")
    with pytest.raises(study.ReferenceCalibrationStudyError, match="input changed"):
        study.load_reference_calibration_study(runner.study_directory)


def test_nonfinite_fit_cannot_become_a_valid_assessment():
    plan, evidence = _fit_evidence()
    names = tuple(s.filename for s in plan.selected_pilot_subjects)
    invalid = tuple(
        replace(e, subject_normalized_residual_p95=tuple((name, math.nan) for name in names))
        for e in evidence
    )
    with pytest.raises(ValueError):
        assess_calibration_stage(plan, stage_id="noise", evidence=invalid)


def test_old_outward_consent_cannot_silently_start_a_different_search(tmp_path, monkeypatch):
    runner, snapshot = _review_ready_stage(tmp_path, monkeypatch)
    before = (runner.study_directory / study.STUDY_EVENTS).read_bytes()
    with pytest.raises(study.ReferenceCalibrationStudyError, match="explicit fit refinement"):
        runner.run_complete_automatic_pilot(
            afk=True, afk_outward_safety_limits={"noise_std": (0.001, 1.0)},
        )
    assert (snapshot.study_directory / study.STUDY_EVENTS).read_bytes() == before
