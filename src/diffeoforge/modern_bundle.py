"""Immutable, verifiable result bundles for the experimental modern atlas engine."""

from __future__ import annotations

import csv
import json
import math
import re
import shutil
import unicodedata
import uuid
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
from diffeoforge.config import ConfigurationError
from diffeoforge.engine import AtlasOptimizationResult, flow_points, shoot
from diffeoforge.mesh import inspect_vtk, sha256_file, write_vtk_polydata

BUNDLE_VERSION = "0.1"
MANIFEST_NAME = "bundle-manifest.json"
MANIFEST_SIDECAR_NAME = "bundle-manifest.sha256"
SCIENTIFIC_BOUNDARY = (
    "Experimental dense float64 CPU result bundle. It is not evidence of scientific "
    "validation, Deformetrica optimizer equivalence, topology preservation, GPU parity, "
    "or production readiness for 300 specimens. Momenta PCA is one explicitly declared "
    "feature space and is not automatically appropriate for every biological question."
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
    flow_integrator: Literal["euler", "heun", "deformetrica_heun"] = (
        "deformetrica_heun"
    )

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
            raise ValueError(
                "flow_integrator must be 'euler', 'heun', or 'deformetrica_heun'"
            )

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


def _pca_files(root: Path, pca: PCAResult) -> dict[str, str]:
    analysis = root / "analysis"
    summary_path = analysis / "pca-summary.json"
    scores_path = analysis / "pca-scores.csv"
    loadings_path = analysis / "pca-loadings.csv"
    mean_path = analysis / "pca-mean.csv"
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
    return {
        "summary_path": summary_path.relative_to(root).as_posix(),
        "scores_path": scores_path.relative_to(root).as_posix(),
        "loadings_path": loadings_path.relative_to(root).as_posix(),
        "mean_path": mean_path.relative_to(root).as_posix(),
    }


def write_modern_atlas_bundle(
    destination: Path | str,
    result: AtlasOptimizationResult,
    template_triangles: torch.Tensor,
    subject_labels: tuple[str, ...] | list[str],
    model_settings: ModernAtlasModelSettings,
    *,
    pca_components: int | None = None,
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
    _validate_result(result, template_triangles.shape[0])
    labels = _labels(subject_labels, result.momenta.shape[0])
    timestamp = (
        datetime.now(UTC).isoformat(timespec="seconds")
        if created_at is None
        else created_at
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
                    ""
                    if record.accepted_step_size is None
                    else _float(record.accepted_step_size),
                    str(record.line_search_evaluations),
                    *(_float(value) for value in record.residuals),
                ]
            )
        _write_csv_exclusive(history_path, history_rows)

        subjects = []
        for index, (label, momenta) in enumerate(
            zip(labels, result.momenta, strict=True)
        ):
            trajectory = shoot(
                result.control_points,
                momenta,
                model_settings.deformation_kernel_width,
                model_settings.number_of_time_points,
                integrator=model_settings.shooting_integrator,
            )
            path = flow_points(
                result.template_vertices,
                trajectory,
                model_settings.deformation_kernel_width,
                integrator=model_settings.flow_integrator,
            )
            reconstruction_path = write_vtk_polydata(
                temporary
                / "reconstructions"
                / f"subject-{index:04d}-{_slug(label)}.vtk",
                path[-1].tolist(),
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
            n_components=pca_components,
            subject_labels=labels,
        )
        pca_paths = _pca_files(temporary, pca)
        artifact_paths = sorted(
            path for path in temporary.rglob("*") if path.is_file()
        )
        artifacts = [_artifact(temporary, path) for path in artifact_paths]
        final = result.history[-1]
        optimizer_manifest = asdict(result.settings)
        optimizer_manifest["block_order"] = list(result.settings.block_order)
        manifest = {
            "bundle_version": BUNDLE_VERSION,
            "created_at": timestamp.strip(),
            "engine": {
                "id": "diffeoforge_modern_dense",
                "diffeoforge": __version__,
                "pytorch": torch.__version__,
                "numpy": np.__version__,
                "device": "cpu",
                "dtype": "float64",
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
    actual_files = {
        path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()
    }
    if actual_files != expected_files:
        missing = sorted(expected_files - actual_files)
        extra = sorted(actual_files - expected_files)
        raise ModernBundleError(
            f"Modern atlas bundle file inventory differs: missing={missing}, extra={extra}"
        )

    vtk_records = [manifest["template"], *manifest["subjects"]]
    for record in vtk_records:
        vtk_path = _resolve_artifact(
            root,
            record.get("path", record.get("reconstruction_path")),
        )
        try:
            metadata = inspect_vtk(vtk_path)
        except ConfigurationError as error:
            raise ModernBundleError(f"Invalid VTK artifact {vtk_path.name}: {error}") from error
        if metadata.points != manifest["template"]["points"]:
            raise ModernBundleError(f"VTK point count differs from manifest: {vtk_path.name}")
        if metadata.cells != manifest["template"]["triangles"]:
            raise ModernBundleError(f"VTK triangle count differs from manifest: {vtk_path.name}")
    return manifest
