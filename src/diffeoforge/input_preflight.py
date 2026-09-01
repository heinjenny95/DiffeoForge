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
from diffeoforge.mesh_quality import (
    ATLAS_INPUT_MESH_QUALITY_SETTINGS,
    MeshQualityResult,
    assess_triangle_mesh,
    mesh_quality_failures,
)
from diffeoforge.surface_io import SurfaceMeshMetadata, load_surface_mesh

InputPreflightSeverity = Literal["warning", "blocker"]

HEAVY_COHORT_FACE_COUNT = 5_000_000
HEAVY_ATTACHMENT_INTERACTION_COUNT = 25_000_000_000
HEAVY_COHORT_FILE_BYTES = 1024**3
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
class InputMeshQualityObservation:
    """Structural quality evidence retained from the initial mesh read."""

    path: str
    result: MeshQualityResult


@dataclass(frozen=True)
class MeshInputPreflight:
    """Immutable inspection of one exact mesh and optional landmark cohort."""

    fingerprint: str
    metadata: tuple[SurfaceMeshMetadata, ...]
    landmark_path: Path | None
    landmark_sha256: str | None
    landmark_count: int | None
    template_name: str
    subject_count: int
    template_triangles: int
    estimated_attachment_interactions: int
    procrustes_enabled: bool
    scale_to_unit_centroid_size: bool
    total_bytes: int
    total_points: int
    total_triangles: int
    mesh_quality: tuple[InputMeshQualityObservation, ...]
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


def _workload_issue(
    metadata: Sequence[SurfaceMeshMetadata],
    *,
    template_index: int,
) -> InputPreflightIssue | None:
    total_faces = sum(item.triangles for item in metadata)
    total_bytes = sum(item.bytes for item in metadata)
    template = metadata[template_index]
    target_faces = total_faces - template.triangles
    estimated_interactions = template.triangles * target_faces
    if (
        total_faces < HEAVY_COHORT_FACE_COUNT
        and total_bytes < HEAVY_COHORT_FILE_BYTES
        and estimated_interactions < HEAVY_ATTACHMENT_INTERACTION_COUNT
    ):
        return None
    largest = max(metadata, key=lambda item: item.triangles)
    ascii_meshes = tuple(
        item
        for item in metadata
        if item.source_format == "ply" and item.encoding.casefold() == "ascii"
    )
    ascii_note = (
        f" {len(ascii_meshes)} PLY files are ASCII and add parsing overhead."
        if ascii_meshes
        else ""
    )
    return InputPreflightIssue(
        code="large_mesh_workload",
        severity="warning",
        title="High combined atlas workload",
        summary=(
            f"The template has {_number(template.triangles)} faces and the "
            f"{len(metadata) - 1} targets contain {_number(target_faces)} faces in total. "
            "One full template-to-target attachment sweep therefore represents about "
            f"{_number(estimated_interactions)} face-pair interactions before tiling, "
            "timepoints, and optimizer iterations. The complete cohort contains "
            f"{_number(total_faces)} faces ({_mib(total_bytes)}); the largest single mesh "
            f"is {Path(largest.path).name} with {_number(largest.triangles)} faces."
            f"{ascii_note} This is an engineering workload estimate, not evidence that "
            "the scientific resolution is unnecessary. Keep required detail; use server "
            "execution or validated multiresolution working copies only when needed. "
            "DiffeoForge will not decimate inputs silently."
        ),
    )


