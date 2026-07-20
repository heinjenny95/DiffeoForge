"""Deterministic SVG evidence for a Deformetrica objective history."""

from __future__ import annotations

import html
import math
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from diffeoforge.result_report import ConvergenceRow

ReferenceStopSignal = Literal[
    "tolerance_threshold",
    "maximum_iterations",
    "line_search_exhausted",
    "unknown",
]

_WIDTH = 1100
_HEIGHT = 720
_LEFT = 92.0
_RIGHT = 38.0
_PLOT_WIDTH = _WIDTH - _LEFT - _RIGHT


@dataclass(frozen=True)
class ReferenceStopEvidence:
    """Bounded interpretation of one terminal Deformetrica log."""

    signal: ReferenceStopSignal
    summary: str
    final_state_visibility: str


def detect_reference_stop_evidence(
    log_text: str,
    *,
    final_iteration: int | None,
    maximum_iterations: int,
) -> ReferenceStopEvidence:
    """Classify only explicit terminal evidence; never infer scientific convergence."""

    if not isinstance(log_text, str):
        raise TypeError("log_text must be a string")
    if maximum_iterations < 1:
        raise ValueError("maximum_iterations must be positive")
    normalized = log_text.casefold()
    if "tolerance threshold met" in normalized:
        return ReferenceStopEvidence(
            "tolerance_threshold",
            (
                "Deformetrica reported that its internal objective-change tolerance was met. "
                "This is an optimizer stop signal, not proof of adequate registration or "
                "scientific convergence."
            ),
            (
                "Deformetrica 4.3 does not print the final accepted step that triggers this "
                "test; the curve therefore ends at the preceding logged state."
            ),
        )
    if "number of line search loops exceeded" in normalized:
        return ReferenceStopEvidence(
            "line_search_exhausted",
            (
                "The terminal log reports a line-search limit or failure. This is not an "
                "optimizer-convergence claim."
            ),
            "The plot contains every objective state recorded in convergence.csv.",
        )
    if final_iteration is not None and final_iteration >= maximum_iterations:
        return ReferenceStopEvidence(
            "maximum_iterations",
            (
                f"The observed history reached the configured maximum of "
                f"{maximum_iterations} iterations. Reaching that limit is not convergence."
            ),
            "The plot contains every objective state recorded in convergence.csv.",
        )
    return ReferenceStopEvidence(
        "unknown",
        (
            "No supported terminal stop signal was found in the captured Deformetrica log. "
            "Process completion alone does not establish convergence."
        ),
        "The plot contains every objective state recorded in convergence.csv.",
    )


def _number(value: float) -> str:
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ValueError("SVG values must be finite")
    return format(0.0 if normalized == 0.0 else normalized, ".12g")


def _tick(value: float) -> str:
    return format(0.0 if value == 0.0 else value, ".4g")


def _extent(values: Sequence[float]) -> tuple[float, float]:
    low = min(values)
    high = max(values)
    span = high - low
    padding = span * 0.08 if span else max(abs(low) * 0.05, 1.0)
    return low - padding, high + padding


def _x(iteration: int, low: int, high: int) -> float:
    if high == low:
        return _LEFT + _PLOT_WIDTH / 2.0
    return _LEFT + (iteration - low) / (high - low) * _PLOT_WIDTH


def _y(value: float, low: float, high: float, top: float, height: float) -> float:
    return top + height - (value - low) / (high - low) * height


def _polyline(
    rows: Sequence[ConvergenceRow],
    values: Sequence[float],
    *,
    x_low: int,
    x_high: int,
    y_low: float,
    y_high: float,
    top: float,
    height: float,
    css_class: str,
) -> str:
    points = " ".join(
        f"{_number(_x(row.iteration, x_low, x_high))},"
        f"{_number(_y(value, y_low, y_high, top, height))}"
        for row, value in zip(rows, values, strict=True)
    )
    return f'  <polyline points="{points}" class="{css_class}"/>'


