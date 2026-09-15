# ruff: noqa: E501
"""Deterministic static views for reference shape-space comparisons."""

from __future__ import annotations

import html
import math
from collections.abc import Mapping, Sequence

import numpy as np

_SHORT_LABELS = {
    "lddmm_deformation_kernel_pca": "LDDMM metric PCA",
    "lddmm_tangent_pcoa": "Tangent-distance PCoA",
    "cartesian_momenta_pca": "Cartesian momenta PCA",
    "roberts_2026_cartesian_momenta_rbf_kpca": "Roberts fixed-gamma kPCA",
    "rbf_kpca_gamma_0.5": "RBF kPCA gamma x0.5",
    "rbf_kpca_gamma_1": "RBF kPCA gamma x1",
    "rbf_kpca_gamma_2": "RBF kPCA gamma x2",
    "isomap": "Isomap",
    "diffusion_map": "Diffusion map",
}
_MATRIX_LABELS = {
    "lddmm_deformation_kernel_pca": "LDDMM PCA",
    "lddmm_tangent_pcoa": "Tangent PCoA",
    "cartesian_momenta_pca": "Cartesian PCA",
    "roberts_2026_cartesian_momenta_rbf_kpca": "Roberts kPCA",
    "rbf_kpca_gamma_0.5": "RBF x0.5",
    "rbf_kpca_gamma_1": "RBF x1",
    "rbf_kpca_gamma_2": "RBF x2",
    "isomap": "Isomap",
    "diffusion_map": "Diffusion",
}


def _number(value: float) -> str:
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ValueError("SVG values must be finite")
    return format(0.0 if normalized == 0.0 else normalized, ".12g")


def _short_label(method_id: str) -> str:
    return _SHORT_LABELS.get(method_id, method_id.replace("_", " "))


def _svg_document(*, width: int, height: int, title: str, body: list[str]) -> str:
    escaped_title = html.escape(title, quote=True)
    return "\n".join(
        [
            '<?xml version="1.0" encoding="UTF-8"?>',
            (
                f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
                f'height="{height}" viewBox="0 0 {width} {height}" role="img" '
                'shape-rendering="geometricPrecision">'
            ),
            f"  <title>{escaped_title}</title>",
            "  <style>",
            "    .title { fill: #17343a; font-family: Arial; font-size: 22px; font-weight: 700; }",
            "    .subtitle { fill: #52666b; font-family: Arial; font-size: 13px; }",
            "    .panel-title { fill: #17343a; font-family: Arial; font-size: 14px; font-weight: 700; }",
            "    .label { fill: #17343a; font-family: Arial; font-size: 12px; }",
            "    .small { fill: #52666b; font-family: Arial; font-size: 10px; }",
            "    .grid { stroke: #e3ebec; stroke-width: 1; }",
            "    .axis { stroke: #789096; stroke-width: 1; }",
            "    .point { fill: #178a78; stroke: #ffffff; stroke-width: 0.8; }",
            "    .outlier { fill: #d8674f; stroke: #ffffff; stroke-width: 0.8; }",
            "    .cell-text { font-family: Arial; font-size: 11px; font-weight: 700; }",
            "  </style>",
            f'  <rect width="{width}" height="{height}" fill="#ffffff"/>',
            *body,
            "</svg>",
            "",
        ]
    )


def _normalized_two_dimensions(values: np.ndarray) -> np.ndarray:
    array = np.asarray(values, dtype=np.float64)
    if array.ndim != 2 or array.shape[0] < 1 or array.shape[1] < 1:
        raise ValueError("Comparison scores must be a non-empty 2D matrix")
    selected = np.zeros((array.shape[0], 2), dtype=np.float64)
    retained = min(2, array.shape[1])
    selected[:, :retained] = array[:, :retained]
    selected -= np.mean(selected, axis=0)
    norm = float(np.linalg.norm(selected))
    if norm > 0:
        selected /= norm
    return selected


def _align_to_reference(values: np.ndarray, reference: np.ndarray) -> np.ndarray:
    cross = values.T @ reference
    try:
        left, _singular, right = np.linalg.svd(cross, full_matrices=False)
    except np.linalg.LinAlgError as error:
        raise ValueError("Could not align comparison scores for display") from error
    return values @ (left @ right)