def _mesh_scale_issue(
    metadata: Sequence[SurfaceMeshMetadata],
    *,
    procrustes_enabled: bool,
    scale_to_unit_centroid_size: bool,
) -> InputPreflightIssue | None:
    values = tuple((Path(item.path).name, item.bounding_box_diagonal) for item in metadata)
    gap, smaller, larger = _largest_scale_gap(values)
    if gap < SCALE_WARNING_GAP or not larger:
        return None
    smaller_center = _geometric_median(tuple(value for _name, value in smaller))
    larger_center = _geometric_median(tuple(value for _name, value in larger))
    separation = larger_center / smaller_center
    alignment_note = (
        "GPA is active but centroid-size scaling is disabled, so this size difference "
        "will remain in the atlas."
        if procrustes_enabled and not scale_to_unit_centroid_size
        else "No active unit-centroid-size GPA will remove this size difference before "
        "atlasing."
    )
    return InputPreflightIssue(
        code="mixed_mesh_coordinate_scales",
        severity="warning",
        title="Separated mesh-size groups need review",
        summary=(
            f"Mesh bounding-box sizes form two separated groups: {len(smaller)} smaller "
            f"and {len(larger)} larger meshes, with typical sizes differing by about "
            f"{separation:.3g}x. Geometry alone cannot distinguish biological size "
            f"variation from mixed coordinate units. {alignment_note} Confirm that this "
            "is the intended size-and-shape policy. DiffeoForge cannot infer an absolute "
            "unit and will not rescale files automatically."
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
    if gap < SCALE_WARNING_GAP and typical_ratio <= EXTREME_LANDMARK_MESH_RATIO:
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


def _mesh_quality_issues(
    observations: Sequence[InputMeshQualityObservation],
) -> tuple[InputPreflightIssue, ...]:
    if not observations:
        return ()
    failures_by_gate: dict[str, list[str]] = {}
    open_meshes: list[str] = []
    multipart_meshes: list[str] = []
    for observation in observations:
        name = Path(observation.path).name
        for failure in mesh_quality_failures(
            observation.result,
            ATLAS_INPUT_MESH_QUALITY_SETTINGS,
        ):
            failures_by_gate.setdefault(failure, []).append(name)
        if observation.result.boundary_edges > 0:
            open_meshes.append(name)
        if observation.result.face_connected_components > 1:
            multipart_meshes.append(name)

    issues: list[InputPreflightIssue] = []
    mesh_count = len(observations)
    for gate, affected in failures_by_gate.items():
        count = len(affected)
        noun = "mesh fails" if count == 1 else "meshes fail"
        issues.append(
            InputPreflightIssue(
                code=f"mesh_quality_{gate.replace('-', '_').replace(' ', '_')}",
                severity="blocker",
                title=f"Required mesh-quality gate failed: {gate}",
                summary=(
                    f"{count} of {mesh_count} selected {noun} the required structural "
                    f"atlas-input gate because {'it contains' if count == 1 else 'they contain'} "
                    f"{gate}. Use documented repaired working copies or correct source "
                    "exports before continuing. DiffeoForge did not modify any input."
                ),
                affected_meshes=tuple(affected),
            )
        )
    if open_meshes:
        issues.append(
            InputPreflightIssue(
                code="open_mesh_surfaces",
                severity="warning",
                title="Open mesh surfaces need review",
                summary=(
                    f"{len(open_meshes)} of {mesh_count} selected meshes have boundary "
                    "edges. Open anatomical surfaces can be intentional, so this is "
                    "advisory rather than an automatic rejection. Confirm and document "
                    "the study-level decision; DiffeoForge will not close surfaces."
                ),
                affected_meshes=tuple(open_meshes),
            )
        )
    if multipart_meshes:
        issues.append(
            InputPreflightIssue(
                code="multipart_mesh_surfaces",
                severity="warning",
                title="Multiple surface components need review",
                summary=(
                    f"{len(multipart_meshes)} of {mesh_count} selected meshes contain "
                    "multiple face-connected components. This can be anatomically "
                    "intentional; confirm and document it before atlasing. DiffeoForge "
                    "will not remove components automatically."
                ),
                affected_meshes=tuple(multipart_meshes),
            )
        )
    return tuple(issues)


def assess_mesh_input_metadata(
    metadata: Sequence[SurfaceMeshMetadata],
    *,
    mesh_quality: Sequence[InputMeshQualityObservation] = (),
    template_path: Path | str | None = None,
    landmark_path: Path | None = None,
    landmark_sha256: str | None = None,
    landmark_labels: Sequence[str] | None = None,
    landmark_values: np.ndarray | None = None,
    procrustes_enabled: bool = True,
    scale_to_unit_centroid_size: bool = True,
) -> MeshInputPreflight:
    """Assess already inspected metadata, primarily for reuse and deterministic tests."""

    items = tuple(metadata)
    quality_observations = tuple(mesh_quality)
    if len(items) < 2:
        raise ConfigurationError("Mesh input preflight requires at least two meshes")
    if len({Path(item.path).name.casefold() for item in items}) != len(items):
        raise ConfigurationError("Mesh filenames must be unique for input preflight")
    if quality_observations and len(quality_observations) != len(items):
        raise ConfigurationError(
            "Mesh-quality observations do not match the inspected mesh cohort"
        )
    if quality_observations and any(
        Path(observation.path).expanduser().resolve()
        != Path(item.path).expanduser().resolve()
        for observation, item in zip(quality_observations, items, strict=True)
    ):
        raise ConfigurationError(
            "Mesh-quality observation order differs from the inspected mesh cohort"
        )
    if not isinstance(procrustes_enabled, bool):
        raise TypeError("procrustes_enabled must be a boolean")
    if not isinstance(scale_to_unit_centroid_size, bool):
        raise TypeError("scale_to_unit_centroid_size must be a boolean")
    if template_path is None:
        template_index = 0
    else:
        expected_template = Path(template_path).expanduser().resolve()
        matches = tuple(
            index
            for index, item in enumerate(items)
            if Path(item.path).expanduser().resolve() == expected_template
        )
        if len(matches) != 1:
            raise ConfigurationError(
                "Template path must identify exactly one inspected mesh"
            )
        template_index = matches[0]
    template = items[template_index]
    total_triangles = sum(item.triangles for item in items)
    estimated_attachment_interactions = template.triangles * (
        total_triangles - template.triangles
    )
    effective_procrustes = procrustes_enabled and landmark_values is not None
    issues = list(_mesh_quality_issues(quality_observations))
    if workload := _workload_issue(items, template_index=template_index):
        issues.append(workload)
    if landmark_values is not None:
        if landmark_labels is None:
            raise TypeError("landmark_labels are required with landmark_values")
        landmark_count = len(tuple(landmark_labels))
        if effective_procrustes and (
            scale_issue := _landmark_scale_issue(items, landmark_values)
        ):
            issues.append(scale_issue)
    else:
        landmark_count = None
    if not (effective_procrustes and scale_to_unit_centroid_size):
        if scale_issue := _mesh_scale_issue(
            items,
            procrustes_enabled=effective_procrustes,
            scale_to_unit_centroid_size=scale_to_unit_centroid_size,
        ):
            issues.append(scale_issue)

    payload = {
        "meshes": [item.as_manifest() for item in items],
        "landmark_path": str(landmark_path) if landmark_path is not None else None,
        "landmark_sha256": landmark_sha256,
        "landmark_count": landmark_count,
        "template": str(template.path),
        "estimated_attachment_interactions": estimated_attachment_interactions,
        "procrustes_enabled": effective_procrustes,
        "scale_to_unit_centroid_size": (
            scale_to_unit_centroid_size if effective_procrustes else False
        ),
        "mesh_quality": [
            {
                "path": observation.path,
                "result": observation.result.as_manifest(),
            }
            for observation in quality_observations
        ],
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
        template_name=Path(template.path).name,
        subject_count=len(items) - 1,
        template_triangles=template.triangles,
        estimated_attachment_interactions=estimated_attachment_interactions,
        procrustes_enabled=effective_procrustes,
        scale_to_unit_centroid_size=(
            scale_to_unit_centroid_size if effective_procrustes else False
        ),
        total_bytes=sum(item.bytes for item in items),
        total_points=sum(item.points for item in items),
        total_triangles=total_triangles,
        mesh_quality=quality_observations,
        issues=tuple(issues),
    )


def inspect_mesh_input_cohort(
    mesh_paths: Sequence[Path | str],
    *,
    template_path: Path | str | None = None,
    landmark_csv: Path | str | None = None,
    procrustes_enabled: bool = True,
    scale_to_unit_centroid_size: bool = True,
) -> MeshInputPreflight:
    """Inspect an exact surface cohort and optional canonical landmark CSV read-only."""

    paths = tuple(Path(path).expanduser().resolve() for path in mesh_paths)
    if len(paths) < 2:
        raise ConfigurationError("Mesh input preflight requires at least two meshes")
    metadata: list[SurfaceMeshMetadata] = []
    quality_observations: list[InputMeshQualityObservation] = []
    for path in paths:
        loaded = load_surface_mesh(path)
        metadata.append(loaded.metadata)
        quality_observations.append(
            InputMeshQualityObservation(
                path=str(path),
                result=assess_triangle_mesh(
                    loaded.geometry.vertices,
                    loaded.geometry.triangles,
                ),
            )
        )
    metadata_tuple = tuple(metadata)
    quality_tuple = tuple(quality_observations)
    if landmark_csv is None:
        return assess_mesh_input_metadata(
            metadata_tuple,
            mesh_quality=quality_tuple,
            template_path=template_path,
            procrustes_enabled=False,
            scale_to_unit_centroid_size=scale_to_unit_centroid_size,
        )
    landmark_path = Path(landmark_csv).expanduser().resolve()
    landmark_sha256 = hashlib.sha256(landmark_path.read_bytes()).hexdigest()
    labels, values = read_landmark_csv(landmark_path, tuple(path.name for path in paths))
    return assess_mesh_input_metadata(
        metadata_tuple,
        mesh_quality=quality_tuple,
        template_path=template_path,
        landmark_path=landmark_path,
        landmark_sha256=landmark_sha256,
        landmark_labels=labels,
        landmark_values=values,
        procrustes_enabled=procrustes_enabled,
        scale_to_unit_centroid_size=scale_to_unit_centroid_size,
    )


def format_mesh_input_preflight(report: MeshInputPreflight) -> str:
    """Return concise user-facing English desktop copy for one report."""

    lines = [
        f"Checked {len(report.metadata)} meshes (template {report.template_name} + "
        f"{report.subject_count} targets): {_number(report.total_points)} vertices, "
        f"{_number(report.total_triangles)} triangles, {_mib(report.total_bytes)}. "
        "Estimated template-to-target face pairs per full attachment sweep: "
        f"{_number(report.estimated_attachment_interactions)}.",
    ]
    if report.mesh_quality:
        lines.append(
            "Checked required structural topology and degenerate-face gates for every "
            "selected mesh. Open surfaces and multiple components are reported "
            "separately as study-level advisories."
        )
    if report.landmark_count is not None:
        if report.procrustes_enabled:
            scaling = (
                "with unit-centroid-size scaling"
                if report.scale_to_unit_centroid_size
                else "without centroid-size scaling"
            )
            lines.append(
                f"Checked {report.landmark_count} landmarks per mesh against its surface "
                f"coordinate frame; GPA is active {scaling}."
            )
        else:
            lines.append(
                f"Matched {report.landmark_count} landmarks per mesh, but GPA is disabled; "
                "the landmarks will not transform atlas surfaces."
            )
    if not report.issues:
        lines.append(
            "No required structural-quality failure was detected. No exceptional combined "
            "workload or unresolved coordinate-scale mismatch was detected. Individual "
            "face counts alone are not treated as a problem."
        )
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
