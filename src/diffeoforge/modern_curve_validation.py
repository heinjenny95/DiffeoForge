"""Source-bound manual-curve validation for paired Modern atlas bundles.

The validation deliberately keeps coordinate transfer, reconstruction projection,
and template-space correspondence dispersion separate.  This prevents a small
reconstruction residual from being mistaken for evidence of biological homology.
"""

from __future__ import annotations

import csv
import json
import math
import shutil
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from diffeoforge.atomic_io import write_text_safely
from diffeoforge.config import ConfigurationError
from diffeoforge.mesh import TriangleMesh, sha256_file
from diffeoforge.modern_bundle import MANIFEST_NAME, verify_modern_atlas_bundle
from diffeoforge.reference_validation_metrics import _point_triangle_squared_distance
from diffeoforge.runs import publish_directory_exclusive
from diffeoforge.strict_json import load_strict_json_object
from diffeoforge.surface_io import load_surface_mesh

MODERN_CURVE_VALIDATION_VERSION = "0.1"
MODERN_CURVE_VALIDATION_MANIFEST = "modern-curve-validation.json"
MODERN_CURVE_VALIDATION_SIDECAR = "modern-curve-validation.sha256"
MAPPING_COLUMNS = (
    "curve_csv",
    "legacy_aligned_mesh",
    "legacy_raw_mesh",
    "legacy_anchor_file",
    "current_subject_label",
    "status",
    "note",
)
_CLOSEST_POINT_BLOCK_SIZE = 16
_TRANSFER_SURFACE_SAMPLE_LIMIT = 512
_DISTANCE_BLOCK_SIZE = 48
SCIENTIFIC_BOUNDARY = (
    "This is a retrospective pilot validation of atlas correspondence against "
    "independently traced surface curves. Legacy-to-current coordinate transfer, "
    "small cohort size, curve endpoint homology, and source scan identity remain "
    "limitations. The evidence does not establish biological validity or an "
    "automatic engine winner."
)
VERIFICATION_CONTRACT = (
    "Both Modern bundles, the complete curve-directory inventory, the explicit "
    "identity mapping, every included legacy source, current GPA landmarks and "
    "transforms, current raw meshes, and the complete numerical calculation are "
    "reverified from source bytes."
)


class ModernCurveValidationError(RuntimeError):
    """Raised when manual-curve validation input or evidence is invalid."""


@dataclass(frozen=True)
class SimilarityTransform:
    """Proper 3D similarity transform using row-vector coordinates."""

    source_centroid: np.ndarray
    target_centroid: np.ndarray
    scale: float
    rotation: np.ndarray

    def apply(self, values: np.ndarray) -> np.ndarray:
        points = np.asarray(values, dtype=np.float64)
        return ((points - self.source_centroid) * self.scale) @ self.rotation + (
            self.target_centroid
        )


@dataclass(frozen=True)
class MappingRow:
    curve_csv: Path
    legacy_aligned_mesh: Path | None
    legacy_raw_mesh: Path | None
    legacy_anchor_file: Path | None
    current_subject_label: str
    status: str
    note: str


@dataclass(frozen=True)
class ModernCurveValidationArtifact:
    artifact_directory: Path
    manifest: dict[str, Any]


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        indent=2,
        sort_keys=True,
        ensure_ascii=False,
        allow_nan=False,
    ) + "\n"


def _fit_similarity(source: np.ndarray, target: np.ndarray) -> SimilarityTransform:
    first = np.asarray(source, dtype=np.float64)
    second = np.asarray(target, dtype=np.float64)
    if first.shape != second.shape or first.ndim != 2 or first.shape[1] != 3:
        raise ModernCurveValidationError("Similarity inputs must have equal (n, 3) shape")
    if len(first) < 3 or not np.isfinite(first).all() or not np.isfinite(second).all():
        raise ModernCurveValidationError(
            "Similarity inputs require at least three finite 3D points"
        )
    source_centroid = first.mean(axis=0)
    target_centroid = second.mean(axis=0)
    centered_source = first - source_centroid
    centered_target = second - target_centroid
    if np.linalg.matrix_rank(centered_source) < 2:
        raise ModernCurveValidationError("Similarity source points are collinear")
    left, _, right_transpose = np.linalg.svd(centered_source.T @ centered_target)
    rotation = left @ right_transpose
    if np.linalg.det(rotation) < 0:
        left[:, -1] *= -1
        rotation = left @ right_transpose
    denominator = float(np.sum(centered_source * centered_source))
    scale = float(
        np.sum((centered_source @ rotation) * centered_target) / denominator
    )
    if not math.isfinite(scale) or scale <= 0 or not np.isclose(
        np.linalg.det(rotation), 1.0, rtol=1e-12, atol=1e-12
    ):
        raise ModernCurveValidationError("Could not fit a proper positive similarity")
    return SimilarityTransform(source_centroid, target_centroid, scale, rotation)


