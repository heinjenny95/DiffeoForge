"""Shared descriptive residual screen, not a biological acceptance criterion."""

from __future__ import annotations

import math


def inspection_threshold(values: tuple[float, ...]) -> float | None:
    """Upper Tukey fence using linearly interpolated quartiles; unavailable for n < 4."""
    if not values or any(not math.isfinite(value) or value < 0 for value in values):
        raise ValueError("Registration residuals must be nonempty, finite and nonnegative")
    if len(values) < 4:
        return None
    ordered = sorted(values)

    def quartile(fraction: float) -> float:
        position = fraction * (len(ordered) - 1)
        lower = math.floor(position)
        upper = math.ceil(position)
        weight = position - lower
        return ordered[lower] * (1.0 - weight) + ordered[upper] * weight

    q1, q3 = quartile(0.25), quartile(0.75)
    threshold = q3 + 1.5 * (q3 - q1)
    if not math.isfinite(threshold):
        raise ValueError("Registration screening threshold is non-finite")
    return threshold
