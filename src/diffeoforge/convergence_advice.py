"""Read-only, rounding-aware advice for an explicitly capped native run."""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from diffeoforge.runs import CONVERGENCE_RE, ITERATION_RE, iteration_extension_limit


@dataclass(frozen=True)
class Observation:
    iteration: int
    objective: float
    rounding: float


def observations(text: str) -> tuple[Observation, ...]:
    rows = []
    iteration = None
    for line in text.splitlines():
        match = ITERATION_RE.search(line)
        if match:
            iteration = int(match[1])
        match = CONVERGENCE_RE.search(line)
        if match and iteration is not None:
            token = Decimal(match[1])
            row = Observation(
                iteration, float(token), float(Decimal(10) ** token.as_tuple().exponent) / 2
            )
            if not all(math.isfinite(v) for v in (row.objective, row.rounding)):
                raise ValueError("Non-finite objective history")
            if rows and row == rows[-1]:
                continue
            if rows and row.iteration <= rows[-1].iteration:
                # Never combine restarted segments or competing states at one iteration.
                rows = []
            rows.append(row)
    return tuple(rows)


def summarize(rows: tuple[Observation, ...]) -> str:
    windows = []
    classifications = []
    boundaries = {}
    for span in (10, 50):
        if not rows or rows[-1].iteration - rows[0].iteration < span:
            continue
        last = rows[-1]
        first = next((r for r in reversed(rows) if r.iteration <= last.iteration - span), None)
        if first is None or last.iteration - first.iteration > span * 1.2:
            continue
        segment = [r for r in rows if first.iteration <= r.iteration <= last.iteration]
        if len(segment) < 3 or any(
            b.iteration - a.iteration > max(5, span / 5)
            for a, b in zip(segment, segment[1:], strict=False)
        ):
            continue
        gain = last.objective - first.objective
        uncertainty = first.rounding + last.rounding
        denominator = abs(first.objective)
        relative = (
            f" ({100 * gain / denominator:.4g}% of |starting objective|)"
            if denominator > uncertainty
            else ""
        )
        windows.append(
            f"Last {last.iteration - first.iteration} iterations: {gain:+.6g}{relative}; "
            f"{len(segment)} observations; rounding ±{uncertainty:.3g}."
        )
        boundaries[span] = first
        decreasing = any(
            b.objective + b.rounding < a.objective - a.rounding
            for a, b in zip(segment, segment[1:], strict=False)
        )
        classifications.append(
            "unstable" if decreasing else "improving" if gain > uncertainty else "unresolved"
        )
    if not windows:
        return (
            "Too few closely spaced objective observations to recommend more iterations. "
            "Inspect the curve before continuing."
        )
    if "unstable" in classifications:
        recommendation = (
            "The objective decreased within this window. "
            "Inspect the curve and backend log before continuing."
        )
    elif _slowing(rows, boundaries):
        recommendation = (
            "Improvement is flattening: the recent per-iteration gain is below a quarter "
            "of the preceding window's rate, allowing for log rounding. "
            "+300 is optional; review the curve before allocating more time. "
            "The quarter-rate cutoff is a heuristic."
        )
    elif "improving" in classifications:
        recommendation = (
            "The objective was still improving beyond log rounding. "
            "Consider +300 iterations, then reassess."
        )
    else:
        recommendation = (
            "Further improvement is smaller than the log's rounding precision. "
            "A plateau is not established; +300 is optional."
        )
    return "\n".join(
        windows
        + [
            recommendation,
            "This advice does not establish native convergence or anatomical quality.",
        ]
    )


def _slowing(rows, boundaries):
    if set(boundaries) != {10, 50}:
        return False
    recent, older, last = boundaries[10], boundaries[50], rows[-1]
    old_span = recent.iteration - older.iteration
    if old_span <= 0:
        return False
    old_lower = (recent.objective - older.objective - recent.rounding - older.rounding) / old_span
    new_upper = (last.objective - recent.objective + last.rounding + recent.rounding) / (
        last.iteration - recent.iteration
    )
    return old_lower > 0 and new_upper < 0.25 * old_lower


def capped_run_advice(source: Path) -> tuple[int, str]:
    maximum = iteration_extension_limit(source)
    try:
        text = (source / "logs/deformetrica.log").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return maximum, (
            "Objective history is unavailable. Review the saved result before continuing."
        )
    return maximum, summarize(observations(text))
