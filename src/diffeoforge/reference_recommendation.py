"""Data-assisted, explicitly non-validating Deformetrica parameter guidance."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import median
from typing import Literal

import numpy as np

from diffeoforge.analysis.procrustes import SimilarityTransform
from diffeoforge.config import ConfigurationError
from diffeoforge.mesh import sha256_file
from diffeoforge.surface_io import load_surface_mesh

RECOMMENDATION_VERSION = "0.1"
SurfaceDetailIntent = Literal["fine", "balanced", "coarse"]
DeformationScaleIntent = Literal["local", "balanced", "global"]
AlignmentBasis = Literal["declared_gpa", "diffeoforge_gpa"]

_ATTACHMENT_NOMINAL_RATIOS: dict[SurfaceDetailIntent, float] = {
    "fine": 0.025,
    "balanced": 0.05,
    "coarse": 0.10,
}
_DEFORMATION_NOMINAL_RATIOS: dict[DeformationScaleIntent, float] = {
    "local": 0.05,
    "balanced": 0.10,
    "global": 0.20,
}


@dataclass(frozen=True)
class MeshGeometryObservation:
    """One aligned mesh's geometry measurements."""

    filename: str
    sha256: str
    points: int
    triangles: int
    bounding_box_diagonal: float
    rms_radius: float
    median_sampled_edge_length: float


@dataclass(frozen=True)
class ReferenceParameterRecommendation:
    """Auditable geometry observations and provisional Deformetrica values."""

    version: str
    fingerprint: str
    alignment_basis: AlignmentBasis
    alignment_fingerprint: str | None
    surface_detail_intent: SurfaceDetailIntent
    deformation_scale_intent: DeformationScaleIntent
    template_filename: str
    template_sha256: str
    mesh_count: int
    subject_count: int
    template_diagonal: float
    cohort_median_diagonal: float
    cohort_diagonal_cv: float
    normalized_centroid_dispersion: float
    median_edge_to_diagonal_ratio: float
    sampling_floor_ratio: float
    attachment_kernel_width_ratio: float
    deformation_kernel_width_ratio: float
    control_point_spacing_ratio: float
    provisional_noise_std_ratio: float
    max_iterations: int
    initial_step_size: float
    convergence_tolerance: float
    observations: tuple[MeshGeometryObservation, ...]
    automatic_inferences: tuple[str, ...]
    user_decisions: tuple[str, ...]
    pilot_validation_required: tuple[str, ...]
    warnings: tuple[str, ...]

    @property
    def parameter_ratios(self) -> dict[str, float]:
        """Return the four ratios consumed by project initialization."""

        return {
            "attachment_kernel_width": self.attachment_kernel_width_ratio,
            "deformation_kernel_width": self.deformation_kernel_width_ratio,
            "initial_control_point_spacing": self.control_point_spacing_ratio,
            "noise_std": self.provisional_noise_std_ratio,
        }

    @property
    def effective_values(self) -> dict[str, float]:
        """Return template-scale effective values in the declared coordinate unit."""

        return {
            name: ratio * self.template_diagonal
            for name, ratio in self.parameter_ratios.items()
        }

    @property
    def provenance(self) -> dict[str, object]:
        """Return the compact recommendation record stored with the configuration."""

        return {
            "version": self.version,
            "fingerprint": self.fingerprint,
            "alignment_basis": self.alignment_basis,
            "alignment_fingerprint": self.alignment_fingerprint,
            "surface_detail_intent": self.surface_detail_intent,
            "deformation_scale_intent": self.deformation_scale_intent,
            "template_filename": self.template_filename,
            "template_sha256": self.template_sha256,
            "mesh_count": self.mesh_count,
            "subject_count": self.subject_count,
            "measurements": {
                "template_diagonal": self.template_diagonal,
                "cohort_median_diagonal": self.cohort_median_diagonal,
                "cohort_diagonal_cv": self.cohort_diagonal_cv,
                "normalized_centroid_dispersion": (
                    self.normalized_centroid_dispersion
                ),
                "median_edge_to_diagonal_ratio": (
                    self.median_edge_to_diagonal_ratio
                ),
                "sampling_floor_ratio": self.sampling_floor_ratio,
            },
            "parameter_ratios": self.parameter_ratios,
            "automatic_inferences": list(self.automatic_inferences),
            "user_decisions": list(self.user_decisions),
            "pilot_validation_required": list(self.pilot_validation_required),
            "warnings": list(self.warnings),
        }

    def as_manifest(self) -> dict[str, object]:
        """Return a JSON-serializable evidence record."""

        value = asdict(self)
        value["parameter_ratios"] = self.parameter_ratios
        value["effective_values"] = self.effective_values
        value["provenance"] = self.provenance
        return value


def _coefficient_of_variation(values: Sequence[float]) -> float:
    mean = sum(values) / len(values)
    if mean <= 0:
        raise ValueError("Coefficient of variation requires a positive mean")
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    return math.sqrt(variance) / mean


