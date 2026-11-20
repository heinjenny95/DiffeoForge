"""Parameter-independent surface evidence for DiffeoForge Validation Lab."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path, PurePosixPath

import numpy as np

from diffeoforge.config import ConfigurationError
from diffeoforge.mesh import TriangleMesh, read_vtk_polydata
from diffeoforge.reference_calibration_metrics import (
    collect_reference_calibration_run_metrics,
)
from diffeoforge.reference_validation import ValidationRunEvidence
from diffeoforge.result_report import collect_run_report

VALIDATION_METRIC_VERSION = "0.2"
_RECONSTRUCTION_MARKER = "__Reconstruction__"
_SUBJECT_MARKER = "__subject_"
_MAX_SOURCE_VERTICES = 3_000
_MAX_TARGET_TRIANGLES = 5_000
_POINT_BLOCK_SIZE = 48


def _sample_rows(values: np.ndarray, maximum: int) -> np.ndarray:
    if len(values) <= maximum:
        return values
    indices = np.linspace(0, len(values) - 1, num=maximum, dtype=np.int64)
    return values[indices]


def _segment_squared_distance(
    points: np.ndarray,
    first: np.ndarray,
    second: np.ndarray,
) -> np.ndarray:
    edge = second - first
    scale = np.max(np.abs(edge), axis=1)
    if not np.all(np.isfinite(scale)):
        raise ConfigurationError("Point-to-surface metric found a non-finite edge")
    if np.any(scale == 0.0):
        raise ConfigurationError("Point-to-surface metric found a zero-length edge")
    normalized_edge = edge / scale[:, None]
    denominator = np.sum(normalized_edge * normalized_edge, axis=1)
    offset = points[:, None, :] - first[None, :, :]
    parameter = (
        np.sum((offset / scale[None, :, None]) * normalized_edge[None, :, :], axis=2)
        / denominator[None, :]
    )
    parameter = np.clip(parameter, 0.0, 1.0)
    residual = offset - parameter[:, :, None] * edge[None, :, :]
    return np.sum(residual * residual, axis=2)


def _point_triangle_squared_distance(
    points: np.ndarray,
    triangles: np.ndarray,
) -> np.ndarray:
    """Return each point's exact squared distance to the triangle collection."""

    first = triangles[:, 0]
    second = triangles[:, 1]
    third = triangles[:, 2]
    edge0 = second - first
    edge1 = third - first
    if not np.all(np.isfinite(points)) or not np.all(np.isfinite(triangles)):
        raise ConfigurationError("Point-to-surface metric requires finite coordinates")
    # A squared cross product has units of length**4. Comparing it with an
    # absolute machine epsilon incorrectly rejects valid small triangles after
    # shape-only normalization. Normalize locally without changing the mesh,
    # sampling, or coordinate units; genuinely collapsed faces still fail.
    scale = np.maximum(np.max(np.abs(edge0), axis=1), np.max(np.abs(edge1), axis=1))
    if not np.all(np.isfinite(scale)):
        raise ConfigurationError("Point-to-surface metric found a non-finite edge")
    if np.any(scale == 0.0):
        raise ConfigurationError("Point-to-surface metric found a zero-area triangle")
    normalized_edge0 = edge0 / scale[:, None]
    normalized_edge1 = edge1 / scale[:, None]
    normal = np.cross(normalized_edge0, normalized_edge1)
    normal_scale = np.max(np.abs(normal), axis=1)
    if np.any(normal_scale == 0.0):
        raise ConfigurationError("Point-to-surface metric found a zero-area triangle")
    scaled_normal = normal / normal_scale[:, None]
    scaled_normal_length = np.sqrt(np.sum(scaled_normal * scaled_normal, axis=1))
    unit_normal = scaled_normal / scaled_normal_length[:, None]
    normal_length = normal_scale * scaled_normal_length

    offset = points[:, None, :] - first[None, :, :]
    signed = np.sum(offset * unit_normal[None, :, :], axis=2)
    normalized_offset = offset / scale[None, :, None]
    # Oriented cross products avoid subtracting nearly equal Gram products
    # (dot00*dot11 - dot01**2) for thin, but non-degenerate, triangles.
    barycentric_second = (
        np.sum(
            np.cross(normalized_offset, normalized_edge1[None, :, :]) * unit_normal[None, :, :],
            axis=2,
        )
        / normal_length[None, :]
    )
    barycentric_third = (
        np.sum(
            np.cross(normalized_edge0[None, :, :], normalized_offset) * unit_normal[None, :, :],
            axis=2,
        )
        / normal_length[None, :]
    )
    inside = (
        (barycentric_second >= -1e-12)
        & (barycentric_third >= -1e-12)
        & (barycentric_second + barycentric_third <= 1.0 + 1e-12)
    )
    plane_squared = signed * signed
    plane_squared[~inside] = np.inf
    squared = np.minimum.reduce(
        (
            plane_squared,
            _segment_squared_distance(points, first, second),
            _segment_squared_distance(points, second, third),
            _segment_squared_distance(points, third, first),
        )
    )
    minimum = np.min(squared, axis=1)
    if not np.all(np.isfinite(minimum)):
        raise ConfigurationError("Point-to-surface distances exceeded finite numeric range")
    return minimum


