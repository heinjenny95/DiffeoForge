"""Lightweight mesh-scaling configuration contract without numerical imports."""

from __future__ import annotations

import math
from enum import StrEnum
from numbers import Real


class MeshScalingMode(StrEnum):
    """Scientifically distinct size policies for an aligned surface cohort."""

    PAMS_AREA_WEIGHTED = "pams_surface_area_weighted_rms"
    PAMS_VERTEX_CENTROID = "pams_surface_vertex_centroid_size"
    PRESERVE_SIZE = "preserve_size"
    LANDMARK_CENTROID_LEGACY = "landmark_centroid_size_legacy"
    LANDMARK_RIGID_LEGACY = "landmark_rigid_gpa_legacy"


DEFAULT_MESH_SCALING_MODE = MeshScalingMode.PAMS_AREA_WEIGHTED
DEFAULT_TARGET_SIZE = 1.0


def normalize_mesh_scaling_mode(value: MeshScalingMode | str) -> MeshScalingMode:
    """Return one supported mode with a stable error for configuration callers."""

    try:
        return MeshScalingMode(value)
    except (TypeError, ValueError) as error:
        supported = ", ".join(item.value for item in MeshScalingMode)
        raise ValueError(f"unsupported mesh scaling mode {value!r}; choose {supported}") from error


def validate_target_size(value: float) -> float:
    """Validate the arbitrary common working size used after size removal."""

    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError("target_size must be a real scalar")
    normalized = float(value)
    if not math.isfinite(normalized) or normalized <= 0:
        raise ValueError("target_size must be finite and greater than zero")
    return normalized


def scaling_mode_label(mode: MeshScalingMode | str) -> str:
    """Return concise, publication-safe English wording."""

    selected = normalize_mesh_scaling_mode(mode)
    return {
        MeshScalingMode.PAMS_AREA_WEIGHTED: (
            "PAMS-style surface scaling (area-weighted RMS radius)"
        ),
        MeshScalingMode.PAMS_VERTEX_CENTROID: (
            "published PAMS-compatible vertex centroid-size scaling"
        ),
        MeshScalingMode.PRESERVE_SIZE: "size-preserving rigid landmark alignment",
        MeshScalingMode.LANDMARK_CENTROID_LEGACY: (
            "legacy landmark-centroid-size similarity scaling"
        ),
        MeshScalingMode.LANDMARK_RIGID_LEGACY: (
            "legacy size-preserving landmark GPA"
        ),
    }[selected]