def _bounds_diagonal(points: np.ndarray) -> float:
    extents = np.max(points, axis=0) - np.min(points, axis=0)
    diagonal = float(np.linalg.norm(extents))
    if not math.isfinite(diagonal) or diagonal <= 0:
        raise ConfigurationError("Aligned mesh has a degenerate bounding box")
    return diagonal


def _sampled_edge_lengths(
    points: np.ndarray,
    triangles: Sequence[tuple[int, int, int]],
    *,
    triangle_budget: int,
) -> tuple[float, ...]:
    if triangle_budget < 1:
        raise ValueError("triangle_budget must be positive")
    stride = max(1, math.ceil(len(triangles) / triangle_budget))
    lengths: list[float] = []
    for first, second, third in triangles[::stride]:
        for left, right in ((first, second), (second, third), (third, first)):
            length = float(np.linalg.norm(points[left] - points[right]))
            if math.isfinite(length) and length > 0:
                lengths.append(length)
    if not lengths:
        raise ConfigurationError("Mesh has no finite positive sampled triangle edges")
    return tuple(lengths)


def _canonical_hash(value: object) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def recommend_reference_parameters(
    mesh_paths: Sequence[Path | str],
    *,
    alignment_basis: AlignmentBasis,
    surface_detail_intent: SurfaceDetailIntent,
    deformation_scale_intent: DeformationScaleIntent,
    transforms: Sequence[SimilarityTransform] | None = None,
    alignment_fingerprint: str | None = None,
    triangle_budget_per_mesh: int = 20_000,
) -> ReferenceParameterRecommendation:
    """Analyze one GPA-aligned cohort and produce transparent starting guidance.

    The first mesh is the selected template. Geometry constrains scale and a
    mesh-sampling lower bound. Anatomical detail, deformation locality, and
    registration-fit strength remain explicit scientific decisions.
    """

    if alignment_basis not in {"declared_gpa", "diffeoforge_gpa"}:
        raise ValueError(f"Unsupported alignment basis: {alignment_basis!r}")
    if surface_detail_intent not in _ATTACHMENT_NOMINAL_RATIOS:
        raise ValueError(f"Unsupported surface-detail intent: {surface_detail_intent!r}")
    if deformation_scale_intent not in _DEFORMATION_NOMINAL_RATIOS:
        raise ValueError(
            f"Unsupported deformation-scale intent: {deformation_scale_intent!r}"
        )
    paths = tuple(Path(path).expanduser().resolve() for path in mesh_paths)
    if len(paths) < 3:
        raise ConfigurationError(
            "Parameter guidance requires one template and at least two subject meshes"
        )
    if len(set(paths)) != len(paths):
        raise ConfigurationError("Parameter guidance mesh paths must be unique")
    if transforms is not None and len(transforms) != len(paths):
        raise ConfigurationError(
            "The GPA transform count does not match the selected mesh cohort"
        )
    if alignment_basis == "diffeoforge_gpa":
        if transforms is None or not alignment_fingerprint:
            raise ConfigurationError(
                "DiffeoForge GPA guidance requires transforms and an alignment fingerprint"
            )
    elif transforms is not None or alignment_fingerprint is not None:
        raise ConfigurationError(
            "User-declared GPA guidance must analyze the current coordinates directly"
        )

    observations: list[MeshGeometryObservation] = []
    centroids: list[np.ndarray] = []
    diagonals: list[float] = []
    edge_medians: list[float] = []
    source_records: list[dict[str, object]] = []
    for index, path in enumerate(paths):
        loaded = load_surface_mesh(path)
        points = np.asarray(loaded.geometry.vertices, dtype=np.float64)
        if transforms is not None:
            points = transforms[index].apply(points)
        diagonal = _bounds_diagonal(points)
        centroid = np.mean(points, axis=0)
        centered = points - centroid
        rms_radius = float(np.sqrt(np.mean(np.sum(centered * centered, axis=1))))
        edge_lengths = _sampled_edge_lengths(
            points,
            loaded.geometry.triangles,
            triangle_budget=triangle_budget_per_mesh,
        )
        edge_median = float(median(edge_lengths))
        observation = MeshGeometryObservation(
            filename=path.name,
            sha256=loaded.metadata.sha256,
            points=loaded.metadata.points,
            triangles=loaded.metadata.triangles,
            bounding_box_diagonal=diagonal,
            rms_radius=rms_radius,
            median_sampled_edge_length=edge_median,
        )
        observations.append(observation)
        centroids.append(centroid)
        diagonals.append(diagonal)
        edge_medians.append(edge_median)
        source_records.append(
            {
                "path_name": path.name,
                "sha256": loaded.metadata.sha256,
                "points": loaded.metadata.points,
                "triangles": loaded.metadata.triangles,
                "aligned_diagonal": diagonal,
                "median_sampled_edge_length": edge_median,
            }
        )
        if sha256_file(path) != loaded.metadata.sha256:
            raise ConfigurationError(
                f"Mesh changed while parameter guidance was computed: {path}"
            )

    cohort_diagonal = float(median(diagonals))
    template_diagonal = diagonals[0]
    edge_to_diagonal = float(median(edge_medians)) / cohort_diagonal
    sampling_floor = min(0.5, max(0.005, 4.0 * edge_to_diagonal))
    attachment_nominal = _ATTACHMENT_NOMINAL_RATIOS[surface_detail_intent]
    attachment_ratio = min(0.5, max(attachment_nominal, sampling_floor))
    deformation_ratio = _DEFORMATION_NOMINAL_RATIOS[deformation_scale_intent]
    control_spacing_ratio = deformation_ratio

    centroid_stack = np.stack(centroids)
    cohort_centroid = np.mean(centroid_stack, axis=0)
    centroid_dispersion = float(
        np.sqrt(np.mean(np.sum((centroid_stack - cohort_centroid) ** 2, axis=1)))
    )
    normalized_centroid_dispersion = centroid_dispersion / cohort_diagonal
    diagonal_cv = _coefficient_of_variation(diagonals)

    warnings = [
        "These values are transparent starting guidance, not a validated scientific optimum.",
        "Noise standard deviation cannot be inferred from mesh geometry alone; the displayed "
        "value is a provisional pilot value and must be calibrated from registration results.",
    ]
    if alignment_basis == "declared_gpa":
        warnings.append(
            "GPA status was declared by the user. Coordinate diagnostics can flag large "
            "translation or scale differences but cannot prove homologous alignment."
        )
    if normalized_centroid_dispersion > 0.05:
        warnings.append(
            "Mesh centroids remain dispersed by more than 5% of the cohort median diagonal; "
            "review alignment before atlas estimation."
        )
    if diagonal_cv > 0.10:
        warnings.append(
            "Aligned bounding-box diagonals have a coefficient of variation above 10%; "
            "confirm whether centroid-size scaling was intended."
        )
    if sampling_floor > attachment_nominal:
        warnings.append(
            "The requested attachment detail was finer than the observed mesh sampling; "
            "the proposed attachment width was raised to the sampling-aware lower bound."
        )

    evidence = {
        "version": RECOMMENDATION_VERSION,
        "alignment_basis": alignment_basis,
        "alignment_fingerprint": alignment_fingerprint,
        "surface_detail_intent": surface_detail_intent,
        "deformation_scale_intent": deformation_scale_intent,
        "sources": source_records,
        "cohort_median_diagonal": cohort_diagonal,
        "cohort_diagonal_cv": diagonal_cv,
        "normalized_centroid_dispersion": normalized_centroid_dispersion,
        "median_edge_to_diagonal_ratio": edge_to_diagonal,
        "sampling_floor_ratio": sampling_floor,
        "attachment_kernel_width_ratio": attachment_ratio,
        "deformation_kernel_width_ratio": deformation_ratio,
        "control_point_spacing_ratio": control_spacing_ratio,
        "provisional_noise_std_ratio": 0.25 * attachment_ratio,
    }
    fingerprint = _canonical_hash(evidence)
    return ReferenceParameterRecommendation(
        version=RECOMMENDATION_VERSION,
        fingerprint=fingerprint,
        alignment_basis=alignment_basis,
        alignment_fingerprint=alignment_fingerprint,
        surface_detail_intent=surface_detail_intent,
        deformation_scale_intent=deformation_scale_intent,
        template_filename=paths[0].name,
        template_sha256=observations[0].sha256,
        mesh_count=len(paths),
        subject_count=len(paths) - 1,
        template_diagonal=template_diagonal,
        cohort_median_diagonal=cohort_diagonal,
        cohort_diagonal_cv=diagonal_cv,
        normalized_centroid_dispersion=normalized_centroid_dispersion,
        median_edge_to_diagonal_ratio=edge_to_diagonal,
        sampling_floor_ratio=sampling_floor,
        attachment_kernel_width_ratio=attachment_ratio,
        deformation_kernel_width_ratio=deformation_ratio,
        control_point_spacing_ratio=control_spacing_ratio,
        provisional_noise_std_ratio=0.25 * attachment_ratio,
        max_iterations=150,
        initial_step_size=0.01,
        convergence_tolerance=0.0001,
        observations=tuple(observations),
        automatic_inferences=(
            "Template and cohort scale from the analyzed aligned coordinates",
            "A lower bound for attachment resolution from sampled triangle-edge lengths",
            "Centroid and size-dispersion diagnostics that can warn about alignment",
        ),
        user_decisions=(
            "Surface detail scale represented by the attachment kernel",
            "Local, balanced, or global deformation scale",
            "Whether reflected configurations are biologically admissible during GPA",
        ),
        pilot_validation_required=(
            "Noise standard deviation and the data-attachment/regularity trade-off",
            "Registration residuals and visual correspondence",
            "Optimizer convergence, iteration cap, and step behavior",
            "Sensitivity to neighboring attachment and deformation kernel widths",
        ),
        warnings=tuple(warnings),
    )
