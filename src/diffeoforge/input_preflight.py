"""Read-only workload and coordinate-scale checks for selected surface cohorts."""

from __future__ import annotations

import hashlib
import json
import math
import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np

from diffeoforge.analysis.landmarks import read_landmark_csv
from diffeoforge.config import ConfigurationError
from diffeoforge.surface_io import SurfaceMeshMetadata, inspect_surface_mesh

InputPreflightSeverity = Literal["warning", "blocker"]

DENSE_MESH_FACE_COUNT = 100_000
HEAVY_COHORT_FACE_COUNT = 2_000_000
LARGE_MESH_FILE_BYTES = 20 * 1024**2
SCALE_WARNING_GAP = 8.0
SCALE_BLOCKER_GAP = 100.0
EXTREME_LANDMARK_MESH_RATIO = 50.0


@dataclass(frozen=True)
class InputPreflightIssue:
    """One evidence-backed workload or coordinate-scale finding."""

    code: str
    severity: InputPreflightSeverity
    title: str
    summary: str
    affected_meshes: tuple[str, ...] = ()


@dataclass(frozen=True)
class MeshInputPreflight:
    """Immutable inspection of one exact mesh and optional landmark cohort."""

    fingerprint: str
    metadata: tuple[SurfaceMeshMetadata, ...]
    landmark_path: Path | None
    landmark_sha256: str | None
    landmark_count: int | None
    total_bytes: int
    total_points: int
    total_triangles: int
    issues: tuple[InputPreflightIssue, ...]

    @property
    def blockers(self) -> tuple[InputPreflightIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity == "blocker")

    @property
    def warnings(self) -> tuple[InputPreflightIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity == "warning")

    @property
    def ready(self) -> bool:
        return not self.blockers


def _number(value: int) -> str:
    return f"{value:,}"


def _mib(value: int) -> str:
    return f"{value / 1024**2:.1f} MiB"


def _geometric_median(values: Sequence[float]) -> float:
    if not values or any(not math.isfinite(value) or value <= 0 for value in values):
        raise ValueError("coordinate-scale values must be positive and finite")
    return 10.0 ** statistics.median(math.log10(value) for value in values)


def _largest_scale_gap(
    values: Sequence[tuple[str, float]],
) -> tuple[float, tuple[tuple[str, float], ...], tuple[tuple[str, float], ...]]:
    ordered = tuple(sorted(values, key=lambda item: item[1]))
    if len(ordered) < 2:
        return 1.0, ordered, ()
    gaps = tuple(
        ordered[index + 1][1] / ordered[index][1]
        for index in range(len(ordered) - 1)
    )
    split = max(range(len(gaps)), key=gaps.__getitem__)
    return gaps[split], ordered[: split + 1], ordered[split + 1 :]


def _workload_issue(metadata: Sequence[SurfaceMeshMetadata]) -> InputPreflightIssue | None:
    dense = tuple(item for item in metadata if item.triangles >= DENSE_MESH_FACE_COUNT)
    large = tuple(item for item in metadata if item.bytes >= LARGE_MESH_FILE_BYTES)
    total_faces = sum(item.triangles for item in metadata)
    if not dense and not large and total_faces < HEAVY_COHORT_FACE_COUNT:
        return None
    largest = max(metadata, key=lambda item: item.triangles)
    ascii_dense = sum(
        item.source_format == "ply"
        and item.encoding == "ascii"
        and item.triangles >= DENSE_MESH_FACE_COUNT
        for item in metadata
    )
    affected = tuple(
        item.path
        for item in sorted(
            set((*dense, *large)),
            key=lambda item: (item.triangles, item.bytes),
            reverse=True,
        )
    )
    ascii_note = (
        f" {ascii_dense} dense PLY files are ASCII and will load especially slowly."
        if ascii_dense
        else ""
    )
    return InputPreflightIssue(
        code="large_mesh_workload",
        severity="warning",
        title="Unusually large or dense meshes",
        summary=(
            f"The selected cohort contains {_number(total_faces)} triangles in total; "
            f"{len(dense)} meshes have at least {_number(DENSE_MESH_FACE_COUNT)} faces. "
            f"The largest is {Path(largest.path).name} with "
            f"{_number(largest.triangles)} faces ({_mib(largest.bytes)})."
            f"{ascii_note} Consider documented simplified working copies before pilot "
            "calibration or atlasing. DiffeoForge will not decimate inputs silently."
        ),
        affected_meshes=tuple(Path(path).name for path in affected),
    )


