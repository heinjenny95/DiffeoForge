"""A common-model trial's visual reference may differ from its numerical seed."""

from copy import deepcopy

import pytest

from diffeoforge import guided_feedback as feedback
from diffeoforge import guided_strategy, pilot_form_progress
from diffeoforge import reference_calibration_study as study
from diffeoforge import reference_guided_pilot as guided
from diffeoforge.pilot_common_review import common_review, seed_outcome


def test_approved_individual_feedback_never_implies_progress_from_shared_seed(
    tmp_path, monkeypatch
):
    from test_pilot_common_candidate import rejected_capacity

    from diffeoforge import pilot_multiscale_choice

    monkeypatch.setattr(
        pilot_multiscale_choice, "choice", lambda snapshot, value, target, previous: previous
    )
    accepted, candidate, trend = rejected_capacity(tmp_path, monkeypatch, outcome=None)
    trend["value"] = "improving"
    identifier = candidate.candidates[0].candidate_id
    ledger = deepcopy(pilot_form_progress.marker(candidate))
    saved_reviews = dict(candidate.visual_reviews)
    reference = feedback.reference(accepted, identifier)
    seed = candidate.attachment_comparison["refinement"]["reference"]
    current = feedback.reference(candidate, identifier)
    assert seed != reference
    context = common_review(candidate, identifier)
    assert context["approved_individual"] == reference and context["numerical_seed"] == seed
    assert context["current"] == current
    decision = dict(
        comparison=reference,
        outcome="worse",
        comparison_displayed=True,
        common_comparison_displayed=True,
        inspected_subjects=[reference["target"]],
        common_review_references=dict(approved_individual=reference, numerical_seed=seed),
        display_scopes={reference["target"]: "original_proxy"},
    )
    with pytest.raises(ValueError, match="selected comparison surface"):
        feedback.save_feedback(
            candidate.study_directory, identifier, dict(decision, comparison_displayed=False)
        )
    with pytest.raises(ValueError, match="review references changed"):
        feedback.save_feedback(
            candidate.study_directory,
            identifier,
            dict(
                decision,
                common_review_references=dict(approved_individual=seed, numerical_seed=seed),
            ),
        )
    seed_vote = None
    for outcome, against, expected in [
        ("worse", reference, "feedback"),
        ("better", reference, "feedback"),
        ("better", seed, "iterations"),
        ("worse", reference, "iterations"),
        ("same", seed, "detail"),
        ("better", reference, "detail"),
    ]:
        candidate = feedback.save_feedback(
            candidate.study_directory,
            identifier,
            dict(decision, outcome=outcome, comparison=against),
        )
        event = study._load_events(candidate.study_directory)[-1]
        assert event["comparison_displayed"] and event["comparison"] == against
        assert event["common_review"]["approved_individual"] == reference
        assert event["common_review"]["numerical_seed"] == seed
        assert seed_outcome(event) == (outcome if against == seed else None)
        context = guided_strategy.state(candidate)
        choice = context["common_recovery"]
        if against == seed:
            seed_vote = event
        if expected == "feedback":
            assert choice["mode"] == "feedback" and choice["requested_comparison"] == seed
        else:
            assert choice["kind"] == expected
            assert choice["reference"] == current and choice["additional_iterations"] == 120
            cited = seed_vote if expected == "iterations" else event
            assert choice["human_feedback"]["event_hash"] == cited["event_hash"]
            assert choice["human_feedback"]["outcome"] == cited["outcome"]
        if against == reference and not seed_vote:
            assert context["feedback"][identifier]["feedback"] is None
        recorded = next(row for row in context["cases"] if row["fit"] == current)["outcome"]
        assert recorded == (seed_vote["outcome"] if seed_vote else None)
        if against == reference and outcome == "worse":
            assert "worse than the approved individual fit" in choice["reason"]
        assert (
            pilot_form_progress.marker(candidate) == ledger
            and candidate.visual_reviews == saved_reviews
        )
        assert guided.record(candidate)["strategy"]["baseline"] == seed
        assert accepted.visual_reviews[identifier] is True