def reference_convergence_svg(
    rows: Sequence[ConvergenceRow],
    *,
    maximum_iterations: int,
    duration_seconds: float,
    stop_evidence: ReferenceStopEvidence,
) -> str:
    """Return a fixed-layout, script-free objective-history SVG."""

    observations = tuple(rows)
    if not observations:
        raise ValueError("at least one convergence observation is required")
    if maximum_iterations < 1:
        raise ValueError("maximum_iterations must be positive")
    if not math.isfinite(duration_seconds) or duration_seconds < 0:
        raise ValueError("duration_seconds must be finite and nonnegative")
    iterations = tuple(row.iteration for row in observations)
    if any(
        right <= left for left, right in zip(iterations, iterations[1:], strict=False)
    ):
        raise ValueError("convergence iterations must be strictly increasing")
    series = tuple(
        tuple(float(getattr(row, name)) for row in observations)
        for name in ("log_likelihood", "attachment", "regularity")
    )
    if any(not math.isfinite(value) for values in series for value in values):
        raise ValueError("convergence values must be finite")

    x_low, x_high = iterations[0], iterations[-1]
    upper_top, upper_height = 105.0, 245.0
    lower_top, lower_height = 430.0, 155.0
    upper_low, upper_high = _extent((*series[0], *series[1]))
    regularity_low, regularity_high = _extent(series[2])
    body: list[str] = [
        '  <rect width="1100" height="720" fill="#ffffff"/>',
        '  <text x="92" y="42" class="title">Deformetrica objective history</text>',
        (
            f'  <text x="92" y="68" class="subtitle">{len(observations)} logged states; '
            f'last logged iteration {x_high} of maximum {maximum_iterations}; runtime '
            f'{duration_seconds:.1f} s</text>'
        ),
    ]
    for top, height, low, high in (
        (upper_top, upper_height, upper_low, upper_high),
        (lower_top, lower_height, regularity_low, regularity_high),
    ):
        for index in range(5):
            value = low + (high - low) * index / 4.0
            y = _y(value, low, high, top, height)
            body.extend(
                [
                    f'  <line x1="{_number(_LEFT)}" y1="{_number(y)}" '
                    f'x2="{_number(_LEFT + _PLOT_WIDTH)}" y2="{_number(y)}" class="grid"/>',
                    f'  <text x="82" y="{_number(y + 4)}" text-anchor="end" '
                    f'class="tick">{html.escape(_tick(value))}</text>',
                ]
            )
    for index in range(6):
        value = round(x_low + (x_high - x_low) * index / 5.0)
        x = _x(value, x_low, x_high)
        body.extend(
            [
                f'  <line x1="{_number(x)}" y1="{_number(upper_top)}" '
                f'x2="{_number(x)}" y2="{_number(upper_top + upper_height)}" class="grid"/>',
                f'  <line x1="{_number(x)}" y1="{_number(lower_top)}" '
                f'x2="{_number(x)}" y2="{_number(lower_top + lower_height)}" class="grid"/>',
                f'  <text x="{_number(x)}" y="608" text-anchor="middle" '
                f'class="tick">{value}</text>',
            ]
        )
    body.extend(
        [
            _polyline(
                observations,
                series[0],
                x_low=x_low,
                x_high=x_high,
                y_low=upper_low,
                y_high=upper_high,
                top=upper_top,
                height=upper_height,
                css_class="likelihood",
            ),
            _polyline(
                observations,
                series[1],
                x_low=x_low,
                x_high=x_high,
                y_low=upper_low,
                y_high=upper_high,
                top=upper_top,
                height=upper_height,
                css_class="attachment",
            ),
            _polyline(
                observations,
                series[2],
                x_low=x_low,
                x_high=x_high,
                y_low=regularity_low,
                y_high=regularity_high,
                top=lower_top,
                height=lower_height,
                css_class="regularity",
            ),
            '  <text x="92" y="94" class="panel">Logged objective and attachment</text>',
            '  <line x1="780" y1="88" x2="815" y2="88" class="likelihood"/>',
            '  <text x="823" y="93" class="legend">log-likelihood</text>',
            '  <line x1="935" y1="88" x2="970" y2="88" class="attachment"/>',
            '  <text x="978" y="93" class="legend">attachment</text>',
            '  <text x="92" y="417" class="panel">Logged regularity term</text>',
            '  <text x="577" y="638" text-anchor="middle" '
            'class="axis-label">Logged iteration</text>',
            '  <text x="28" y="228" text-anchor="middle" class="axis-label" '
            'transform="rotate(-90 28 228)">Objective value</text>',
            '  <text x="28" y="507" text-anchor="middle" class="axis-label" '
            'transform="rotate(-90 28 507)">Regularity</text>',
            (
                f'  <text x="92" y="674" class="note">Stop signal: '
                f'{html.escape(stop_evidence.signal.replace("_", " "))}. '
                f'{html.escape(stop_evidence.final_state_visibility)}</text>'
            ),
            '  <text x="92" y="699" class="note">A completed or improving curve does not '
            'by itself establish adequate registration or scientific convergence.</text>',
        ]
    )
    return "\n".join(
        [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<svg xmlns="http://www.w3.org/2000/svg" width="1100" height="720" '
            'viewBox="0 0 1100 720" role="img">',
            "  <title>Deformetrica objective history</title>",
            "  <style>",
            "    text { font-family: Arial, sans-serif; fill: #17343a; }",
            "    .title { font-size: 22px; font-weight: 700; }",
            "    .subtitle { font-size: 13px; fill: #52666b; }",
            "    .panel { font-size: 14px; font-weight: 700; }",
            "    .tick { font-size: 11px; fill: #52666b; }",
            "    .axis-label { font-size: 13px; font-weight: 600; }",
            "    .legend { font-size: 11px; fill: #52666b; }",
            "    .note { font-size: 11px; fill: #52666b; }",
            "    .grid { stroke: #dfe8e9; stroke-width: 1; }",
            "    polyline { fill: none; stroke-linejoin: round; stroke-linecap: round; }",
            "    .likelihood { stroke: #087f6b; stroke-width: 2.5; fill: none; }",
            "    .attachment { stroke: #2c6e9b; stroke-width: 2; fill: none; }",
            "    .regularity { stroke: #b86620; stroke-width: 2.5; fill: none; }",
            "  </style>",
            *body,
            "</svg>",
            "",
        ]
    )


def write_reference_convergence_svg(
    path: Path | str,
    rows: Sequence[ConvergenceRow],
    *,
    maximum_iterations: int,
    duration_seconds: float,
    stop_evidence: ReferenceStopEvidence,
) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    content = reference_convergence_svg(
        rows,
        maximum_iterations=maximum_iterations,
        duration_seconds=duration_seconds,
        stop_evidence=stop_evidence,
    )
    with destination.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(content)
    return destination
