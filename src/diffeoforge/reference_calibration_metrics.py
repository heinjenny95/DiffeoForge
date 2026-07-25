"""Deterministic quality-control metrics for executed calibration candidates.

These measurements supplement, but do not replace, Deformetrica's own
attachment objective or a researcher's anatomical registration review.  In
particular, the surface-distance statistic is an explicitly labelled
nearest-vertex QC proxy so it cannot be mistaken for the configured varifold
or current metric.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import numpy as np

from diffeoforge.analysis.reference_convergence_visualization import (
    detect_reference_stop_evidence,
)
from diffeoforge.config import ConfigurationError
from diffeoforge.mesh import TriangleMesh, read_vtk_polydata
from diffeoforge.mesh_quality import assess_triangle_mesh
from diffeoforge.result_report import RunReport, collect_run_report

_ESTIMATED_TEMPLATE_MARKER = "__EstimatedParameters__Template_"
_RECONSTRUCTION_MARKER = "__Reconstruction__"
_SUBJECT_MARKER = "__subject_"
_MAX_DISTANCE_VERTICES = 5_000
_DISTANCE_BLOCK_SIZE = 512


@dataclass(frozen=True)
class ReferenceCalibrationRunMetrics:
    """Auditable automatic evidence extracted from one immutable pilot run."""

    metric_version: str
    completed: bool
    converged: bool
    optimizer_stop_signal: str
    stop_interpretation: str
    final_iteration: int | None
    maximum_iterations: int
    residual_p95: float
    residual_median: float
    resampling_sensitivity: float
    deformation_energy: float
    attachment_objective_magnitude: float
    distortion_p95: float
    invalid_face_count: int
    runtime_seconds: float
    subject_reconstruction_count: int
    atlas_path: str
    notes: tuple[str, ...]

    def as_manifest(self) -> dict[str, object]:
        return {
            "metric_version": self.metric_version,
            "completed": self.completed,
            "converged": self.converged,
            "optimizer_stop_signal": self.optimizer_stop_signal,
            "stop_interpretation": self.stop_interpretation,
            "final_iteration": self.final_iteration,
            "maximum_iterations": self.maximum_iterations,
            "residual_p95": self.residual_p95,
            "residual_median": self.residual_median,
            "resampling_sensitivity": self.resampling_sensitivity,
            "deformation_energy": self.deformation_energy,
            "attachment_objective_magnitude": self.attachment_objective_magnitude,
            "distortion_p95": self.distortion_p95,
            "invalid_face_count": self.invalid_face_count,
            "runtime_seconds": self.runtime_seconds,
            "subject_reconstruction_count": self.subject_reconstruction_count,
            "atlas_path": self.atlas_path,
            "notes": list(self.notes),
            "metric_definitions": {
                "residual_p95": (
                    "Pooled symmetric nearest-vertex distance p95 after deterministic "
                    "sampling; this is a geometric QC proxy, not the Deformetrica "
                    "attachment objective."
                ),
                "resampling_sensitivity": (
                    "Relative difference between interleaved deterministic halves of "
                    "the pooled surface-distance observations."
                ),
                "deformation_energy": (
                    "Absolute final logged Deformetrica regularity term; reported as "
                    "an optimizer comparison proxy, not physical energy."
                ),
                "distortion_p95": (
                    "P95 absolute log triangle-area ratio between the initial template "
                    "and final atlas with identical ordered connectivity."
                ),
            },
        }


def _safe_output_path(run: Path, relative_value: object) -> Path:
    relative = PurePosixPath(str(relative_value))
    if (
        relative.is_absolute()
        or not relative.parts
        or "." in relative.parts
        or ".." in relative.parts
    ):
        raise ConfigurationError(
            f"Calibration output inventory contains an unsafe path: {relative}"
        )
    output = (run / "output").resolve()
    candidate = output.joinpath(*relative.parts).resolve()
    if not candidate.is_relative_to(output) or not candidate.is_file():
        raise ConfigurationError(f"Calibration output is missing: {relative}")
    return candidate


def _inventory_vtk(
    report: RunReport,
    marker: str,
) -> tuple[tuple[str, Path], ...]:
    values: list[tuple[str, Path]] = []
    for record in report.inventory:
        relative = str(record["path"])
        name = PurePosixPath(relative).name
        if marker in name and name.casefold().endswith(".vtk"):
            values.append((relative, _safe_output_path(report.run_directory, relative)))
    return tuple(sorted(values))


def _sample_vertices(vertices: tuple[tuple[float, float, float], ...]) -> np.ndarray:
    values = np.asarray(vertices, dtype=np.float64)
    if values.shape[0] <= _MAX_DISTANCE_VERTICES:
        return values
    indices = np.linspace(
        0,
        values.shape[0] - 1,
        num=_MAX_DISTANCE_VERTICES,
        dtype=np.int64,
    )
    return values[indices]


def _directed_nearest_distances(source: np.ndarray, target: np.ndarray) -> np.ndarray:
    if not len(source) or not len(target):
        raise ConfigurationError("Surface-distance QC requires nonempty meshes")
    result = np.empty(len(source), dtype=np.float64)
    for start in range(0, len(source), _DISTANCE_BLOCK_SIZE):
        block = source[start : start + _DISTANCE_BLOCK_SIZE]
        squared = np.sum((block[:, None, :] - target[None, :, :]) ** 2, axis=2)
        result[start : start + len(block)] = np.sqrt(np.min(squared, axis=1))
    return result


def symmetric_nearest_vertex_distances(
    first: TriangleMesh,
    second: TriangleMesh,
) -> np.ndarray:
    """Return deterministic sampled bidirectional nearest-vertex distances."""

    first_points = _sample_vertices(first.vertices)
    second_points = _sample_vertices(second.vertices)
    return np.concatenate(
        (
            _directed_nearest_distances(first_points, second_points),
            _directed_nearest_distances(second_points, first_points),
        )
    )


def _triangle_areas(mesh: TriangleMesh) -> np.ndarray:
    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    triangles = np.asarray(mesh.triangles, dtype=np.int64)
    first = vertices[triangles[:, 1]] - vertices[triangles[:, 0]]
    second = vertices[triangles[:, 2]] - vertices[triangles[:, 0]]
    return 0.5 * np.linalg.norm(np.cross(first, second), axis=1)


def _atlas_distortion(reference: TriangleMesh, atlas: TriangleMesh) -> float:
    if reference.triangles != atlas.triangles or len(reference.vertices) != len(
        atlas.vertices
    ):
        raise ConfigurationError(
            "Final atlas connectivity differs from the initial template; "
            "triangle-area distortion is undefined"
        )
    reference_area = _triangle_areas(reference)
    atlas_area = _triangle_areas(atlas)
    valid = (reference_area > 0.0) & (atlas_area > 0.0)
    if not np.all(valid):
        raise ConfigurationError(
            "Initial template or final atlas contains zero-area triangles"
        )
    return float(
        np.quantile(
            np.abs(np.log(atlas_area / reference_area)),
            0.95,
            method="linear",
        )
    )


def _subject_from_reconstruction_name(name: str) -> str:
    if _SUBJECT_MARKER not in name:
        raise ConfigurationError(
            f"Could not identify subject in reconstruction filename: {name}"
        )
    value = name.split(_SUBJECT_MARKER, 1)[1]
    if not value.casefold().endswith(".vtk"):
        raise ConfigurationError(f"Unexpected reconstruction extension: {name}")
    return value[:-4]


def _run_duration(report: RunReport) -> float:
    try:
        value = float(report.result["duration_seconds"])
    except (KeyError, TypeError, ValueError) as error:
        raise ConfigurationError(
            "Calibration result does not contain a valid duration"
        ) from error
    if not math.isfinite(value) or value < 0:
        raise ConfigurationError("Calibration result duration is invalid")
    return value


def collect_reference_calibration_run_metrics(
    run_directory: Path | str,
) -> ReferenceCalibrationRunMetrics:
    """Verify a completed run and derive deterministic calibration evidence."""

    run = Path(run_directory).expanduser().resolve()
    report = collect_run_report(run)
    if report.result["status"] != "completed":
        raise ConfigurationError(
            "Automatic calibration metrics require a completed pilot run"
        )
    templates = _inventory_vtk(report, _ESTIMATED_TEMPLATE_MARKER)
    if len(templates) != 1:
        raise ConfigurationError(
            "Calibration run must contain exactly one estimated atlas template"
        )
    reconstructions = _inventory_vtk(report, _RECONSTRUCTION_MARKER)
    effective_input = report.manifest["effective_config"]["input"]
    input_directory = Path(str(effective_input["directory"])).expanduser().resolve()
    template_path = Path(str(effective_input["template"])).expanduser().resolve()
    subject_pattern = str(effective_input["subject_pattern"])
    subjects = {
        path.name: path.resolve()
        for path in sorted(input_directory.glob(subject_pattern))
        if path.is_file() and path.resolve() != template_path
    }
    if not subjects:
        raise ConfigurationError("Calibration run contains no pilot subjects")
    by_subject: dict[str, Path] = {}
    for relative, path in reconstructions:
        subject = _subject_from_reconstruction_name(PurePosixPath(relative).name)
        if subject in by_subject:
            raise ConfigurationError(
                f"Calibration run contains duplicate reconstruction for {subject}"
            )
        by_subject[subject] = path
    if set(by_subject) != set(subjects):
        raise ConfigurationError(
            "Calibration reconstructions do not match the immutable pilot cohort; "
            f"missing={sorted(set(subjects) - set(by_subject))}, "
            f"unexpected={sorted(set(by_subject) - set(subjects))}"
        )

    distance_parts: list[np.ndarray] = []
    for subject in sorted(subjects):
        distance_parts.append(
            symmetric_nearest_vertex_distances(
                read_vtk_polydata(subjects[subject]),
                read_vtk_polydata(by_subject[subject]),
            )
        )
    distances = np.concatenate(distance_parts)
    residual_p95 = float(np.quantile(distances, 0.95, method="linear"))
    residual_median = float(np.quantile(distances, 0.5, method="linear"))
    first_half = float(np.quantile(distances[::2], 0.95, method="linear"))
    second_half = float(np.quantile(distances[1::2], 0.95, method="linear"))
    sensitivity_denominator = max(first_half, second_half, np.finfo(float).eps)
    resampling_sensitivity = abs(first_half - second_half) / sensitivity_denominator

    atlas_path = templates[0][1]
    atlas = read_vtk_polydata(atlas_path)
    quality = assess_triangle_mesh(atlas.vertices, atlas.triangles)
    invalid_faces = (
        quality.zero_area_faces
        + quality.zero_length_edge_faces
        + quality.undefined_angle_faces
    )
    distortion = _atlas_distortion(read_vtk_polydata(template_path), atlas)
    if not report.convergence:
        raise ConfigurationError(
            "Calibration run has no verified optimization history"
        )
    final = report.convergence[-1]
    final_iteration = report.final_iteration
    log_path = run / "logs" / "deformetrica.log"
    try:
        log_text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError as error:
        raise ConfigurationError(
            f"Could not read calibration terminal log: {error}"
        ) from error
    stop = detect_reference_stop_evidence(
        log_text,
        final_iteration=final_iteration,
        maximum_iterations=report.max_iterations,
    )
    converged = stop.signal == "tolerance_threshold"
    notes = (
        "Only Deformetrica's explicit tolerance-threshold message is treated as "
        "optimizer convergence evidence; it is not proof of adequate registration.",
        "Surface distances use at most 5,000 deterministic vertices per direction "
        "and are not Deformetrica's configured attachment metric.",
    )
    return ReferenceCalibrationRunMetrics(
        metric_version="0.1",
        completed=True,
        converged=converged,
        optimizer_stop_signal=stop.signal,
        stop_interpretation=stop.summary,
        final_iteration=final_iteration,
        maximum_iterations=report.max_iterations,
        residual_p95=residual_p95,
        residual_median=residual_median,
        resampling_sensitivity=float(resampling_sensitivity),
        deformation_energy=abs(float(final.regularity)),
        attachment_objective_magnitude=abs(float(final.attachment)),
        distortion_p95=distortion,
        invalid_face_count=invalid_faces,
        runtime_seconds=_run_duration(report),
        subject_reconstruction_count=len(reconstructions),
        atlas_path=str(atlas_path),
        notes=notes,
    )


def atlas_rms_distance(first_path: Path | str, second_path: Path | str) -> float:
    """Return ordered-vertex RMS displacement for matching atlas topology."""

    first = read_vtk_polydata(first_path)
    second = read_vtk_polydata(second_path)
    if first.triangles != second.triangles or len(first.vertices) != len(
        second.vertices
    ):
        raise ConfigurationError(
            "Numerical atlas comparison requires identical ordered topology"
        )
    difference = np.asarray(first.vertices) - np.asarray(second.vertices)
    return float(np.sqrt(np.mean(np.sum(difference**2, axis=1))))
