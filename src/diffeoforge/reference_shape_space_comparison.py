"""Immutable method comparison for completed Deformetrica atlas momenta."""

from __future__ import annotations

import csv
import io
import json
import math
import shutil
import uuid
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
COMPARISON_VERSION = "0.2"
SUPPORTED_COMPARISON_VERSIONS = (LEGACY_COMPARISON_VERSION, COMPARISON_VERSION)
COMPARISON_MANIFEST = "shape-space-comparison.json"
COMPARISON_SIDECAR = "shape-space-comparison.sha256"
METRICS_CSV = "method-metrics.csv"
SCORES_CSV = "scores.csv"
README_NAME = "README.md"
DEFAULT_COMPARISON_DIRECTORY = Path("analysis") / "reference-shape-space-comparison-v0.2"
DEFAULT_METHOD_ID = "lddmm_deformation_kernel_pca"
ROBERTS_2026_RBF_GAMMA = 0.00000025
SCIENTIFIC_BOUNDARY = (
    "This comparison evaluates numerical representations of one completed atlas. It does "
    "not establish biological group separation, registration validity, or an exact geodesic "
    "PGA. Generic RBF KernelPCA, Isomap, and diffusion maps are exploratory and do not "
    "provide automatically shootable Deformetrica momenta."
)


class ReferenceShapeSpaceComparisonError(RuntimeError):
    """Raised when shape-space evidence is invalid or no longer reproducible."""


@dataclass(frozen=True)
class ReferenceShapeSpaceComparison:
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