def _mesh_scale_issue(metadata: Sequence[SurfaceMeshMetadata]) -> InputPreflightIssue | None:
    values = tuple((Path(item.path).name, item.bounding_box_diagonal) for item in metadata)
    gap, smaller, larger = _largest_scale_gap(values)
    if gap < SCALE_WARNING_GAP or not larger:
        return None
    severity: InputPreflightSeverity = (
        "blocker" if gap >= SCALE_BLOCKER_GAP else "warning"
    )
    smaller_center = _geometric_median(tuple(value for _name, value in smaller))
    larger_center = _geometric_median(tuple(value for _name, value in larger))
    separation = larger_center / smaller_center
    return InputPreflightIssue(
        code="mixed_mesh_coordinate_scales",
        severity=severity,
        title="Different mesh coordinate scales detected",
        summary=(
            f"Mesh bounding-box sizes form two separated groups: {len(smaller)} smaller "
            f"and {len(larger)} larger meshes, with typical sizes differing by about "
            f"{separation:.3g}x. This is consistent with mixed coordinate units. "
            "DiffeoForge cannot determine the correct absolute unit from geometry alone "
            "and will not rescale files automatically."
        ),
        affected_meshes=tuple(name for name, _value in smaller),
    )


def _landmark_scale_issue(
    metadata: Sequence[SurfaceMeshMetadata],
    landmark_values: np.ndarray,
) -> InputPreflightIssue | None:
    coordinates = np.asarray(landmark_values, dtype=np.float64)
    if coordinates.shape[0] != len(metadata) or coordinates.ndim != 3:
        raise ConfigurationError("Landmark coordinates do not match the inspected mesh cohort")
    ratios: list[tuple[str, float]] = []
    for item, points in zip(metadata, coordinates, strict=True):
        landmark_diagonal = float(np.linalg.norm(np.max(points, axis=0) - np.min(points, axis=0)))
        if not math.isfinite(landmark_diagonal) or landmark_diagonal <= 0:
            raise ConfigurationError(
                f"Landmarks have no positive finite 3D extent for {Path(item.path).name}"
            )
        ratios.append((Path(item.path).name, landmark_diagonal / item.bounding_box_diagonal))

    gap, lower, upper = _largest_scale_gap(ratios)
    all_ratios = tuple(value for _name, value in ratios)
    typical_ratio = _geometric_median(all_ratios)
    if gap < SCALE_WARNING_GAP and (
        1.0 / EXTREME_LANDMARK_MESH_RATIO
        <= typical_ratio
        <= EXTREME_LANDMARK_MESH_RATIO
    ):
        return None

    lower_center = _geometric_median(tuple(value for _name, value in lower))
    upper_center = (
        _geometric_median(tuple(value for _name, value in upper)) if upper else lower_center
    )
    if upper and abs(math.log10(upper_center)) > abs(math.log10(lower_center)):
        affected = upper
        affected_ratio = upper_center
    elif upper:
        affected = lower
        affected_ratio = lower_center
    else:
        affected = tuple(ratios)
        affected_ratio = typical_ratio

    severity: InputPreflightSeverity = (
        "blocker"
        if gap >= SCALE_BLOCKER_GAP
        or typical_ratio >= EXTREME_LANDMARK_MESH_RATIO
        or typical_ratio <= 1.0 / EXTREME_LANDMARK_MESH_RATIO
        else "warning"
    )
    group_note = (
        f" The landmark-to-mesh ratios split into groups separated by {gap:.3g}x."
        if upper
        else ""
    )
    return InputPreflightIssue(
        code="landmark_mesh_coordinate_scale_mismatch",
        severity=severity,
        title="Landmark and mesh coordinate scales disagree",
        summary=(
            f"For {len(affected)} of {len(metadata)} meshes, landmark extent is typically "
            f"{affected_ratio:.3g}x the mesh extent.{group_note} This is consistent with "
            "different coordinate units or an incorrect mesh-to-landmark match. GPA would "
            "apply invalid transforms to those meshes. Correct documented working copies "
            "before continuing; landmark coordinates and original meshes remain unchanged."
        ),
        affected_meshes=tuple(name for name, _value in affected),
    )


