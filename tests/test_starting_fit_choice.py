"""A Better rating with unresolved checks never silently picks an older seed."""

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from diffeoforge import guided_feedback as feedback
from diffeoforge import guided_strategy as strategy
from diffeoforge import reference_calibration_study as study
from diffeoforge import reference_guided_pilot as guided


@pytest.fixture
def case(monkeypatch):
    identifier = "guided-varifold"
    current = dict(directory="current", candidate_id=identifier, target="target.vtk",
                   method="varifold", binding={"hash": "current"})
    previous = dict(current, directory="previous", binding={"hash": "previous"})
    quality = dict(numerical_selection_suitable=False, no_new_intersection_flags=False,
                   spatial_resolution_sufficient=False)
    candidate = SimpleNamespace(candidate_id=identifier, status="completed", metrics=dict(
        attachment_comparison=dict(subjects={"target.vtk": dict(regional_quality=quality)})))
    snapshot = SimpleNamespace(study_directory=Path("current"), candidates=[candidate],
        plan=SimpleNamespace(pilot_subject_count=1), visual_reviews={}, region_edits={},
        problem_regions={},
        attachment_comparison=dict(methods={identifier: "varifold"}))
    parent = SimpleNamespace(study_directory=Path("previous"))
    infos = {"current": dict(target="target.vtk", screen_trials_spent=4, history=[], strategy={}),
             "previous": dict(target="target.vtk", screen_trials_spent=3)}
    events = [dict(event="guided_fit_feedback", sequence=0, current=current,
                   comparison=previous, outcome="better", problem_regions={})]
    rows = [dict(reference=current, label="Test 4 · Varifold", trial_index=4,
                 current=True, approved=False),
            dict(reference=previous, label="Test 3 · Varifold", trial_index=3,
                 current=False, approved=False)]

    def same_source(_snapshot, ref):
        if ref not in (current, previous):
            raise ValueError("Preferred starting fit or inspection binding changed")
        return snapshot if ref == current else parent

    monkeypatch.setattr(feedback, "_same_source", same_source)
    monkeypatch.setattr(feedback, "reference", lambda *_a, **_k: deepcopy(current))
    monkeypatch.setattr(feedback, "choices", lambda *_: deepcopy(rows))
    monkeypatch.setattr(feedback, "local_strategy_reference", lambda *_: deepcopy(previous))
    monkeypatch.setattr(feedback, "_local_events", lambda *_: (
        row for row in events if row["event"] == "guided_fit_feedback"))
    monkeypatch.setattr(study, "_load_events", lambda *_: deepcopy(events))
    monkeypatch.setattr(guided, "record", lambda value: infos[str(value.study_directory)])
    from diffeoforge import retained_mark_source

    monkeypatch.setattr(retained_mark_source, "context", lambda *_: None)
    return SimpleNamespace(snapshot=snapshot, identifier=identifier, current=current,
                           previous=previous, events=events, quality=quality)


def choose(case, reference, *, kind="guided_starting_fit_selected"):
    payload = {"reference" if kind == "guided_starting_fit_selected" else "preference": reference}
    case.events.append(dict(event=kind, sequence=len(case.events), **payload,
                            anatomical_approval_created=False, optimizer_started=False))


def test_pending_choice_explains_both_fits_and_returns_no_implicit_seed(case):
    before = deepcopy(case.events)
    state = feedback.starting_fit_choice(case.snapshot, case.identifier)
    assert state["choice_required"] and state["latest"] == state["current"] == case.current
    assert state["comparison"] == case.previous
    assert state["latest_label"] == "Varifold · Test 4"
    assert state["comparison_label"] == "Varifold · Test 3"
    assert "intersection" in " ".join(state["reasons"])
    assert "resolution" in " ".join(state["reasons"])
    assert feedback.selection(case.snapshot, case.identifier) is None
    with pytest.raises(ValueError, match="Choose the inspected starting fit explicitly"):
        feedback.require_starting_fit_choice(case.snapshot, case.identifier)
    assert case.events == before and not case.snapshot.visual_reviews


def test_presentation_keeps_marks_and_exposes_direction_without_anatomical_approval(case):
    state = feedback.presentation(case.snapshot, case.identifier)
    assert state["selected"] is None and state["needs_direction"]
    assert state["starting_fit_choice"]["current"] == case.current
    assert state["current_inspected"] and state["comparison"] == case.previous
    assert state["problem_regions"] == {"target.vtk": []}
    assert not case.snapshot.visual_reviews


