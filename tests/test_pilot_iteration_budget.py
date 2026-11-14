"""Pilot effort follows verified checkpoint lineage without adopting its fields."""

import copy
import hashlib

import pytest

from diffeoforge.iteration_budget import (
    CONTINUATION_VERSION,
    recommend_iteration_budget,
    recommend_pilot_iteration_budget,
)


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def completion(stage, identifier, last, cap=None):
    return {
        "event": "candidate_completed",
        "stage_id": stage,
        "candidate_id": identifier,
        "event_hash": digest(stage + identifier + str(last)),
        "metrics": {
            "completed": True,
            "final_iteration": last,
            "maximum_iterations": last if cap is None else cap,
            "runtime_seconds": float(last),
            "invalid_face_count": 0,
            "optimizer_stop_signal": "maximum_iterations",
        },
    }


def continued(events, parent, identifier, *, last=None):
    initial = parent["metrics"]["maximum_iterations"]
    checkpoint = {
        "version": CONTINUATION_VERSION,
        "initial_iteration": initial,
        "additional_iterations": 300,
        "maximum_iterations": initial + 300,
        "checkpoint_sha256": digest(identifier),
        "history": "Native resume",
    }
    declaration = {
        "event": "pilot_qualification_declared",
        "version": CONTINUATION_VERSION,
        "stage_id": parent["stage_id"],
        "candidate": {"candidate_id": identifier},
        "checkpoint_continuation": checkpoint,
        "source": {
            "candidate_id": parent["candidate_id"],
            "completed_event_hash": parent["event_hash"],
        },
    }
    done = completion(
        parent["stage_id"], identifier, initial + 300 if last is None else last, initial + 300
    )
    done["metrics"]["pilot_continuation"] = {
        **checkpoint,
        "source_candidate_id": parent["candidate_id"],
    }
    if last is not None and last < initial + 300:
        done["metrics"]["optimizer_stop_signal"] = "tolerance_threshold"
    events.extend([declaration, done])
    return declaration, done


def observations(events):
    return [
        {
            "stage_id": e["stage_id"],
            "candidate_id": e["candidate_id"],
            **{
                key: e["metrics"][key]
                for key in ("final_iteration", "maximum_iterations", "runtime_seconds")
            },
        }
        for e in events
        if e["event"] == "candidate_completed" and e["candidate_id"] != "retained"
    ]


def history():
    joint = completion("attachment", "joint", 120)
    retained = completion("timepoints", "retained", 120)
    events = [joint, retained]
    declaration, child = continued(events, retained, "continued")
    selected = {"attachment": "joint", "timepoints": "retained"}
    return events, selected, declaration, child


def test_kept_120_field_uses_420_continuation_for_800_budget_without_adoption():
    events, selected, _, _ = history()
    rows = observations(events)
    saved = copy.deepcopy((events, selected, rows))
    assert (
        recommend_iteration_budget(150, rows, selected.values())["suggested_max_iterations"] == 500
    )
    result = recommend_pilot_iteration_budget(150, rows, selected, events)
    assert result["version"] == "2"
    assert result["suggested_max_iterations"] == 800
    assert result["continuation_evidence"][0]["source_candidate_id"] == "retained"
    assert [r["final_iteration"] for r in result["observations"]] == [120, 420]
    assert (events, selected, rows) == saved


def test_repeated_resume_uses_cumulative_counter_once_and_preserves_higher_manual_cap():
    events, selected, _, first = history()
    continued(events, first, "continued-again")
    result = recommend_pilot_iteration_budget(150, observations(events), selected, events)
    assert result["suggested_max_iterations"] == 1100  # max(720 * 1.5, 720 + 300), rounded
    assert [row["maximum_iterations"] for row in result["continuation_evidence"]] == [420, 720]
    assert (
        recommend_pilot_iteration_budget(2000, observations(events), selected, events)[
            "suggested_max_iterations"
        ]
        == 2000
    )
    selected["timepoints"] = "continued"
    assert (
        recommend_pilot_iteration_budget(150, observations(events), selected, events)[
            "suggested_max_iterations"
        ]
        == 1100
    )


