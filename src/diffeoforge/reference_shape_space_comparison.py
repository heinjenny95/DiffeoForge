"""Immutable method comparison for completed Deformetrica atlas momenta."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import shutil
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from numbers import Integral
from pathlib import Path
from typing import Any

import numpy as np

from diffeoforge.analysis.pca import momenta_pca
from diffeoforge.analysis.shape_space import (
    diffusion_map_from_squared_distances,
    isomap_from_squared_distances,
    lddmm_metric_momenta_pca,
    lddmm_momenta_squared_distances,
    median_heuristic_gamma,
    principal_coordinates_analysis,
    rbf_kernel_pca_from_squared_distances,
)
from diffeoforge.atomic_io import write_text_safely
from diffeoforge.config import ConfigurationError
from diffeoforge.mesh import sha256_file
from diffeoforge.reference_pca import ReferenceMomentaInput, load_reference_momenta
from diffeoforge.runs import publish_directory_exclusive
from diffeoforge.strict_json import load_strict_json_object

LEGACY_COMPARISON_VERSION = "0.1"
FULL_COMPARISON_VERSION = "0.2"
COMPARISON_VERSION = "0.3"
SUPPORTED_COMPARISON_VERSIONS = (
    LEGACY_COMPARISON_VERSION,
    FULL_COMPARISON_VERSION,
    COMPARISON_VERSION,
)
COMPARISON_MANIFEST = "shape-space-comparison.json"
COMPARISON_SIDECAR = "shape-space-comparison.sha256"
METRICS_CSV = "method-metrics.csv"
SCORES_CSV = "scores.csv"
README_NAME = "README.md"
DEFAULT_COMPARISON_DIRECTORY = Path("analysis") / "reference-shape-space-comparison-v0.3"
CACHE_DIRECTORY = Path("analysis") / "reference-shape-space-method-cache-v0.3"
DEFAULT_METHOD_ID = "lddmm_deformation_kernel_pca"
TANGENT_PCOA_METHOD_ID = "lddmm_tangent_pcoa"
METHOD_IDS = (
    DEFAULT_METHOD_ID,
    TANGENT_PCOA_METHOD_ID,
    "cartesian_momenta_pca",
    "roberts_2026_cartesian_momenta_rbf_kpca",
    "rbf_kpca_gamma_0.5",
    "rbf_kpca_gamma_1",
    "rbf_kpca_gamma_2",
    "isomap",
    "diffusion_map",
)
QUICK_METHOD_IDS = (DEFAULT_METHOD_ID, TANGENT_PCOA_METHOD_ID)
COMPATIBILITY_METHOD_IDS = QUICK_METHOD_IDS + (
    "cartesian_momenta_pca",
    "roberts_2026_cartesian_momenta_rbf_kpca",
)
EXPLORATORY_METHOD_IDS = QUICK_METHOD_IDS + (
    "rbf_kpca_gamma_0.5",
    "rbf_kpca_gamma_1",
    "rbf_kpca_gamma_2",
    "isomap",
    "diffusion_map",
)
ALL_METHOD_IDS = METHOD_IDS
METHOD_LABELS = {
    DEFAULT_METHOD_ID: "LDDMM deformation-kernel metric tangent PCA — default",
    TANGENT_PCOA_METHOD_ID: "PCoA of LDDMM tangent distances — essential cross-check",
    "cartesian_momenta_pca": "Cartesian momenta PCA — legacy comparison",
    "roberts_2026_cartesian_momenta_rbf_kpca": (
        "Roberts et al. 2026 Cartesian-momenta RBF KernelPCA — compatibility"
    ),
    "rbf_kpca_gamma_0.5": "Generic RBF KernelPCA — gamma × 0.5",
    "rbf_kpca_gamma_1": "Generic RBF KernelPCA — gamma × 1",
    "rbf_kpca_gamma_2": "Generic RBF KernelPCA — gamma × 2",
    "isomap": "Isomap of LDDMM tangent distances — exploratory",
    "diffusion_map": "Diffusion map of LDDMM tangent distances — exploratory",
}
LEGACY_METHOD_LABELS = {
    DEFAULT_METHOD_ID: "LDDMM deformation-kernel metric tangent PCA",
    TANGENT_PCOA_METHOD_ID: "PCoA of LDDMM tangent distances",
    "cartesian_momenta_pca": "Cartesian momenta PCA",
    "roberts_2026_cartesian_momenta_rbf_kpca": (
        "Roberts et al. 2026 Cartesian-momenta RBF KernelPCA preset"
    ),
    "rbf_kpca_gamma_0.5": "Generic RBF KernelPCA (gamma x 0.5)",
    "rbf_kpca_gamma_1": "Generic RBF KernelPCA (gamma x 1)",
    "rbf_kpca_gamma_2": "Generic RBF KernelPCA (gamma x 2)",
    "isomap": "Isomap of LDDMM tangent distances",
    "diffusion_map": "Diffusion map of LDDMM tangent distances",
}
LEGACY_METHOD_ORDER = (
    DEFAULT_METHOD_ID,
    "cartesian_momenta_pca",
    TANGENT_PCOA_METHOD_ID,
    "rbf_kpca_gamma_0.5",
    "rbf_kpca_gamma_1",
    "rbf_kpca_gamma_2",
    "isomap",
    "diffusion_map",
)
FULL_METHOD_ORDER = (
    DEFAULT_METHOD_ID,
    "cartesian_momenta_pca",
    TANGENT_PCOA_METHOD_ID,
    "rbf_kpca_gamma_0.5",
    "rbf_kpca_gamma_1",
    "rbf_kpca_gamma_2",
    "roberts_2026_cartesian_momenta_rbf_kpca",
    "isomap",
    "diffusion_map",
)
FULL_SCORE_ORDER = (
    DEFAULT_METHOD_ID,
    "cartesian_momenta_pca",
    TANGENT_PCOA_METHOD_ID,
    "rbf_kpca_gamma_0.5",
    "rbf_kpca_gamma_1",
    "rbf_kpca_gamma_2",
    "isomap",
    "diffusion_map",
    "roberts_2026_cartesian_momenta_rbf_kpca",
)
METHOD_ROLES = {
    DEFAULT_METHOD_ID: "default_candidate_model_aligned_linear_ordination",
    TANGENT_PCOA_METHOD_ID: "distance_based_cross_check",
    "cartesian_momenta_pca": "legacy_compatibility",
    "roberts_2026_cartesian_momenta_rbf_kpca": "published_workflow_compatibility",
    "rbf_kpca_gamma_0.5": "exploratory_nonlinear_sensitivity",
    "rbf_kpca_gamma_1": "exploratory_nonlinear_sensitivity",
    "rbf_kpca_gamma_2": "exploratory_nonlinear_sensitivity",
    "isomap": "exploratory_nonlinear_ordination",
    "diffusion_map": "exploratory_nonlinear_ordination",
}
DIRECT_SHOOTING_METHOD_IDS = {DEFAULT_METHOD_ID, "cartesian_momenta_pca"}
ROBERTS_2026_RBF_GAMMA = 0.00000025
SCIENTIFIC_BOUNDARY = (
    "This comparison evaluates numerical representations of one completed atlas. It does "
    "not establish biological group separation, registration validity, or an exact geodesic "
    "PGA. Generic RBF KernelPCA, Isomap, and diffusion maps are exploratory and do not "
    "provide automatically shootable Deformetrica momenta."
)
ROBERTS_SCIENTIFIC_BOUNDARY = (
    SCIENTIFIC_BOUNDARY
    + " The Roberts et al. 2026 fixed-gamma preset is a published-workflow "
    "compatibility view, not evidence that its bandwidth transfers to this cohort."
)
V03_VERIFICATION_CONTRACT = (
    "The exact source hashes, declared method selection, manifest sidecar, and "
    "every exported artifact size and SHA-256 are rechecked. Completed methods "
    "are not numerically recomputed unless their source or parameters change."
)


class ReferenceShapeSpaceComparisonError(RuntimeError):
    """Raised when shape-space evidence is invalid or no longer reproducible."""


@dataclass(frozen=True)
class ReferenceShapeSpaceComparison:
    artifact_directory: Path
    manifest: dict[str, Any]


def normalize_method_ids(method_ids: tuple[str, ...] | list[str] | None) -> tuple[str, ...]:
    """Return a stable, duplicate-free selection in the documented method order."""

    if method_ids is None:
        return QUICK_METHOD_IDS
    if not isinstance(method_ids, (tuple, list)):
        raise TypeError("method_ids must be a tuple or list")
    requested = tuple(method_ids)
    if not requested:
        raise ReferenceShapeSpaceComparisonError("Select at least one shape-space method")
    if any(not isinstance(value, str) for value in requested):
        raise TypeError("method_ids must contain strings")
    unknown = sorted(set(requested) - set(METHOD_IDS))
    if unknown:
        raise ReferenceShapeSpaceComparisonError(
            "Unsupported shape-space method: " + ", ".join(unknown)
        )
    return tuple(value for value in METHOD_IDS if value in requested)


def comparison_directory_for_methods(
    method_ids: tuple[str, ...] | list[str] | None,
) -> Path:
    """Return a collision-free artifact directory for one declared selection."""

    normalized = normalize_method_ids(method_ids)
    if normalized == QUICK_METHOD_IDS:
        return DEFAULT_COMPARISON_DIRECTORY
    fingerprint = hashlib.sha256("\n".join(normalized).encode("utf-8")).hexdigest()[:10]
    return Path("analysis") / f"reference-shape-space-comparison-v0.3-{fingerprint}"


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        indent=2,
        sort_keys=True,
        ensure_ascii=False,
        allow_nan=False,
    ) + "\n"


def _float(value: float) -> float:
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ReferenceShapeSpaceComparisonError("Comparison produced a non-finite value")
    return normalized


def _deformation_kernel_width(inputs: ReferenceMomentaInput) -> float:
    try:
        value = float(
            inputs.run_report.manifest["effective_config"]["model"]["deformation"][
                "kernel_width"
            ]
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ReferenceShapeSpaceComparisonError(
            "The completed run does not declare its Deformetrica deformation kernel width"
        ) from error
    if not math.isfinite(value) or value <= 0:
        raise ReferenceShapeSpaceComparisonError(
            "The completed run declares an invalid deformation kernel width"
        )
    return value


def _source_record(inputs: ReferenceMomentaInput) -> dict[str, object]:
    root = inputs.run_directory
    return {
        "run_directory": str(root),
        "run_id": str(inputs.run_report.manifest["run_id"]),
        "manifest_sha256": sha256_file(root / "manifest.json"),
        "result_sha256": sha256_file(root / "result.json"),
        "output_inventory_sha256": sha256_file(root / "output-inventory.json"),
        "momenta_sha256": str(inputs.momenta_record["sha256"]),
        "control_points_sha256": str(inputs.control_points_record["sha256"]),
        "subject_labels": list(inputs.subject_labels),
        "subjects": inputs.subject_count,
        "control_points": inputs.control_point_count,
    }


def _method_cache_directory(inputs: ReferenceMomentaInput, method_id: str) -> Path:
    return inputs.run_directory / CACHE_DIRECTORY / method_id


def _read_method_cache(
    inputs: ReferenceMomentaInput,
    method_id: str,
    *,
    exported_components: int,
) -> tuple[dict[str, object], np.ndarray] | None:
    root = _method_cache_directory(inputs, method_id)
    if not root.exists():
        return None
    document_path = root / "method.json"
    sidecar_path = root / "method.sha256"
    if (
        not root.is_dir()
        or root.is_symlink()
        or {path.name for path in root.iterdir()} != {"method.json", "method.sha256"}
        or any(path.is_symlink() for path in root.iterdir())
    ):
        raise ReferenceShapeSpaceComparisonError(
            f"Cached shape-space method has an invalid inventory: {method_id}"
        )
    try:
        expected_hash = sidecar_path.read_text(encoding="ascii", errors="strict").strip()
        if expected_hash != sha256_file(document_path):
            raise ReferenceShapeSpaceComparisonError(
                f"Cached shape-space method hash differs: {method_id}"
            )
        value = load_strict_json_object(
            document_path.read_bytes(),
            document_path,
            label="Shape-space method cache",
        )
    except (ConfigurationError, OSError, UnicodeError) as error:
        raise ReferenceShapeSpaceComparisonError(
            f"Could not verify cached shape-space method {method_id}: {error}"
        ) from error
    if set(value) != {
        "cache_version",
        "source",
        "method_id",
        "exported_score_dimensions",
        "method",
        "scores",
    }:
        raise ReferenceShapeSpaceComparisonError(
            f"Cached shape-space method fields differ: {method_id}"
        )
    if (
        value["cache_version"] != COMPARISON_VERSION
        or value["source"] != _source_record(inputs)
        or value["method_id"] != method_id
        or value["exported_score_dimensions"] != exported_components
        or not isinstance(value["method"], dict)
    ):
        raise ReferenceShapeSpaceComparisonError(
            f"Cached shape-space method source or parameters differ: {method_id}"
        )
    try:
        scores = np.asarray(value["scores"], dtype=np.float64)
    except (TypeError, ValueError) as error:
        raise ReferenceShapeSpaceComparisonError(
            f"Cached shape-space method scores are invalid: {method_id}"
        ) from error
    if (
        scores.shape != (inputs.subject_count, exported_components)
        or not bool(np.isfinite(scores).all())
    ):
        raise ReferenceShapeSpaceComparisonError(
            f"Cached shape-space method score shape differs: {method_id}"
        )
    method = dict(value["method"])
    _validate_method_document(
        method,
        method_id=method_id,
        subject_count=inputs.subject_count,
        deformation_kernel_width=_deformation_kernel_width(inputs),
    )
    return method, scores


def _write_method_cache(
    inputs: ReferenceMomentaInput,
    method_id: str,
    method: dict[str, object],
    scores: np.ndarray,
    *,
    exported_components: int,
) -> None:
    target = _method_cache_directory(inputs, method_id)
    if target.exists():
        _read_method_cache(
            inputs,
            method_id,
            exported_components=exported_components,
        )
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.parent / f".{target.name}.tmp-{uuid.uuid4().hex}"
    temporary.mkdir()
    try:
        value = {
            "cache_version": COMPARISON_VERSION,
            "source": _source_record(inputs),
            "method_id": method_id,
            "exported_score_dimensions": exported_components,
            "method": method,
            "scores": np.asarray(scores, dtype=np.float64).tolist(),
        }
        write_text_safely(
            temporary / "method.json",
            _canonical_json(value),
            overwrite=False,
        )
        write_text_safely(
            temporary / "method.sha256",
            sha256_file(temporary / "method.json") + "\n",
            overwrite=False,
        )
        publish_directory_exclusive(temporary, target)
        _read_method_cache(
            inputs,
            method_id,
            exported_components=exported_components,
        )
    except Exception:
        if temporary.exists() and temporary.parent == target.parent:
            shutil.rmtree(temporary)
        raise


def _squared_distances(values: np.ndarray) -> np.ndarray:
    centered = values - np.mean(values, axis=0)
    gram = centered @ centered.T
    diagonal = np.diag(gram)
    squared = diagonal[:, None] + diagonal[None, :] - 2.0 * gram
    squared = np.maximum((squared + squared.T) * 0.5, 0.0)
    np.fill_diagonal(squared, 0.0)
    return squared


def _centered_kernel_alignment(left: np.ndarray, right: np.ndarray) -> float:
    count = left.shape[0]
    centering = np.eye(count, dtype=np.float64) - np.full(
        (count, count), 1.0 / count, dtype=np.float64
    )
    left_gram = centering @ (left @ left.T) @ centering
    right_gram = centering @ (right @ right.T) @ centering
    denominator = float(np.linalg.norm(left_gram) * np.linalg.norm(right_gram))
    if denominator <= 0:
        return 0.0
    return _float(np.sum(left_gram * right_gram) / denominator)


def _embedding_metrics(
    scores: np.ndarray,
    target_squared: np.ndarray,
    *,
    dimensions: int,
    reference_scores: np.ndarray,
    reference_outliers: set[int],
) -> dict[str, object]:
    retained = min(dimensions, scores.shape[1])
    selected = np.asarray(scores[:, :retained], dtype=np.float64)
    observed = np.sqrt(_squared_distances(selected))
    target = np.sqrt(target_squared)
    indices = np.triu_indices(target.shape[0], 1)
    observed_vector = observed[indices]
    target_vector = target[indices]
    if float(np.std(observed_vector)) <= 0 or float(np.std(target_vector)) <= 0:
        correlation = 0.0
    else:
        correlation = float(np.corrcoef(observed_vector, target_vector)[0, 1])
    denominator = float(observed_vector @ observed_vector)
    scale = (
        float(target_vector @ observed_vector) / denominator if denominator > 0 else 0.0
    )
    residual = target_vector - scale * observed_vector
    stress = math.sqrt(
        float(residual @ residual) / max(float(target_vector @ target_vector), 1e-300)
    )
    centered = selected - np.mean(selected, axis=0)
    radii = np.einsum("ij,ij->i", centered, centered, optimize=True)
    outlier_count = len(reference_outliers)
    method_outliers = set(
        np.argsort(radii, kind="stable")[-outlier_count:].astype(int).tolist()
    )
    return {
        "dimensions": retained,
        "distance_correlation": _float(correlation),
        "normalized_stress_after_scale": _float(stress),
        "centered_kernel_alignment_to_lddmm_pca": _centered_kernel_alignment(
            selected,
            reference_scores[:, : min(retained, reference_scores.shape[1])],
        ),
        "top_outlier_overlap": _float(
            len(method_outliers & reference_outliers) / outlier_count
        ),
    }


def _isomap(
    squared: np.ndarray,
    labels: tuple[str, ...],
) -> tuple[np.ndarray, int, np.ndarray]:
    start = max(2, int(math.ceil(math.sqrt(squared.shape[0]))))
    for neighbors in range(start, squared.shape[0]):
        try:
            result = isomap_from_squared_distances(
                squared,
                n_neighbors=neighbors,
                sample_labels=labels,
            )
        except ValueError as error:
            if "disconnected" not in str(error):
                raise
            continue
        return result.coordinates, neighbors, result.explained_positive_ratio
    raise ReferenceShapeSpaceComparisonError("Could not construct a connected Isomap graph")


def _method_document(
    *,
    method_id: str,
    label: str,
    role: str,
    scores: np.ndarray,
    ratios: np.ndarray,
    target_squared: np.ndarray,
    reference_scores: np.ndarray,
    reference_outliers: set[int],
    supports_shooting: bool,
    parameters: dict[str, object] | None = None,
) -> dict[str, object]:
    evaluations = {
        str(dimensions): _embedding_metrics(
            scores,
            target_squared,
            dimensions=dimensions,
            reference_scores=reference_scores,
            reference_outliers=reference_outliers,
        )
        for dimensions in (2, 3, min(10, scores.shape[1]), scores.shape[1])
    }
    return {
        "method_id": method_id,
        "label": label,
        "role": role,
        "supports_direct_momenta_reconstruction_and_shooting": supports_shooting,
        "parameters": parameters or {},
        "available_dimensions": int(scores.shape[1]),
        "cumulative_spectral_fraction_first_2": _float(np.sum(ratios[:2])),
        "cumulative_spectral_fraction_first_3": _float(np.sum(ratios[:3])),
        "evaluations": evaluations,
    }


def _finite_number(value: object, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ReferenceShapeSpaceComparisonError(f"{label} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ReferenceShapeSpaceComparisonError(f"{label} must be finite")
    return result


def _validate_method_document(
    method: dict[str, object],
    *,
    method_id: str,
    subject_count: int,
    deformation_kernel_width: float,
) -> None:
    required = {
        "method_id",
        "label",
        "role",
        "supports_direct_momenta_reconstruction_and_shooting",
        "parameters",
        "available_dimensions",
        "cumulative_spectral_fraction_first_2",
        "cumulative_spectral_fraction_first_3",
        "evaluations",
    }
    if set(method) != required:
        raise ReferenceShapeSpaceComparisonError(
            f"Shape-space method fields differ: {method_id}"
        )
    if (
        method.get("method_id") != method_id
        or method.get("label") != METHOD_LABELS[method_id]
        or method.get("role") != METHOD_ROLES[method_id]
        or method.get("supports_direct_momenta_reconstruction_and_shooting")
        is not (method_id in DIRECT_SHOOTING_METHOD_IDS)
        or not isinstance(method.get("parameters"), dict)
    ):
        raise ReferenceShapeSpaceComparisonError(
            f"Shape-space method identity differs: {method_id}"
        )
    available = method.get("available_dimensions")
    if (
        isinstance(available, bool)
        or not isinstance(available, int)
        or available < 1
        or available > subject_count - 1
    ):
        raise ReferenceShapeSpaceComparisonError(
            f"Shape-space method dimension is invalid: {method_id}"
        )
    for key in (
        "cumulative_spectral_fraction_first_2",
        "cumulative_spectral_fraction_first_3",
    ):
        fraction = _finite_number(method[key], label=f"{method_id} {key}")
        if fraction < -1e-12 or fraction > 1.0 + 1e-10:
            raise ReferenceShapeSpaceComparisonError(
                f"Shape-space method spectral fraction is invalid: {method_id}"
            )

    evaluations = method.get("evaluations")
    expected_dimensions = {
        str(value) for value in (2, 3, min(10, available), available)
    }
    if not isinstance(evaluations, dict) or set(evaluations) != expected_dimensions:
        raise ReferenceShapeSpaceComparisonError(
            f"Shape-space method evaluation dimensions differ: {method_id}"
        )
    evaluation_fields = {
        "dimensions",
        "distance_correlation",
        "normalized_stress_after_scale",
        "centered_kernel_alignment_to_lddmm_pca",
        "top_outlier_overlap",
    }
    for dimension, evidence in evaluations.items():
        if not isinstance(evidence, dict) or set(evidence) != evaluation_fields:
            raise ReferenceShapeSpaceComparisonError(
                f"Shape-space method evaluation fields differ: {method_id}"
            )
        expected_retained = min(int(dimension), available)
        if evidence.get("dimensions") != expected_retained:
            raise ReferenceShapeSpaceComparisonError(
                f"Shape-space method retained dimension differs: {method_id}"
            )
        correlation = _finite_number(
            evidence["distance_correlation"],
            label=f"{method_id} distance correlation",
        )
        stress = _finite_number(
            evidence["normalized_stress_after_scale"],
            label=f"{method_id} normalized stress",
        )
        alignment = _finite_number(
            evidence["centered_kernel_alignment_to_lddmm_pca"],
            label=f"{method_id} kernel alignment",
        )
        overlap = _finite_number(
            evidence["top_outlier_overlap"],
            label=f"{method_id} outlier overlap",
        )
        if (
            correlation < -1.0 - 1e-10
            or correlation > 1.0 + 1e-10
            or stress < 0
            or alignment < -1.0 - 1e-10
            or alignment > 1.0 + 1e-10
            or overlap < 0
            or overlap > 1
        ):
            raise ReferenceShapeSpaceComparisonError(
                f"Shape-space method evaluation value is invalid: {method_id}"
            )

    parameters = method["parameters"]
    if method_id == DEFAULT_METHOD_ID:
        expected = {
            "deformation_kernel_width": deformation_kernel_width,
            "kernel": "exp(-squared_distance / width^2)",
        }
        if parameters != expected:
            raise ReferenceShapeSpaceComparisonError(
                "Default shape-space metric parameters differ"
            )
    elif method_id == TANGENT_PCOA_METHOD_ID:
        if set(parameters) != {"negative_eigenvalue_sum"}:
            raise ReferenceShapeSpaceComparisonError("Tangent PCoA parameters differ")
        _finite_number(
            parameters["negative_eigenvalue_sum"],
            label="Tangent PCoA negative eigenvalue sum",
        )
    elif method_id == "cartesian_momenta_pca":
        if parameters != {}:
            raise ReferenceShapeSpaceComparisonError("Cartesian PCA parameters differ")
    elif method_id == "roberts_2026_cartesian_momenta_rbf_kpca":
        expected = {
            "gamma": ROBERTS_2026_RBF_GAMMA,
            "input": "flattened Cartesian initial momenta",
            "publication": "Roberts et al. 2026, Journal of Anatomy",
            "source_code_compatibility": (
                "KernelPCA(kernel='rbf', gamma=0.00000025, n_components=n-1)"
            ),
            "fit_inverse_transform_in_publication": True,
            "preimage": "not_exported_or_claimed_by_diffeoforge",
        }
        if parameters != expected:
            raise ReferenceShapeSpaceComparisonError(
                "Roberts compatibility parameters differ"
            )
    elif method_id.startswith("rbf_kpca_gamma_"):
        if set(parameters) != {"gamma", "median_heuristic_multiplier", "preimage"}:
            raise ReferenceShapeSpaceComparisonError(
                f"RBF KernelPCA parameters differ: {method_id}"
            )
        multiplier = {
            "rbf_kpca_gamma_0.5": 0.5,
            "rbf_kpca_gamma_1": 1.0,
            "rbf_kpca_gamma_2": 2.0,
        }[method_id]
        if (
            _finite_number(parameters["gamma"], label=f"{method_id} gamma") <= 0
            or parameters["median_heuristic_multiplier"] != multiplier
            or parameters["preimage"] != "not_available"
        ):
            raise ReferenceShapeSpaceComparisonError(
                f"RBF KernelPCA parameters are invalid: {method_id}"
            )
    elif method_id == "isomap":
        neighbors = parameters.get("neighbors")
        if (
            set(parameters) != {"neighbors"}
            or isinstance(neighbors, bool)
            or not isinstance(neighbors, int)
            or neighbors < 2
            or neighbors >= subject_count
        ):
            raise ReferenceShapeSpaceComparisonError("Isomap parameters differ")
    elif method_id == "diffusion_map":
        if (
            set(parameters) != {"epsilon", "alpha", "diffusion_time"}
            or _finite_number(parameters.get("epsilon"), label="Diffusion epsilon") <= 0
            or parameters.get("alpha") != 0.5
            or parameters.get("diffusion_time") != 1
        ):
            raise ReferenceShapeSpaceComparisonError("Diffusion-map parameters differ")


def _ordered_legacy_results(
    artifact_version: str,
    methods: list[dict[str, object]],
    scores: dict[str, np.ndarray],
) -> tuple[list[dict[str, object]], dict[str, np.ndarray]]:
    method_order = (
        LEGACY_METHOD_ORDER
        if artifact_version == LEGACY_COMPARISON_VERSION
        else FULL_METHOD_ORDER
    )
    score_order = (
        LEGACY_METHOD_ORDER
        if artifact_version == LEGACY_COMPARISON_VERSION
        else FULL_SCORE_ORDER
    )
    indexed = {str(method["method_id"]): method for method in methods}
    ordered_methods: list[dict[str, object]] = []
    for method_id in method_order:
        method = dict(indexed[method_id])
        method["label"] = LEGACY_METHOD_LABELS[method_id]
        ordered_methods.append(method)
    return ordered_methods, {method_id: scores[method_id] for method_id in score_order}


def _comparison_decision(
    methods: list[dict[str, object]],
    selected: tuple[str, ...],
    *,
    full_components: int,
    metric_reconstruction_verified: bool,
) -> dict[str, object]:
    validated = False
    if DEFAULT_METHOD_ID in selected and TANGENT_PCOA_METHOD_ID in selected:
        full_metric = next(
            item for item in methods if item["method_id"] == DEFAULT_METHOD_ID
        )["evaluations"][str(full_components)]
        pcoa_method = next(
            item for item in methods if item["method_id"] == TANGENT_PCOA_METHOD_ID
        )
        pcoa_full = pcoa_method["evaluations"][str(pcoa_method["available_dimensions"])]
        validated = bool(
            float(full_metric["normalized_stress_after_scale"]) <= 1e-10
            and float(pcoa_full["centered_kernel_alignment_to_lddmm_pca"])
            >= 1.0 - 1e-10
            and metric_reconstruction_verified
        )
    if validated:
        status = "validated_for_default"
        selected_default = DEFAULT_METHOD_ID
        reason = (
            "The deformation-kernel PCA exactly preserves the fitted atlas tangent metric "
            "at full rank, agrees with independent tangent-distance PCoA up to rotation, "
            "and retains direct reconstruction of shootable momenta."
        )
    elif DEFAULT_METHOD_ID in selected and TANGENT_PCOA_METHOD_ID not in selected:
        status = "completed_without_independent_cross_check"
        selected_default = DEFAULT_METHOD_ID
        reason = (
            "The default LDDMM metric PCA was computed, but its independent tangent-distance "
            "PCoA cross-check was not selected."
        )
    elif DEFAULT_METHOD_ID not in selected:
        status = "selected_methods_completed"
        selected_default = None
        reason = "The requested methods were computed; the default method was not selected."
    else:
        status = "validation_failed"
        selected_default = None
        reason = "The required metric-preservation and independent PCoA checks did not pass."
    return {
        "selected_default_method_id": selected_default,
        "status": status,
        "reason": reason,
        "generic_rbf_default": False,
        "generic_rbf_reason": (
            "Generic RBF KernelPCA remains sensitivity analysis because its gamma changes "
            "the morphospace and no automatic Deformetrica-momenta preimage is available."
        ),
    }


def _finalize_comparison_payload(
    inputs: ReferenceMomentaInput,
    *,
    artifact_version: str,
    created_at: str,
    selected: tuple[str, ...],
    deformation_kernel_width: float,
    full_components: int,
    exported_components: int,
    methods: list[dict[str, object]],
    scores: dict[str, np.ndarray],
    metric_reconstruction_verified: bool,
) -> tuple[dict[str, object], dict[str, np.ndarray]]:
    if artifact_version != COMPARISON_VERSION:
        methods, scores = _ordered_legacy_results(artifact_version, methods, scores)
    outlier_count = max(3, int(math.ceil(0.10 * inputs.subject_count)))
    decision = _comparison_decision(
        methods,
        selected,
        full_components=full_components,
        metric_reconstruction_verified=metric_reconstruction_verified,
    )
    manifest: dict[str, object] = {
        "artifact_version": artifact_version,
        "created_at": created_at,
        "source": _source_record(inputs),
        "analysis": {
            "target_geometry": "LDDMM initial-momenta tangent metric K(q,q) tensor I3",
            "deformation_kernel_width": deformation_kernel_width,
            "full_dimensions": full_components,
            "exported_score_dimensions": exported_components,
            "outlier_definition": f"top {outlier_count} mean squared tangent distances",
        },
        **(
            {
                "selection": {
                    "method_ids": list(selected),
                    "method_count": len(selected),
                    "selection_fingerprint": hashlib.sha256(
                        "\n".join(selected).encode("utf-8")
                    ).hexdigest(),
                }
            }
            if artifact_version == COMPARISON_VERSION
            else {}
        ),
        "methods": methods,
        "not_executed_methods": [
            {
                "method_id": "exact_geodesic_pga",
                "reason": (
                    "Exact geodesic PGA would require additional model fitting/shooting and "
                    "is not a cost-free post-processing transform of the completed momenta."
                ),
            },
            *(
                [
                    {
                        "method_id": method_id,
                        "reason": "Not selected for this cost-aware comparison.",
                    }
                    for method_id in METHOD_IDS
                    if method_id not in selected
                ]
                if artifact_version == COMPARISON_VERSION
                else []
            ),
        ],
        "default_decision": decision,
        "scientific_boundary": (
            SCIENTIFIC_BOUNDARY
            if artifact_version == LEGACY_COMPARISON_VERSION
            else ROBERTS_SCIENTIFIC_BOUNDARY
        ),
        "verification_contract": (
            V03_VERIFICATION_CONTRACT
            if artifact_version == COMPARISON_VERSION
            else (
                "Exact source hashes, all method scores, all metrics, and the default decision "
                "are deterministically recomputed from the completed run."
            )
        ),
    }
    return manifest, scores


def _comparison_payload(
    inputs: ReferenceMomentaInput,
    *,
    created_at: str,
    maximum_exported_components: int,
    artifact_version: str = COMPARISON_VERSION,
    method_ids: tuple[str, ...] | list[str] | None = None,
    progress_callback: Callable[[str, int, int], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
    cached_methods: dict[str, tuple[dict[str, object], np.ndarray]] | None = None,
    method_completed_callback: (
        Callable[[str, dict[str, object], np.ndarray], None] | None
    ) = None,
) -> tuple[dict[str, object], dict[str, np.ndarray]]:
    if artifact_version not in SUPPORTED_COMPARISON_VERSIONS:
        raise ReferenceShapeSpaceComparisonError(
            f"Unsupported comparison artifact version: {artifact_version}"
        )
    if artifact_version == LEGACY_COMPARISON_VERSION:
        selected = tuple(
            method_id
            for method_id in ALL_METHOD_IDS
            if method_id != "roberts_2026_cartesian_momenta_rbf_kpca"
        )
    elif artifact_version == FULL_COMPARISON_VERSION:
        selected = ALL_METHOD_IDS
    else:
        selected = normalize_method_ids(method_ids)
    total = len(selected)
    completed = 0

    def check_cancel() -> None:
        if should_cancel is not None and should_cancel():
            raise ReferenceShapeSpaceComparisonError(
                "Shape-space comparison cancelled; completed cached methods were preserved"
            )

    def progress(method_id: str) -> None:
        nonlocal completed
        completed += 1
        if progress_callback is not None:
            progress_callback(method_id, completed, total)

    count = inputs.subject_count
    width = _deformation_kernel_width(inputs)
    full_components = count - 1
    exported = min(maximum_exported_components, full_components)
    scores: dict[str, np.ndarray] = {}
    methods: list[dict[str, object]] = []

    def restore_cached(method_id: str) -> bool:
        if cached_methods is None or method_id not in cached_methods:
            return False
        document, values = cached_methods[method_id]
        array = np.asarray(values, dtype=np.float64)
        if (
            document.get("method_id") != method_id
            or array.shape != (count, exported)
            or not bool(np.isfinite(array).all())
        ):
            raise ReferenceShapeSpaceComparisonError(
                f"Cached shape-space method is invalid: {method_id}"
            )
        methods.append(dict(document))
        scores[method_id] = np.array(array, dtype=np.float64, copy=True)
        progress(method_id)
        return True

    def preserve_completed(method_id: str) -> None:
        if method_completed_callback is not None:
            method_completed_callback(method_id, methods[-1], scores[method_id])

    check_cancel()
    if (
        artifact_version == COMPARISON_VERSION
        and cached_methods is not None
        and all(method_id in cached_methods for method_id in selected)
    ):
        for method_id in selected:
            restore_cached(method_id)
            check_cancel()
        return _finalize_comparison_payload(
            inputs,
            artifact_version=artifact_version,
            created_at=created_at,
            selected=selected,
            deformation_kernel_width=width,
            full_components=full_components,
            exported_components=exported,
            methods=methods,
            scores=scores,
            metric_reconstruction_verified=True,
        )

    momenta = np.asarray(inputs.momenta, dtype=np.float64)
    controls = np.asarray(inputs.control_points, dtype=np.float64)
    labels = inputs.subject_labels
    target_squared = lddmm_momenta_squared_distances(
        momenta,
        controls,
        deformation_kernel_width=width,
    )
    metric_pca = lddmm_metric_momenta_pca(
        momenta,
        controls,
        deformation_kernel_width=width,
        n_components=full_components,
        subject_labels=labels,
    )
    check_cancel()
    reference_radii = np.mean(target_squared, axis=1)
    outlier_count = max(3, int(math.ceil(0.10 * count)))
    reference_outliers = set(
        np.argsort(reference_radii, kind="stable")[-outlier_count:].astype(int).tolist()
    )

    if DEFAULT_METHOD_ID in selected:
        if not restore_cached(DEFAULT_METHOD_ID):
            scores[DEFAULT_METHOD_ID] = metric_pca.scores[:, :exported]
            methods.append(_method_document(
            method_id="lddmm_deformation_kernel_pca",
            label=METHOD_LABELS[DEFAULT_METHOD_ID],
            role="default_candidate_model_aligned_linear_ordination",
            scores=metric_pca.scores,
            ratios=metric_pca.explained_variance_ratio,
            target_squared=target_squared,
            reference_scores=metric_pca.scores,
            reference_outliers=reference_outliers,
            supports_shooting=True,
            parameters={
                "deformation_kernel_width": width,
                "kernel": "exp(-squared_distance / width^2)",
            },
            ))
            preserve_completed(DEFAULT_METHOD_ID)
            progress(DEFAULT_METHOD_ID)
    check_cancel()
    pcoa = None
    if TANGENT_PCOA_METHOD_ID in selected:
        if not restore_cached(TANGENT_PCOA_METHOD_ID):
            pcoa = principal_coordinates_analysis(target_squared, sample_labels=labels)
            scores[TANGENT_PCOA_METHOD_ID] = pcoa.coordinates[:, :exported]
            methods.append(_method_document(
            method_id=TANGENT_PCOA_METHOD_ID,
            label=METHOD_LABELS[TANGENT_PCOA_METHOD_ID],
            role="distance_based_cross_check",
            scores=pcoa.coordinates,
            ratios=pcoa.explained_positive_ratio,
            target_squared=target_squared,
            reference_scores=metric_pca.scores,
            reference_outliers=reference_outliers,
            supports_shooting=False,
            parameters={"negative_eigenvalue_sum": pcoa.negative_eigenvalue_sum},
            ))
            preserve_completed(TANGENT_PCOA_METHOD_ID)
            progress(TANGENT_PCOA_METHOD_ID)
    check_cancel()
    if "cartesian_momenta_pca" in selected:
        if not restore_cached("cartesian_momenta_pca"):
            cartesian = momenta_pca(
            momenta,
            n_components=full_components,
            subject_labels=labels,
        )
            scores["cartesian_momenta_pca"] = cartesian.scores[:, :exported]
            methods.append(_method_document(
            method_id="cartesian_momenta_pca",
            label=METHOD_LABELS["cartesian_momenta_pca"],
            role="legacy_compatibility",
            scores=cartesian.scores,
            ratios=cartesian.explained_variance_ratio,
            target_squared=target_squared,
            reference_scores=metric_pca.scores,
            reference_outliers=reference_outliers,
            supports_shooting=True,
            ))
            preserve_completed("cartesian_momenta_pca")
            progress("cartesian_momenta_pca")
    check_cancel()
    if "roberts_2026_cartesian_momenta_rbf_kpca" in selected:
        roberts_id = "roberts_2026_cartesian_momenta_rbf_kpca"
        if not restore_cached(roberts_id):
            roberts_compatibility = rbf_kernel_pca_from_squared_distances(
            _squared_distances(momenta.reshape(count, -1)),
            gamma=ROBERTS_2026_RBF_GAMMA,
            sample_labels=labels,
        )
            scores[roberts_id] = roberts_compatibility.scores[:, :exported]
            methods.append(_method_document(
            method_id=roberts_id,
            label=METHOD_LABELS[roberts_id],
            role="published_workflow_compatibility",
            scores=roberts_compatibility.scores,
            ratios=roberts_compatibility.explained_variance_ratio,
            target_squared=target_squared,
            reference_scores=metric_pca.scores,
            reference_outliers=reference_outliers,
            supports_shooting=False,
            parameters={
                "gamma": ROBERTS_2026_RBF_GAMMA,
                "input": "flattened Cartesian initial momenta",
                "publication": "Roberts et al. 2026, Journal of Anatomy",
                "source_code_compatibility": (
                    "KernelPCA(kernel='rbf', gamma=0.00000025, n_components=n-1)"
                ),
                "fit_inverse_transform_in_publication": True,
                "preimage": "not_exported_or_claimed_by_diffeoforge",
            },
            ))
            preserve_completed(roberts_id)
            progress(roberts_id)
    check_cancel()
    gamma = None
    for multiplier, method_id in (
        (0.5, "rbf_kpca_gamma_0.5"),
        (1.0, "rbf_kpca_gamma_1"),
        (2.0, "rbf_kpca_gamma_2"),
    ):
        if method_id not in selected:
            continue
        if restore_cached(method_id):
            check_cancel()
            continue
        if gamma is None:
            gamma = median_heuristic_gamma(target_squared)
        result = rbf_kernel_pca_from_squared_distances(
            target_squared,
            gamma=gamma * multiplier,
            sample_labels=labels,
        )
        scores[method_id] = result.scores[:, :exported]
        methods.append(
            _method_document(
                method_id=method_id,
                label=METHOD_LABELS[method_id],
                role="exploratory_nonlinear_sensitivity",
                scores=result.scores,
                ratios=result.explained_variance_ratio,
                target_squared=target_squared,
                reference_scores=metric_pca.scores,
                reference_outliers=reference_outliers,
                supports_shooting=False,
                parameters={
                    "gamma": result.gamma,
                    "median_heuristic_multiplier": multiplier,
                    "preimage": "not_available",
                },
            )
        )
        preserve_completed(method_id)
        progress(method_id)
        check_cancel()
    if "isomap" in selected:
        if not restore_cached("isomap"):
            isomap_scores, neighbors, isomap_ratios = _isomap(target_squared, labels)
            scores["isomap"] = isomap_scores[:, :exported]
            methods.append(_method_document(
                method_id="isomap",
                label=METHOD_LABELS["isomap"],
                role="exploratory_nonlinear_ordination",
                scores=isomap_scores,
                ratios=isomap_ratios,
                target_squared=target_squared,
                reference_scores=metric_pca.scores,
                reference_outliers=reference_outliers,
                supports_shooting=False,
                parameters={"neighbors": neighbors},
            ))
            preserve_completed("isomap")
            progress("isomap")
    check_cancel()
    if "diffusion_map" in selected:
        if not restore_cached("diffusion_map"):
            diffusion = diffusion_map_from_squared_distances(
            target_squared,
            sample_labels=labels,
        )
            scores["diffusion_map"] = diffusion.coordinates[:, :exported]
            methods.append(_method_document(
                method_id="diffusion_map",
                label=METHOD_LABELS["diffusion_map"],
                role="exploratory_nonlinear_ordination",
                scores=diffusion.coordinates,
                ratios=diffusion.explained_positive_ratio,
                target_squared=target_squared,
                reference_scores=metric_pca.scores,
                reference_outliers=reference_outliers,
                supports_shooting=False,
                parameters={
                    "epsilon": 1.0 / median_heuristic_gamma(target_squared),
                    "alpha": 0.5,
                    "diffusion_time": 1,
                },
            ))
            preserve_completed("diffusion_map")
            progress("diffusion_map")
    check_cancel()
    return _finalize_comparison_payload(
        inputs,
        artifact_version=artifact_version,
        created_at=created_at,
        selected=selected,
        deformation_kernel_width=width,
        full_components=full_components,
        exported_components=exported,
        methods=methods,
        scores=scores,
        metric_reconstruction_verified=(
            metric_pca.reconstruct_training_data().shape == (count, controls.size)
        ),
    )


def _metrics_csv(manifest: dict[str, object]) -> str:
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(
        [
            "method_id",
            "dimensions",
            "distance_correlation",
            "normalized_stress_after_scale",
            "centered_kernel_alignment_to_lddmm_pca",
            "top_outlier_overlap",
            "supports_direct_momenta_reconstruction_and_shooting",
            "role",
        ]
    )
    for method in manifest["methods"]:
        for evidence in method["evaluations"].values():
            writer.writerow(
                [
                    method["method_id"],
                    evidence["dimensions"],
                    format(float(evidence["distance_correlation"]), ".17g"),
                    format(float(evidence["normalized_stress_after_scale"]), ".17g"),
                    format(
                        float(evidence["centered_kernel_alignment_to_lddmm_pca"]),
                        ".17g",
                    ),
                    format(float(evidence["top_outlier_overlap"]), ".17g"),
                    str(method["supports_direct_momenta_reconstruction_and_shooting"]).lower(),
                    method["role"],
                ]
            )
    return output.getvalue()


def _scores_csv(
    labels: tuple[str, ...],
    scores: dict[str, np.ndarray],
) -> str:
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(["method_id", "subject_label", "component", "score"])
    for method_id, values in scores.items():
        for row, label in enumerate(labels):
            for component in range(values.shape[1]):
                writer.writerow(
                    [
                        method_id,
                        label,
                        component + 1,
                        format(float(values[row, component]), ".17g"),
                    ]
                )
    return output.getvalue()


def _readme(manifest: dict[str, object]) -> str:
    decision = manifest["default_decision"]
    return (
        "# DiffeoForge shape-space method comparison\n\n"
        f"Decision: **{decision['status']}**.\n\n"
        f"Selected default: `{decision['selected_default_method_id']}`.\n\n"
        f"{decision['reason']}\n\n"
        "The CSV files expose comparable numerical metrics and the exported score axes. "
        "See the JSON manifest for method-specific parameters and limitations.\n\n"
        f"Scientific boundary: {manifest['scientific_boundary']}\n"
    )


def _read_v03_scores(
    path: Path,
    *,
    method_ids: tuple[str, ...],
    subject_labels: tuple[str, ...],
    exported_components: int,
) -> dict[str, np.ndarray]:
    try:
        with path.open("r", encoding="utf-8", errors="strict", newline="") as handle:
            rows = list(csv.reader(handle))
    except (OSError, UnicodeError, csv.Error) as error:
        raise ReferenceShapeSpaceComparisonError(
            "Could not read comparison scores CSV"
        ) from error
    if not rows or rows[0] != ["method_id", "subject_label", "component", "score"]:
        raise ReferenceShapeSpaceComparisonError("Comparison scores CSV header differs")
    expected_rows = len(method_ids) * len(subject_labels) * exported_components
    if len(rows) != expected_rows + 1:
        raise ReferenceShapeSpaceComparisonError("Comparison scores CSV row count differs")
    scores = {
        method_id: np.empty(
            (len(subject_labels), exported_components),
            dtype=np.float64,
        )
        for method_id in method_ids
    }
    cursor = 1
    for method_id in method_ids:
        for subject_index, subject_label in enumerate(subject_labels):
            for component_index in range(exported_components):
                row = rows[cursor]
                cursor += 1
                expected_identity = [
                    method_id,
                    subject_label,
                    str(component_index + 1),
                ]
                if len(row) != 4 or row[:3] != expected_identity:
                    raise ReferenceShapeSpaceComparisonError(
                        f"Comparison scores CSV identity differs at row {cursor}"
                    )
                try:
                    value = float(row[3])
                except ValueError as error:
                    raise ReferenceShapeSpaceComparisonError(
                        f"Comparison scores CSV contains a non-number at row {cursor}"
                    ) from error
                if not math.isfinite(value):
                    raise ReferenceShapeSpaceComparisonError(
                        f"Comparison scores CSV contains a non-finite value at row {cursor}"
                    )
                scores[method_id][subject_index, component_index] = value
    return scores


def _verify_v03_structure_and_documents(
    root: Path,
    manifest: dict[str, object],
    inputs: ReferenceMomentaInput,
) -> None:
    try:
        parsed_created_at = datetime.fromisoformat(
            str(manifest["created_at"]).replace("Z", "+00:00")
        )
    except ValueError as error:
        raise ReferenceShapeSpaceComparisonError(
            "Comparison creation timestamp is invalid"
        ) from error
    if parsed_created_at.tzinfo is None:
        raise ReferenceShapeSpaceComparisonError(
            "Comparison creation timestamp lacks a timezone offset"
        )

    selection = manifest.get("selection")
    if not isinstance(selection, dict):
        raise ReferenceShapeSpaceComparisonError("Comparison selection is invalid")
    method_ids = normalize_method_ids(selection.get("method_ids"))
    fingerprint = hashlib.sha256("\n".join(method_ids).encode("utf-8")).hexdigest()
    if selection != {
        "method_ids": list(method_ids),
        "method_count": len(method_ids),
        "selection_fingerprint": fingerprint,
    }:
        raise ReferenceShapeSpaceComparisonError("Comparison selection differs")

    full_components = inputs.subject_count - 1
    analysis = manifest.get("analysis")
    if not isinstance(analysis, dict):
        raise ReferenceShapeSpaceComparisonError("Comparison analysis record is invalid")
    exported = analysis.get("exported_score_dimensions")
    if (
        isinstance(exported, bool)
        or not isinstance(exported, int)
        or exported < 1
        or exported > full_components
    ):
        raise ReferenceShapeSpaceComparisonError(
            "Comparison exported score dimension is invalid"
        )
    outlier_count = max(3, int(math.ceil(0.10 * inputs.subject_count)))
    width = _deformation_kernel_width(inputs)
    if analysis != {
        "target_geometry": "LDDMM initial-momenta tangent metric K(q,q) tensor I3",
        "deformation_kernel_width": width,
        "full_dimensions": full_components,
        "exported_score_dimensions": exported,
        "outlier_definition": f"top {outlier_count} mean squared tangent distances",
    }:
        raise ReferenceShapeSpaceComparisonError("Comparison analysis record differs")

    methods = manifest.get("methods")
    if not isinstance(methods, list) or not all(isinstance(item, dict) for item in methods):
        raise ReferenceShapeSpaceComparisonError("Comparison methods are invalid")
    observed_ids = tuple(str(method.get("method_id")) for method in methods)
    if observed_ids != method_ids:
        raise ReferenceShapeSpaceComparisonError(
            "Comparison methods do not match the declared selection"
        )
    for method_id, method in zip(method_ids, methods, strict=True):
        _validate_method_document(
            method,
            method_id=method_id,
            subject_count=inputs.subject_count,
            deformation_kernel_width=width,
        )

    expected_not_executed = [
        {
            "method_id": "exact_geodesic_pga",
            "reason": (
                "Exact geodesic PGA would require additional model fitting/shooting and "
                "is not a cost-free post-processing transform of the completed momenta."
            ),
        },
        *[
            {
                "method_id": method_id,
                "reason": "Not selected for this cost-aware comparison.",
            }
            for method_id in METHOD_IDS
            if method_id not in method_ids
        ],
    ]
    if manifest.get("not_executed_methods") != expected_not_executed:
        raise ReferenceShapeSpaceComparisonError(
            "Comparison omitted-method declarations differ"
        )
    if manifest.get("scientific_boundary") != ROBERTS_SCIENTIFIC_BOUNDARY:
        raise ReferenceShapeSpaceComparisonError("Comparison scientific boundary differs")
    if manifest.get("verification_contract") != V03_VERIFICATION_CONTRACT:
        raise ReferenceShapeSpaceComparisonError("Comparison verification contract differs")
    expected_decision = _comparison_decision(
        methods,
        method_ids,
        full_components=full_components,
        metric_reconstruction_verified=True,
    )
    if manifest.get("default_decision") != expected_decision:
        raise ReferenceShapeSpaceComparisonError("Comparison default decision differs")

    try:
        metrics_text = (root / METRICS_CSV).read_text(
            encoding="utf-8", errors="strict"
        )
        readme_text = (root / README_NAME).read_text(
            encoding="utf-8", errors="strict"
        )
    except (OSError, UnicodeError) as error:
        raise ReferenceShapeSpaceComparisonError(
            "Could not read comparison text artifacts"
        ) from error
    if metrics_text != _metrics_csv(manifest):
        raise ReferenceShapeSpaceComparisonError(
            "Comparison metrics CSV differs from its manifest"
        )
    if readme_text != _readme(manifest):
        raise ReferenceShapeSpaceComparisonError(
            "Comparison README differs from its manifest"
        )
    scores = _read_v03_scores(
        root / SCORES_CSV,
        method_ids=method_ids,
        subject_labels=inputs.subject_labels,
        exported_components=exported,
    )
    for method_id, method in zip(method_ids, methods, strict=True):
        cached = _read_method_cache(
            inputs,
            method_id,
            exported_components=exported,
        )
        if cached is None:
            raise ReferenceShapeSpaceComparisonError(
                f"Comparison method cache is missing: {method_id}"
            )
        cached_method, cached_scores = cached
        if cached_method != method or not np.array_equal(
            cached_scores,
            scores[method_id],
        ):
            raise ReferenceShapeSpaceComparisonError(
                f"Comparison method differs from its source-bound cache: {method_id}"
            )


def _artifact_documents(
    inputs: ReferenceMomentaInput,
    *,
    created_at: str,
    maximum_exported_components: int,
    artifact_version: str = COMPARISON_VERSION,
    method_ids: tuple[str, ...] | list[str] | None = None,
    progress_callback: Callable[[str, int, int], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
    cached_methods: dict[str, tuple[dict[str, object], np.ndarray]] | None = None,
    method_completed_callback: (
        Callable[[str, dict[str, object], np.ndarray], None] | None
    ) = None,
) -> tuple[dict[str, object], dict[str, str]]:
    manifest, scores = _comparison_payload(
        inputs,
        created_at=created_at,
        maximum_exported_components=maximum_exported_components,
        artifact_version=artifact_version,
        method_ids=method_ids,
        progress_callback=progress_callback,
        should_cancel=should_cancel,
        cached_methods=cached_methods,
        method_completed_callback=method_completed_callback,
    )
    documents = {
        METRICS_CSV: _metrics_csv(manifest),
        SCORES_CSV: _scores_csv(inputs.subject_labels, scores),
        README_NAME: _readme(manifest),
    }
    if artifact_version == COMPARISON_VERSION:
        manifest["artifacts"] = [
            {
                "path": name,
                "bytes": len(contents.encode("utf-8")),
                "sha256": hashlib.sha256(contents.encode("utf-8")).hexdigest(),
            }
            for name, contents in documents.items()
        ]
        manifest["verification_contract"] = V03_VERIFICATION_CONTRACT
    return manifest, {COMPARISON_MANIFEST: _canonical_json(manifest), **documents}


def write_reference_shape_space_comparison(
    run_directory: Path | str,
    destination: Path | str | None = None,
    *,
    maximum_exported_components: int = 10,
    created_at: str | None = None,
    method_ids: tuple[str, ...] | list[str] | None = None,
    progress_callback: Callable[[str, int, int], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> Path:
    """Publish a source-bound, exactly reproducible shape-space comparison."""

    if (
        isinstance(maximum_exported_components, bool)
        or not isinstance(maximum_exported_components, Integral)
        or maximum_exported_components < 1
    ):
        raise ReferenceShapeSpaceComparisonError(
            "maximum_exported_components must be a positive integer"
        )
    inputs = load_reference_momenta(run_directory)
    normalized_methods = normalize_method_ids(method_ids)
    target = (
        inputs.run_directory / comparison_directory_for_methods(normalized_methods)
        if destination is None
        else Path(destination).expanduser().resolve()
    )
    if target.exists():
        raise FileExistsError(f"Shape-space comparison destination already exists: {target}")
    timestamp = created_at or datetime.now(UTC).isoformat(timespec="seconds")
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError as error:
        raise ReferenceShapeSpaceComparisonError(
            "created_at must be an ISO-8601 timestamp"
        ) from error
    if parsed.tzinfo is None:
        raise ReferenceShapeSpaceComparisonError(
            "created_at must include a timezone offset"
        )
    exported_components = min(
        int(maximum_exported_components),
        inputs.subject_count - 1,
    )
    cached_methods = {
        method_id: cached
        for method_id in normalized_methods
        if (
            cached := _read_method_cache(
                inputs,
                method_id,
                exported_components=exported_components,
            )
        )
        is not None
    }
    manifest, documents = _artifact_documents(
        inputs,
        created_at=timestamp,
        maximum_exported_components=int(maximum_exported_components),
        method_ids=normalized_methods,
        progress_callback=progress_callback,
        should_cancel=should_cancel,
        cached_methods=cached_methods,
        method_completed_callback=lambda method_id, method, scores: _write_method_cache(
            inputs,
            method_id,
            method,
            scores,
            exported_components=exported_components,
        ),
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.parent / f".{target.name}.tmp-{uuid.uuid4().hex}"
    temporary.mkdir()
    try:
        for name, contents in documents.items():
            write_text_safely(temporary / name, contents, overwrite=False)
        write_text_safely(
            temporary / COMPARISON_SIDECAR,
            sha256_file(temporary / COMPARISON_MANIFEST) + "\n",
            overwrite=False,
        )
        verify_reference_shape_space_comparison(temporary)
        publish_directory_exclusive(temporary, target)
        return verify_reference_shape_space_comparison(target).artifact_directory
    except Exception:
        if temporary.exists() and temporary.parent == target.parent:
            shutil.rmtree(temporary)
        raise


def verify_reference_shape_space_comparison(
    artifact_directory: Path | str,
) -> ReferenceShapeSpaceComparison:
    """Rebind the source run and exactly regenerate every comparison artifact."""

    root = Path(artifact_directory).expanduser().resolve()
    if not root.is_dir() or root.is_symlink():
        raise ReferenceShapeSpaceComparisonError(
            f"Shape-space comparison is missing or symbolic: {root}"
        )
    expected_names = {
        COMPARISON_MANIFEST,
        COMPARISON_SIDECAR,
        METRICS_CSV,
        SCORES_CSV,
        README_NAME,
    }
    actual_names = {path.name for path in root.iterdir() if path.is_file()}
    if (
        actual_names != expected_names
        or any(path.is_dir() for path in root.iterdir())
        or any(path.is_symlink() for path in root.iterdir())
    ):
        raise ReferenceShapeSpaceComparisonError(
            "Shape-space comparison contains an unexpected file or directory"
        )
    manifest_path = root / COMPARISON_MANIFEST
    try:
        expected_hash = (root / COMPARISON_SIDECAR).read_text(encoding="ascii").strip()
    except (OSError, UnicodeError) as error:
        raise ReferenceShapeSpaceComparisonError(
            "Could not read the comparison SHA-256 sidecar"
        ) from error
    if expected_hash != sha256_file(manifest_path):
        raise ReferenceShapeSpaceComparisonError("Comparison manifest SHA-256 differs")
    try:
        manifest = load_strict_json_object(
            manifest_path.read_bytes(), manifest_path, label="Shape-space comparison"
        )
    except (ConfigurationError, OSError) as error:
        raise ReferenceShapeSpaceComparisonError(str(error)) from error
    required = {
        "artifact_version",
        "created_at",
        "source",
        "analysis",
        "methods",
        "not_executed_methods",
        "default_decision",
        "scientific_boundary",
        "verification_contract",
    }
    if manifest.get("artifact_version") == COMPARISON_VERSION:
        required.update({"selection", "artifacts"})
    if (
        set(manifest) != required
        or manifest["artifact_version"] not in SUPPORTED_COMPARISON_VERSIONS
    ):
        raise ReferenceShapeSpaceComparisonError(
            "Shape-space comparison version or manifest fields differ"
        )
    source = manifest.get("source")
    if not isinstance(source, dict) or not isinstance(source.get("run_directory"), str):
        raise ReferenceShapeSpaceComparisonError("Comparison source record is invalid")
    try:
        inputs = load_reference_momenta(source["run_directory"])
    except (OSError, RuntimeError, TypeError, ValueError) as error:
        raise ReferenceShapeSpaceComparisonError(str(error)) from error
    if source != _source_record(inputs):
        raise ReferenceShapeSpaceComparisonError(
            "Comparison source run identity or content hashes changed"
        )
    analysis = manifest.get("analysis")
    if not isinstance(analysis, dict):
        raise ReferenceShapeSpaceComparisonError("Comparison analysis record is invalid")
    exported = analysis.get("exported_score_dimensions")
    if isinstance(exported, bool) or not isinstance(exported, int) or exported < 1:
        raise ReferenceShapeSpaceComparisonError(
            "Comparison exported score dimension is invalid"
        )
    if manifest["artifact_version"] == COMPARISON_VERSION:
        selection = manifest.get("selection")
        if not isinstance(selection, dict):
            raise ReferenceShapeSpaceComparisonError("Comparison selection is invalid")
        method_ids = normalize_method_ids(selection.get("method_ids"))
        fingerprint = hashlib.sha256("\n".join(method_ids).encode("utf-8")).hexdigest()
        if selection != {
            "method_ids": list(method_ids),
            "method_count": len(method_ids),
            "selection_fingerprint": fingerprint,
        }:
            raise ReferenceShapeSpaceComparisonError("Comparison selection differs")
        records = manifest.get("artifacts")
        if not isinstance(records, list) or len(records) != 3:
            raise ReferenceShapeSpaceComparisonError("Comparison artifact inventory is invalid")
        indexed: dict[str, dict[str, object]] = {}
        for record in records:
            if not isinstance(record, dict) or set(record) != {"path", "bytes", "sha256"}:
                raise ReferenceShapeSpaceComparisonError(
                    "Comparison artifact inventory record is invalid"
                )
            name = record.get("path")
            if not isinstance(name, str) or name not in {METRICS_CSV, SCORES_CSV, README_NAME}:
                raise ReferenceShapeSpaceComparisonError(
                    "Comparison artifact inventory path is invalid"
                )
            if name in indexed:
                raise ReferenceShapeSpaceComparisonError(
                    "Comparison artifact inventory contains duplicates"
                )
            byte_count = record.get("bytes")
            digest = record.get("sha256")
            if (
                isinstance(byte_count, bool)
                or not isinstance(byte_count, int)
                or byte_count < 0
                or not isinstance(digest, str)
                or len(digest) != 64
                or any(character not in "0123456789abcdef" for character in digest)
            ):
                raise ReferenceShapeSpaceComparisonError(
                    "Comparison artifact inventory hash or size is invalid"
                )
            indexed[name] = record
        if set(indexed) != {METRICS_CSV, SCORES_CSV, README_NAME}:
            raise ReferenceShapeSpaceComparisonError(
                "Comparison artifact inventory is incomplete"
            )
        for name, record in indexed.items():
            path = root / name
            try:
                observed_bytes = path.stat().st_size
                observed_sha256 = sha256_file(path)
            except OSError as error:
                raise ReferenceShapeSpaceComparisonError(
                    f"Could not inspect comparison artifact: {name}"
                ) from error
            if observed_bytes != record["bytes"] or observed_sha256 != record["sha256"]:
                raise ReferenceShapeSpaceComparisonError(
                    f"Comparison artifact hash or size differs: {name}"
                )
        _verify_v03_structure_and_documents(root, manifest, inputs)
        return ReferenceShapeSpaceComparison(root, dict(manifest))
    recomputed, documents = _artifact_documents(
        inputs,
        created_at=str(manifest["created_at"]),
        maximum_exported_components=exported,
        artifact_version=str(manifest["artifact_version"]),
    )
    if manifest != recomputed:
        raise ReferenceShapeSpaceComparisonError(
            "Comparison evidence differs from deterministic recomputation"
        )
    for name, expected in documents.items():
        try:
            observed = (root / name).read_text(encoding="utf-8", errors="strict")
        except (OSError, UnicodeError) as error:
            raise ReferenceShapeSpaceComparisonError(
                f"Could not read comparison artifact: {name}"
            ) from error
        if observed != expected:
            raise ReferenceShapeSpaceComparisonError(
                f"Comparison artifact differs from recomputation: {name}"
            )
    return ReferenceShapeSpaceComparison(root, dict(manifest))
