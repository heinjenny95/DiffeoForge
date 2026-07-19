"""Immutable, verifiable result bundles for the experimental modern atlas engine."""

from __future__ import annotations

import csv
import json
import math
import re
import shutil
import unicodedata
import uuid
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from importlib.resources import files
from numbers import Integral, Real
from pathlib import Path
from typing import Literal

import jsonschema
import numpy as np
import torch

from diffeoforge import __version__
from diffeoforge.analysis.pca import PCAResult, momenta_pca
from diffeoforge.analysis.pca_visualization import (
    write_pca_score_pair_svg,
    write_pca_scores_svg,
    write_pca_scree_svg,
)
from diffeoforge.config import ConfigurationError
from diffeoforge.engine import (
    AtlasOptimizationResult,
    PairwiseEvaluationPlan,
    flow_points,
    shoot,
)
from diffeoforge.mesh import inspect_vtk, sha256_file, write_vtk_polydata
from diffeoforge.mesh_quality import MeshQualitySettings
from diffeoforge.mesh_quality_report import (
    build_mesh_quality_report,
    mesh_quality_csv_rows,
)

BUNDLE_VERSION = "0.1"
MANIFEST_NAME = "bundle-manifest.json"
MANIFEST_SIDECAR_NAME = "bundle-manifest.sha256"
SCIENTIFIC_BOUNDARY = (
    "Experimental exact pairwise float64 CPU result bundle. It is not evidence of scientific "
    "validation, Deformetrica optimizer equivalence, topology preservation, GPU parity, "
    "or production readiness for 300 specimens. Momenta PCA is one explicitly declared "
    "feature space and is not automatically appropriate for every biological question."
)
PCA_DEFORMATION_EQUATION = (
    "mean_momenta +/- standard_deviations * sqrt(explained_variance) * component_loading"
)
PCA_DEFORMATION_BOUNDARY = (
    "PCA deformations visualize axes in the declared training-momenta feature space. "
    "Their signs are conventional; endpoints are not observed specimens, confidence "
    "intervals, biological effects, or evidence of group separation."
)


class ModernBundleError(RuntimeError):
    """Raised when a modern result bundle cannot be created or verified safely."""


@dataclass(frozen=True)
class ModernAtlasModelSettings:
    """Objective and flow settings required to interpret and reconstruct an atlas."""

    deformation_kernel_width: float
    attachment_kernel_width: float
    noise_variance: float
    number_of_time_points: int
    attachment_type: Literal["current", "varifold"] = "current"
    shooting_integrator: Literal["euler", "rk2"] = "rk2"
    flow_integrator: Literal["euler", "heun", "deformetrica_heun"] = "deformetrica_heun"

    def __post_init__(self) -> None:
        for name in (
            "deformation_kernel_width",
            "attachment_kernel_width",
            "noise_variance",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, Real):
                raise TypeError(f"{name} must be a real scalar")
            if not math.isfinite(float(value)) or float(value) <= 0:
                raise ValueError(f"{name} must be finite and greater than zero")
        if isinstance(self.number_of_time_points, bool) or not isinstance(
            self.number_of_time_points, Integral
        ):
            raise TypeError("number_of_time_points must be an integer")
        if self.number_of_time_points < 2:
            raise ValueError("number_of_time_points must be at least 2")
        if self.attachment_type not in {"current", "varifold"}:
            raise ValueError("attachment_type must be 'current' or 'varifold'")
        if self.shooting_integrator not in {"euler", "rk2"}:
            raise ValueError("shooting_integrator must be 'euler' or 'rk2'")
        if self.flow_integrator not in {"euler", "heun", "deformetrica_heun"}:
            raise ValueError("flow_integrator must be 'euler', 'heun', or 'deformetrica_heun'")

    def as_manifest(self) -> dict[str, object]:
        """Return normalized JSON-compatible settings."""

        return {
            "deformation_kernel_width": float(self.deformation_kernel_width),
            "attachment_kernel_width": float(self.attachment_kernel_width),
            "noise_variance": float(self.noise_variance),
            "number_of_time_points": int(self.number_of_time_points),
            "attachment_type": self.attachment_type,
            "shooting_integrator": self.shooting_integrator,
            "flow_integrator": self.flow_integrator,
        }


def _schema() -> dict:
    resource = files("diffeoforge.schema").joinpath("modern-atlas-bundle-v0.1.json")
    return json.loads(resource.read_text(encoding="utf-8"))


def _validate_schema(manifest: dict) -> None:
    try:
        jsonschema.Draft202012Validator(_schema()).validate(manifest)
    except jsonschema.ValidationError as error:
        location = ".".join(str(part) for part in error.absolute_path) or "document"
        raise ModernBundleError(
            f"Modern bundle manifest schema validation failed at {location}: {error.message}"
        ) from error


