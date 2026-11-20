"""Conservative starting budgets from observed selected pilot fits, never an ETA."""

from __future__ import annotations

import math
from collections.abc import Mapping

CONTINUATION_VERSION = "native-pilot-continuation-v1"


def recommend_iteration_budget(current: int, observations, selected_ids) -> dict:
    selected = set(selected_ids)
    evidence = [
        row
        for row in observations
        if row["candidate_id"] in selected
        and int(row["final_iteration"]) > 0
        and int(row["maximum_iterations"]) > 0
    ]
    required = current
    near_cap = False
    for row in evidence:
        last, cap = int(row["final_iteration"]), int(row["maximum_iterations"])
        near_cap |= last >= 0.9 * cap
        required = max(required, math.ceil(last * 1.5), cap + 300 if last >= 0.9 * cap else 0)
    suggested = max(current, min(100_000, math.ceil(required / 100) * 100)) if evidence else current
    return {
        "version": "1",
        "suggested_max_iterations": suggested,
        "previous_max_iterations": current,
        "observations": evidence,
        "pilot_near_iteration_cap": near_cap,
        "reason": (
            "Retain the higher declared budget; further increases require a manual budget."
            if current >= 100_000
            else "A selected pilot used at least 90% of its cap; add headroom."
            if near_cap
            else "Allow headroom above the selected pilot's observed iterations."
            if evidence
            else "No matching pilot timing evidence; retain the declared budget."
        ),
        "boundary": "A starting budget, not predicted convergence. Control/timepoint counts affect "
        "work per iteration; only the native tolerance stop establishes convergence.",
    }


def recommend_pilot_iteration_budget(
    current: int,
    observations,
    selected_by_stage,
    events,
    *,
    rejected_candidates=(),
) -> dict:
    """Include completed native checkpoint descendants of the selected pilot.

    The caller supplies the already verified study journal. Continuations add
    effort evidence only: they do not adopt a field or confer visual approval.
    Other parameter candidates and uncompleted/rejected branches stay excluded.
    """
    legacy = recommend_iteration_budget(current, observations, selected_by_stage.values())
    selected = {(stage, identifier) for stage, identifier in selected_by_stage.items()}
    rejected = set(rejected_candidates)
    completed, latest, declarations = {}, {}, []
    for event in events:
        kind = event.get("event")
        key = event.get("stage_id"), event.get("candidate_id")
        if kind in {
            "candidate_started",
            "candidate_completed",
            "candidate_failed",
            "candidate_cancelled",
            "candidate_interrupted",
            "candidate_stopped",
        }:
            latest[key] = kind
        if kind == "candidate_completed":
            completed[key] = event
        elif (
            kind == "pilot_qualification_declared" and event.get("version") == CONTINUATION_VERSION
        ):
            declarations.append(event)
    eligible, included = selected - rejected, {}
    # A native continuation restores one cumulative counter. Follow the chain;
    # never add the parent's total again or choose unrelated high-cap options.
    for _ in range(len(declarations)):
        changed = False
        for declaration in declarations:
            stage = declaration.get("stage_id")
            key = stage, declaration.get("candidate", {}).get("candidate_id")
            parent_key = stage, declaration.get("source", {}).get("candidate_id")
            if key in eligible or key in rejected or parent_key not in eligible:
                continue
            child, parent = completed.get(key), completed.get(parent_key)
            checkpoint = declaration.get("checkpoint_continuation", {})
            if (
                child is None
                or parent is None
                or latest.get(key) != "candidate_completed"
                or latest.get(parent_key) != "candidate_completed"
                or checkpoint.get("version") != CONTINUATION_VERSION
            ):
                continue
            source_hash = declaration.get("source", {}).get("completed_event_hash")
            if not source_hash or source_hash not in {
                parent.get("event_hash"),
                parent.get("imported_source_event_hash"),
            }:
                continue
            metrics, parent_metrics = child.get("metrics", {}), parent.get("metrics", {})
            if not isinstance(metrics, Mapping) or not isinstance(parent_metrics, Mapping):
                continue
            initial, extra, cap = (
                checkpoint.get(name)
                for name in ("initial_iteration", "additional_iterations", "maximum_iterations")
            )
            if (
                any(type(value) is not int for value in (initial, extra, cap))
                or initial <= 0
                or extra != 300
                or cap != initial + extra
                or parent_metrics.get("final_iteration") != initial
                or parent_metrics.get("maximum_iterations") != initial
                or metrics.get("pilot_continuation")
                != {**checkpoint, "source_candidate_id": parent_key[1]}
                or metrics.get("completed") is not True
                or metrics.get("invalid_face_count") != 0
                or type(metrics.get("final_iteration")) is not int
                or not initial <= metrics["final_iteration"] <= cap
                or metrics.get("maximum_iterations") != cap
                or metrics.get("optimizer_stop_signal")
                not in {"maximum_iterations", "tolerance_threshold"}
                or (
                    metrics["optimizer_stop_signal"] == "maximum_iterations"
                    and metrics["final_iteration"] != cap
                )
            ):
                continue
            eligible.add(key)
            included[key] = {
                "stage_id": stage,
                "candidate_id": key[1],
                "source_candidate_id": parent_key[1],
                "source_completed_event_hash": source_hash,
                "completed_event_hash": child["event_hash"],
                "initial_iteration": initial,
                "additional_iterations": extra,
                "maximum_iterations": cap,
            }
            changed = True
        if not changed:
            break
    matching = []
    for row in observations:
        key = row.get("stage_id"), row.get("candidate_id")
        if key not in eligible:
            continue
        if key in included:
            metrics = completed[key]["metrics"]
            if any(
                row.get(name) != metrics.get(name)
                for name in ("final_iteration", "maximum_iterations", "runtime_seconds")
            ):
                continue
        matching.append(row)
    counted = {(row["stage_id"], row["candidate_id"]) for row in matching} & included.keys()
    if not counted:
        return legacy
    budget = recommend_iteration_budget(
        current, matching, [row["candidate_id"] for row in matching]
    )
    budget.update(
        version="2",
        evidence_policy="selected-pilot-native-continuations-v1",
        continuation_evidence=[included[key] for key in sorted(counted)],
        evidence_scope="Iteration effort of the selected pilot and matching native checkpoint "
        "continuations; retained fields and visual decisions are unchanged.",
    )
    last = max(row["final_iteration"] for row in budget["observations"])
    budget["reason"] = (
        f"Includes matching completed pilot checkpoint continuations through {last} iterations."
    )
    return budget
