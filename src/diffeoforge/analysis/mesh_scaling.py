"""Explicit, auditable size treatment for landmark-guided surface alignment."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from diffeoforge.mesh_scaling_contract import (
    DEFAULT_MESH_SCALING_MODE as DEFAULT_MESH_SCALING_MODE,
)
from diffeoforge.mesh_scaling_contract import (
    DEFAULT_TARGET_SIZE as DEFAULT_TARGET_SIZE,
)
from diffeoforge.mesh_scaling_contract import (
    MeshScalingMode as MeshScalingMode,
)
from diffeoforge.mesh_scaling_contract import (
    normalize_mesh_scaling_mode as normalize_mesh_scaling_mode,
)
from diffeoforge.mesh_scaling_contract import (
    scaling_mode_label as scaling_mode_label,
)
from diffeoforge.mesh_scaling_contract import (
    validate_target_size as validate_target_size,
)


@dataclass(frozen=True)
class MeshScaleMetrics:
    """Scale observations computed from one immutable triangular surface."""

    vertex_centroid_size: float
    area_weighted_rms_radius: float
    surface_area: float
    area_weighted_centroid: tuple[float, float, float]

    def __post_init__(self) -> None:
        values = (
            self.vertex_centroid_size,
            self.area_weighted_rms_radius,
            self.surface_area,
            *self.area_weighted_centroid,
        )
        if not all(math.isfinite(float(value)) for value in values):
            raise ValueError("mesh scale metrics must be finite")
        if self.vertex_centroid_size <= 0:
            raise ValueError("vertex centroid size must be greater than zero")
        if self.area_weighted_rms_radius <= 0 or self.surface_area <= 0:
            raise ValueError("surface scale metrics must be greater than zero")

    def as_manifest(self) -> dict[str, object]:
        return {
            "vertex_centroid_size": self.vertex_centroid_size,
            "area_weighted_rms_radius": self.area_weighted_rms_radius,
            "surface_area": self.surface_area,
            "area_weighted_centroid": list(self.area_weighted_centroid),
        }


def mesh_scale_metrics(
    vertices: Sequence[Sequence[float]] | np.ndarray,
    triangles: Sequence[Sequence[int]] | np.ndarray,
) -> MeshScaleMetrics:
    """Compute vertex-PAMS and tessellation-invariant surface scale measures.

    ``vertex_centroid_size`` reproduces the centroid-size definition commonly
    applied to a mesh vertex matrix. It depends on sampling density. The
    area-weighted RMS radius integrates first and second moments over every
    triangle, so subdivision of an unchanged piecewise-linear surface does not
    change the result apart from floating-point roundoff.
    """

    points = np.asarray(vertices, dtype=np.float64)
    faces = np.asarray(triangles, dtype=np.int64)
    if points.ndim != 2 or points.shape[1] != 3 or points.shape[0] < 3:
        raise ValueError("vertices must have shape (n, 3) with at least three rows")
    if faces.ndim != 2 or faces.shape[1] != 3 or faces.shape[0] < 1:
        raise ValueError("triangles must have shape (m, 3) with at least one row")
    if not bool(np.isfinite(points).all()):
        raise ValueError("vertices must contain only finite values")
    if int(faces.min()) < 0 or int(faces.max()) >= points.shape[0]:
        raise ValueError("triangles contain an out-of-range vertex index")

    vertex_centroid = np.mean(points, axis=0)
    centered = points - vertex_centroid
    vertex_size = float(np.sqrt(np.sum(centered * centered)))

    a = points[faces[:, 0]]
    b = points[faces[:, 1]]
    c = points[faces[:, 2]]
    areas = 0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1)
    total_area = float(np.sum(areas))
    if not math.isfinite(total_area) or total_area <= 0:
        raise ValueError("triangular surface has no positive finite area")

    triangle_centroids = (a + b + c) / 3.0
    surface_centroid = np.sum(areas[:, None] * triangle_centroids, axis=0) / total_area
    squared_norm_integral = np.sum(
        areas
        * (
            np.sum(a * a, axis=1)
            + np.sum(b * b, axis=1)
            + np.sum(c * c, axis=1)
            + np.sum(a * b, axis=1)
            + np.sum(a * c, axis=1)
            + np.sum(b * c, axis=1)
        )
        / 6.0
    )
    mean_squared_radius = float(
        squared_norm_integral / total_area - np.dot(surface_centroid, surface_centroid)
    )
    numerical_scale = max(1.0, float(np.max(np.abs(points))))
    if mean_squared_radius < 0 and abs(mean_squared_radius) <= 1e-12 * numerical_scale**2:
        mean_squared_radius = 0.0
    if not math.isfinite(mean_squared_radius) or mean_squared_radius <= 0:
        raise ValueError("triangular surface has no positive finite RMS radius")

    return MeshScaleMetrics(
        vertex_centroid_size=vertex_size,
        area_weighted_rms_radius=math.sqrt(mean_squared_radius),
        surface_area=total_area,
        area_weighted_centroid=tuple(float(value) for value in surface_centroid),
    )


def scaling_factor(
    mode: MeshScalingMode | str,
    *,
    target_size: float,
    landmark_centroid_size: float,
    mesh_metrics: MeshScaleMetrics,
) -> float:
    """Return the one explicitly selected isotropic scale factor."""

    selected = normalize_mesh_scaling_mode(mode)
    target = validate_target_size(target_size)
    if not math.isfinite(landmark_centroid_size) or landmark_centroid_size <= 0:
        raise ValueError("landmark_centroid_size must be finite and greater than zero")
    if selected in {
        MeshScalingMode.PRESERVE_SIZE,
        MeshScalingMode.LANDMARK_RIGID_LEGACY,
    }:
        return 1.0
    if selected is MeshScalingMode.LANDMARK_CENTROID_LEGACY:
        return target / landmark_centroid_size
    if selected is MeshScalingMode.PAMS_VERTEX_CENTROID:
        return target / mesh_metrics.vertex_centroid_size
    return target / mesh_metrics.area_weighted_rms_radius