@pytest.mark.parametrize("which", ["current", "previous"])
@pytest.mark.parametrize("kind", ["guided_starting_fit_selected", "guided_method_preference"])
def test_newer_explicit_inspected_choice_resolves_source_without_clearing_checks(case, which, kind):
    selected = getattr(case, which)
    choose(case, selected, kind=kind)
    assert feedback.starting_fit_choice(case.snapshot, case.identifier) is None
    assert feedback.selection(case.snapshot, case.identifier) == selected
    feedback.require_starting_fit_choice(case.snapshot, case.identifier)
    assert feedback.severe_regression(case.snapshot, case.identifier)
    assert case.quality["no_new_intersection_flags"] is False
    assert not case.snapshot.visual_reviews


def test_old_explicit_choice_does_not_silence_newer_better_quality_conflict(case):
    review = case.events.pop()
    choose(case, case.previous)
    case.events.append(dict(review, sequence=1))
    assert feedback.starting_fit_choice(case.snapshot, case.identifier)
    assert feedback.selection(case.snapshot, case.identifier) is None


def test_a_later_better_review_requires_a_fresh_explicit_source_decision(case):
    choose(case, case.previous)
    case.events.append(dict(case.events[0], sequence=2))
    assert feedback.starting_fit_choice(case.snapshot, case.identifier)


@pytest.mark.parametrize("invalid", ["changed_binding", "uninspected", "approval", "optimizer"])
def test_forged_or_stale_explicit_choice_cannot_clear_pending_state(case, monkeypatch, invalid):
    choose(case, case.current)
    if invalid == "changed_binding":
        case.events[-1]["reference"] = dict(case.current, binding={"hash": "changed"})
    elif invalid == "uninspected":
        monkeypatch.setattr(feedback, "choices", lambda *_: [])
    else:
        key = "anatomical_approval_created" if invalid == "approval" else "optimizer_started"
        case.events[-1][key] = True
    before = deepcopy(case.events)
    with pytest.raises(ValueError):
        feedback.starting_fit_choice(case.snapshot, case.identifier)
    assert case.events == before


@pytest.mark.parametrize("outcome", ["same", "worse", "unsure"])
def test_other_relative_feedback_preserves_existing_explicit_return_semantics(case, outcome):
    case.events[-1]["outcome"] = outcome
    assert feedback.starting_fit_choice(case.snapshot, case.identifier) is None
    assert feedback.selection(case.snapshot, case.identifier) == case.previous


def test_better_without_failed_checks_keeps_current_fit_and_creates_no_approval(case):
    case.quality.update(numerical_selection_suitable=True, no_new_intersection_flags=True,
                        spatial_resolution_sufficient=True)
    assert feedback.starting_fit_choice(case.snapshot, case.identifier) is None
    assert feedback.selection(case.snapshot, case.identifier) == case.current
    assert not case.snapshot.visual_reviews


def test_refinement_regression_also_requires_explicit_choice(case):
    subjects = case.snapshot.candidates[0].metrics["attachment_comparison"]["subjects"]
    row = next(iter(subjects.values()))
    row.clear()
    row["refinement_guard"] = dict(severe=True)
    state = feedback.starting_fit_choice(case.snapshot, case.identifier)
    assert "regression" in " ".join(state["warnings"])


def test_cached_guidance_skips_all_parameter_proposals_until_source_is_chosen(case, monkeypatch):
    from diffeoforge import guided_search

    pending = feedback.starting_fit_choice(case.snapshot, case.identifier)
    context = dict(feedback={case.identifier: dict(starting_fit_choice=pending, selected=None)},
                   allowed={case.identifier: True}, starting_fit_choice=pending)
    monkeypatch.setattr(strategy, "_explicit_start", lambda *_: None)
    monkeypatch.setattr(guided_search, "inputs",
                        lambda *_: pytest.fail("Pending source computed an implicit proposal"))
    prepared = strategy.prepare_proposals(case.snapshot, context)
    assert prepared["proposals"] == prepared["working_proposals"] == {}
    assert prepared["fit_direction"]["mode"] == "choose_start"
    assert prepared["fit_direction"]["comparison"] == case.previous


@pytest.mark.parametrize("action", ["recover", "recover_start", "confirm", "confirm_start",
                                    "density_comparison", "multiscale_detail"])
def test_direct_transition_cannot_bypass_fresh_starting_choice_gate(case, action):
    before = deepcopy(case.events)
    with pytest.raises(ValueError, match="Choose the inspected starting fit explicitly"):
        strategy.transition(case.snapshot, action, case.identifier, goal="regional:detail")
    assert case.events == before


def test_direct_transition_without_identifier_checks_every_candidate(case):
    with pytest.raises(ValueError, match="Choose the inspected starting fit explicitly"):
        strategy.transition(case.snapshot, "confirm", None)
