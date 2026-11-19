"""Read-only, rounding-aware diagnosis for a completed native run."""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal, DecimalException
from pathlib import Path

from diffeoforge.config import ConfigurationError
from diffeoforge.runs import CONVERGENCE_RE, ITERATION_RE, completed_gradient_ascent_history

_TOLERANCE_STOP = "tolerance threshold met"
_OTHER_STOPS = ("number of line search loops exceeded", ">> stop: pilot review request")


@dataclass(frozen=True)
class Observation:
    iteration: int
    objective: float
    rounding: float
    fit_error: float | None = None
    fit_rounding: float = 0.0


def _logged_number(text: str) -> tuple[float, float]:
    try:
        token = Decimal(text)
        value = float(token)
        rounding = float(Decimal(10) ** token.as_tuple().exponent / 2)
    except (DecimalException, OverflowError) as error:
        raise ValueError("Invalid objective history") from error
    if not all(math.isfinite(number) for number in (value, rounding)):
        raise ValueError("Non-finite objective history")
    return value, rounding


def observations(text: str) -> tuple[Observation, ...]:
    rows = []
    iteration = None
    stopped = False
    for line in text.splitlines():
        lower = line.casefold()
        if _TOLERANCE_STOP in lower or any(marker in lower for marker in _OTHER_STOPS):
            stopped = True
            continue
        match = ITERATION_RE.search(line)
        if match:
            iteration = int(match[1])
        match = CONVERGENCE_RE.search(line)
        if match and iteration is not None:
            objective, rounding = _logged_number(match[1])
            attachment, fit_rounding = _logged_number(match[2])
            # A deterministic atlas reports the weighted data discrepancy as a penalty.
            row = Observation(iteration, objective, rounding,
                              -attachment if attachment <= 0 else None, fit_rounding)
            if rows and row == rows[-1]:
                continue
            if stopped or (rows and row.iteration <= rows[-1].iteration):
                # Never combine restarted segments or competing states at one iteration.
                rows = []
                stopped = False
            rows.append(row)
    return tuple(rows)


def _change(start: float, end: float, uncertainty: float, reference: str = "") -> str:
    difference = end - start
    if abs(difference) <= uncertainty:
        return f"change within log rounding (±{uncertainty:.3g})."
    percent = ""
    if abs(start) > uncertainty:
        ratio = 100 * (difference / abs(start))
        if math.isfinite(ratio):
            display = f"{ratio:+.2f}" if abs(ratio) >= 0.01 else f"{ratio:+.2g}"
            percent = f"approx. {display}%{reference}, "
    return f"{difference:+.6g} ({percent}rounding ±{uncertainty:.3g})."


def summarize(rows: tuple[Observation, ...], *, at_iteration_limit: bool = True) -> str:
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
        objective = _change(first.objective, last.objective, uncertainty,
                            " of |window-start objective|")
        fit = "Weighted fit error unavailable for this window."
        if first.fit_error is not None and last.fit_error is not None:
            fit = "Weighted fit error " + _change(
                first.fit_error, last.fit_error, first.fit_rounding + last.fit_rounding)
        windows.append(
            f"Last {last.iteration - first.iteration} iterations "
            f"({first.iteration}–{last.iteration}, {len(segment)} observations). "
            f"Total objective {objective} {fit}"
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
            "Too few closely spaced log entries for a 10- or 50-iteration comparison. "
            "Inspect the saved objective curve."
        )
    if len(windows) < 2:
        missing = 50 if 10 in boundaries else 10
        windows.append(f"The saved log does not support the {missing}-iteration comparison.")
    if "unstable" in classifications:
        recommendation = (
            "The logged objective decreased within a window. Inspect the curve and backend log."
        )
    elif not at_iteration_limit:
        recommendation = (
            "The logged objective improved beyond rounding in at least one window."
            if "improving" in classifications else
            "The log's rounding obscures further change. A plateau is not established."
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
    return "\n".join([*windows, recommendation])


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


def run_advice(source: Path) -> tuple[int | None, str]:
    """Return displayed evidence and, only after a cap, the current extension limit."""
    maximum, log_text, stop = completed_gradient_ascent_history(source)
    capped = stop.signal == "maximum_iterations"
    if not capped and stop.signal != "tolerance_threshold":
        raise ConfigurationError("No supported native tolerance or iteration-limit stop.")
    if not capped:
        last_header = max((match.end() for match in ITERATION_RE.finditer(log_text)), default=0)
        terminal_log = log_text[last_header:].casefold()
        if _TOLERANCE_STOP not in terminal_log or any(
            marker in terminal_log for marker in _OTHER_STOPS
        ):
            raise ConfigurationError(
                "The native tolerance message is not a distinct terminal stop."
            )
    try:
        summary = summarize(observations(log_text), at_iteration_limit=capped)
    except ValueError:
        summary = "The retained log could not support a reliable window comparison."
    if capped:
        heading = f"Native stop · Iteration limit reached ({maximum})"
    else:
        heading = (
            "Native stop · Deformetrica met its objective-change tolerance\n"
            "The windows end at the last logged state. Deformetrica 4.3 skips printing "
            "the accepted step that triggers this stop."
        )
    note = "Weighted fit error is −attachment. Assess the anatomy in Visual QC."
    return maximum if capped else None, "\n".join((heading, summary, note))