def _resample_curve(points: np.ndarray, sample_count: int) -> np.ndarray:
    values = np.asarray(points, dtype=np.float64)
    if values.ndim != 2 or values.shape[1] != 3 or len(values) < 2:
        raise ModernCurveValidationError("A curve requires at least two 3D points")
    if sample_count < 4:
        raise ModernCurveValidationError("Curve validation requires at least four samples")
    segments = np.linalg.norm(np.diff(values, axis=0), axis=1)
    if not np.isfinite(segments).all() or np.any(segments <= np.finfo(float).eps):
        raise ModernCurveValidationError("Curve contains a zero-length or invalid segment")
    cumulative = np.concatenate((np.zeros(1, dtype=np.float64), np.cumsum(segments)))
    targets = np.linspace(0.0, cumulative[-1], num=sample_count, dtype=np.float64)
    result = np.empty((sample_count, 3), dtype=np.float64)
    for axis in range(3):
        result[:, axis] = np.interp(targets, cumulative, values[:, axis])
    return result


def _edge_candidates(
    points: np.ndarray,
    first: np.ndarray,
    second: np.ndarray,
    first_weights: np.ndarray,
    second_weights: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    edge = second - first
    denominator = np.sum(edge * edge, axis=1)
    if np.any(denominator <= np.finfo(float).eps):
        raise ModernCurveValidationError("Surface contains a zero-length triangle edge")
    parameter = np.sum(
        (points[:, None, :] - first[None, :, :]) * edge[None, :, :], axis=2
    ) / denominator[None, :]
    parameter = np.clip(parameter, 0.0, 1.0)
    closest = first[None, :, :] + parameter[:, :, None] * edge[None, :, :]
    weights = (
        (1.0 - parameter)[:, :, None] * first_weights
        + parameter[:, :, None] * second_weights
    )
    squared = np.sum((closest - points[:, None, :]) ** 2, axis=2)
    return squared, closest, weights


def _closest_surface_coordinates(
    points: np.ndarray,
    mesh: TriangleMesh,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return exact distances, triangle indices, and barycentric coordinates."""

    queries = np.asarray(points, dtype=np.float64)
    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    indices = np.asarray(mesh.triangles, dtype=np.int64)
    triangles = vertices[indices]
    if queries.ndim != 2 or queries.shape[1] != 3 or not np.isfinite(queries).all():
        raise ModernCurveValidationError("Surface queries must be finite (n, 3) points")
    first = triangles[:, 0]
    second = triangles[:, 1]
    third = triangles[:, 2]
    edge0 = second - first
    edge1 = third - first
    normal = np.cross(edge0, edge1)
    normal_squared = np.sum(normal * normal, axis=1)
    denominator = (
        np.sum(edge0 * edge0, axis=1) * np.sum(edge1 * edge1, axis=1)
        - np.sum(edge0 * edge1, axis=1) ** 2
    )
    if np.any(normal_squared <= np.finfo(float).eps) or np.any(
        denominator <= np.finfo(float).eps
    ):
        raise ModernCurveValidationError("Surface contains a degenerate triangle")
    unit = np.eye(3, dtype=np.float64)
    distances = np.empty(len(queries), dtype=np.float64)
    triangle_indices = np.empty(len(queries), dtype=np.int64)
    barycentric = np.empty((len(queries), 3), dtype=np.float64)
    dot00 = np.sum(edge0 * edge0, axis=1)
    dot01 = np.sum(edge0 * edge1, axis=1)
    dot11 = np.sum(edge1 * edge1, axis=1)
    for start in range(0, len(queries), _CLOSEST_POINT_BLOCK_SIZE):
        block = queries[start : start + _CLOSEST_POINT_BLOCK_SIZE]
        offset = block[:, None, :] - first[None, :, :]
        signed = np.sum(offset * normal[None, :, :], axis=2) / normal_squared[None, :]
        projected = block[:, None, :] - signed[:, :, None] * normal[None, :, :]
        projected_offset = projected - first[None, :, :]
        dot20 = np.sum(projected_offset * edge0[None, :, :], axis=2)
        dot21 = np.sum(projected_offset * edge1[None, :, :], axis=2)
        second_weight = (
            dot11[None, :] * dot20 - dot01[None, :] * dot21
        ) / denominator[None, :]
        third_weight = (
            dot00[None, :] * dot21 - dot01[None, :] * dot20
        ) / denominator[None, :]
        first_weight = 1.0 - second_weight - third_weight
        face_weights = np.stack(
            (first_weight, second_weight, third_weight), axis=2
        )
        inside = np.all(face_weights >= -1e-12, axis=2)
        face_squared = signed * signed * normal_squared[None, :]
        face_squared[~inside] = np.inf
        candidates = [(face_squared, projected, face_weights)]
        candidates.append(_edge_candidates(block, first, second, unit[0], unit[1]))
        candidates.append(_edge_candidates(block, second, third, unit[1], unit[2]))
        candidates.append(_edge_candidates(block, third, first, unit[2], unit[0]))
        local_squared = np.stack([candidate[0] for candidate in candidates], axis=2)
        local_weights = np.stack([candidate[2] for candidate in candidates], axis=2)
        flat_indices = np.argmin(local_squared.reshape(len(block), -1), axis=1)
        block_triangles = flat_indices // len(candidates)
        block_candidates = flat_indices % len(candidates)
        rows = np.arange(len(block))
        best_squared = local_squared[rows, block_triangles, block_candidates]
        distances[start : start + len(block)] = np.sqrt(np.maximum(best_squared, 0.0))
        triangle_indices[start : start + len(block)] = block_triangles
        barycentric[start : start + len(block)] = local_weights[
            rows, block_triangles, block_candidates
        ]
    return distances, triangle_indices, barycentric


def _surface_transfer_distances(
    source_vertices: np.ndarray,
    target: TriangleMesh,
) -> tuple[np.ndarray, int]:
    points = np.asarray(source_vertices, dtype=np.float64)
    sample_count = min(len(points), _TRANSFER_SURFACE_SAMPLE_LIMIT)
    if len(points) > sample_count:
        indices = np.linspace(0, len(points) - 1, num=sample_count, dtype=np.int64)
        points = points[indices]
    target_vertices = np.asarray(target.vertices, dtype=np.float64)
    target_triangles = target_vertices[np.asarray(target.triangles, dtype=np.int64)]
    distances = np.empty(len(points), dtype=np.float64)
    for start in range(0, len(points), _DISTANCE_BLOCK_SIZE):
        block = points[start : start + _DISTANCE_BLOCK_SIZE]
        squared = _point_triangle_squared_distance(block, target_triangles)
        distances[start : start + len(block)] = np.sqrt(np.maximum(squared, 0.0))
    return distances, sample_count


def _read_curve(path: Path) -> np.ndarray:
    try:
        with path.open("r", encoding="utf-8-sig", errors="strict", newline="") as handle:
            rows = list(csv.reader(handle))
    except (OSError, UnicodeError, csv.Error) as error:
        raise ModernCurveValidationError(f"Could not read curve CSV: {path}") from error
    if len(rows) < 4 or len(rows[0]) < 2 or rows[0][0] != "Landmarks":
        raise ModernCurveValidationError(f"Curve CSV header differs: {path}")
    try:
        declared = int(rows[0][1])
        points = np.asarray(
            [[float(row[index]) for index in (3, 4, 5)] for row in rows[2:]],
            dtype=np.float64,
        )
    except (IndexError, TypeError, ValueError) as error:
        raise ModernCurveValidationError(f"Curve CSV coordinates are invalid: {path}") from error
    if len(points) != declared or len(points) < 2 or not np.isfinite(points).all():
        raise ModernCurveValidationError(f"Curve CSV point count or values differ: {path}")
    return points


def _read_legacy_anchors(path: Path) -> np.ndarray:
    try:
        lines = path.read_text(encoding="utf-8", errors="strict").splitlines()
    except (OSError, UnicodeError) as error:
        raise ModernCurveValidationError(f"Could not read legacy anchors: {path}") from error
    values: list[list[float]] = []
    for line in lines:
        fields = line.split()
        if len(fields) != 3:
            continue
        try:
            values.append([float(field) for field in fields])
        except ValueError:
            continue
    if len(values) != 3:
        raise ModernCurveValidationError(
            f"Legacy anchor file must contain exactly three coordinate rows: {path}"
        )
    result = np.asarray(values, dtype=np.float64)
    if not np.isfinite(result).all():
        raise ModernCurveValidationError(f"Legacy anchors are not finite: {path}")
    return result


def _optional_path(value: str, base: Path) -> Path | None:
    if not value.strip():
        return None
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base / path
    return path.resolve()


def _read_mapping(path: Path, curve_directory: Path) -> tuple[MappingRow, ...]:
    try:
        with path.open("r", encoding="utf-8-sig", errors="strict", newline="") as handle:
            reader = csv.DictReader(handle)
            if tuple(reader.fieldnames or ()) != MAPPING_COLUMNS:
                raise ModernCurveValidationError(
                    "Curve mapping header must be exactly: " + ",".join(MAPPING_COLUMNS)
                )
            raw_rows = list(reader)
    except ModernCurveValidationError:
        raise
    except (OSError, UnicodeError, csv.Error) as error:
        raise ModernCurveValidationError(f"Could not read curve mapping: {path}") from error
    base = path.parent
    rows: list[MappingRow] = []
    for line_number, raw in enumerate(raw_rows, start=2):
        if None in raw:
            raise ModernCurveValidationError(
                f"Curve mapping row {line_number} has unexpected columns"
            )
        curve = _optional_path(raw["curve_csv"], base)
        status = raw["status"].strip().casefold()
        note = raw["note"].strip()
        subject = raw["current_subject_label"].strip()
        if curve is None or curve.parent != curve_directory or not curve.is_file():
            raise ModernCurveValidationError(
                f"Curve mapping row {line_number} is outside the curve inventory"
            )
        if status not in {"include", "exclude"}:
            raise ModernCurveValidationError(
                f"Curve mapping row {line_number} status must be include or exclude"
            )
        aligned = _optional_path(raw["legacy_aligned_mesh"], base)
        legacy_raw = _optional_path(raw["legacy_raw_mesh"], base)
        anchors = _optional_path(raw["legacy_anchor_file"], base)
        if status == "include":
            if not subject or any(value is None for value in (aligned, legacy_raw, anchors)):
                raise ModernCurveValidationError(
                    f"Included curve mapping row {line_number} is incomplete"
                )
            if any(not value.is_file() for value in (aligned, legacy_raw, anchors)):
                raise ModernCurveValidationError(
                    f"Included curve mapping row {line_number} names a missing source"
                )
        elif not note:
            raise ModernCurveValidationError(
                f"Excluded curve mapping row {line_number} requires a reason"
            )
        rows.append(
            MappingRow(curve, aligned, legacy_raw, anchors, subject, status, note)
        )
    if not rows or not any(row.status == "include" for row in rows):
        raise ModernCurveValidationError("Curve mapping contains no included subject")
    curves = [row.curve_csv for row in rows]
    subjects = [row.current_subject_label for row in rows if row.status == "include"]
    if len(set(curves)) != len(curves) or len(set(subjects)) != len(subjects):
        raise ModernCurveValidationError("Curve mapping repeats a curve or included subject")
    return tuple(rows)


def _read_preprocessing(
    directory: Path,
) -> tuple[dict[str, Any], dict[str, np.ndarray], Path, Path]:
    procrustes_path = directory / "procrustes.json"
    landmarks_path = directory / "landmarks.csv"
    try:
        document = load_strict_json_object(
            procrustes_path.read_bytes(), procrustes_path, label="Procrustes manifest"
        )
    except (ConfigurationError, OSError) as error:
        raise ModernCurveValidationError(str(error)) from error
    if document.get("coordinate_convention") != (
        "aligned = ((raw - centroid) * scale) @ rotation"
    ):
        raise ModernCurveValidationError("Current Procrustes coordinate convention differs")
    try:
        with landmarks_path.open(
            "r", encoding="utf-8", errors="strict", newline=""
        ) as handle:
            reader = csv.DictReader(handle)
            if tuple(reader.fieldnames or ()) != (
                "mesh_file",
                "landmark",
                "x",
                "y",
                "z",
            ):
                raise ModernCurveValidationError("Current landmark CSV header differs")
            rows = list(reader)
    except ModernCurveValidationError:
        raise
    except (OSError, UnicodeError, csv.Error) as error:
        raise ModernCurveValidationError("Could not read current landmarks") from error
    landmarks: dict[str, list[list[float]]] = {}
    for row in rows:
        try:
            values = [float(row[axis]) for axis in ("x", "y", "z")]
        except (TypeError, ValueError) as error:
            raise ModernCurveValidationError("Current landmarks contain a non-number") from error
        landmarks.setdefault(str(row["mesh_file"]), []).append(values)
    arrays = {label: np.asarray(values, dtype=np.float64) for label, values in landmarks.items()}
    if any(value.shape != (3, 3) or not np.isfinite(value).all() for value in arrays.values()):
        raise ModernCurveValidationError("Current landmarks must provide three finite anchors")
    return document, arrays, procrustes_path, landmarks_path


def _safe_bundle_path(root: Path, value: object, label: str) -> Path:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ModernCurveValidationError(f"{label} path is invalid")
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise ModernCurveValidationError(f"{label} path escapes its bundle")
    candidate = root.joinpath(*relative.parts).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise ModernCurveValidationError(f"{label} path escapes its bundle") from error
    if not candidate.is_file():
        raise ModernCurveValidationError(f"{label} is missing: {candidate}")
    return candidate


def _safe_preprocessing_path(root: Path, value: object, label: str) -> Path:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ModernCurveValidationError(f"{label} path is invalid")
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise ModernCurveValidationError(f"{label} path escapes preprocessing")
    candidate = root.joinpath(*relative.parts).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise ModernCurveValidationError(f"{label} path escapes preprocessing") from error
    if not candidate.is_file():
        raise ModernCurveValidationError(f"{label} is missing: {candidate}")
    return candidate


def _mesh_diagonal(mesh: TriangleMesh) -> float:
    points = np.asarray(mesh.vertices, dtype=np.float64)
    diagonal = float(np.linalg.norm(points.max(axis=0) - points.min(axis=0)))
    if not math.isfinite(diagonal) or diagonal <= 0:
        raise ModernCurveValidationError("Mesh bounding-box diagonal is invalid")
    return diagonal


def _procrustes_transform(record: dict[str, Any], points: np.ndarray) -> np.ndarray:
    try:
        transform = record["transform"]
        centroid = np.asarray(transform["centroid"], dtype=np.float64)
        rotation = np.asarray(transform["rotation"], dtype=np.float64)
        scale = float(transform["scale"])
    except (KeyError, TypeError, ValueError) as error:
        raise ModernCurveValidationError("Current Procrustes transform is invalid") from error
    if centroid.shape != (3,) or rotation.shape != (3, 3) or scale <= 0:
        raise ModernCurveValidationError("Current Procrustes transform shape differs")
    return ((points - centroid) * scale) @ rotation


def _rank(values: np.ndarray) -> np.ndarray:
    order = np.argsort(values, kind="mergesort")
    ranks = np.empty(len(values), dtype=np.float64)
    start = 0
    while start < len(values):
        end = start + 1
        while end < len(values) and values[order[end]] == values[order[start]]:
            end += 1
        ranks[order[start:end]] = 0.5 * (start + end - 1)
        start = end
    return ranks


def _correlation(first: np.ndarray, second: np.ndarray) -> float:
    x = np.asarray(first, dtype=np.float64)
    y = np.asarray(second, dtype=np.float64)
    x = x - x.mean()
    y = y - y.mean()
    denominator = float(np.linalg.norm(x) * np.linalg.norm(y))
    if denominator <= np.finfo(float).eps:
        raise ModernCurveValidationError("Curve distance ranks have zero variance")
    return float(np.dot(x, y) / denominator)


def _engine_evidence(
    bundle_root: Path,
    manifest: dict[str, Any],
    subject_curves: dict[str, np.ndarray],
) -> tuple[dict[str, Any], dict[str, np.ndarray], np.ndarray]:
    template_path = _safe_bundle_path(
        bundle_root, manifest["template"]["path"], "Modern template"
    )
    template = load_surface_mesh(template_path).geometry
    template_vertices = np.asarray(template.vertices, dtype=np.float64)
    template_triangles = np.asarray(template.triangles, dtype=np.int64)
    template_diagonal = _mesh_diagonal(template)
    records = {str(record["label"]): record for record in manifest["subjects"]}
    pulled: dict[str, np.ndarray] = {}
    projection_metrics: dict[str, dict[str, float]] = {}
    for subject, curve in subject_curves.items():
        if subject not in records:
            raise ModernCurveValidationError(
                f"Included subject is absent from Modern bundle: {subject}"
            )
        reconstruction_path = _safe_bundle_path(
            bundle_root,
            records[subject]["reconstruction_path"],
            f"Modern reconstruction for {subject}",
        )
        reconstruction = load_surface_mesh(reconstruction_path).geometry
        if reconstruction.triangles != template.triangles:
            raise ModernCurveValidationError(
                f"Reconstruction topology differs from template for {subject}"
            )
        distances, triangle_indices, weights = _closest_surface_coordinates(
            curve, reconstruction
        )
        pulled[subject] = np.sum(
            template_vertices[template_triangles[triangle_indices]] * weights[:, :, None],
            axis=1,
        )
        reconstruction_diagonal = _mesh_diagonal(reconstruction)
        normalized = distances / reconstruction_diagonal
        projection_metrics[subject] = {
            "projection_rms_normalized": float(np.sqrt(np.mean(normalized**2))),
            "projection_p95_normalized": float(
                np.quantile(normalized, 0.95, method="linear")
            ),
        }
    labels = tuple(sorted(pulled))
    curves = np.stack([pulled[label] for label in labels])
    loo_values: list[float] = []
    subject_metrics: list[dict[str, Any]] = []
    for index, label in enumerate(labels):
        others = np.delete(curves, index, axis=0)
        if len(others) == 0:
            raise ModernCurveValidationError("Curve validation needs at least two subjects")
        distances = np.linalg.norm(curves[index] - others.mean(axis=0), axis=1)
        loo = float(np.sqrt(np.mean(distances**2)) / template_diagonal)
        loo_values.append(loo)
        subject_metrics.append(
            {
                "subject_label": label,
                **projection_metrics[label],
                "loo_curve_rms_normalized": loo,
            }
        )
    pairwise: list[float] = []
    direction_cosines: list[float] = []
    directions = curves[:, -1] - curves[:, 0]
    norms = np.linalg.norm(directions, axis=1)
    if np.any(norms <= np.finfo(float).eps):
        raise ModernCurveValidationError("A pulled-back curve has coincident endpoints")
    directions /= norms[:, None]
    for first in range(len(labels)):
        for second in range(first + 1, len(labels)):
            pairwise.append(
                float(
                    np.sqrt(np.mean(np.sum((curves[first] - curves[second]) ** 2, axis=1)))
                    / template_diagonal
                )
            )
            direction_cosines.append(float(np.dot(directions[first], directions[second])))
    loo_array = np.asarray(loo_values, dtype=np.float64)
    projection_p95 = np.asarray(
        [projection_metrics[label]["projection_p95_normalized"] for label in labels]
    )
    cosine_array = np.asarray(direction_cosines, dtype=np.float64)
    evidence = {
        "engine_implementation_version": str(manifest["engine"]["implementation_version"]),
        "template_sha256": sha256_file(template_path),
        "template_bbox_diagonal": template_diagonal,
        "subjects": subject_metrics,
        "summary": {
            "loo_curve_rms_normalized_mean": float(loo_array.mean()),
            "loo_curve_rms_normalized_median": float(np.median(loo_array)),
            "loo_curve_rms_normalized_p95": float(
                np.quantile(loo_array, 0.95, method="linear")
            ),
            "subject_projection_p95_normalized_median": float(
                np.median(projection_p95)
            ),
            "endpoint_direction_pairwise_cosine_median": float(np.median(cosine_array)),
            "endpoint_direction_pairwise_negative_fraction": float(
                np.mean(cosine_array < 0)
            ),
        },
    }
    return evidence, pulled, np.asarray(pairwise, dtype=np.float64)


def _bundle_record(root: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "bundle_directory": str(root),
        "bundle_version": str(manifest["bundle_version"]),
        "engine_implementation_version": str(manifest["engine"]["implementation_version"]),
        "manifest_sha256": sha256_file(root / MANIFEST_NAME),
        "subject_labels": [str(record["label"]) for record in manifest["subjects"]],
    }


def _path_record(path: Path) -> dict[str, str]:
    return {"path": str(path), "sha256": sha256_file(path)}


def _compute(
    mapping_path: Path,
    curve_directory: Path,
    preprocessing_directory: Path,
    reference_bundle: Path,
    comparison_bundle: Path,
    *,
    sample_count: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if sample_count < 4:
        raise ModernCurveValidationError("Curve validation requires at least four samples")
    mapping = _read_mapping(mapping_path, curve_directory)
    procrustes, current_landmarks, procrustes_path, landmarks_path = _read_preprocessing(
        preprocessing_directory
    )
    reference_manifest = verify_modern_atlas_bundle(reference_bundle)
    comparison_manifest = verify_modern_atlas_bundle(comparison_bundle)
    reference_labels = [str(record["label"]) for record in reference_manifest["subjects"]]
    comparison_labels = [str(record["label"]) for record in comparison_manifest["subjects"]]
    if reference_bundle == comparison_bundle:
        raise ModernCurveValidationError("Curve validation requires two distinct bundles")
    if reference_labels != comparison_labels:
        raise ModernCurveValidationError("Modern bundle subject identities or order differ")
    preprocessing_records = {
        str(record["filename"]): record for record in procrustes.get("meshes", [])
    }
    inventory_paths = sorted(curve_directory.glob("*_aligned.csv"))
    if not inventory_paths:
        raise ModernCurveValidationError("Curve directory contains no *_aligned.csv files")
    mapped_paths = {row.curve_csv for row in mapping}
    if not mapped_paths.issubset(set(inventory_paths)):
        raise ModernCurveValidationError("Mapping is not a subset of the curve inventory")
    transfer_records: list[dict[str, Any]] = []
    source_rows: list[dict[str, Any]] = []
    subject_curves: dict[str, np.ndarray] = {}
    for row in mapping:
        source_row: dict[str, Any] = {
            "curve": _path_record(row.curve_csv),
            "current_subject_label": row.current_subject_label,
            "status": row.status,
            "note": row.note,
        }
        for key, path in (
            ("legacy_aligned_mesh", row.legacy_aligned_mesh),
            ("legacy_raw_mesh", row.legacy_raw_mesh),
            ("legacy_anchor_file", row.legacy_anchor_file),
        ):
            source_row[key] = None if path is None else _path_record(path)
        source_rows.append(source_row)
        if row.status == "exclude":
            continue
        assert row.legacy_aligned_mesh is not None
        assert row.legacy_raw_mesh is not None
        assert row.legacy_anchor_file is not None
        subject = row.current_subject_label
        if subject not in current_landmarks or subject not in preprocessing_records:
            raise ModernCurveValidationError(
                f"Included subject is absent from current preprocessing: {subject}"
            )
        if subject not in reference_labels:
            raise ModernCurveValidationError(
                f"Included subject is absent from paired Modern bundles: {subject}"
            )
        preprocess_record = preprocessing_records[subject]
        current_raw_path = _safe_preprocessing_path(
            preprocessing_directory,
            preprocess_record["raw_copy_path"],
            f"Current raw mesh for {subject}",
        )
        if sha256_file(current_raw_path) != str(
            preprocess_record["raw_copy_sha256"]
        ):
            raise ModernCurveValidationError(
                f"Current raw mesh identity differs for {subject}"
            )
        source_row["current_raw_mesh"] = _path_record(current_raw_path)
        legacy_aligned = load_surface_mesh(row.legacy_aligned_mesh)
        legacy_raw = load_surface_mesh(row.legacy_raw_mesh)
        current_raw = load_surface_mesh(current_raw_path)
        if (
            legacy_aligned.geometry.triangles != legacy_raw.geometry.triangles
            or len(legacy_aligned.geometry.vertices) != len(legacy_raw.geometry.vertices)
        ):
            raise ModernCurveValidationError(
                f"Legacy raw/aligned topology differs for {subject}"
            )
        aligned_values = np.asarray(legacy_aligned.geometry.vertices, dtype=np.float64)
        raw_values = np.asarray(legacy_raw.geometry.vertices, dtype=np.float64)
        legacy_to_raw = _fit_similarity(aligned_values, raw_values)
        legacy_fit = np.linalg.norm(legacy_to_raw.apply(aligned_values) - raw_values, axis=1)
        anchor_transfer = _fit_similarity(
            _read_legacy_anchors(row.legacy_anchor_file), current_landmarks[subject]
        )
        transferred_surface_values = anchor_transfer.apply(
            legacy_to_raw.apply(aligned_values)
        )
        current_diagonal = current_raw.metadata.bounding_box_diagonal
        surface_distances, surface_sample_count = _surface_transfer_distances(
            transferred_surface_values, current_raw.geometry
        )
        curve = _read_curve(row.curve_csv)
        curve_current_raw = anchor_transfer.apply(legacy_to_raw.apply(curve))
        curve_distances, _, _ = _closest_surface_coordinates(
            curve_current_raw, current_raw.geometry
        )
        aligned_curve = _procrustes_transform(preprocess_record, curve_current_raw)
        subject_curves[subject] = _resample_curve(aligned_curve, sample_count)
        anchor_residual = np.linalg.norm(
            anchor_transfer.apply(_read_legacy_anchors(row.legacy_anchor_file))
            - current_landmarks[subject],
            axis=1,
        )
        transfer_records.append(
            {
                "subject_label": subject,
                "source_curve_points": int(len(curve)),
                "surface_transfer_sample_count": surface_sample_count,
                "legacy_alignment_fit_max_normalized": float(
                    legacy_fit.max() / legacy_raw.metadata.bounding_box_diagonal
                ),
                "anchor_transfer_rms_normalized": float(
                    np.sqrt(np.mean(anchor_residual**2)) / current_diagonal
                ),
                "surface_transfer_p95_normalized": float(
                    np.quantile(
                        surface_distances / current_diagonal, 0.95, method="linear"
                    )
                ),
                "curve_transfer_p95_normalized": float(
                    np.quantile(
                        curve_distances / current_diagonal, 0.95, method="linear"
                    )
                ),
            }
        )
    if len(subject_curves) < 3:
        raise ModernCurveValidationError(
            "Curve validation requires at least three included subjects"
        )
    reference_evidence, _, reference_distances = _engine_evidence(
        reference_bundle, reference_manifest, subject_curves
    )
    comparison_evidence, _, comparison_distances = _engine_evidence(
        comparison_bundle, comparison_manifest, subject_curves
    )
    reference_subjects = {
        row["subject_label"]: row for row in reference_evidence["subjects"]
    }
    comparison_subjects = {
        row["subject_label"]: row for row in comparison_evidence["subjects"]
    }
    paired = np.asarray(
        [
            comparison_subjects[label]["loo_curve_rms_normalized"]
            - reference_subjects[label]["loo_curve_rms_normalized"]
            for label in sorted(reference_subjects)
        ],
        dtype=np.float64,
    )
    evidence = {
        "sample_count": sample_count,
        "curve_inventory_count": len(inventory_paths),
        "mapped_curve_count": len(mapping),
        "included_subject_count": len(subject_curves),
        "excluded_mapping_count": sum(row.status == "exclude" for row in mapping),
        "unmapped_curve_count": len(inventory_paths) - len(mapping),
        "transfer": transfer_records,
        "reference": reference_evidence,
        "comparison": comparison_evidence,
        "paired": {
            "comparison_minus_reference_loo_rms_mean": float(paired.mean()),
            "comparison_minus_reference_loo_rms_median": float(np.median(paired)),
            "comparison_lower_subject_count": int(np.sum(paired < 0)),
            "reference_lower_subject_count": int(np.sum(paired > 0)),
            "equal_subject_count": int(np.sum(paired == 0)),
            "subject_curve_distance_spearman": _correlation(
                _rank(reference_distances), _rank(comparison_distances)
            ),
        },
    }
    source = {
        "mapping": _path_record(mapping_path),
        "curve_directory": str(curve_directory),
        "curve_inventory": [_path_record(path) for path in inventory_paths],
        "preprocessing_directory": str(preprocessing_directory),
        "procrustes": _path_record(procrustes_path),
        "current_landmarks": _path_record(landmarks_path),
        "mapping_rows": source_rows,
        "reference_bundle": _bundle_record(reference_bundle, reference_manifest),
        "comparison_bundle": _bundle_record(comparison_bundle, comparison_manifest),
    }
    return source, evidence


def write_modern_curve_validation(
    mapping: Path | str,
    curve_directory: Path | str,
    preprocessing_directory: Path | str,
    reference_bundle: Path | str,
    comparison_bundle: Path | str,
    destination: Path | str,
    *,
    sample_count: int = 64,
    created_at: str | None = None,
) -> Path:
    """Atomically publish a source-bound paired manual-curve validation."""

    mapping_path = Path(mapping).expanduser().resolve()
    curves = Path(curve_directory).expanduser().resolve()
    preprocessing = Path(preprocessing_directory).expanduser().resolve()
    reference = Path(reference_bundle).expanduser().resolve()
    comparison = Path(comparison_bundle).expanduser().resolve()
    source, evidence = _compute(
        mapping_path,
        curves,
        preprocessing,
        reference,
        comparison,
        sample_count=sample_count,
    )
    timestamp = created_at or datetime.now(UTC).isoformat(timespec="seconds")
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError as error:
        raise ModernCurveValidationError("created_at must be ISO-8601") from error
    if parsed.tzinfo is None:
        raise ModernCurveValidationError("created_at must include a timezone offset")
    target = Path(destination).expanduser().resolve()
    if target.exists():
        raise FileExistsError(f"Modern curve validation destination already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.parent / f".{target.name}.tmp-{uuid.uuid4().hex}"
    temporary.mkdir()
    try:
        manifest = {
            "artifact_version": MODERN_CURVE_VALIDATION_VERSION,
            "created_at": timestamp,
            "source": source,
            "evidence": evidence,
            "scientific_boundary": SCIENTIFIC_BOUNDARY,
            "verification_contract": VERIFICATION_CONTRACT,
        }
        manifest_path = temporary / MODERN_CURVE_VALIDATION_MANIFEST
        write_text_safely(manifest_path, _canonical_json(manifest), overwrite=False)
        write_text_safely(
            temporary / MODERN_CURVE_VALIDATION_SIDECAR,
            sha256_file(manifest_path) + "\n",
            overwrite=False,
        )
        verify_modern_curve_validation(temporary)
        publish_directory_exclusive(temporary, target)
        return target
    except Exception:
        if temporary.exists() and temporary.parent == target.parent:
            shutil.rmtree(temporary)
        raise


def verify_modern_curve_validation(
    artifact_directory: Path | str,
) -> ModernCurveValidationArtifact:
    """Reverify every source and exactly recompute manual-curve evidence."""

    root = Path(artifact_directory).expanduser().resolve()
    if not root.is_dir() or root.is_symlink():
        raise ModernCurveValidationError(
            f"Modern curve validation artifact is missing or symbolic: {root}"
        )
    manifest_path = root / MODERN_CURVE_VALIDATION_MANIFEST
    sidecar_path = root / MODERN_CURVE_VALIDATION_SIDECAR
    actual = {path.name for path in root.iterdir() if path.is_file()}
    expected = {MODERN_CURVE_VALIDATION_MANIFEST, MODERN_CURVE_VALIDATION_SIDECAR}
    if actual != expected or any(path.is_dir() for path in root.iterdir()):
        raise ModernCurveValidationError(
            "Modern curve validation contains an unexpected file or directory"
        )
    try:
        expected_hash = sidecar_path.read_text(encoding="ascii", errors="strict").strip()
    except (OSError, UnicodeError) as error:
        raise ModernCurveValidationError("Could not read curve validation sidecar") from error
    if expected_hash != sha256_file(manifest_path):
        raise ModernCurveValidationError("Modern curve validation manifest SHA-256 differs")
    try:
        manifest = load_strict_json_object(
            manifest_path.read_bytes(), manifest_path, label="Modern curve validation"
        )
    except (ConfigurationError, OSError) as error:
        raise ModernCurveValidationError(str(error)) from error
    if set(manifest) != {
        "artifact_version",
        "created_at",
        "source",
        "evidence",
        "scientific_boundary",
        "verification_contract",
    }:
        raise ModernCurveValidationError("Modern curve validation manifest fields differ")
    if manifest["artifact_version"] != MODERN_CURVE_VALIDATION_VERSION:
        raise ModernCurveValidationError("Unsupported Modern curve validation version")
    if (
        manifest["scientific_boundary"] != SCIENTIFIC_BOUNDARY
        or manifest["verification_contract"] != VERIFICATION_CONTRACT
    ):
        raise ModernCurveValidationError(
            "Curve validation claim boundary or verification contract differs"
        )
    try:
        parsed = datetime.fromisoformat(str(manifest["created_at"]).replace("Z", "+00:00"))
    except ValueError as error:
        raise ModernCurveValidationError("Curve validation created_at is not ISO-8601") from error
    if parsed.tzinfo is None:
        raise ModernCurveValidationError("Curve validation created_at has no timezone offset")
    source = manifest["source"]
    if not isinstance(source, dict):
        raise ModernCurveValidationError("Curve validation source record is invalid")
    try:
        mapping_path = Path(str(source["mapping"]["path"])).resolve()
        curves = Path(str(source["curve_directory"])).resolve()
        preprocessing = Path(str(source["preprocessing_directory"])).resolve()
        reference = Path(str(source["reference_bundle"]["bundle_directory"])).resolve()
        comparison = Path(str(source["comparison_bundle"]["bundle_directory"])).resolve()
        sample_count = int(manifest["evidence"]["sample_count"])
    except (KeyError, TypeError, ValueError) as error:
        raise ModernCurveValidationError("Curve validation source paths differ") from error
    computed_source, computed_evidence = _compute(
        mapping_path,
        curves,
        preprocessing,
        reference,
        comparison,
        sample_count=sample_count,
    )
    if source != computed_source:
        raise ModernCurveValidationError("Curve validation source identities or hashes changed")
    if manifest["evidence"] != computed_evidence:
        raise ModernCurveValidationError(
            "Recorded Modern curve validation differs from exact recomputation"
        )
    return ModernCurveValidationArtifact(root, dict(manifest))
