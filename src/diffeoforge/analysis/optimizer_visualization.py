"""Deterministic, dependency-light SVG evidence for atlas optimization."""

from __future__ import annotations

import html
import math
from pathlib import Path

from diffeoforge.engine.atlas_optimizer import AtlasOptimizationResult

_WIDTH = 1000
_HEIGHT = 720
_LEFT = 100.0
_RIGHT = 42.0
_PLOT_WIDTH = _WIDTH - _LEFT - _RIGHT
_OBJECTIVE_TOP = 105.0
_OBJECTIVE_HEIGHT = 285.0
_GRADIENT_TOP = 485.0
_GRADIENT_HEIGHT = 135.0


def _number(value: float) -> str:
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ValueError("SVG values must be finite")
    return format(0.0 if normalized == 0.0 else normalized, ".12g")


def _data_number(value: float) -> str:
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ValueError("SVG data values must be finite")
    return format(0.0 if normalized == 0.0 else normalized, ".17g")


def _extent(values: tuple[float, ...]) -> tuple[float, float]:
    minimum = min(values)
    maximum = max(values)
    span = maximum - minimum
    padding = max(abs(minimum) * 0.05, 1.0) if span == 0 else span * 0.08
    return minimum - padding, maximum + padding


def _x(index: int, count: int) -> float:
    if count == 1:
        return _LEFT + _PLOT_WIDTH / 2.0
    return _LEFT + _PLOT_WIDTH * index / (count - 1)


def _y(value: float, low: float, high: float, *, top: float, height: float) -> float:
    return top + height - ((float(value) - low) / (high - low)) * height


def _polyline(
    values: tuple[float, ...],
    *,
    low: float,
    high: float,
    css_class: str,
    series: str,
) -> str:
    points = " ".join(
        _point(
            index,
            len(values),
            value,
            low,
            high,
            top=_OBJECTIVE_TOP,
            height=_OBJECTIVE_HEIGHT,
        )
        for index, value in enumerate(values)
    )
    return (
        f'  <polyline points="{points}" class="{css_class}" '
        f'data-series="{html.escape(series, quote=True)}"/>'
    )


def _point(
    index: int,
    count: int,
    value: float,
    low: float,
    high: float,
    *,
    top: float,
    height: float,
) -> str:
    return f"{_number(_x(index, count))},{_number(_y(value, low, high, top=top, height=height))}"


def _write_exclusive(path: Path | str, content: str) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(content)
    return destination


