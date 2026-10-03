"""Engine-independent open PCA tables and deterministic static plots."""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path

from diffeoforge.analysis.pca import PCAResult
from diffeoforge.analysis.pca_visualization import (
    write_pca_score_pair_svg,
    write_pca_scores_svg,
    write_pca_scree_svg,
)


def pca_float(value: float) -> str:
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ValueError("PCA artifact values must be finite")
    return format(0.0 if normalized == 0.0 else normalized, ".17g")


def pca_csv_label(value: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("PCA CSV labels must be non-empty strings")
    return f"'{value}" if value[0] in "=+-@\t\r" else value


def pca_summary_document(pca: PCAResult) -> dict[str, object]:
    if not isinstance(pca, PCAResult):
        raise TypeError("pca must be a PCAResult")
    return {
        "feature_space": pca.feature_space,
        "sample_labels": list(pca.sample_labels),
        "feature_labels": list(pca.feature_labels),
        "number_of_components": pca.number_of_components,
        "numerical_rank": pca.numerical_rank,
        "total_variance": pca.total_variance,
        "singular_values": pca.singular_values.tolist(),
        "explained_variance": pca.explained_variance.tolist(),
        "explained_variance_ratio": pca.explained_variance_ratio.tolist(),
        "tied_component_groups": [list(group) for group in pca.tied_component_groups],
        "zero_variance_components": list(pca.zero_variance_components),
        "sign_convention": pca.sign_convention,
    }


def pca_score_rows(pca: PCAResult) -> list[list[str]]:
    component_labels = [f"PC{index + 1}" for index in range(pca.number_of_components)]
    return [["subject_label", *component_labels]] + [
        [pca_csv_label(label), *(pca_float(value) for value in scores)]
        for label, scores in zip(pca.sample_labels, pca.scores, strict=True)
    ]


def pca_loading_rows(pca: PCAResult) -> list[list[str]]:
    component_labels = [f"PC{index + 1}" for index in range(pca.number_of_components)]
    return [["feature_label", *component_labels]] + [
        [
            pca_csv_label(label),
            *(pca_float(value) for value in pca.components[:, index]),
        ]
        for index, label in enumerate(pca.feature_labels)
    ]


def pca_mean_rows(pca: PCAResult) -> list[list[str]]:
    return [["feature_label", "mean"]] + [
        [pca_csv_label(label), pca_float(value)]
        for label, value in zip(pca.feature_labels, pca.mean, strict=True)
    ]


def _write_json_exclusive(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(
            value,
            handle,
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
            allow_nan=False,
        )
        handle.write("\n")


def _write_csv_exclusive(path: Path, rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="") as handle:
        csv.writer(handle, lineterminator="\n").writerows(rows)


def write_pca_artifacts(root: Path | str, pca: PCAResult) -> dict[str, object]:
    """Write the shared PCA JSON/CSV/SVG surface below an existing private root."""

    if not isinstance(pca, PCAResult):
        raise TypeError("pca must be a PCAResult")
    bundle_root = Path(root)
    analysis = bundle_root / "analysis"
    summary_path = analysis / "pca-summary.json"
    scores_path = analysis / "pca-scores.csv"
    loadings_path = analysis / "pca-loadings.csv"
    mean_path = analysis / "pca-mean.csv"
    scree_path = analysis / "pca-scree.svg"
    scores_plot_path = analysis / "pca-scores.svg"
    pc2_pc3_plot_path = analysis / "pca-scores-pc2-pc3.svg"
    _write_json_exclusive(summary_path, pca_summary_document(pca))
    _write_csv_exclusive(scores_path, pca_score_rows(pca))
    _write_csv_exclusive(loadings_path, pca_loading_rows(pca))
    _write_csv_exclusive(mean_path, pca_mean_rows(pca))
    write_pca_scree_svg(scree_path, pca)
    write_pca_scores_svg(scores_plot_path, pca)
    if pca.number_of_components >= 3:
        write_pca_score_pair_svg(
            pc2_pc3_plot_path,
            pca,
            x_component=2,
            y_component=3,
        )
        pc2_pc3_path: str | None = pc2_pc3_plot_path.relative_to(bundle_root).as_posix()
        pc2_pc3_axes: list[str] | None = ["PC2", "PC3"]
        pc2_pc3_unavailable_reason: str | None = None
    else:
        pc2_pc3_path = None
        pc2_pc3_axes = None
        pc2_pc3_unavailable_reason = (
            "PC3 is not mathematically available because the retained PCA has "
            f"{pca.number_of_components} component"
            f"{'s' if pca.number_of_components != 1 else ''}."
        )
    return {
        "summary_path": summary_path.relative_to(bundle_root).as_posix(),
        "scores_path": scores_path.relative_to(bundle_root).as_posix(),
        "loadings_path": loadings_path.relative_to(bundle_root).as_posix(),
        "mean_path": mean_path.relative_to(bundle_root).as_posix(),
        "plots": {
            "scree_path": scree_path.relative_to(bundle_root).as_posix(),
            "scores_path": scores_plot_path.relative_to(bundle_root).as_posix(),
            "score_axes": ["PC1"] if pca.number_of_components == 1 else ["PC1", "PC2"],
            "scores_pc2_pc3_path": pc2_pc3_path,
            "scores_pc2_pc3_axes": pc2_pc3_axes,
            "scores_pc2_pc3_unavailable_reason": pc2_pc3_unavailable_reason,
        },
    }