def assess_mesh_input_metadata(
    metadata: Sequence[SurfaceMeshMetadata],
    *,
    landmark_path: Path | None = None,
    landmark_sha256: str | None = None,
    landmark_labels: Sequence[str] | None = None,
    landmark_values: np.ndarray | None = None,
) -> MeshInputPreflight:
    """Assess already inspected metadata, primarily for reuse and deterministic tests."""

    items = tuple(metadata)
    if len(items) < 2:
        raise ConfigurationError("Mesh input preflight requires at least two meshes")
    if len({Path(item.path).name.casefold() for item in items}) != len(items):
        raise ConfigurationError("Mesh filenames must be unique for input preflight")
    issues: list[InputPreflightIssue] = []
    if workload := _workload_issue(items):
        issues.append(workload)
    if landmark_values is None:
        if scale_issue := _mesh_scale_issue(items):
            issues.append(scale_issue)
        landmark_count = None
    else:
        if landmark_labels is None:
            raise TypeError("landmark_labels are required with landmark_values")
        landmark_count = len(tuple(landmark_labels))
        if scale_issue := _landmark_scale_issue(items, landmark_values):
            issues.append(scale_issue)

    payload = {
        "meshes": [item.as_manifest() for item in items],
        "landmark_path": str(landmark_path) if landmark_path is not None else None,
        "landmark_sha256": landmark_sha256,
        "landmark_count": landmark_count,
        "issues": [issue.__dict__ for issue in issues],
    }
    fingerprint = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return MeshInputPreflight(
        fingerprint=fingerprint,
        metadata=items,
        landmark_path=landmark_path,
        landmark_sha256=landmark_sha256,
        landmark_count=landmark_count,
        total_bytes=sum(item.bytes for item in items),
        total_points=sum(item.points for item in items),
        total_triangles=sum(item.triangles for item in items),
        issues=tuple(issues),
    )


def inspect_mesh_input_cohort(
    mesh_paths: Sequence[Path | str],
    *,
    landmark_csv: Path | str | None = None,
) -> MeshInputPreflight:
    """Inspect an exact surface cohort and optional canonical landmark CSV read-only."""

    paths = tuple(Path(path).expanduser().resolve() for path in mesh_paths)
    if len(paths) < 2:
        raise ConfigurationError("Mesh input preflight requires at least two meshes")
    metadata = tuple(inspect_surface_mesh(path) for path in paths)
    if landmark_csv is None:
        return assess_mesh_input_metadata(metadata)
    landmark_path = Path(landmark_csv).expanduser().resolve()
    landmark_sha256 = hashlib.sha256(landmark_path.read_bytes()).hexdigest()
    labels, values = read_landmark_csv(landmark_path, tuple(path.name for path in paths))
    return assess_mesh_input_metadata(
        metadata,
        landmark_path=landmark_path,
        landmark_sha256=landmark_sha256,
        landmark_labels=labels,
        landmark_values=values,
    )


def format_mesh_input_preflight(report: MeshInputPreflight) -> str:
    """Return concise user-facing English desktop copy for one report."""

    lines = [
        f"Checked {len(report.metadata)} meshes: {_number(report.total_points)} vertices, "
        f"{_number(report.total_triangles)} triangles, {_mib(report.total_bytes)}.",
    ]
    if report.landmark_count is not None:
        lines.append(
            f"Compared {report.landmark_count} landmarks per mesh with the surface "
            "coordinate scale."
        )
    if not report.issues:
        lines.append("No unusual workload or relative coordinate-scale split was detected.")
        return "\n".join(lines)
    for issue in report.issues:
        label = "BLOCKER" if issue.severity == "blocker" else "WARNING"
        lines.append(f"\n{label} — {issue.title}\n{issue.summary}")
        if issue.affected_meshes:
            preview = ", ".join(issue.affected_meshes[:8])
            remainder = len(issue.affected_meshes) - 8
            lines.append(
                f"Affected examples: {preview}"
                + (f" (+{remainder} more)" if remainder > 0 else "")
            )
    return "\n".join(lines)
