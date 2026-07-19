"""Deterministic, dependency-light SVG views of declared PCA products."""

from __future__ import annotations

import html
import math
from numbers import Integral
from pathlib import Path

import numpy as np

from diffeoforge.analysis.pca import PCAResult

_WIDTH = 900
_HEIGHT = 600
_LEFT = 90.0
_RIGHT = 35.0
_TOP = 70.0
_BOTTOM = 90.0
_PLOT_WIDTH = _WIDTH - _LEFT - _RIGHT
_PLOT_HEIGHT = _HEIGHT - _TOP - _BOTTOM


def _number(value: float) -> str:
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ValueError("SVG values must be finite")
    return format(0.0 if normalized == 0.0 else normalized, ".12g")


def _percent(value: float) -> str:
    return f"{float(value) * 100.0:.2f}%"


def _extent(values: np.ndarray) -> tuple[float, float]:
    minimum = float(np.min(values))
    maximum = float(np.max(values))
    span = maximum - minimum
    if span == 0.0:
        padding = max(abs(minimum) * 0.05, 1.0)
    else:
        padding = span * 0.08
    return minimum - padding, maximum + padding


def _map(value: float, low: float, high: float, start: float, length: float) -> float:
    return start + ((float(value) - low) / (high - low)) * length


def _svg_document(title: str, body: list[str]) -> str:
    escaped_title = html.escape(title, quote=True)
    return "\n".join(
        [
            '<?xml version="1.0" encoding="UTF-8"?>',
            (
                f'<svg xmlns="http://www.w3.org/2000/svg" width="{_WIDTH}" '
                f'height="{_HEIGHT}" viewBox="0 0 {_WIDTH} {_HEIGHT}" '
                'role="img">'
            ),
            f"  <title>{escaped_title}</title>",
            "  <style>",
            "    .axis { stroke: #263238; stroke-width: 1.5; }",
            "    .grid { stroke: #dce4e7; stroke-width: 1; }",
            "    .label { fill: #263238; font: 14px sans-serif; }",
            "    .small { fill: #455a64; font: 12px sans-serif; }",
            "    .title { fill: #102a43; font: bold 22px sans-serif; }",
            "    .bar { fill: #1976d2; }",
            "    .point { fill: #d84315; stroke: #ffffff; stroke-width: 1; }",
            "  </style>",
            f'  <rect width="{_WIDTH}" height="{_HEIGHT}" fill="#ffffff"/>',
            *body,
            "</svg>",
            "",
        ]
    )


def _write_exclusive(path: Path | str, content: str) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(content)
    return destination