def _write_json_exclusive(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, indent=2, ensure_ascii=False, sort_keys=True, allow_nan=False)
        handle.write("\n")


def _write_csv_exclusive(path: Path, rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerows(rows)


def _float(value: float) -> str:
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ValueError("bundle values must be finite")
    return format(0.0 if normalized == 0.0 else normalized, ".17g")


def _positive_real(name: str, value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError(f"{name} must be a real scalar")
    normalized = float(value)
    if not math.isfinite(normalized) or normalized <= 0:
        raise ValueError(f"{name} must be finite and greater than zero")
    return normalized


def _optional_positive_integer(name: str, value: int | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, Integral):
        raise TypeError(f"{name} must be an integer or None")
    normalized = int(value)
    if normalized < 1:
        raise ValueError(f"{name} must be at least 1")
    return normalized


def _csv_label(value: str) -> str:
    return f"'{value}" if value[0] in "=+-@\t\r" else value


def _labels(values: tuple[str, ...] | list[str], count: int) -> tuple[str, ...]:
    if not isinstance(values, (tuple, list)):
        raise TypeError("subject_labels must be a tuple or list of strings")
    labels = tuple(values)
    if len(labels) != count:
        raise ValueError(f"subject_labels must contain exactly {count} labels")
    if any(not isinstance(label, str) or not label.strip() for label in labels):
        raise ValueError("subject_labels must contain non-empty strings")
    if len(set(labels)) != len(labels):
        raise ValueError("subject_labels must be unique")
    return labels


def _slug(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    normalized = re.sub(r"[^a-z0-9]+", "-", ascii_value.lower()).strip("-")
    return normalized or "specimen"


def _validate_result(result: AtlasOptimizationResult, triangle_count: int) -> None:
    if not isinstance(result, AtlasOptimizationResult):
        raise TypeError("result must be an AtlasOptimizationResult")
    if not result.history:
        raise ValueError("result history must contain at least the initial state")
    tensors = {
        "template_vertices": result.template_vertices,
        "control_points": result.control_points,
        "momenta": result.momenta,
    }
    for name, tensor in tensors.items():
        if not isinstance(tensor, torch.Tensor):
            raise TypeError(f"result.{name} must be a torch.Tensor")
        if tensor.dtype != torch.float64:
            raise TypeError(f"result.{name} must use torch.float64")
        if tensor.device.type != "cpu":
            raise ValueError(f"result.{name} must be on the CPU for bundle v0.1")
        if tensor.requires_grad:
            raise ValueError(f"result.{name} must be detached before bundle creation")
        if not bool(torch.isfinite(tensor).all()):
            raise ValueError(f"result.{name} must contain only finite values")
    if result.template_vertices.ndim != 2 or result.template_vertices.shape[1] != 3:
        raise ValueError("result.template_vertices must have shape (vertices, 3)")
    if result.control_points.ndim != 2 or result.control_points.shape[1] != 3:
        raise ValueError("result.control_points must have shape (control_points, 3)")
    if result.momenta.ndim != 3 or result.momenta.shape[2] != 3:
        raise ValueError("result.momenta must have shape (subjects, control_points, 3)")
    if result.momenta.shape[0] < 2:
        raise ValueError("result.momenta must contain at least two subjects")
    if result.momenta.shape[1:] != result.control_points.shape:
        raise ValueError("result momenta and control-point shapes are incompatible")
    if triangle_count < 1:
        raise ValueError("template_triangles must contain at least one face")
    if len(result.history[-1].residuals) != result.momenta.shape[0]:
        raise ValueError("final optimizer residuals must match the subject count")


def _artifact(root: Path, path: Path) -> dict[str, object]:
    return {
        "path": path.relative_to(root).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def _pca_files(root: Path, pca: PCAResult) -> dict[str, object]:
    analysis = root / "analysis"
    summary_path = analysis / "pca-summary.json"
    scores_path = analysis / "pca-scores.csv"
    loadings_path = analysis / "pca-loadings.csv"
    mean_path = analysis / "pca-mean.csv"
    scree_path = analysis / "pca-scree.svg"
    scores_plot_path = analysis / "pca-scores.svg"
    pc2_pc3_plot_path = analysis / "pca-scores-pc2-pc3.svg"
    component_labels = [f"PC{index + 1}" for index in range(pca.number_of_components)]
    _write_json_exclusive(
        summary_path,
        {
            "feature_space": pca.feature_space,
            "sample_labels": list(pca.sample_labels),
            "feature_labels": list(pca.feature_labels),
            "number_of_components": pca.number_of_components,
            "numerical_rank": pca.numerical_rank,
            "total_variance": pca.total_variance,
            "singular_values": pca.singular_values.tolist(),
            "explained_variance": pca.explained_variance.tolist(),
            "explained_variance_ratio": pca.explained_variance_ratio.tolist(),
            "tied_component_groups": [list(group) for group in pca.tied_component_groups],
            "zero_variance_components": list(pca.zero_variance_components),
            "sign_convention": pca.sign_convention,
        },
    )
    _write_csv_exclusive(
        scores_path,
        [["subject_label", *component_labels]]
        + [
            [_csv_label(label), *(_float(value) for value in scores)]
            for label, scores in zip(pca.sample_labels, pca.scores, strict=True)
        ],
    )
    _write_csv_exclusive(
        loadings_path,
        [["feature_label", *component_labels]]
        + [
            [_csv_label(label), *(_float(value) for value in pca.components[:, index])]
            for index, label in enumerate(pca.feature_labels)
        ],
    )
    _write_csv_exclusive(
        mean_path,
        [["feature_label", "mean"]]
        + [
            [_csv_label(label), _float(value)]
            for label, value in zip(pca.feature_labels, pca.mean, strict=True)
        ],
    )
    write_pca_scree_svg(scree_path, pca)
    write_pca_scores_svg(scores_plot_path, pca)
    if pca.number_of_components >= 3:
        write_pca_score_pair_svg(
            pc2_pc3_plot_path,
            pca,
            x_component=2,
            y_component=3,
        )
        pc2_pc3_path: str | None = pc2_pc3_plot_path.relative_to(root).as_posix()
        pc2_pc3_axes: list[str] | None = ["PC2", "PC3"]
        pc2_pc3_unavailable_reason: str | None = None
    else:
        pc2_pc3_path = None
        pc2_pc3_axes = None
        pc2_pc3_unavailable_reason = (
            "PC3 is not mathematically available because the retained PCA has "
            f"{pca.number_of_components} component"
            f"{'s' if pca.number_of_components != 1 else ''}."
        )
    return {
        "summary_path": summary_path.relative_to(root).as_posix(),
        "scores_path": scores_path.relative_to(root).as_posix(),
        "loadings_path": loadings_path.relative_to(root).as_posix(),
        "mean_path": mean_path.relative_to(root).as_posix(),
        "plots": {
            "scree_path": scree_path.relative_to(root).as_posix(),
            "scores_path": scores_plot_path.relative_to(root).as_posix(),
            "score_axes": ["PC1"] if pca.number_of_components == 1 else ["PC1", "PC2"],
            "scores_pc2_pc3_path": pc2_pc3_path,
            "scores_pc2_pc3_axes": pc2_pc3_axes,
            "scores_pc2_pc3_unavailable_reason": pc2_pc3_unavailable_reason,
        },
    }


def _deformed_template_endpoint(
    result: AtlasOptimizationResult,
    momenta: torch.Tensor,
    model_settings: ModernAtlasModelSettings,
    pairwise_evaluation: PairwiseEvaluationPlan,
) -> torch.Tensor:
    gaussian_tile_plan = pairwise_evaluation.gaussian_tile_plan
    trajectory = shoot(
        result.control_points,
        momenta,
        model_settings.deformation_kernel_width,
        model_settings.number_of_time_points,
        integrator=model_settings.shooting_integrator,
        gaussian_tile_plan=gaussian_tile_plan,
    )
    return flow_points(
        result.template_vertices,
        trajectory,
        model_settings.deformation_kernel_width,
        integrator=model_settings.flow_integrator,
        gaussian_tile_plan=gaussian_tile_plan,
    )[-1]


def _pca_deformation_files(
    root: Path,
    pca: PCAResult,
    result: AtlasOptimizationResult,
    triangle_rows: list[list[int]],
    model_settings: ModernAtlasModelSettings,
    pairwise_evaluation: PairwiseEvaluationPlan,
    *,
    standard_deviations: float,
    requested_components: int | None,
) -> dict[str, object]:
    resolved_components = (
        pca.number_of_components if requested_components is None else requested_components
    )
    if resolved_components > pca.number_of_components:
        raise ValueError(
            "pca_deformation_components cannot exceed the retained PCA component count "
            f"({pca.number_of_components})"
        )
    feature_shape = tuple(result.control_points.shape)
    mean_momenta = torch.from_numpy(
        np.array(pca.mean.reshape(feature_shape), dtype=np.float64, copy=True)
    )
    deformation_directory = root / "analysis" / "pca-deformations"
    mean_path = write_vtk_polydata(
        deformation_directory / "mean-momenta.vtk",
        _deformed_template_endpoint(
            result,
            mean_momenta,
            model_settings,
            pairwise_evaluation,
        ).tolist(),
        triangle_rows,
        title="DiffeoForge PCA mean-momenta reconstruction",
    )
    zero_components = set(pca.zero_variance_components)
    skipped: list[int] = []
    components: list[dict[str, object]] = []
    for index in range(resolved_components):
        component_number = index + 1
        if index in zero_components:
            skipped.append(component_number)
            continue
        component_standard_deviation = math.sqrt(float(pca.explained_variance[index]))
        displacement = standard_deviations * component_standard_deviation * pca.components[index]
        minus_momenta = torch.from_numpy(
            np.array((pca.mean - displacement).reshape(feature_shape), copy=True)
        )
        plus_momenta = torch.from_numpy(
            np.array((pca.mean + displacement).reshape(feature_shape), copy=True)
        )
        minus_path = write_vtk_polydata(
            deformation_directory / f"pc-{component_number:04d}-minus.vtk",
            _deformed_template_endpoint(
                result,
                minus_momenta,
                model_settings,
                pairwise_evaluation,
            ).tolist(),
            triangle_rows,
            title=f"DiffeoForge PCA PC{component_number} minus",
        )
        plus_path = write_vtk_polydata(
            deformation_directory / f"pc-{component_number:04d}-plus.vtk",
            _deformed_template_endpoint(
                result,
                plus_momenta,
                model_settings,
                pairwise_evaluation,
            ).tolist(),
            triangle_rows,
            title=f"DiffeoForge PCA PC{component_number} plus",
        )
        components.append(
            {
                "component": component_number,
                "label": f"PC{component_number}",
                "explained_variance": float(pca.explained_variance[index]),
                "explained_variance_ratio": float(pca.explained_variance_ratio[index]),
                "momenta_standard_deviation": component_standard_deviation,
                "minus_path": minus_path.relative_to(root).as_posix(),
                "plus_path": plus_path.relative_to(root).as_posix(),
            }
        )
    definition = {
        "feature_space": pca.feature_space,
        "feature_order": "control point index outer; Cartesian x, y, z inner",
        "sign_convention": pca.sign_convention,
        "equation": PCA_DEFORMATION_EQUATION,
        "standard_deviations": standard_deviations,
        "requested_components": resolved_components,
        "mean_path": mean_path.relative_to(root).as_posix(),
        "components": components,
        "skipped_zero_variance_components": skipped,
        "interpretation_boundary": PCA_DEFORMATION_BOUNDARY,
    }
    definition_path = root / "analysis" / "pca-deformations.json"
    _write_json_exclusive(definition_path, definition)
    return {
        "definition_path": definition_path.relative_to(root).as_posix(),
        **definition,
    }


def write_modern_atlas_bundle(
    destination: Path | str,
    result: AtlasOptimizationResult,
    template_triangles: torch.Tensor,
    subject_labels: tuple[str, ...] | list[str],
    model_settings: ModernAtlasModelSettings,
    *,
    pairwise_evaluation: PairwiseEvaluationPlan | None = None,
    pca_components: int | None = None,
    pca_deformation_standard_deviations: float = 2.0,
    pca_deformation_components: int | None = None,
    quality_settings: MeshQualitySettings | None = None,
    created_at: str | None = None,
) -> Path:
    """Atomically create a new immutable modern-atlas result bundle."""

    if not isinstance(template_triangles, torch.Tensor):
        raise TypeError("template_triangles must be a torch.Tensor")
    if template_triangles.dtype != torch.int64:
        raise TypeError("template_triangles must use torch.int64")
    if template_triangles.device.type != "cpu":
        raise ValueError("template_triangles must be on the CPU for bundle v0.1")
    if template_triangles.ndim != 2 or template_triangles.shape[1] != 3:
        raise ValueError("template_triangles must have shape (triangles, 3)")
    if not isinstance(model_settings, ModernAtlasModelSettings):
        raise TypeError("model_settings must be ModernAtlasModelSettings")
    resolved_pairwise_evaluation = (
        PairwiseEvaluationPlan() if pairwise_evaluation is None else pairwise_evaluation
    )
    if not isinstance(resolved_pairwise_evaluation, PairwiseEvaluationPlan):
        raise TypeError("pairwise_evaluation must be PairwiseEvaluationPlan or None")
    resolved_quality_settings = (
        MeshQualitySettings() if quality_settings is None else quality_settings
    )
    if not isinstance(resolved_quality_settings, MeshQualitySettings):
        raise TypeError("quality_settings must be MeshQualitySettings or None")
    normalized_pca_components = _optional_positive_integer("pca_components", pca_components)
    deformation_standard_deviations = _positive_real(
        "pca_deformation_standard_deviations",
        pca_deformation_standard_deviations,
    )
    deformation_components = _optional_positive_integer(
        "pca_deformation_components", pca_deformation_components
    )
    _validate_result(result, template_triangles.shape[0])
    labels = _labels(subject_labels, result.momenta.shape[0])
    timestamp = (
        datetime.now(UTC).isoformat(timespec="seconds") if created_at is None else created_at
    )
    if not isinstance(timestamp, str) or not timestamp.strip():
        raise ValueError("created_at must be a non-empty string")
    try:
        parsed_timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("created_at must be an ISO-8601 timestamp") from error
    if parsed_timestamp.tzinfo is None:
        raise ValueError("created_at must include a timezone offset")
    destination_path = Path(destination).expanduser().resolve()
    if destination_path.exists():
        raise FileExistsError(f"Modern atlas bundle destination already exists: {destination_path}")
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination_path.parent / f".{destination_path.name}.tmp-{uuid.uuid4().hex}"
    temporary.mkdir()
    try:
        triangle_rows = template_triangles.tolist()
        template_path = write_vtk_polydata(
            temporary / "atlas" / "estimated-template.vtk",
            result.template_vertices.tolist(),
            triangle_rows,
            title="DiffeoForge estimated template",
        )
        control_points_path = temporary / "parameters" / "control-points.csv"
        _write_csv_exclusive(
            control_points_path,
            [["control_point", "x", "y", "z"]]
            + [
                [str(index), *(_float(value) for value in point)]
                for index, point in enumerate(result.control_points.tolist())
            ],
        )
        momenta_path = temporary / "parameters" / "momenta.csv"
        momenta_rows = [["subject_label", "control_point", "x", "y", "z"]]
        for label, subject_momenta in zip(labels, result.momenta.tolist(), strict=True):
            momenta_rows.extend(
                [_csv_label(label), str(index), *(_float(value) for value in point)]
                for index, point in enumerate(subject_momenta)
            )
        _write_csv_exclusive(momenta_path, momenta_rows)

        history_path = temporary / "optimization" / "history.csv"
        history_rows = [
            [
                "cycle",
                "block",
                "status",
                "objective",
                "attachment",
                "regularity",
                "gradient_norm",
                "accepted_step_size",
                "line_search_evaluations",
                *(f"residual_{index:04d}" for index in range(len(labels))),
            ]
        ]
        for record in result.history:
            history_rows.append(
                [
                    str(record.cycle),
                    record.block or "",
                    record.status,
                    _float(record.objective),
                    _float(record.attachment),
                    _float(record.regularity),
                    "" if record.gradient_norm is None else _float(record.gradient_norm),
                    "" if record.accepted_step_size is None else _float(record.accepted_step_size),
                    str(record.line_search_evaluations),
                    *(_float(value) for value in record.residuals),
                ]
            )
        _write_csv_exclusive(history_path, history_rows)

        subjects = []
        for index, (label, momenta) in enumerate(zip(labels, result.momenta, strict=True)):
            reconstruction_path = write_vtk_polydata(
                temporary / "reconstructions" / f"subject-{index:04d}-{_slug(label)}.vtk",
                _deformed_template_endpoint(
                    result,
                    momenta,
                    model_settings,
                    resolved_pairwise_evaluation,
                ).tolist(),
                triangle_rows,
                title=f"DiffeoForge reconstruction {index:04d}",
            )
            subjects.append(
                {
                    "index": index,
                    "label": label,
                    "reconstruction_path": reconstruction_path.relative_to(temporary).as_posix(),
                    "residual": result.history[-1].residuals[index],
                }
            )

        pca = momenta_pca(
            np.array(result.momenta.detach().numpy(), dtype=np.float64, copy=True),
            n_components=normalized_pca_components,
            subject_labels=labels,
        )
        pca_paths = _pca_files(temporary, pca)
        pca_deformations = _pca_deformation_files(
            temporary,
            pca,
            result,
            triangle_rows,
            model_settings,
            resolved_pairwise_evaluation,
            standard_deviations=deformation_standard_deviations,
            requested_components=deformation_components,
        )
        quality_descriptors = [
            {
                "label": "estimated template",
                "role": "template",
                "stage": "estimated",
                "path": str(template_path),
            },
            *[
                {
                    "label": record["label"],
                    "role": "subject",
                    "stage": "reconstruction",
                    "path": str(temporary / record["reconstruction_path"]),
                }
                for record in subjects
            ],
            {
                "label": "mean momenta",
                "role": "pca",
                "stage": "mean",
                "path": str(temporary / pca_deformations["mean_path"]),
            },
            *[
                {
                    "label": f"{component['label']} -",
                    "role": "pca",
                    "stage": "minus endpoint",
                    "path": str(temporary / component["minus_path"]),
                }
                for component in pca_deformations["components"]
            ],
            *[
                {
                    "label": f"{component['label']} +",
                    "role": "pca",
                    "stage": "plus endpoint",
                    "path": str(temporary / component["plus_path"]),
                }
                for component in pca_deformations["components"]
            ],
        ]
        quality_report = build_mesh_quality_report(
            temporary,
            quality_descriptors,
            resolved_quality_settings,
            reference_path=template_path,
        )
        quality_report_path = temporary / "quality" / "mesh-quality.json"
        quality_csv_path = temporary / "quality" / "mesh-quality.csv"
        _write_json_exclusive(quality_report_path, quality_report)
        _write_csv_exclusive(quality_csv_path, mesh_quality_csv_rows(quality_report))
        artifact_paths = sorted(path for path in temporary.rglob("*") if path.is_file())
        artifacts = [_artifact(temporary, path) for path in artifact_paths]
        final = result.history[-1]
        optimizer_manifest = asdict(result.settings)
        optimizer_manifest["block_order"] = list(result.settings.block_order)
        manifest = {
            "bundle_version": BUNDLE_VERSION,
            "created_at": timestamp.strip(),
            "engine": {
                "id": resolved_pairwise_evaluation.engine_id,
                "diffeoforge": __version__,
                "pytorch": torch.__version__,
                "numpy": np.__version__,
                "device": "cpu",
                "dtype": "float64",
                "pairwise_evaluation": resolved_pairwise_evaluation.as_manifest(),
            },
            "model": model_settings.as_manifest(),
            "optimizer": {
                "settings": optimizer_manifest,
                "termination_reason": result.termination_reason,
                "converged": result.converged,
                "failed_block": result.failed_block,
                "cycles_completed": result.cycles_completed,
                "total_line_search_evaluations": result.total_line_search_evaluations,
                "history_path": history_path.relative_to(temporary).as_posix(),
                "final_objective": final.objective,
                "final_attachment": final.attachment,
                "final_regularity": final.regularity,
            },
            "template": {
                "path": template_path.relative_to(temporary).as_posix(),
                "points": result.template_vertices.shape[0],
                "triangles": template_triangles.shape[0],
            },
            "parameters": {
                "control_points_path": control_points_path.relative_to(temporary).as_posix(),
                "momenta_path": momenta_path.relative_to(temporary).as_posix(),
                "control_points": result.control_points.shape[0],
                "subjects": result.momenta.shape[0],
                "dimensions": 3,
            },
            "subjects": subjects,
            "pca": {
                "feature_space": pca.feature_space,
                "components": pca.number_of_components,
                "numerical_rank": pca.numerical_rank,
                "total_variance": pca.total_variance,
                **pca_paths,
                "deformations": pca_deformations,
            },
            "quality": {
                "report_path": quality_report_path.relative_to(temporary).as_posix(),
                "csv_path": quality_csv_path.relative_to(temporary).as_posix(),
                "settings": resolved_quality_settings.as_manifest(),
                "reference_path": template_path.relative_to(temporary).as_posix(),
                "assessed_meshes": len(quality_report["meshes"]),
                "scientific_boundary": quality_report["scientific_boundary"],
            },
            "artifacts": artifacts,
            "scientific_boundary": SCIENTIFIC_BOUNDARY,
            "immutability_contract": {
                "creation": "atomic rename into a previously nonexistent destination",
                "manifest": "SHA-256 sidecar",
                "artifacts": "all listed files require matching byte size and SHA-256",
                "extra_files": "verification failure",
                "signature": "not cryptographically signed",
            },
        }
        _validate_schema(manifest)
        manifest_path = temporary / MANIFEST_NAME
        _write_json_exclusive(manifest_path, manifest)
        sidecar_path = temporary / MANIFEST_SIDECAR_NAME
        with sidecar_path.open("x", encoding="ascii", newline="\n") as handle:
            handle.write(f"{sha256_file(manifest_path)}  {MANIFEST_NAME}\n")
        verify_modern_atlas_bundle(temporary)
        if destination_path.exists():
            raise FileExistsError(
                f"Modern atlas bundle destination appeared during creation: {destination_path}"
            )
        temporary.rename(destination_path)
    except Exception:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise
    return destination_path


def _resolve_artifact(root: Path, value: object) -> Path:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ModernBundleError("Bundle artifact paths must be non-empty POSIX-style strings")
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise ModernBundleError(f"Bundle artifact path escapes the bundle: {value!r}")
    resolved = (root / relative).resolve()
    if resolved != root and root not in resolved.parents:
        raise ModernBundleError(f"Bundle artifact path escapes the bundle: {value!r}")
    return resolved


def _verify_static_svg(path: Path) -> ET.Element:
    try:
        document = ET.parse(path)
    except (OSError, ET.ParseError) as error:
        raise ModernBundleError(f"Invalid SVG artifact {path.name}: {error}") from error
    root = document.getroot()
    if root.tag != "{http://www.w3.org/2000/svg}svg":
        raise ModernBundleError(f"SVG artifact has an invalid root element: {path.name}")
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1].lower() == "script":
            raise ModernBundleError(f"SVG artifact contains a script: {path.name}")
        if any(attribute.rsplit("}", 1)[-1].lower() == "href" for attribute in element.attrib):
            raise ModernBundleError(f"SVG artifact contains an external reference: {path.name}")
    return root


def _verify_score_svg(
    path: Path,
    *,
    axes: list[str],
    subject_labels: list[str],
) -> None:
    root = _verify_static_svg(path)
    expected_title = (
        "PCA subject scores: PC1 strip"
        if axes == ["PC1"]
        else f"PCA subject scores: {axes[0]} vs {axes[1]}"
    )
    title = root.find("{http://www.w3.org/2000/svg}title")
    if title is None or title.text != expected_title:
        raise ModernBundleError(f"PCA score SVG axes differ from the manifest: {path.name}")
    circles = [
        element for element in root.iter() if element.tag == "{http://www.w3.org/2000/svg}circle"
    ]
    observed_labels = [element.attrib.get("data-subject-label") for element in circles]
    if observed_labels != subject_labels:
        raise ModernBundleError(
            f"PCA score SVG subject order differs from the manifest: {path.name}"
        )
    text_values = [
        "".join(element.itertext())
        for element in root.iter()
        if element.tag == "{http://www.w3.org/2000/svg}text"
    ]
    if not all(any(value.startswith(f"{axis} (") for value in text_values) for axis in axes):
        raise ModernBundleError(f"PCA score SVG variance-labelled axes are incomplete: {path.name}")


def verify_modern_atlas_bundle(directory: Path | str) -> dict:
    """Verify schema, sidecar, exact file inventory, hashes, sizes, and VTK geometry."""

    root = Path(directory).expanduser().resolve()
    if not root.is_dir():
        raise ModernBundleError(f"Modern atlas bundle directory does not exist: {root}")
    manifest_path = root / MANIFEST_NAME
    sidecar_path = root / MANIFEST_SIDECAR_NAME
    if not manifest_path.is_file() or not sidecar_path.is_file():
        raise ModernBundleError("Modern atlas bundle manifest or SHA-256 sidecar is missing")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ModernBundleError(
            f"Modern atlas bundle manifest is not valid JSON: {error}"
        ) from error
    if not isinstance(manifest, dict):
        raise ModernBundleError("Modern atlas bundle manifest must be a JSON object")
    _validate_schema(manifest)
    sidecar_parts = sidecar_path.read_text(encoding="ascii").strip().split()
    if len(sidecar_parts) != 2 or sidecar_parts[1] != MANIFEST_NAME:
        raise ModernBundleError("Modern atlas bundle manifest sidecar is malformed")
    if sidecar_parts[0] != sha256_file(manifest_path):
        raise ModernBundleError("Modern atlas bundle manifest SHA-256 does not match")

    expected_files = {MANIFEST_NAME, MANIFEST_SIDECAR_NAME}
    seen_paths: set[str] = set()
    for record in manifest["artifacts"]:
        relative_path = record["path"]
        if relative_path in seen_paths:
            raise ModernBundleError(f"Duplicate artifact path in manifest: {relative_path}")
        seen_paths.add(relative_path)
        expected_files.add(relative_path)
        artifact_path = _resolve_artifact(root, relative_path)
        if not artifact_path.is_file():
            raise ModernBundleError(f"Modern atlas bundle artifact is missing: {relative_path}")
        if artifact_path.stat().st_size != record["bytes"]:
            raise ModernBundleError(f"Modern atlas bundle artifact size differs: {relative_path}")
        if sha256_file(artifact_path) != record["sha256"]:
            raise ModernBundleError(
                f"Modern atlas bundle artifact SHA-256 differs: {relative_path}"
            )
    actual_files = {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}
    if actual_files != expected_files:
        missing = sorted(expected_files - actual_files)
        extra = sorted(actual_files - expected_files)
        raise ModernBundleError(
            f"Modern atlas bundle file inventory differs: missing={missing}, extra={extra}"
        )

    deformation_record = manifest["pca"]["deformations"]
    definition_path = _resolve_artifact(root, deformation_record["definition_path"])
    try:
        definition = json.loads(definition_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ModernBundleError(f"Invalid PCA deformation definition: {error}") from error
    expected_definition = {
        key: value for key, value in deformation_record.items() if key != "definition_path"
    }
    if definition != expected_definition:
        raise ModernBundleError("PCA deformation definition differs from the bundle manifest")

    vtk_paths = [
        manifest["template"]["path"],
        *(record["reconstruction_path"] for record in manifest["subjects"]),
        deformation_record["mean_path"],
        *(
            path
            for component in deformation_record["components"]
            for path in (component["minus_path"], component["plus_path"])
        ),
    ]
    for relative_path in vtk_paths:
        vtk_path = _resolve_artifact(root, relative_path)
        try:
            metadata = inspect_vtk(vtk_path)
        except ConfigurationError as error:
            raise ModernBundleError(f"Invalid VTK artifact {vtk_path.name}: {error}") from error
        if metadata.points != manifest["template"]["points"]:
            raise ModernBundleError(f"VTK point count differs from manifest: {vtk_path.name}")
        if metadata.cells != manifest["template"]["triangles"]:
            raise ModernBundleError(f"VTK triangle count differs from manifest: {vtk_path.name}")
    quality_record = manifest["quality"]
    quality_path = _resolve_artifact(root, quality_record["report_path"])
    try:
        quality_report = json.loads(quality_path.read_text(encoding="utf-8"))
        quality_settings = MeshQualitySettings.from_mapping(quality_record["settings"])
        quality_descriptors = [
            {
                "label": "estimated template",
                "role": "template",
                "stage": "estimated",
                "path": str(_resolve_artifact(root, manifest["template"]["path"])),
            },
            *[
                {
                    "label": record["label"],
                    "role": "subject",
                    "stage": "reconstruction",
                    "path": str(_resolve_artifact(root, record["reconstruction_path"])),
                }
                for record in manifest["subjects"]
            ],
            {
                "label": "mean momenta",
                "role": "pca",
                "stage": "mean",
                "path": str(_resolve_artifact(root, deformation_record["mean_path"])),
            },
            *[
                {
                    "label": f"{component['label']} -",
                    "role": "pca",
                    "stage": "minus endpoint",
                    "path": str(_resolve_artifact(root, component["minus_path"])),
                }
                for component in deformation_record["components"]
            ],
            *[
                {
                    "label": f"{component['label']} +",
                    "role": "pca",
                    "stage": "plus endpoint",
                    "path": str(_resolve_artifact(root, component["plus_path"])),
                }
                for component in deformation_record["components"]
            ],
        ]
        reference_path = _resolve_artifact(root, manifest["template"]["path"])
        expected_quality = build_mesh_quality_report(
            root,
            quality_descriptors,
            quality_settings,
            reference_path=reference_path,
        )
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        raise ModernBundleError(f"Invalid mesh-quality evidence: {error}") from error
    if quality_report != expected_quality:
        raise ModernBundleError("Mesh-quality JSON differs from recomputed geometry evidence")
    if quality_record["assessed_meshes"] != len(quality_report["meshes"]):
        raise ModernBundleError("Mesh-quality assessed mesh count differs")
    if quality_record["reference_path"] != quality_report["reference_path"]:
        raise ModernBundleError("Mesh-quality reference path differs")
    if quality_record["scientific_boundary"] != quality_report["scientific_boundary"]:
        raise ModernBundleError("Mesh-quality scientific boundary differs")
    quality_csv_path = _resolve_artifact(root, quality_record["csv_path"])
    try:
        with quality_csv_path.open(encoding="utf-8", newline="") as handle:
            quality_rows = list(csv.reader(handle))
    except (OSError, UnicodeError, csv.Error) as error:
        raise ModernBundleError(f"Invalid mesh-quality CSV: {error}") from error
    if quality_rows != mesh_quality_csv_rows(expected_quality):
        raise ModernBundleError("Mesh-quality CSV differs from recomputed geometry evidence")
    plots = manifest["pca"]["plots"]
    subject_labels = [record["label"] for record in manifest["subjects"]]
    _verify_static_svg(_resolve_artifact(root, plots["scree_path"]))
    _verify_score_svg(
        _resolve_artifact(root, plots["scores_path"]),
        axes=plots["score_axes"],
        subject_labels=subject_labels,
    )
    if "scores_pc2_pc3_path" in plots:
        secondary_path = plots["scores_pc2_pc3_path"]
        secondary_axes = plots.get("scores_pc2_pc3_axes")
        unavailable_reason = plots.get("scores_pc2_pc3_unavailable_reason")
        if secondary_path is None:
            if secondary_axes is not None or not isinstance(unavailable_reason, str):
                raise ModernBundleError("Unavailable PC2-versus-PC3 plot metadata is inconsistent")
        else:
            if secondary_axes != ["PC2", "PC3"] or unavailable_reason is not None:
                raise ModernBundleError("PC2-versus-PC3 plot metadata is inconsistent")
            _verify_score_svg(
                _resolve_artifact(root, secondary_path),
                axes=secondary_axes,
                subject_labels=subject_labels,
            )
    return manifest
