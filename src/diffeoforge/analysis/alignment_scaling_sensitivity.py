"""Cheap, deterministic sensitivity diagnostics for mesh size treatment."""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np

from diffeoforge.analysis.mesh_scaling import (
    MeshScaleMetrics,
    MeshScalingMode,
    scaling_factor,
    scaling_mode_label,
    validate_target_size,
)

ASSESSED_MODES = (
    MeshScalingMode.PAMS_AREA_WEIGHTED,
    MeshScalingMode.PAMS_VERTEX_CENTROID,
    MeshScalingMode.LANDMARK_CENTROID_LEGACY,
    MeshScalingMode.PRESERVE_SIZE,
    MeshScalingMode.LANDMARK_RIGID_LEGACY,
)


def _summary(values: Sequence[float]) -> dict[str, float]:
    array = np.asarray(values, dtype=np.float64)
    mean = float(np.mean(array))
    standard_deviation = float(np.std(array))
    return {
        "minimum": float(np.min(array)),
        "median": float(np.median(array)),
        "maximum": float(np.max(array)),
        "mean": mean,
        "standard_deviation": standard_deviation,
        "coefficient_of_variation": (
            standard_deviation / mean if not math.isclose(mean, 0.0) else 0.0
        ),
    }


def build_alignment_scaling_sensitivity(
    filenames: Sequence[str],
    point_counts: Sequence[int],
    metrics: Sequence[MeshScaleMetrics],
    landmark_centroid_sizes: Sequence[float],
    *,
    selected_mode: MeshScalingMode,
    target_size: float,
) -> dict[str, object]:
    """Compare all supported scientific size policies without running an atlas.

    This intentionally stops at coordinate preprocessing. It can expose a
    resolution-sensitive or strongly influential scaling decision cheaply, but
    it cannot claim that atlas templates or morphospaces are robust.
    """

    names = tuple(filenames)
    counts = tuple(int(value) for value in point_counts)
    scale_metrics = tuple(metrics)
    landmark_sizes = tuple(float(value) for value in landmark_centroid_sizes)
    size = validate_target_size(target_size)
    length = len(names)
    if length < 2 or not (
        len(counts) == len(scale_metrics) == len(landmark_sizes) == length
    ):
        raise ValueError("scaling sensitivity inputs must describe the same mesh cohort")
    if any(value < 3 for value in counts):
        raise ValueError("point counts must be at least three")

    mode_values: dict[MeshScalingMode, tuple[float, ...]] = {}
    modes: list[dict[str, object]] = []
    for mode in ASSESSED_MODES:
        factors = tuple(
            scaling_factor(
                mode,
                target_size=size,
                landmark_centroid_size=landmark_size,
                mesh_metrics=metric,
            )
            for metric, landmark_size in zip(
                scale_metrics, landmark_sizes, strict=True
            )
        )
        mode_values[mode] = factors
        post_surface = tuple(
            metric.area_weighted_rms_radius * factor
            for metric, factor in zip(scale_metrics, factors, strict=True)
        )
        post_vertex = tuple(
            metric.vertex_centroid_size * factor
            for metric, factor in zip(scale_metrics, factors, strict=True)
        )
        post_landmarks = tuple(
            landmark_size * factor
            for landmark_size, factor in zip(landmark_sizes, factors, strict=True)
        )
        modes.append(
            {
                "mode": mode.value,
                "label": scaling_mode_label(mode),
                "selected": mode is selected_mode,
                "scale_factor": _summary(factors),
                "post_area_weighted_rms_radius": _summary(post_surface),
                "post_vertex_centroid_size": _summary(post_vertex),
                "post_landmark_centroid_size": _summary(post_landmarks),
            }
        )

    specimen_rows: list[dict[str, object]] = []
    selected_factors = mode_values[selected_mode]
    for index, (name, count, metric, landmark_size) in enumerate(
        zip(names, counts, scale_metrics, landmark_sizes, strict=True)
    ):
        factors = {mode.value: mode_values[mode][index] for mode in ASSESSED_MODES}
        specimen_rows.append(
            {
                "filename": name,
                "point_count": count,
                "landmark_centroid_size": landmark_size,
                "surface_area": metric.surface_area,
                "area_weighted_rms_radius": metric.area_weighted_rms_radius,
                "vertex_centroid_size": metric.vertex_centroid_size,
                "selected_scale_factor": selected_factors[index],
                "scale_factors": factors,
            }
        )

    point_ratio = max(counts) / min(counts)
    vertex_to_area = tuple(
        metric.vertex_centroid_size / metric.area_weighted_rms_radius
        for metric in scale_metrics
    )
    warnings: list[str] = []
    if point_ratio >= 1.25:
        warnings.append(
            "Vertex counts differ enough that published vertex-centroid PAMS scaling "
            "may encode tessellation density as well as biological size."
        )
    if _summary(vertex_to_area)["coefficient_of_variation"] >= 0.05:
        warnings.append(
            "Vertex-based and area-weighted surface size disagree non-uniformly across "
            "specimens; include the two policies in a full atlas sensitivity analysis."
        )

    return {
        "assessment_version": "0.1",
        "selected_mode": selected_mode.value,
        "selected_label": scaling_mode_label(selected_mode),
        "target_size": size,
        "computed_without_atlas_reruns": True,
        "interpretation_scope": (
            "Preprocessing-scale sensitivity only. This diagnoses coordinate effects "
            "but does not establish template, deformation, or morphospace robustness."
        ),
        "required_follow_up": (
            "When scientific conclusions depend on size treatment, run and compare "
            "complete atlases under the declared shape-only and size-preserving modes."
        ),
        "vertex_count_ratio_max_to_min": point_ratio,
        "vertex_to_area_scale_ratio": _summary(vertex_to_area),
        "warnings": warnings,
        "modes": modes,
        "specimens": specimen_rows,
    }


def alignment_scaling_sensitivity_csv_rows(
    report: dict[str, object],
) -> tuple[tuple[object, ...], ...]:
    """Flatten specimen evidence into a stable, spreadsheet-friendly table."""

    specimens = report.get("specimens")
    if not isinstance(specimens, list):
        raise TypeError("scaling sensitivity report has no specimen records")
    mode_columns = tuple(mode.value for mode in ASSESSED_MODES)
    rows: list[tuple[object, ...]] = [
        (
            "filename",
            "point_count",
            "landmark_centroid_size",
            "surface_area",
            "area_weighted_rms_radius",
            "vertex_centroid_size",
            "selected_scale_factor",
            *(f"scale_factor__{value}" for value in mode_columns),
        )
    ]
    for item in specimens:
        if not isinstance(item, dict) or not isinstance(item.get("scale_factors"), dict):
            raise TypeError("scaling sensitivity specimen record is malformed")
        factors = item["scale_factors"]
        rows.append(
            (
                item["filename"],
                item["point_count"],
                item["landmark_centroid_size"],
                item["surface_area"],
                item["area_weighted_rms_radius"],
                item["vertex_centroid_size"],
                item["selected_scale_factor"],
                *(factors[value] for value in mode_columns),
            )
        )
    return tuple(rows)