def test_only_a_rating_against_the_bound_seed_reports_numerical_progress():
    seed, approved, other = ({"directory": name} for name in ("seed", "individual", "alternative"))
    base = dict(
        outcome="better", common_review=dict(numerical_seed=seed, approved_individual=approved)
    )
    assert seed_outcome(dict(base, comparison=other)) is None
    assert seed_outcome(dict(base, comparison=approved)) is None
    assert seed_outcome(dict(base, comparison=seed)) == "better"
    assert (
        seed_outcome(
            dict(
                base,
                comparison=approved,
                common_review=dict(numerical_seed=approved, approved_individual=approved),
            )
        )
        == "better"
    )
    assert seed_outcome(dict(outcome="better", comparison=seed)) == "better"


def test_seed_rating_lookup_stops_at_changed_marks_or_start():
    from diffeoforge.pilot_common_review import progress_feedback

    rating = dict(current="trial", comparison="start", outcome="better",
                  problem_regions={"specimen": ["A"]}, common_review={"numerical_seed": "start"})
    other = dict(rating, comparison="approved", outcome="worse")
    assert progress_feedback([rating, other]) is rating
    assert progress_feedback([rating, dict(other, problem_regions={}), other]) is None
    sibling = dict(other, common_review={"numerical_seed": "sibling"})
    assert progress_feedback([rating, sibling]) is None
    assert progress_feedback([rating, dict(other, current="another trial")]) is None
    unseeded = dict(rating, comparison=None, common_review={"numerical_seed": None})
    assert progress_feedback([unseeded]) is None


def test_later_mark_edit_requires_new_progress_review(monkeypatch):
    from diffeoforge import pilot_common_diagnosis
    from diffeoforge.pilot_common_review import current_progress_feedback

    ref = {"target": "specimen"}
    marks = ["A"]
    event = dict(current=ref, common_review={"numerical_seed": "start"}, comparison="start",
                 problem_regions={"specimen": list(marks)}, outcome="better")
    monkeypatch.setattr(pilot_common_diagnosis, "comparison_regions", lambda *args: marks)
    assert current_progress_feedback(None, None, ref, [event]) == event
    marks.clear()
    assert current_progress_feedback(None, None, ref, [event]) is None


def test_common_review_from_later_protocol_preserves_exact_historical_seed(tmp_path, monkeypatch):
    from test_reviewed_start_progress import selected_local_after_common_failure

    local, common = selected_local_after_common_failure(tmp_path, monkeypatch, outcome=None)
    identifier = local.candidates[0].candidate_id
    original = feedback.reference(local, identifier)
    assert common_review(local, identifier) is None
    reused = common_review(local, identifier, origin=common)
    assert reused["current"] == reused["approved_individual"] == original
    assert reused["context_directory"] == str(common.study_directory)
    assert reused["numerical_seed"] == local.attachment_comparison["refinement"]["reference"]


def test_seed_progress_followup_requests_the_other_surface(tmp_path, monkeypatch):
    from test_guided_pilot import run_batch
    from test_pilot_region_feedback import reject
    from test_reviewed_start_progress import selected_local_after_common_failure

    from diffeoforge import pilot_common_diagnosis, pilot_common_model

    accepted, first = selected_local_after_common_failure(tmp_path, monkeypatch)
    monkeypatch.setattr(pilot_common_diagnosis, "diagnose", lambda *args: None)
    identifier = first.candidates[0].candidate_id
    next_fit = guided.next_action(first.study_directory, "adaptive_common_continue", identifier)
    next_fit = reject(run_batch(next_fit, monkeypatch, capped=True), identifier)
    refs = common_review(next_fit, identifier)
    approved = refs["approved_individual"]
    assert approved == feedback.reference(accepted, identifier)
    seed = refs["numerical_seed"]
    assert seed == feedback.reference(first, identifier)
    decision = dict(
        comparison=approved,
        outcome="better",
        comparison_displayed=True,
        common_comparison_displayed=True,
        inspected_subjects=[approved["target"]],
        common_review_references=dict(approved_individual=approved, numerical_seed=seed),
        display_scopes={approved["target"]: "original_proxy"},
    )
    reviewed = feedback.save_feedback(next_fit.study_directory, identifier, decision)
    decision = pilot_common_model.preview(reviewed, {}, approved["target"])
    assert decision["mode"] == "feedback"
    assert decision["requested_comparison"] == seed
    assert decision["review_reference"] == feedback.reference(next_fit, identifier)