def write_pca_scree_svg(path: Path | str, pca: PCAResult) -> Path:
    """Write a fixed-layout scree plot with exact retained variance percentages."""

    if not isinstance(pca, PCAResult):
        raise TypeError("pca must be a PCAResult")
    ratios = pca.explained_variance_ratio
    maximum = max(float(np.max(ratios)) * 1.12, 0.01)
    bar_slot = _PLOT_WIDTH / pca.number_of_components
    bar_width = min(bar_slot * 0.68, 80.0)
    label_stride = max(1, math.ceil(pca.number_of_components / 20))
    show_percent_labels = pca.number_of_components <= 20
    body = [
        '  <text x="450" y="38" text-anchor="middle" class="title">PCA scree plot</text>',
    ]
    for tick in range(6):
        value = maximum * tick / 5.0
        y = _TOP + _PLOT_HEIGHT - (value / maximum) * _PLOT_HEIGHT
        body.extend(
            [
                f'  <line x1="{_number(_LEFT)}" y1="{_number(y)}" '
                f'x2="{_number(_LEFT + _PLOT_WIDTH)}" y2="{_number(y)}" class="grid"/>',
                f'  <text x="{_number(_LEFT - 10)}" y="{_number(y + 4)}" '
                f'text-anchor="end" class="small">{_percent(value)}</text>',
            ]
        )
    body.extend(
        [
            f'  <line x1="{_number(_LEFT)}" y1="{_number(_TOP)}" '
            f'x2="{_number(_LEFT)}" y2="{_number(_TOP + _PLOT_HEIGHT)}" class="axis"/>',
            f'  <line x1="{_number(_LEFT)}" y1="{_number(_TOP + _PLOT_HEIGHT)}" '
            f'x2="{_number(_LEFT + _PLOT_WIDTH)}" '
            f'y2="{_number(_TOP + _PLOT_HEIGHT)}" class="axis"/>',
        ]
    )
    for index, ratio in enumerate(ratios):
        x = _LEFT + index * bar_slot + (bar_slot - bar_width) / 2.0
        height = (float(ratio) / maximum) * _PLOT_HEIGHT
        y = _TOP + _PLOT_HEIGHT - height
        component = f"PC{index + 1}"
        body.extend(
            [
                f'  <rect x="{_number(x)}" y="{_number(y)}" '
                f'width="{_number(bar_width)}" height="{_number(height)}" class="bar">',
                f"    <title>{component}: {_percent(float(ratio))}</title>",
                "  </rect>",
            ]
        )
        if index % label_stride == 0 or index == pca.number_of_components - 1:
            body.append(
                f'  <text x="{_number(x + bar_width / 2.0)}" '
                f'y="{_number(_TOP + _PLOT_HEIGHT + 24)}" text-anchor="middle" '
                f'class="label">{component}</text>'
            )
        if show_percent_labels:
            body.append(
                f'  <text x="{_number(x + bar_width / 2.0)}" y="{_number(y - 8)}" '
                f'text-anchor="middle" class="small">{_percent(float(ratio))}</text>'
            )
    body.extend(
        [
            f'  <text x="{_number(_LEFT + _PLOT_WIDTH / 2.0)}" y="565" '
            'text-anchor="middle" class="label">Retained principal component</text>',
            '  <text x="22" y="290" text-anchor="middle" class="label" '
            'transform="rotate(-90 22 290)">Explained total variance</text>',
        ]
    )
    return _write_exclusive(path, _svg_document("PCA scree plot", body))


def _component_axis_label(pca: PCAResult, index: int) -> str:
    component = f"PC{index + 1}"
    ratio = _percent(float(pca.explained_variance_ratio[index]))
    if index in pca.zero_variance_components:
        return f"{component} ({ratio}; numerical zero-variance component)"
    return f"{component} ({ratio})"