def score_overview_svg(
    *,
    subject_labels: Sequence[str],
    method_ids: Sequence[str],
    method_labels: Mapping[str, str],
    scores: Mapping[str, np.ndarray],
    reference_method_id: str,
    outlier_count: int,
) -> str:
    """Render Procrustes-aligned two-axis panels without changing exported scores."""

    if reference_method_id not in method_ids:
        raise ValueError("The visual reference method is not selected")
    labels = tuple(str(label) for label in subject_labels)
    if not labels:
        raise ValueError("Subject labels are required")
    reference = _normalized_two_dimensions(scores[reference_method_id])
    aligned: dict[str, np.ndarray] = {}
    for method_id in method_ids:
        values = _normalized_two_dimensions(scores[method_id])
        if values.shape[0] != len(labels):
            raise ValueError("Score and subject counts differ")
        aligned[method_id] = (
            values if method_id == reference_method_id else _align_to_reference(values, reference)
        )
    radii = np.einsum("ij,ij->i", reference, reference, optimize=True)
    count = min(max(1, int(outlier_count)), len(labels))
    outliers = set(np.argsort(radii, kind="stable")[-count:].astype(int).tolist())
    maximum = max(float(np.max(np.abs(values))) for values in aligned.values())
    extent = max(maximum * 1.12, 1e-12)

    columns = min(3, max(1, len(method_ids)))
    rows = math.ceil(len(method_ids) / columns)
    panel_width = 380
    panel_height = 300
    width = columns * panel_width + 60
    height = 112 + rows * panel_height
    body = [
        f'  <text x="{width / 2}" y="34" text-anchor="middle" class="title">Aligned two-axis morphospace overview</text>',
        (
            f'  <text x="{width / 2}" y="58" text-anchor="middle" class="subtitle">'
            "Each panel is centered, unit-scaled, and orthogonally aligned to the visual "
            f"reference: {html.escape(_short_label(reference_method_id))}. Axis signs and "
            "rotation are arbitrary; exact unmodified scores remain in scores.csv.</text>"
        ),
        (
            f'  <text x="{width / 2}" y="78" text-anchor="middle" class="subtitle">'
            "Orange points are the reference method’s declared tangent-distance outliers; "
            "hover a point to identify the specimen.</text>"
        ),
    ]
    for index, method_id in enumerate(method_ids):
        column = index % columns
        row = index // columns
        panel_x = 30 + column * panel_width
        panel_y = 98 + row * panel_height
        plot_x = panel_x + 45
        plot_y = panel_y + 48
        plot_width = panel_width - 70
        plot_height = panel_height - 78
        zero_x = plot_x + plot_width / 2
        zero_y = plot_y + plot_height / 2
        full_label = str(method_labels.get(method_id, method_id))
        body.extend(
            [
                f'  <rect x="{panel_x}" y="{panel_y}" width="{panel_width - 12}" height="{panel_height - 14}" rx="8" fill="#f8fbfb" stroke="#d9e5e6"/>',
                f'  <text x="{panel_x + (panel_width - 12) / 2}" y="{panel_y + 25}" text-anchor="middle" class="panel-title">{html.escape(_short_label(method_id))}<title>{html.escape(full_label)}</title></text>',
                f'  <line x1="{plot_x}" y1="{zero_y}" x2="{plot_x + plot_width}" y2="{zero_y}" class="axis"/>',
                f'  <line x1="{zero_x}" y1="{plot_y}" x2="{zero_x}" y2="{plot_y + plot_height}" class="axis"/>',
                f'  <rect x="{plot_x}" y="{plot_y}" width="{plot_width}" height="{plot_height}" fill="none" stroke="#d9e5e6"/>',
            ]
        )
        values = aligned[method_id]
        for subject_index, (label, point) in enumerate(zip(labels, values, strict=True)):
            x = plot_x + ((float(point[0]) + extent) / (2.0 * extent)) * plot_width
            y = plot_y + plot_height - ((float(point[1]) + extent) / (2.0 * extent)) * plot_height
            css_class = "outlier" if subject_index in outliers else "point"
            body.extend(
                [
                    f'  <circle cx="{_number(x)}" cy="{_number(y)}" r="3.5" class="{css_class}" data-method-id="{html.escape(method_id, quote=True)}" data-subject-label="{html.escape(label, quote=True)}">',
                    f"    <title>{html.escape(label)} — {html.escape(_short_label(method_id))}</title>",
                    "  </circle>",
                ]
            )
    return _svg_document(
        width=width,
        height=height,
        title="Aligned two-axis morphospace overview",
        body=body,
    )