def _comparison_payload(
    inputs: ReferenceMomentaInput,
    *,
    created_at: str,
    maximum_exported_components: int,
    artifact_version: str = COMPARISON_VERSION,
) -> tuple[dict[str, object], dict[str, np.ndarray]]:
    if artifact_version not in SUPPORTED_COMPARISON_VERSIONS:
        raise ReferenceShapeSpaceComparisonError(
            f"Unsupported comparison artifact version: {artifact_version}"
        )
    count = inputs.subject_count
    width = _deformation_kernel_width(inputs)
    full_components = count - 1
    exported = min(maximum_exported_components, full_components)
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
    cartesian = momenta_pca(
        momenta,
        n_components=full_components,
        subject_labels=labels,
    )
    pcoa = principal_coordinates_analysis(
        target_squared,
        sample_labels=labels,
    )
    gamma = median_heuristic_gamma(target_squared)
    rbf_results = {
        multiplier: rbf_kernel_pca_from_squared_distances(
            target_squared,
            gamma=gamma * multiplier,
            sample_labels=labels,
        )
        for multiplier in (0.5, 1.0, 2.0)
    }
    roberts_compatibility = rbf_kernel_pca_from_squared_distances(
        _squared_distances(momenta.reshape(count, -1)),
        gamma=ROBERTS_2026_RBF_GAMMA,
        sample_labels=labels,
    )
    isomap_scores, neighbors, isomap_ratios = _isomap(target_squared, labels)
    diffusion = diffusion_map_from_squared_distances(
        target_squared,
        sample_labels=labels,
    )
    reference_radii = np.mean(target_squared, axis=1)
    outlier_count = max(3, int(math.ceil(0.10 * count)))
    reference_outliers = set(
        np.argsort(reference_radii, kind="stable")[-outlier_count:].astype(int).tolist()
    )
    scores = {
        "lddmm_deformation_kernel_pca": metric_pca.scores[:, :exported],
        "cartesian_momenta_pca": cartesian.scores[:, :exported],
        "lddmm_tangent_pcoa": pcoa.coordinates[:, :exported],
        "rbf_kpca_gamma_0.5": rbf_results[0.5].scores[:, :exported],
        "rbf_kpca_gamma_1": rbf_results[1.0].scores[:, :exported],
        "rbf_kpca_gamma_2": rbf_results[2.0].scores[:, :exported],
        "isomap": isomap_scores[:, :exported],
        "diffusion_map": diffusion.coordinates[:, :exported],
    }
    if artifact_version != LEGACY_COMPARISON_VERSION:
        scores["roberts_2026_cartesian_momenta_rbf_kpca"] = (
            roberts_compatibility.scores[:, :exported]
        )
    methods = [
        _method_document(
            method_id="lddmm_deformation_kernel_pca",
            label="LDDMM deformation-kernel metric tangent PCA",
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
        ),
        _method_document(
            method_id="cartesian_momenta_pca",
            label="Cartesian momenta PCA",
            role="legacy_compatibility",
            scores=cartesian.scores,
            ratios=cartesian.explained_variance_ratio,
            target_squared=target_squared,
            reference_scores=metric_pca.scores,
            reference_outliers=reference_outliers,
            supports_shooting=True,
        ),
        _method_document(
            method_id="lddmm_tangent_pcoa",
            label="PCoA of LDDMM tangent distances",
            role="distance_based_cross_check",
            scores=pcoa.coordinates,
            ratios=pcoa.explained_positive_ratio,
            target_squared=target_squared,
            reference_scores=metric_pca.scores,
            reference_outliers=reference_outliers,
            supports_shooting=False,
            parameters={"negative_eigenvalue_sum": pcoa.negative_eigenvalue_sum},
        ),
    ]
    for multiplier, method_id in (
        (0.5, "rbf_kpca_gamma_0.5"),
        (1.0, "rbf_kpca_gamma_1"),
        (2.0, "rbf_kpca_gamma_2"),
    ):
        result = rbf_results[multiplier]
        methods.append(
            _method_document(
                method_id=method_id,
                label=f"Generic RBF KernelPCA (gamma x {multiplier:g})",
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
    if artifact_version != LEGACY_COMPARISON_VERSION:
        methods.append(
            _method_document(
                method_id="roberts_2026_cartesian_momenta_rbf_kpca",
                label="Roberts et al. 2026 Cartesian-momenta RBF KernelPCA preset",
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
            )
        )
    methods.extend(
        [
            _method_document(
                method_id="isomap",
                label="Isomap of LDDMM tangent distances",
                role="exploratory_nonlinear_ordination",
                scores=isomap_scores,
                ratios=isomap_ratios,
                target_squared=target_squared,
                reference_scores=metric_pca.scores,
                reference_outliers=reference_outliers,
                supports_shooting=False,
                parameters={"neighbors": neighbors},
            ),
            _method_document(
                method_id="diffusion_map",
                label="Diffusion map of LDDMM tangent distances",
                role="exploratory_nonlinear_ordination",
                scores=diffusion.coordinates,
                ratios=diffusion.explained_positive_ratio,
                target_squared=target_squared,
                reference_scores=metric_pca.scores,
                reference_outliers=reference_outliers,
                supports_shooting=False,
                parameters={
                    "epsilon": 1.0 / gamma,
                    "alpha": 0.5,
                    "diffusion_time": 1,
                },
            ),
        ]
    )
    full_metric = next(
        item for item in methods if item["method_id"] == DEFAULT_METHOD_ID
    )["evaluations"][str(full_components)]
    pcoa_full = next(
        item for item in methods if item["method_id"] == "lddmm_tangent_pcoa"
    )["evaluations"][str(pcoa.coordinates.shape[1])]
    validated = bool(
        float(full_metric["normalized_stress_after_scale"]) <= 1e-10
        and float(pcoa_full["centered_kernel_alignment_to_lddmm_pca"])
        >= 1.0 - 1e-10
        and metric_pca.reconstruct_training_data().shape == (count, controls.size)
    )
    decision = {
        "selected_default_method_id": DEFAULT_METHOD_ID if validated else None,
        "status": "validated_for_default" if validated else "validation_failed",
        "reason": (
            "The deformation-kernel PCA exactly preserves the fitted atlas tangent metric "
            "at full rank, agrees with independent tangent-distance PCoA up to rotation, "
            "and retains direct reconstruction of shootable momenta."
            if validated
            else "The required metric-preservation and independent PCoA checks did not pass."
        ),
        "generic_rbf_default": False,
        "generic_rbf_reason": (
            "Generic RBF KernelPCA remains sensitivity analysis because its gamma changes "
            "the morphospace and no automatic Deformetrica-momenta preimage is available."
        ),
    }
    manifest: dict[str, object] = {
        "artifact_version": artifact_version,
        "created_at": created_at,
        "source": _source_record(inputs),
        "analysis": {
            "target_geometry": "LDDMM initial-momenta tangent metric K(q,q) tensor I3",
            "deformation_kernel_width": width,
            "full_dimensions": full_components,
            "exported_score_dimensions": exported,
            "outlier_definition": f"top {outlier_count} mean squared tangent distances",
        },
        "methods": methods,
        "not_executed_methods": [
            {
                "method_id": "exact_geodesic_pga",
                "reason": (
                    "Exact geodesic PGA would require additional model fitting/shooting and "
                    "is not a cost-free post-processing transform of the completed momenta."
                ),
            }
        ],
        "default_decision": decision,
        "scientific_boundary": (
            SCIENTIFIC_BOUNDARY
            if artifact_version == LEGACY_COMPARISON_VERSION
            else SCIENTIFIC_BOUNDARY
            + " The Roberts et al. 2026 fixed-gamma preset is a published-workflow "
            "compatibility view, not evidence that its bandwidth transfers to this cohort."
        ),
        "verification_contract": (
            "Exact source hashes, all method scores, all metrics, and the default decision "
            "are deterministically recomputed from the completed run."
        ),
    }
    return manifest, scores


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


def _artifact_documents(
    inputs: ReferenceMomentaInput,
    *,
    created_at: str,
    maximum_exported_components: int,
    artifact_version: str = COMPARISON_VERSION,
) -> tuple[dict[str, object], dict[str, str]]:
    manifest, scores = _comparison_payload(
        inputs,
        created_at=created_at,
        maximum_exported_components=maximum_exported_components,
        artifact_version=artifact_version,
    )
    return manifest, {
        COMPARISON_MANIFEST: _canonical_json(manifest),
        METRICS_CSV: _metrics_csv(manifest),
        SCORES_CSV: _scores_csv(inputs.subject_labels, scores),
        README_NAME: _readme(manifest),
    }


def write_reference_shape_space_comparison(
    run_directory: Path | str,
    destination: Path | str | None = None,
    *,
    maximum_exported_components: int = 10,
    created_at: str | None = None,
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
    target = (
        inputs.run_directory / DEFAULT_COMPARISON_DIRECTORY
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
    manifest, documents = _artifact_documents(
        inputs,
        created_at=timestamp,
        maximum_exported_components=int(maximum_exported_components),
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
    if actual_names != expected_names or any(path.is_dir() for path in root.iterdir()):
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
