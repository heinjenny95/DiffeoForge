"""Sampled distances already measured on the original surfaces during fitting."""

import math


def sampled_fit_label(candidate, target):
    metrics = candidate.metrics or {}
    if metrics.get("fit_scope") != "full_targets":
        return ""
    row = metrics.get("original_surface_fit", {}).get(target, {})
    diagonal, p95, p99 = (row.get(key) for key in ("diagonal", "p95", "p99"))
    if (not all(type(value) in (int, float) and math.isfinite(value)
                for value in (diagonal, p95, p99))
            or diagonal <= 0 or not 0 <= p95 <= p99):
        return ""
    return (f"Surface distance · P95 {p95 / diagonal:.2%} · P99 {p99 / diagonal:.2%} "
            "of original diagonal")