def _agreement_color(value: float) -> str:
    clipped = min(max(float(value), 0.0), 1.0)
    low = np.array([214.0, 99.0, 79.0])
    middle = np.array([246.0, 219.0, 129.0])
    high = np.array([23.0, 138.0, 120.0])
    if clipped <= 0.7:
        weight = clipped / 0.7
        color = low * (1.0 - weight) + middle * weight
    else:
        weight = (clipped - 0.7) / 0.3
        color = middle * (1.0 - weight) + high * weight
    return "#" + "".join(f"{int(round(channel)):02x}" for channel in color)


def agreement_heatmap_svg(
    *,
    method_ids: Sequence[str],
    method_labels: Mapping[str, str],
    pairwise_rows: Sequence[Mapping[str, object]],
    dimensions: int,
) -> str:
    """Render a symmetric heatmap of pairwise-distance correlations."""

    selected = tuple(method_ids)
    indexed: dict[frozenset[str], float] = {}
    for row in pairwise_rows:
        if int(row["dimensions"]) != int(dimensions):
            continue
        key = frozenset((str(row["method_a_id"]), str(row["method_b_id"])))
        indexed[key] = float(row["pairwise_distance_correlation"])
    count = len(selected)
    cell = 68
    left = 235
    top = 225
    width = left + count * cell + 160
    height = top + count * cell + 105
    body = [
        f'  <text x="{width / 2}" y="34" text-anchor="middle" class="title">Pairwise morphospace agreement at {dimensions} dimensions</text>',
        (
            f'  <text x="{width / 2}" y="58" text-anchor="middle" class="subtitle">'
            "Pearson correlation of all specimen-to-specimen distances; invariant to "
            "translation, axis sign, rotation, and uniform scale.</text>"
        ),
        (
            f'  <text x="{width / 2}" y="79" text-anchor="middle" class="subtitle">'
            "Heuristic reading only: 0.95–1.00 very high, 0.85–0.95 high, 0.70–0.85 moderate, below 0.70 low.</text>"
        ),
    ]
    for index, method_id in enumerate(selected):
        label = _short_label(method_id)
        matrix_label = _MATRIX_LABELS.get(method_id, label)
        full_label = str(method_labels.get(method_id, method_id))
        x = left + index * cell + cell / 2
        y = top + index * cell + cell / 2
        body.extend(
            [
                f'  <text x="{x}" y="{top - 13}" text-anchor="start" class="small" transform="rotate(-55 {x} {top - 13})">{html.escape(matrix_label)}<title>{html.escape(full_label)}</title></text>',
                f'  <text x="{left - 12}" y="{y + 4}" text-anchor="end" class="small">{html.escape(label)}<title>{html.escape(full_label)}</title></text>',
            ]
        )
    for row_index, method_a in enumerate(selected):
        for column_index, method_b in enumerate(selected):
            value = 1.0 if method_a == method_b else indexed[frozenset((method_a, method_b))]
            x = left + column_index * cell
            y = top + row_index * cell
            color = _agreement_color(value)
            text_color = "#ffffff" if value >= 0.88 or value < 0.30 else "#17343a"
            body.extend(
                [
                    f'  <rect x="{x}" y="{y}" width="{cell}" height="{cell}" fill="{color}" stroke="#ffffff" data-value="{_number(value)}">',
                    f"    <title>{html.escape(_short_label(method_a))} vs {html.escape(_short_label(method_b))}: {_number(value)}</title>",
                    "  </rect>",
                    f'  <text x="{x + cell / 2}" y="{y + cell / 2 + 4}" text-anchor="middle" class="cell-text" fill="{text_color}">{value:.2f}</text>',
                ]
            )
    legend_y = top + count * cell + 40
    legend_values = (
        (0.0, "low"),
        (0.70, "moderate"),
        (0.85, "high"),
        (0.95, "very high"),
        (1.0, "identical distances"),
    )
    for index, (value, label) in enumerate(legend_values):
        x = left + index * 145
        body.extend(
            [
                f'  <rect x="{x}" y="{legend_y}" width="22" height="16" fill="{_agreement_color(value)}"/>',
                f'  <text x="{x + 28}" y="{legend_y + 13}" class="small">{value:.2f} {label}</text>',
            ]
        )
    return _svg_document(
        width=width,
        height=height,
        title=f"Pairwise morphospace agreement at {dimensions} dimensions",
        body=body,
    )