def write_optimizer_convergence_svg(
    path: Path | str,
    result: AtlasOptimizationResult,
) -> Path:
    """Write objective and block-gradient trajectories with exact decision metadata."""

    if not isinstance(result, AtlasOptimizationResult):
        raise TypeError("result must be an AtlasOptimizationResult")
    if not result.history:
        raise ValueError("optimizer history must contain at least one observation")

    history = result.history
    objectives = tuple(float(record.objective) for record in history)
    attachments = tuple(float(record.attachment) for record in history)
    regularities = tuple(float(record.regularity) for record in history)
    if not all(
        math.isfinite(value)
        for values in (objectives, attachments, regularities)
        for value in values
    ):
        raise ValueError("optimizer history contains a non-finite objective component")
    component_low, component_high = _extent(objectives + attachments + regularities)
    termination = html.escape(result.termination_reason, quote=True)
    converged = str(result.converged).lower()

    body = [
        (
            '  <text x="500" y="38" text-anchor="middle" class="title">'
            "Atlas optimizer convergence</text>"
        ),
        (
            '  <text x="500" y="66" text-anchor="middle" class="subtitle">'
            f"Termination: {termination} &#183; converged={converged} &#183; "
            f"{result.cycles_completed} of {result.settings.max_cycles} cycles</text>"
        ),
        (
            f'  <g data-termination-reason="{termination}" data-converged="{converged}" '
            f'data-cycles-completed="{result.cycles_completed}" '
            f'data-max-cycles="{result.settings.max_cycles}">'
        ),
        '  <text x="100" y="92" class="section">Objective components (accepted states)</text>',
    ]
    for tick in range(6):
        value = component_low + (component_high - component_low) * tick / 5.0
        y = _y(value, component_low, component_high, top=_OBJECTIVE_TOP, height=_OBJECTIVE_HEIGHT)
        body.extend(
            [
                f'  <line x1="{_number(_LEFT)}" y1="{_number(y)}" '
                f'x2="{_number(_LEFT + _PLOT_WIDTH)}" y2="{_number(y)}" class="grid"/>',
                f'  <text x="{_number(_LEFT - 12)}" y="{_number(y + 4)}" '
                f'text-anchor="end" class="small">{html.escape(_number(value))}</text>',
            ]
        )
    body.extend(
        [
            f'  <line x1="{_number(_LEFT)}" y1="{_number(_OBJECTIVE_TOP)}" '
            f'x2="{_number(_LEFT)}" '
            f'y2="{_number(_OBJECTIVE_TOP + _OBJECTIVE_HEIGHT)}" class="axis"/>',
            f'  <line x1="{_number(_LEFT)}" y1="{_number(_OBJECTIVE_TOP + _OBJECTIVE_HEIGHT)}" '
            f'x2="{_number(_LEFT + _PLOT_WIDTH)}" '
            f'y2="{_number(_OBJECTIVE_TOP + _OBJECTIVE_HEIGHT)}" class="axis"/>',
            _polyline(
                objectives,
                low=component_low,
                high=component_high,
                css_class="objective",
                series="objective",
            ),
            _polyline(
                attachments,
                low=component_low,
                high=component_high,
                css_class="attachment",
                series="attachment",
            ),
            _polyline(
                regularities,
                low=component_low,
                high=component_high,
                css_class="regularity",
                series="regularity",
            ),
        ]
    )
    for index, record in enumerate(history):
        x = _x(index, len(history))
        y = _y(
            record.objective,
            component_low,
            component_high,
            top=_OBJECTIVE_TOP,
            height=_OBJECTIVE_HEIGHT,
        )
        block = "initial" if record.block is None else record.block
        body.extend(
            [
                (
                    f'  <circle cx="{_number(x)}" cy="{_number(y)}" r="4" '
                    f'class="objective-point" data-history-index="{index}" '
                    f'data-cycle="{record.cycle}" data-block="{html.escape(block, quote=True)}" '
                    f'data-status="{html.escape(record.status, quote=True)}" '
                    f'data-objective="{_data_number(record.objective)}" '
                    f'data-attachment="{_data_number(record.attachment)}" '
                    f'data-regularity="{_data_number(record.regularity)}">'
                ),
                (
                    f"    <title>cycle {record.cycle}; {html.escape(block)}; "
                    f"objective {_number(record.objective)}</title>"
                ),
                "  </circle>",
            ]
        )
        if index == 0 or index == len(history) - 1:
            anchor = "start" if index == 0 else "end"
            body.append(
                f'  <text x="{_number(x)}" y="{_number(_OBJECTIVE_TOP + _OBJECTIVE_HEIGHT + 22)}" '
                f'text-anchor="{anchor}" class="small">decision {index}</text>'
            )
    body.extend(
        [
            '  <line x1="116" y1="425" x2="146" y2="425" class="objective"/>',
            '  <text x="154" y="429" class="small">objective</text>',
            '  <line x1="270" y1="425" x2="300" y2="425" class="attachment"/>',
            '  <text x="308" y="429" class="small">attachment</text>',
            '  <line x1="438" y1="425" x2="468" y2="425" class="regularity"/>',
            '  <text x="476" y="429" class="small">regularity</text>',
            '  <text x="100" y="468" class="section">Block gradient norm (log10 scale)</text>',
        ]
    )

    gradient_records = tuple(
        (index, float(record.gradient_norm))
        for index, record in enumerate(history)
        if record.gradient_norm is not None
    )
    if gradient_records:
        if any(not math.isfinite(value) or value < 0 for _, value in gradient_records):
            raise ValueError("optimizer history contains an invalid gradient norm")
        positive_values = [value for _, value in gradient_records if value > 0]
        tolerance = float(result.settings.gradient_tolerance)
        if tolerance > 0:
            positive_values.append(tolerance)
        floor = min(positive_values) / 10.0 if positive_values else 1e-16
        log_values = tuple(math.log10(max(value, floor)) for _, value in gradient_records)
        log_low, log_high = _extent(
            log_values + ((math.log10(tolerance),) if tolerance > 0 else ())
        )
        for tick in range(4):
            value = log_low + (log_high - log_low) * tick / 3.0
            y = _y(value, log_low, log_high, top=_GRADIENT_TOP, height=_GRADIENT_HEIGHT)
            body.extend(
                [
                    f'  <line x1="{_number(_LEFT)}" y1="{_number(y)}" '
                    f'x2="{_number(_LEFT + _PLOT_WIDTH)}" y2="{_number(y)}" class="grid"/>',
                    f'  <text x="{_number(_LEFT - 12)}" y="{_number(y + 4)}" '
                    f'text-anchor="end" class="small">10^{_number(value)}</text>',
                ]
            )
        if tolerance > 0:
            tolerance_y = _y(
                math.log10(tolerance),
                log_low,
                log_high,
                top=_GRADIENT_TOP,
                height=_GRADIENT_HEIGHT,
            )
            body.extend(
                [
                    f'  <line x1="{_number(_LEFT)}" y1="{_number(tolerance_y)}" '
                    f'x2="{_number(_LEFT + _PLOT_WIDTH)}" y2="{_number(tolerance_y)}" '
                    f'class="tolerance" data-gradient-tolerance="{_data_number(tolerance)}"/>',
                    f'  <text x="{_number(_LEFT + _PLOT_WIDTH - 4)}" '
                    f'y="{_number(tolerance_y - 6)}" '
                    f'text-anchor="end" class="small">tolerance {_number(tolerance)}</text>',
                ]
            )
        gradient_points = " ".join(
            _point(
                index,
                len(history),
                log_value,
                log_low,
                log_high,
                top=_GRADIENT_TOP,
                height=_GRADIENT_HEIGHT,
            )
            for (index, _), log_value in zip(gradient_records, log_values, strict=True)
        )
        body.append(
            f'  <polyline points="{gradient_points}" class="gradient" data-series="gradient_norm"/>'
        )
        for (index, value), log_value in zip(gradient_records, log_values, strict=True):
            gradient_y = _y(
                log_value,
                log_low,
                log_high,
                top=_GRADIENT_TOP,
                height=_GRADIENT_HEIGHT,
            )
            body.append(
                f'  <circle cx="{_number(_x(index, len(history)))}" '
                f'cy="{_number(gradient_y)}" '
                f'r="3.5" class="gradient-point" data-history-index="{index}" '
                f'data-gradient-norm="{_data_number(value)}"/>'
            )
    else:
        body.append(
            '  <text x="500" y="555" text-anchor="middle" class="subtitle">'
            "No block-gradient observations were recorded.</text>"
        )
    body.extend(
        [
            f'  <line x1="{_number(_LEFT)}" y1="{_number(_GRADIENT_TOP + _GRADIENT_HEIGHT)}" '
            f'x2="{_number(_LEFT + _PLOT_WIDTH)}" '
            f'y2="{_number(_GRADIENT_TOP + _GRADIENT_HEIGHT)}" class="axis"/>',
            (
                '  <text x="500" y="680" text-anchor="middle" class="label">'
                "Accepted optimizer decision</text>"
            ),
            "  </g>",
        ]
    )
    document = "\n".join(
        [
            '<?xml version="1.0" encoding="UTF-8"?>',
            (
                f'<svg xmlns="http://www.w3.org/2000/svg" width="{_WIDTH}" '
                f'height="{_HEIGHT}" viewBox="0 0 {_WIDTH} {_HEIGHT}" role="img">'
            ),
            "  <title>Atlas optimizer convergence</title>",
            "  <style>",
            "    .axis { stroke: #263238; stroke-width: 1.5; }",
            "    .grid { stroke: #dce4e7; stroke-width: 1; }",
            "    .label { fill: #263238; font-family: Arial; font-size: 14px; }",
            "    .small { fill: #455a64; font-family: Arial; font-size: 12px; }",
            "    .subtitle { fill: #455a64; font-family: Arial; font-size: 14px; }",
            (
                "    .section { fill: #102a43; font-family: Arial; font-size: 15px; "
                "font-weight: bold; }"
            ),
            (
                "    .title { fill: #102a43; font-family: Arial; font-size: 22px; "
                "font-weight: bold; }"
            ),
            "    .objective { fill: none; stroke: #00796b; stroke-width: 2.5; }",
            "    .attachment { fill: none; stroke: #ef6c00; stroke-width: 2; }",
            "    .regularity { fill: none; stroke: #6a1b9a; stroke-width: 2; }",
            "    .objective-point { fill: #00796b; stroke: #ffffff; stroke-width: 1; }",
            "    .gradient { fill: none; stroke: #1565c0; stroke-width: 2.5; }",
            "    .gradient-point { fill: #1565c0; }",
            "    .tolerance { stroke: #c62828; stroke-width: 1.5; stroke-dasharray: 7 5; }",
            "  </style>",
            f'  <rect width="{_WIDTH}" height="{_HEIGHT}" fill="#ffffff"/>',
            *body,
            "</svg>",
            "",
        ]
    )
    return _write_exclusive(path, document)
