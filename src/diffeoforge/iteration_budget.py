"""Conservative starting budgets from observed selected pilot fits, never an ETA."""

from __future__ import annotations

import math


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
