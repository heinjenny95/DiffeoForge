"""Regression journeys for worsening improvements, feedback and earlier fits."""

import pytest
from test_guided_pilot import approve, run_batch
from test_interactive_pilot import initial
from test_pilot_region_feedback import patch, reject

from diffeoforge import guided_feedback as feedback
from diffeoforge import guided_strategy as strategy
from diffeoforge import reference_calibration_study as study
from diffeoforge import reference_guided_pilot as guided


def attempted(tmp_path, monkeypatch):
    base = reject(run_batch(initial(tmp_path), monkeypatch), "guided-varifold")
    trial = guided.next_action(
        base.study_directory, "adaptive_recover", "guided-varifold", goal="goal:detail"
    )
    return base, run_batch(trial, monkeypatch)


def decision(base, trial, outcome):
    target = guided.record(trial)["target"]
    return dict(
        comparison=feedback.reference(base, "guided-varifold"),
        outcome=outcome,
        inspected_subjects=[target],
        display_scopes={target: "original_proxy"},
        note="The local shape moved farther from the original",
        comparison_displayed=False,
    )


@pytest.mark.parametrize("outcome", ["worse", "same", "unsure"])
def test_non_improvement_returns_to_bound_start_without_any_approval(
    tmp_path, monkeypatch, outcome
):
    base, trial = attempted(tmp_path, monkeypatch)
    selected = feedback.save_feedback(
        trial.study_directory, "guided-varifold", decision(base, trial, outcome)
    )
    assert not selected.visual_reviews
    assert feedback.inspected(selected, "guided-varifold")
    assert feedback.selection(selected, "guided-varifold") == feedback.reference(
        base, "guided-varifold"
    )
    duplicate = strategy.trial_proposal(selected, "guided-varifold", "goal:detail")
    assert not duplicate["available"]
    proposed = strategy.trial_proposal(selected, "guided-varifold", "goal:local_motion")
    assert (
        proposed["values"]["attachment_kernel_width"]
        == base.plan.effective_values["attachment_kernel_width"]
    )
    assert (
        proposed["values"]["deformation_kernel_width"]
        == base.plan.effective_values["deformation_kernel_width"] / 2
    )
    next_trial = guided.next_action(
        selected.study_directory, "adaptive_recover", "guided-varifold", goal="goal:local_motion"
    )
    assert guided.record(next_trial)["strategy"]["baseline"] == feedback.reference(
        base, "guided-varifold"
    )
    assert not next_trial.visual_reviews and all(c.attempts == 0 for c in next_trial.candidates)
    assert not study.load_reference_calibration_study(base.study_directory).visual_reviews.get(
        "guided-varifold"
    )


def test_better_can_be_a_preferred_unapproved_fit_and_regions_are_not_lost(tmp_path, monkeypatch):
    base, trial = attempted(tmp_path, monkeypatch)
    form = trial.plan.selected_pilot_subjects[0]
    report = decision(base, trial, "better")
    report["problem_regions"] = {form.filename: [patch(form.sha256)]}
    selected = feedback.save_feedback(trial.study_directory, "guided-varifold", report)
    assert not selected.visual_reviews
    assert feedback.selection(selected, "guided-varifold") == feedback.reference(
        selected, "guided-varifold"
    )
    assert (
        feedback.regions(selected, "guided-varifold", form.filename)
        == report["problem_regions"][form.filename]
    )
    proposed = strategy.trial_proposal(selected, "guided-varifold", "goal:local_motion")
    assert (
        proposed["values"]["attachment_kernel_width"]
        == trial.plan.effective_values["attachment_kernel_width"]
    )
    with pytest.raises(ValueError, match="approve"):
        guided.next_action(selected.study_directory, "adaptive_confirm", "guided-varifold")


def test_explicit_older_fit_escapes_multiple_rejected_improvements(tmp_path, monkeypatch):
    base, trial = attempted(tmp_path, monkeypatch)
    trial = reject(trial)
    second = guided.next_action(
        trial.study_directory, "adaptive_recover", "guided-varifold", goal="goal:local_motion"
    )
    second = run_batch(second, monkeypatch)  # Not approved or rejected yet.
    first_ref = feedback.reference(base, "guided-varifold")
    selected = guided.next_action(
        second.study_directory, "adaptive_select_start", "guided-varifold", goal=first_ref
    )
    assert not selected.visual_reviews
    proposed = strategy.trial_proposal(selected, "guided-varifold", "goal:weight")
    assert (
        proposed["values"]["attachment_kernel_width"]
        == base.plan.effective_values["attachment_kernel_width"]
    )
    assert (
        proposed["values"]["deformation_kernel_width"]
        == base.plan.effective_values["deformation_kernel_width"]
    )
    with pytest.raises(ValueError, match="approve"):
        guided.next_action(selected.study_directory, "adaptive_confirm_start", "guided-varifold")
    assert not (selected.study_directory / "fit-search-latest.json").exists()


def test_reviewed_earlier_fit_is_reused_without_recalculating_it(tmp_path, monkeypatch):
    base, trial = attempted(tmp_path, monkeypatch)
    # A new explicit human review of the earlier result is still needed.
    base = approve(base, "guided-varifold")
    selected = feedback.select(
        trial.study_directory, "guided-varifold", feedback.reference(base, "guided-varifold")
    )
    continued = guided.next_action(
        selected.study_directory, "adaptive_confirm_start", "guided-varifold"
    )
    assert guided.record(continued)["phase"] == "validate"
    assert guided.record(continued)["target"] != guided.record(base)["target"]
    assert continued.plan.effective_values == base.plan.effective_values
    assert not continued.visual_reviews and all(c.attempts == 0 for c in continued.candidates)
    assert guided.record(continued)["approved"] == [
        guided._approved_record(base, "guided-varifold")
    ]


@pytest.mark.parametrize("invalid", ["not_seen", "other_form", "wrong_region"])
def test_feedback_requires_inspection_and_matching_original(tmp_path, monkeypatch, invalid):
    base, trial = attempted(tmp_path, monkeypatch)
    report = decision(base, trial, "worse")
    if invalid == "not_seen":
        report["display_scopes"] = {}
    elif invalid == "other_form":
        report["comparison"] = dict(report["comparison"], target="another.vtk")
    else:
        report["problem_regions"] = {
            trial.plan.selected_pilot_subjects[0].filename: [patch("x" * 64)]
        }
    with pytest.raises(ValueError):
        feedback.save_feedback(trial.study_directory, "guided-varifold", report)
    assert not list(feedback._local_events(trial, "guided-varifold"))
    assert not trial.visual_reviews