@pytest.mark.parametrize(
    "change",
    [
        "other_parent",
        "wrong_version",
        "wrong_source_hash",
        "wrong_initial_counter",
        "changed_checkpoint",
        "not_completed",
        "invalid_geometry",
        "line_search_failure",
        "unknown_stop",
        "missing_lineage",
        "false_cap_stop",
        "over_cap",
        "failed_retry",
        "pending_retry",
    ],
)
def test_unrelated_unverified_failed_or_pending_continuations_do_not_inflate_budget(change):
    events, selected, declaration, child = history()
    if change == "other_parent":
        declaration["source"]["candidate_id"] = "unselected-alternative"
    elif change == "wrong_version":
        declaration["version"] = "different-refinement"
    elif change == "wrong_source_hash":
        declaration["source"]["completed_event_hash"] = digest("other-fit")
    elif change == "wrong_initial_counter":
        declaration["checkpoint_continuation"]["initial_iteration"] = 100
    elif change == "changed_checkpoint":
        child["metrics"]["pilot_continuation"]["checkpoint_sha256"] = digest("changed")
    elif change == "not_completed":
        child["metrics"]["completed"] = False
    elif change == "invalid_geometry":
        child["metrics"]["invalid_face_count"] = 1
    elif change == "line_search_failure":
        child["metrics"]["optimizer_stop_signal"] = "line_search_exhausted"
    elif change == "unknown_stop":
        child["metrics"]["optimizer_stop_signal"] = "unknown"
    elif change == "missing_lineage":
        child["metrics"].pop("pilot_continuation")
    elif change == "false_cap_stop":
        child["metrics"]["final_iteration"] = 419
    elif change == "over_cap":
        child["metrics"]["final_iteration"] = 421
    else:
        events.append(
            {
                "event": "candidate_failed" if change == "failed_retry" else "candidate_started",
                "stage_id": "timepoints",
                "candidate_id": "continued",
            }
        )
    result = recommend_pilot_iteration_budget(150, observations(events), selected, events)
    assert result["suggested_max_iterations"] == 500
    assert result["version"] == "1"


@pytest.mark.parametrize("rejected", [{("timepoints", "continued")}, {("timepoints", "retained")}])
def test_explicitly_rejected_branch_is_excluded(rejected):
    events, selected, _, _ = history()
    result = recommend_pilot_iteration_budget(
        150, observations(events), selected, events, rejected_candidates=rejected
    )
    assert result["suggested_max_iterations"] == 500


def test_other_parameters_stage_collisions_and_stale_attempts_cannot_supply_effort():
    events, selected, _, _ = history()
    events.append(completion("timepoints", "different-parameters", 50_000))
    rows = observations(events)
    rows.append(
        {
            "stage_id": "noise",
            "candidate_id": "continued",
            "final_iteration": 90_000,
            "maximum_iterations": 90_000,
            "runtime_seconds": 9000.0,
        }
    )
    rows.insert(
        0,
        {
            "stage_id": "timepoints",
            "candidate_id": "continued",
            "final_iteration": 900,
            "maximum_iterations": 900,
            "runtime_seconds": 900.0,
        },
    )
    result = recommend_pilot_iteration_budget(150, rows, selected, events)
    assert result["suggested_max_iterations"] == 800
    assert [r["final_iteration"] for r in result["observations"]] == [120, 420]


def test_early_native_stop_uses_observed_steps_instead_of_unspent_allowance():
    events, selected, _, _ = history()
    events = events[:2]
    continued(events, events[1], "early-stop", last=200)
    result = recommend_pilot_iteration_budget(150, observations(events), selected, events)
    assert result["version"] == "2"
    assert result["suggested_max_iterations"] == 500  # Original 120-near-cap still dominates.


def test_imported_verified_parent_hash_can_keep_its_native_continuation_link():
    events, selected, declaration, _ = history()
    parent = events[1]
    parent["imported_source_event_hash"] = parent["event_hash"]
    parent["event_hash"] = digest("imported-parent")
    assert declaration["source"]["completed_event_hash"] == parent["imported_source_event_hash"]
    assert (
        recommend_pilot_iteration_budget(150, observations(events), selected, events)[
            "suggested_max_iterations"
        ]
        == 800
    )