def _write_pca_score_view(
    path: Path | str,
    pca: PCAResult,
    *,
    x_index: int,
    y_index: int | None,
) -> Path:
    x_zero_variance = x_index in pca.zero_variance_components
    y_zero_variance = y_index is not None and y_index in pca.zero_variance_components
    x_values = (
        np.zeros(pca.scores.shape[0], dtype=np.float64)
        if x_zero_variance
        else pca.scores[:, x_index]
    )
    y_values = (
        np.zeros_like(x_values) if y_index is None or y_zero_variance else pca.scores[:, y_index]
    )
    x_low, x_high = _extent(x_values)
    y_low, y_high = (-1.0, 1.0) if y_index is None else _extent(y_values)
    x_axis = _component_axis_label(pca, x_index)
    y_axis = (
        "Single-component strip (no PC2 retained)"
        if y_index is None
        else _component_axis_label(pca, y_index)
    )
    title = (
        "PCA subject scores: PC1 strip"
        if y_index is None
        else f"PCA subject scores: PC{x_index + 1} vs PC{y_index + 1}"
    )
    body = [
        f'  <text x="450" y="38" text-anchor="middle" class="title">{html.escape(title)}</text>',
    ]
    for tick in range(6):
        x_value = x_low + (x_high - x_low) * tick / 5.0
        x = _LEFT + _PLOT_WIDTH * tick / 5.0
        body.extend(
            [
                f'  <line x1="{_number(x)}" y1="{_number(_TOP)}" x2="{_number(x)}" '
                f'y2="{_number(_TOP + _PLOT_HEIGHT)}" class="grid"/>',
                f'  <text x="{_number(x)}" y="{_number(_TOP + _PLOT_HEIGHT + 22)}" '
                f'text-anchor="middle" class="small">{html.escape(_number(x_value))}</text>',
            ]
        )
        if y_index is not None:
            y_value = y_low + (y_high - y_low) * tick / 5.0
            y = _TOP + _PLOT_HEIGHT - _PLOT_HEIGHT * tick / 5.0
            body.extend(
                [
                    f'  <line x1="{_number(_LEFT)}" y1="{_number(y)}" '
                    f'x2="{_number(_LEFT + _PLOT_WIDTH)}" y2="{_number(y)}" class="grid"/>',
                    f'  <text x="{_number(_LEFT - 10)}" y="{_number(y + 4)}" '
                    f'text-anchor="end" class="small">{html.escape(_number(y_value))}</text>',
                ]
            )
    zero_x = _map(0.0, x_low, x_high, _LEFT, _PLOT_WIDTH)
    zero_y = _TOP + _PLOT_HEIGHT - _map(0.0, y_low, y_high, 0.0, _PLOT_HEIGHT)
    if _LEFT <= zero_x <= _LEFT + _PLOT_WIDTH:
        body.append(
            f'  <line x1="{_number(zero_x)}" y1="{_number(_TOP)}" '
            f'x2="{_number(zero_x)}" y2="{_number(_TOP + _PLOT_HEIGHT)}" class="axis"/>'
        )
    if _TOP <= zero_y <= _TOP + _PLOT_HEIGHT:
        body.append(
            f'  <line x1="{_number(_LEFT)}" y1="{_number(zero_y)}" '
            f'x2="{_number(_LEFT + _PLOT_WIDTH)}" y2="{_number(zero_y)}" class="axis"/>'
        )
    for label, x_value, y_value in zip(pca.sample_labels, x_values, y_values, strict=True):
        x = _map(float(x_value), x_low, x_high, _LEFT, _PLOT_WIDTH)
        y = _TOP + _PLOT_HEIGHT - _map(float(y_value), y_low, y_high, 0.0, _PLOT_HEIGHT)
        escaped_label = html.escape(label, quote=True)
        body.extend(
            [
                f'  <circle cx="{_number(x)}" cy="{_number(y)}" r="5" '
                f'class="point" data-subject-label="{escaped_label}">',
                f"    <title>{html.escape(label)}</title>",
                "  </circle>",
            ]
        )
    body.extend(
        [
            f'  <text x="{_number(_LEFT + _PLOT_WIDTH / 2.0)}" y="565" '
            f'text-anchor="middle" class="label">{html.escape(x_axis)}</text>',
            f'  <text x="22" y="290" text-anchor="middle" class="label" '
            f'transform="rotate(-90 22 290)">{html.escape(y_axis)}</text>',
        ]
    )
    return _write_exclusive(path, _svg_document(title, body))


def write_pca_score_pair_svg(
    path: Path | str,
    pca: PCAResult,
    *,
    x_component: int,
    y_component: int,
) -> Path:
    """Write one declared two-component score plot using one-based PC numbers."""

    if not isinstance(pca, PCAResult):
        raise TypeError("pca must be a PCAResult")
    for name, component in (("x_component", x_component), ("y_component", y_component)):
        if isinstance(component, bool) or not isinstance(component, Integral):
            raise TypeError(f"{name} must be an integer")
        if int(component) < 1 or int(component) > pca.number_of_components:
            raise ValueError(
                f"{name} must be between 1 and {pca.number_of_components} for this PCA"
            )
    if int(x_component) == int(y_component):
        raise ValueError("x_component and y_component must differ")
    return _write_pca_score_view(
        path,
        pca,
        x_index=int(x_component) - 1,
        y_index=int(y_component) - 1,
    )


def write_pca_scores_svg(path: Path | str, pca: PCAResult) -> Path:
    """Write PC1/PC2 scores, or an explicit PC1 strip when only one axis exists."""

    if not isinstance(pca, PCAResult):
        raise TypeError("pca must be a PCAResult")
    if pca.number_of_components == 1:
        return _write_pca_score_view(path, pca, x_index=0, y_index=None)
    return write_pca_score_pair_svg(
        path,
        pca,
        x_component=1,
        y_component=2,
    )