def directed_vertex_to_surface_distances(
    source: TriangleMesh,
    target: TriangleMesh,
) -> np.ndarray:
    """Return deterministic sampled source-vertex to target-triangle distances."""

    source_points = _sample_rows(
        np.asarray(source.vertices, dtype=np.float64), _MAX_SOURCE_VERTICES
    )
    target_vertices = np.asarray(target.vertices, dtype=np.float64)
    target_indices = _sample_rows(
        np.asarray(target.triangles, dtype=np.int64), _MAX_TARGET_TRIANGLES
    )
    triangles = target_vertices[target_indices]
    distances = np.empty(len(source_points), dtype=np.float64)
    for start in range(0, len(source_points), _POINT_BLOCK_SIZE):
        block = source_points[start : start + _POINT_BLOCK_SIZE]
        squared = _point_triangle_squared_distance(block, triangles)
        distances[start : start + len(block)] = np.sqrt(np.maximum(squared, 0.0))
    return distances


def symmetric_vertex_to_surface_distances(
    first: TriangleMesh,
    second: TriangleMesh,
) -> np.ndarray:
    """Return bidirectional sampled vertex-to-triangle distances."""

    return np.concatenate(
        (
            directed_vertex_to_surface_distances(first, second),
            directed_vertex_to_surface_distances(second, first),
        )
    )


def _safe_output_path(run: Path, relative_value: object) -> Path:
    relative = PurePosixPath(str(relative_value))
    if (
        relative.is_absolute()
        or not relative.parts
        or "." in relative.parts
        or ".." in relative.parts
    ):
        raise ConfigurationError(f"Validation output inventory contains an unsafe path: {relative}")
    output = (run / "output").resolve()
    candidate = output.joinpath(*relative.parts).resolve()
    if not candidate.is_relative_to(output) or not candidate.is_file():
        raise ConfigurationError(f"Validation output is missing: {relative}")
    return candidate


def _subject_name(reconstruction_name: str) -> str:
    if _SUBJECT_MARKER not in reconstruction_name:
        raise ConfigurationError(f"Could not identify validation subject in {reconstruction_name}")
    value = reconstruction_name.split(_SUBJECT_MARKER, 1)[1]
    if not value.casefold().endswith(".vtk"):
        raise ConfigurationError(
            f"Validation reconstruction has an unexpected name: {reconstruction_name}"
        )
    return value[:-4]


def collect_reference_validation_run_evidence(
    run_directory: Path | str,
    *,
    run_id: str,
    finalist_id: str,
    cohort_id: str,
    progress_callback: Callable[[str, int, int], None] | None = None,
) -> ValidationRunEvidence:
    """Verify a run and collect common external finalist-comparison evidence."""

    run = Path(run_directory).expanduser().resolve()
    if progress_callback is not None:
        progress_callback("Verifying completed run and geometric evidence", 0, 0)
    base = collect_reference_calibration_run_metrics(run)
    report = collect_run_report(run)
    effective_input = report.manifest["effective_config"]["input"]
    input_directory = Path(str(effective_input["directory"])).expanduser().resolve()
    template_path = Path(str(effective_input["template"])).expanduser().resolve()
    pattern = str(effective_input["subject_pattern"])
    subjects = {
        path.name: path.resolve()
        for path in sorted(input_directory.glob(pattern))
        if path.is_file() and path.resolve() != template_path
    }
    reconstructions: dict[str, Path] = {}
    for record in report.inventory:
        relative = str(record["path"])
        name = PurePosixPath(relative).name
        if _RECONSTRUCTION_MARKER not in name or not name.casefold().endswith(".vtk"):
            continue
        subject = _subject_name(name)
        if subject in reconstructions:
            raise ConfigurationError(
                f"Validation run contains duplicate reconstruction for {subject}"
            )
        reconstructions[subject] = _safe_output_path(run, relative)
    if set(reconstructions) != set(subjects):
        raise ConfigurationError("Validation reconstructions do not match the predeclared cohort")
    parts: list[np.ndarray] = []
    subject_values: list[tuple[str, float]] = []
    for subject in sorted(subjects):
        distances = symmetric_vertex_to_surface_distances(
            read_vtk_polydata(subjects[subject]),
            read_vtk_polydata(reconstructions[subject]),
        )
        parts.append(distances)
        subject_values.append((subject, float(np.quantile(distances, 0.95, method="linear"))))
        if progress_callback is not None:
            progress_callback(subject, len(subject_values), len(subjects))
    pooled = np.concatenate(parts)
    return ValidationRunEvidence(
        run_id=run_id,
        finalist_id=finalist_id,
        cohort_id=cohort_id,
        completed=base.completed,
        converged=base.converged,
        invalid_face_count=base.invalid_face_count,
        external_residual_p95=float(np.quantile(pooled, 0.95, method="linear")),
        distortion_p95=base.distortion_p95,
        runtime_seconds=base.runtime_seconds,
        atlas_path=base.atlas_path,
        subject_residual_p95=tuple(subject_values),
    )