def default_profile_svg(
    *,
    method_ids: Sequence[str],
    method_labels: Mapping[str, str],
    method_evaluations: Mapping[str, Mapping[str, object]],
    pairwise_rows: Sequence[Mapping[str, object]],
    reference_method_id: str,
    dimensions: int,
) -> str:
    """Render one readable method-by-metric profile against the visual reference."""

    columns = (
        ("distance_correlation", ("Tangent", "distance r")),
        ("fit_after_stress", ("1 - stress", "")),
        ("centered_kernel_alignment_to_lddmm_pca", ("CKA", "to default")),
        ("top_outlier_overlap", ("Tangent", "outliers")),
        ("pairwise_distance_correlation", ("Distance r", "to reference")),
        ("orthogonal_procrustes_correlation", ("Procrustes r", "")),
        ("nearest_neighbor_overlap", ("5-NN", "overlap")),
    )
    pair_index: dict[frozenset[str], Mapping[str, object]] = {}
    for row in pairwise_rows:
        if int(row["dimensions"]) == int(dimensions):
            pair_index[frozenset((str(row["method_a_id"]), str(row["method_b_id"])))] = row
    count = len(method_ids)
    cell_width = 112
    cell_height = 52
    left = 245
    top = 170
    width = left + len(columns) * cell_width + 55
    height = top + count * cell_height + 95
    body = [
        f'  <text x="{width / 2}" y="34" text-anchor="middle" class="title">Method profile at {dimensions} dimensions</text>',
        (
            f'  <text x="{width / 2}" y="58" text-anchor="middle" class="subtitle">'
            f"Reference for pairwise columns: {html.escape(_short_label(reference_method_id))}. "
            "All values are higher-is-more-similar after converting stress to 1 - stress.</text>"
        ),
        (
            f'  <text x="{width / 2}" y="79" text-anchor="middle" class="subtitle">'
            "These are descriptive numerical checks, not hypothesis tests or biological validation.</text>"
        ),
    ]
    for column_index, (_key, label_lines) in enumerate(columns):
        x = left + column_index * cell_width + cell_width / 2
        second_line = (
            f'<tspan x="{x}" dy="14">{html.escape(label_lines[1])}</tspan>'
            if label_lines[1]
            else ""
        )
        body.append(
            f'  <text x="{x}" y="{top - 34}" text-anchor="middle" class="small">'
            f'<tspan x="{x}">{html.escape(label_lines[0])}</tspan>{second_line}</text>'
        )
    for row_index, method_id in enumerate(method_ids):
        y = top + row_index * cell_height
        label = _short_label(method_id)
        full_label = str(method_labels.get(method_id, method_id))
        body.append(
            f'  <text x="{left - 12}" y="{y + cell_height / 2 + 4}" text-anchor="end" class="small">{html.escape(label)}<title>{html.escape(full_label)}</title></text>'
        )
        evaluation = method_evaluations[method_id]
        pair = (
            None
            if method_id == reference_method_id
            else pair_index[frozenset((method_id, reference_method_id))]
        )
        values = {
            "distance_correlation": float(evaluation["distance_correlation"]),
            "fit_after_stress": 1.0 - float(evaluation["normalized_stress_after_scale"]),
            "centered_kernel_alignment_to_lddmm_pca": float(
                evaluation["centered_kernel_alignment_to_lddmm_pca"]
            ),
            "top_outlier_overlap": float(evaluation["top_outlier_overlap"]),
            "pairwise_distance_correlation": 1.0
            if pair is None
            else float(pair["pairwise_distance_correlation"]),
            "orthogonal_procrustes_correlation": 1.0
            if pair is None
            else float(pair["orthogonal_procrustes_correlation"]),
            "nearest_neighbor_overlap": 1.0
            if pair is None
            else float(pair["nearest_neighbor_overlap"]),
        }
        for column_index, (key, _label) in enumerate(columns):
            value = values[key]
            x = left + column_index * cell_width
            color = _agreement_color(value)
            text_color = "#ffffff" if value >= 0.88 or value < 0.30 else "#17343a"
            body.extend(
                [
                    f'  <rect x="{x}" y="{y}" width="{cell_width}" height="{cell_height}" fill="{color}" stroke="#ffffff" data-value="{_number(value)}"/>',
                    f'  <text x="{x + cell_width / 2}" y="{y + cell_height / 2 + 4}" text-anchor="middle" class="cell-text" fill="{text_color}">{value:.2f}</text>',
                ]
            )
    return _svg_document(
        width=width,
        height=height,
        title=f"Method profile at {dimensions} dimensions",
        body=body,
    )
