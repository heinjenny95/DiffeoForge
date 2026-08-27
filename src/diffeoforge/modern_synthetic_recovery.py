"""Prospective known-correspondence recovery studies for the Modern Engine."""

from __future__ import annotations

import html
import json
import math
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from diffeoforge.atomic_io import write_text_safely
from diffeoforge.config import ConfigurationError
from diffeoforge.engine.execution import ENGINE_IMPLEMENTATION_VERSION
from diffeoforge.mesh import read_vtk_polydata, sha256_file
from diffeoforge.modern_bundle import (
    MANIFEST_NAME as BUNDLE_MANIFEST_NAME,
)
from diffeoforge.modern_bundle import (
    verify_modern_atlas_bundle,
)
from diffeoforge.modern_workflow import (
    CONFIG_MARKER,
    initialize_modern_workflow,
    validate_modern_workflow_config,
    verify_modern_workflow,
)
from diffeoforge.reference_validation_synthetic import (
    SYNTHETIC_MANIFEST,
    verify_synthetic_validation_benchmark,
)

DESIGN_VERSION = "0.1"
ASSESSMENT_VERSION = "0.1"
DESIGN_NAME = "modern-synthetic-recovery-design.json"
DESIGN_SIDECAR_NAME = "modern-synthetic-recovery-design.sha256"
ASSESSMENT_NAME = "modern-synthetic-recovery-assessment.json"
ASSESSMENT_SIDECAR_NAME = "modern-synthetic-recovery-assessment.sha256"
ASSESSMENT_HTML_NAME = "modern-synthetic-recovery-assessment.html"
ARM_IDS = ("euclidean", "sobolev")
SCIENTIFIC_BOUNDARY = (
    "This known-correspondence analytic benchmark tests one small, smooth, topology-preserving "
    "synthetic cohort. It is an engineering recovery and template-gradient sensitivity test; "
    "it cannot establish biological validity, performance on arbitrary anatomy or artifacts, "
    "or superiority of one template-gradient mode."
)


class ModernSyntheticRecoveryError(RuntimeError):
    """Raised when a synthetic recovery design or assessment is invalid."""


def _json_bytes(value: dict[str, Any]) -> bytes:
    return (
        json.dumps(
            value,
            sort_keys=True,
            indent=2,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ModernSyntheticRecoveryError(f"{label} is unreadable: {path}") from error
    if not isinstance(value, dict):
        raise ModernSyntheticRecoveryError(f"{label} must be a JSON object")
    return value


def _write_sidecar(path: Path, payload_name: str, payload_path: Path) -> None:
    write_text_safely(
        path,
        f"{sha256_file(payload_path)}  {payload_name}\n",
        overwrite=False,
    )


def _verify_sidecar(root: Path, payload_name: str, sidecar_name: str) -> None:
    expected = f"{sha256_file(root / payload_name)}  {payload_name}\n"
    try:
        observed = (root / sidecar_name).read_text(encoding="ascii")
    except (OSError, UnicodeError) as error:
        raise ModernSyntheticRecoveryError(f"{sidecar_name} is unreadable") from error
    if observed != expected:
        raise ModernSyntheticRecoveryError(f"{sidecar_name} does not match")


def _timestamp(value: str | None) -> str:
    if value is None:
        return datetime.now(UTC).isoformat(timespec="seconds")
    if not isinstance(value, str) or not value:
        raise ValueError("created_at must be a non-empty string")
    return value


def _positive_integer(name: str, value: int, *, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if not 1 <= value <= maximum:
        raise ValueError(f"{name} must be between 1 and {maximum}")
    return value


def _rewrite_optimizer_config(path: Path, *, max_cycles: int, gradient: str) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0] != CONFIG_MARKER:
        raise ModernSyntheticRecoveryError("Generated Modern configuration marker is missing")
    value = yaml.safe_load("\n".join(lines[1:]))
    if not isinstance(value, dict):
        raise ModernSyntheticRecoveryError("Generated Modern configuration is invalid")
    optimization = value["optimization"]
    optimization.update(
        {
            "max_cycles": max_cycles,
            "momenta_updates_per_cycle": 2,
            "direction_update": "lbfgs",
            "gradient_tolerance": 0.0,
            "max_line_search_iterations": 10,
            "relative_objective_tolerance": 0.0001,
            "template_gradient": gradient,
            "sobolev_kernel_width_ratio": 1.0,
            "checkpoint_interval_cycles": 10,
            "checkpoint_retention": "latest",
        }
    )
    validate_modern_workflow_config(value)
    path.write_text(
        CONFIG_MARKER + "\n" + yaml.safe_dump(value, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
        newline="\n",
    )


def create_modern_synthetic_recovery_design(
    benchmark_directory: Path | str,
    destination: Path | str,
    *,
    max_cycles: int = 100,
    control_point_count: int = 9,
    attachment_type: str = "current",
    created_at: str | None = None,
) -> Path:
    """Freeze paired Euclidean/Sobolev full-atlas configs before results exist."""

    cycles = _positive_integer("max_cycles", max_cycles, maximum=1_000)
    controls = _positive_integer("control_point_count", control_point_count, maximum=1_000)
    if attachment_type not in {"current", "varifold", "landmark"}:
        raise ValueError("attachment_type must be current, varifold, or landmark")
    source = Path(benchmark_directory).expanduser().resolve()
    source_manifest = verify_synthetic_validation_benchmark(source)
    output = Path(destination).expanduser().resolve()
    if output.exists():
        raise ConfigurationError(f"Synthetic recovery design already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.tmp-{uuid.uuid4().hex}")
    temporary.mkdir()
    try:
        benchmark = temporary / "inputs" / "benchmark"
        shutil.copytree(source, benchmark)
        copied_manifest = verify_synthetic_validation_benchmark(benchmark)
        if copied_manifest["fingerprint"] != source_manifest["fingerprint"]:
            raise ModernSyntheticRecoveryError("Copied synthetic benchmark differs from source")

        arms: list[dict[str, Any]] = []
        for arm_id in ARM_IDS:
            config = temporary / f"modern-{arm_id}.yaml"
            run_output = output.parent / f"{output.name}-{arm_id}-run"
            initialize_modern_workflow(
                benchmark,
                units="unitless",
                config_path=config,
                template=benchmark / "template.vtk",
                subject_pattern="truth-*.vtk",
                project_name=f"modern-synthetic-recovery-{arm_id}",
                output_directory=run_output,
                control_point_count=controls,
                attachment_type=attachment_type,
                attachment_kernel_width=0.45,
                deformation_kernel_width=0.6,
                noise_variance=0.01,
                max_cycles=cycles,
                threads=1,
                runtime_device="cpu",
                random_seed=20260827,
                pairwise_mode="dense",
                template_gradient=arm_id,
                sobolev_kernel_width_ratio=1.0,
            )
            _rewrite_optimizer_config(config, max_cycles=cycles, gradient=arm_id)
            arms.append(
                {
                    "arm_id": arm_id,
                    "engine_implementation": ENGINE_IMPLEMENTATION_VERSION,
                    "template_gradient": arm_id,
                    "sobolev_kernel_width_ratio": 1.0,
                    "config_path": config.relative_to(temporary).as_posix(),
                    "config_sha256": sha256_file(config),
                    "planned_run_directory": str(run_output),
                }
            )

        design = {
            "design_version": DESIGN_VERSION,
            "created_at": _timestamp(created_at),
            "status": "prospective_no_modern_results",
            "benchmark": {
                "path": "inputs/benchmark",
                "manifest_sha256": sha256_file(benchmark / SYNTHETIC_MANIFEST),
                "fingerprint": copied_manifest["fingerprint"],
                "subjects": len(copied_manifest["subjects"]),
                "subjects_per_family": copied_manifest["subjects_per_family"],
            },
            "protocol": {
                "scope": "full_atlas_known_correspondence_recovery",
                "paired_variable": "template_gradient",
                "arms": arms,
                "shared_settings": {
                    "max_cycles": cycles,
                    "control_point_count": controls,
                    "attachment_type": attachment_type,
                    "optimizer": "lbfgs",
                    "momenta_updates_per_cycle": 2,
                    "relative_objective_tolerance": 0.0001,
                    "attachment_kernel_width": 0.45,
                    "deformation_kernel_width": 0.6,
                    "noise_variance": 0.01,
                    "device": "cpu",
                    "precision": "float64",
                    "random_seed": 20260827,
                },
                "predeclared_arm_gates": {
                    "require_verified_workflow": True,
                    "require_optimizer_convergence": True,
                    "minimum_pooled_vertex_error_reduction_fraction": 0.5,
                    "maximum_pooled_reconstruction_p95_over_template_diagonal": 0.02,
                    "maximum_generating_template_p95_over_template_diagonal": 0.02,
                },
                "comparison_policy": (
                    "Report paired Sobolev-minus-Euclidean deltas. No superiority gate or "
                    "winner is selected from this miniature benchmark."
                ),
                "template_target_policy": (
                    "Report distance both to the analytic generating template and to the "
                    "ordered cohort coordinate mean because atlas gauge and nonlinear "
                    "deformation centering make neither target universally canonical."
                ),
            },
            "scientific_boundary": SCIENTIFIC_BOUNDARY,
        }
        design_path = temporary / DESIGN_NAME
        design_path.write_bytes(_json_bytes(design))
        _write_sidecar(temporary / DESIGN_SIDECAR_NAME, DESIGN_NAME, design_path)
        verify_modern_synthetic_recovery_design(temporary)
        temporary.rename(output)
    except BaseException:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise
    return output / DESIGN_NAME


def verify_modern_synthetic_recovery_design(directory: Path | str) -> dict[str, Any]:
    """Verify a prospective recovery design and its self-contained benchmark."""

    root = Path(directory).expanduser().resolve()
    if not root.is_dir():
        raise ModernSyntheticRecoveryError(f"Synthetic recovery design does not exist: {root}")
    if any(path.is_symlink() for path in root.rglob("*")):
        raise ModernSyntheticRecoveryError("Synthetic recovery designs must not contain symlinks")
    design = _read_json(root / DESIGN_NAME, "Synthetic recovery design")
    _verify_sidecar(root, DESIGN_NAME, DESIGN_SIDECAR_NAME)
    if design.get("design_version") != DESIGN_VERSION:
        raise ModernSyntheticRecoveryError("Unsupported synthetic recovery design version")
    benchmark_record = design.get("benchmark")
    protocol = design.get("protocol")
    if not isinstance(benchmark_record, dict) or not isinstance(protocol, dict):
        raise ModernSyntheticRecoveryError("Synthetic recovery design structure is invalid")
    benchmark = root / str(benchmark_record.get("path"))
    manifest = verify_synthetic_validation_benchmark(benchmark)
    if (
        sha256_file(benchmark / SYNTHETIC_MANIFEST) != benchmark_record.get("manifest_sha256")
        or manifest.get("fingerprint") != benchmark_record.get("fingerprint")
        or len(manifest.get("subjects", [])) != benchmark_record.get("subjects")
    ):
        raise ModernSyntheticRecoveryError("Synthetic recovery benchmark binding differs")
    arms = protocol.get("arms")
    if not isinstance(arms, list) or [item.get("arm_id") for item in arms] != list(ARM_IDS):
        raise ModernSyntheticRecoveryError("Synthetic recovery arms differ")
    paired_configs = []
    for arm in arms:
        if not isinstance(arm, dict):
            raise ModernSyntheticRecoveryError("Synthetic recovery arm is invalid")
        config_path = root / str(arm.get("config_path"))
        if not config_path.is_file() or sha256_file(config_path) != arm.get("config_sha256"):
            raise ModernSyntheticRecoveryError("Synthetic recovery configuration hash differs")
        lines = config_path.read_text(encoding="utf-8").splitlines()
        config = yaml.safe_load("\n".join(lines[1:]))
        validate_modern_workflow_config(config)
        if (
            config["optimization"]["template_gradient"] != arm["arm_id"]
            or config["optimization"]["sobolev_kernel_width_ratio"] != 1.0
            or config["optimization"]["block_order"] != ["momenta", "template", "control_points"]
            or config["model"]["attachment"]["type"]
            != protocol["shared_settings"].get("attachment_type", "current")
        ):
            raise ModernSyntheticRecoveryError(
                "Synthetic recovery paired-variable contract differs"
            )
        paired = json.loads(json.dumps(config))
        paired["project"]["name"] = "<paired-arm>"
        paired["output"]["directory"] = "<paired-run-directory>"
        paired["optimization"]["template_gradient"] = "<paired-variable>"
        paired_configs.append(paired)
    if paired_configs[0] != paired_configs[1]:
        raise ModernSyntheticRecoveryError(
            "Synthetic recovery configs differ beyond the declared paired variable"
        )
    expected_files = {
        DESIGN_NAME,
        DESIGN_SIDECAR_NAME,
        "modern-euclidean.yaml",
        "modern-sobolev.yaml",
        *{f"inputs/benchmark/{path.name}" for path in benchmark.iterdir() if path.is_file()},
    }
    actual_files = {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}
    if actual_files != expected_files:
        raise ModernSyntheticRecoveryError("Synthetic recovery design exact inventory differs")
    return design


def _distance_summary(distances: np.ndarray, diagonal: float) -> dict[str, float | int]:
    if distances.ndim != 1 or not distances.size or not np.all(np.isfinite(distances)):
        raise ModernSyntheticRecoveryError("Synthetic recovery distances are invalid")
    return {
        "vertices": int(distances.size),
        "rmse": float(math.sqrt(float(np.mean(distances * distances)))),
        "p95": float(np.quantile(distances, 0.95, method="linear")),
        "maximum": float(np.max(distances)),
        "rmse_over_template_diagonal": float(
            math.sqrt(float(np.mean(distances * distances))) / diagonal
        ),
        "p95_over_template_diagonal": float(
            np.quantile(distances, 0.95, method="linear") / diagonal
        ),
        "maximum_over_template_diagonal": float(np.max(distances) / diagonal),
    }


def _ordered_distances(recovered: Path, truth: Path) -> np.ndarray:
    observed = read_vtk_polydata(recovered)
    expected = read_vtk_polydata(truth)
    if observed.triangles != expected.triangles or len(observed.vertices) != len(expected.vertices):
        raise ModernSyntheticRecoveryError("Recovered mesh does not preserve ordered topology")
    return np.linalg.norm(
        np.asarray(observed.vertices, dtype=np.float64)
        - np.asarray(expected.vertices, dtype=np.float64),
        axis=1,
    )


def _arm_assessment(
    design_root: Path,
    design: dict[str, Any],
    arm: dict[str, Any],
    run_directory: Path,
) -> dict[str, Any]:
    workflow = verify_modern_workflow(run_directory)
    source_config = run_directory / workflow["config"]["source_path"]
    if sha256_file(source_config) != arm["config_sha256"]:
        raise ModernSyntheticRecoveryError(f"{arm['arm_id']} run used a different source config")
    if workflow["engine"]["implementation_version"] != arm["engine_implementation"]:
        raise ModernSyntheticRecoveryError(f"{arm['arm_id']} engine implementation differs")
    benchmark = design_root / design["benchmark"]["path"]
    benchmark_manifest = verify_synthetic_validation_benchmark(benchmark)
    subject_records = benchmark_manifest["subjects"]
    expected_hashes = {record["filename"]: record["sha256"] for record in subject_records}
    observed_hashes = {
        record["source_filename"]: record["sha256"] for record in workflow["input"]["subjects"]
    }
    if observed_hashes != expected_hashes:
        raise ModernSyntheticRecoveryError(f"{arm['arm_id']} run subject binding differs")
    template_record = benchmark_manifest["template"]
    if workflow["input"]["template"]["sha256"] != template_record["sha256"]:
        raise ModernSyntheticRecoveryError(f"{arm['arm_id']} run template binding differs")

    bundle_root = run_directory / workflow["result_bundle"]["path"]
    bundle = verify_modern_atlas_bundle(bundle_root)
    if bundle["optimizer"]["settings"]["template_gradient"] != arm["arm_id"]:
        raise ModernSyntheticRecoveryError(f"{arm['arm_id']} result gradient differs")
    template_path = benchmark / template_record["filename"]
    template_mesh = read_vtk_polydata(template_path)
    template_vertices = np.asarray(template_mesh.vertices, dtype=np.float64)
    extents = np.ptp(template_vertices, axis=0)
    diagonal = float(np.linalg.norm(extents))
    estimated_template = bundle_root / bundle["template"]["path"]
    generating_template_distances = _ordered_distances(estimated_template, template_path)

    truth_vertices = []
    truth_by_name = {record["filename"]: record for record in subject_records}
    reconstruction_distances: list[np.ndarray] = []
    baseline_distances: list[np.ndarray] = []
    per_subject = []
    by_family: dict[str, list[np.ndarray]] = {"local": [], "global": [], "mixed": []}
    for result_record in bundle["subjects"]:
        label = result_record["label"]
        truth_record = truth_by_name.get(label)
        if truth_record is None:
            raise ModernSyntheticRecoveryError(f"Unexpected reconstruction label: {label}")
        truth_path = benchmark / label
        recovered_path = bundle_root / result_record["reconstruction_path"]
        distances = _ordered_distances(recovered_path, truth_path)
        baseline = _ordered_distances(template_path, truth_path)
        reconstruction_distances.append(distances)
        baseline_distances.append(baseline)
        by_family[truth_record["family"]].append(distances)
        truth_vertices.append(np.asarray(read_vtk_polydata(truth_path).vertices, dtype=np.float64))
        per_subject.append(
            {
                "filename": label,
                "family": truth_record["family"],
                "signed_strength": truth_record["signed_strength"],
                "reconstruction": _distance_summary(distances, diagonal),
                "undeformed_template_baseline": _distance_summary(baseline, diagonal),
            }
        )
    if len(per_subject) != len(subject_records):
        raise ModernSyntheticRecoveryError("Synthetic recovery reconstruction count differs")

    estimated_vertices = np.asarray(
        read_vtk_polydata(estimated_template).vertices, dtype=np.float64
    )
    coordinate_mean = np.mean(np.stack(truth_vertices), axis=0)
    coordinate_mean_distances = np.linalg.norm(estimated_vertices - coordinate_mean, axis=1)
    pooled = np.concatenate(reconstruction_distances)
    baseline_pooled = np.concatenate(baseline_distances)
    pooled_summary = _distance_summary(pooled, diagonal)
    baseline_summary = _distance_summary(baseline_pooled, diagonal)
    reduction = 1.0 - float(pooled_summary["rmse"]) / float(baseline_summary["rmse"])
    gates = design["protocol"]["predeclared_arm_gates"]
    gate_results = {
        "verified_workflow": True,
        "optimizer_converged": bool(bundle["optimizer"]["converged"]),
        "minimum_pooled_vertex_error_reduction_fraction": reduction
        >= gates["minimum_pooled_vertex_error_reduction_fraction"],
        "maximum_pooled_reconstruction_p95_over_template_diagonal": float(
            pooled_summary["p95_over_template_diagonal"]
        )
        <= gates["maximum_pooled_reconstruction_p95_over_template_diagonal"],
        "maximum_generating_template_p95_over_template_diagonal": float(
            _distance_summary(generating_template_distances, diagonal)["p95_over_template_diagonal"]
        )
        <= gates["maximum_generating_template_p95_over_template_diagonal"],
    }
    if not gate_results["optimizer_converged"]:
        decision = "inconclusive_not_converged"
    else:
        decision = "pass" if all(gate_results.values()) else "fail"
    return {
        "arm_id": arm["arm_id"],
        "run_directory": str(run_directory),
        "workflow_manifest_sha256": sha256_file(run_directory / "workflow-manifest.json"),
        "bundle_manifest_sha256": sha256_file(bundle_root / BUNDLE_MANIFEST_NAME),
        "engine_implementation": workflow["engine"]["implementation_version"],
        "optimizer": {
            "termination_reason": bundle["optimizer"]["termination_reason"],
            "converged": bundle["optimizer"]["converged"],
            "cycles_completed": bundle["optimizer"]["cycles_completed"],
            "total_line_search_evaluations": bundle["optimizer"]["total_line_search_evaluations"],
            "final_objective": bundle["optimizer"]["final_objective"],
            "final_attachment": bundle["optimizer"]["final_attachment"],
            "final_regularity": bundle["optimizer"]["final_regularity"],
        },
        "template_diagonal": diagonal,
        "generating_template_error": _distance_summary(generating_template_distances, diagonal),
        "cohort_coordinate_mean_error": _distance_summary(coordinate_mean_distances, diagonal),
        "pooled_reconstruction_error": pooled_summary,
        "undeformed_template_baseline_error": baseline_summary,
        "pooled_rmse_reduction_fraction": reduction,
        "per_family_reconstruction_error": {
            family: _distance_summary(np.concatenate(values), diagonal)
            for family, values in by_family.items()
        },
        "subjects": per_subject,
        "gates": gate_results,
        "decision": decision,
    }


def _assessment_payload(
    design_directory: Path,
    euclidean_run: Path,
    sobolev_run: Path,
    *,
    created_at: str,
) -> dict[str, Any]:
    design = verify_modern_synthetic_recovery_design(design_directory)
    arm_records = {item["arm_id"]: item for item in design["protocol"]["arms"]}
    euclidean = _arm_assessment(design_directory, design, arm_records["euclidean"], euclidean_run)
    sobolev = _arm_assessment(design_directory, design, arm_records["sobolev"], sobolev_run)

    def delta(path: tuple[str, str]) -> float:
        section, metric = path
        return float(sobolev[section][metric]) - float(euclidean[section][metric])

    return {
        "assessment_version": ASSESSMENT_VERSION,
        "created_at": created_at,
        "design": {
            "directory": str(design_directory),
            "sha256": sha256_file(design_directory / DESIGN_NAME),
        },
        "arms": [euclidean, sobolev],
        "paired_sobolev_minus_euclidean": {
            "pooled_reconstruction_rmse_over_template_diagonal": delta(
                ("pooled_reconstruction_error", "rmse_over_template_diagonal")
            ),
            "pooled_reconstruction_p95_over_template_diagonal": delta(
                ("pooled_reconstruction_error", "p95_over_template_diagonal")
            ),
            "generating_template_p95_over_template_diagonal": delta(
                ("generating_template_error", "p95_over_template_diagonal")
            ),
            "cohort_coordinate_mean_p95_over_template_diagonal": delta(
                ("cohort_coordinate_mean_error", "p95_over_template_diagonal")
            ),
            "pooled_rmse_reduction_fraction": float(sobolev["pooled_rmse_reduction_fraction"])
            - float(euclidean["pooled_rmse_reduction_fraction"]),
        },
        "comparison_decision": "descriptive_no_predeclared_superiority_gate",
        "scientific_boundary": SCIENTIFIC_BOUNDARY,
    }


def _render_html(payload: dict[str, Any]) -> str:
    rows = []
    for arm in payload["arms"]:
        rows.append(
            "<tr>"
            f"<td>{html.escape(arm['arm_id'])}</td>"
            f"<td>{html.escape(arm['decision'])}</td>"
            f"<td>{arm['optimizer']['cycles_completed']}</td>"
            f"<td>{arm['pooled_reconstruction_error']['p95_over_template_diagonal']:.6g}</td>"
            f"<td>{arm['generating_template_error']['p95_over_template_diagonal']:.6g}</td>"
            f"<td>{arm['pooled_rmse_reduction_fraction']:.6g}</td>"
            "</tr>"
        )
    return (
        """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Modern synthetic recovery</title>
<style>body{font:16px system-ui;max-width:980px;margin:2rem auto;padding:0 1rem;color:#172033}
table{border-collapse:collapse;width:100%}
th,td{border:1px solid #ccd3df;padding:.55rem;text-align:left}
th{background:#eef2f7}code{background:#eef2f7;padding:.1rem .25rem}</style></head><body>
<h1>Modern synthetic recovery assessment</h1>
<p>Paired Engine """
        + html.escape(str(payload["arms"][0]["engine_implementation"]))
        + """ full-atlas runs with exact analytic vertex correspondence.</p>
<table><thead><tr><th>Gradient</th><th>Decision</th><th>Cycles</th>
<th>Reconstruction p95 / diagonal</th><th>Template p95 / diagonal</th>
<th>RMSE reduction</th></tr></thead><tbody>"""
        + "".join(rows)
        + """</tbody></table>
<p><strong>Comparison:</strong> <code>descriptive_no_predeclared_superiority_gate</code>.</p>
<p>"""
        + html.escape(payload["scientific_boundary"])
        + "</p></body></html>\n"
    )


def assess_modern_synthetic_recovery(
    design_directory: Path | str,
    euclidean_run: Path | str,
    sobolev_run: Path | str,
    destination: Path | str,
    *,
    created_at: str | None = None,
) -> Path:
    """Assess two completed paired runs against exact synthetic ground truth."""

    design_root = Path(design_directory).expanduser().resolve()
    euclidean_root = Path(euclidean_run).expanduser().resolve()
    sobolev_root = Path(sobolev_run).expanduser().resolve()
    output = Path(destination).expanduser().resolve()
    if output.exists():
        raise ConfigurationError(f"Synthetic recovery assessment already exists: {output}")
    payload = _assessment_payload(
        design_root,
        euclidean_root,
        sobolev_root,
        created_at=_timestamp(created_at),
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.tmp-{uuid.uuid4().hex}")
    temporary.mkdir()
    try:
        assessment_path = temporary / ASSESSMENT_NAME
        assessment_path.write_bytes(_json_bytes(payload))
        write_text_safely(
            temporary / ASSESSMENT_HTML_NAME,
            _render_html(payload),
            overwrite=False,
        )
        _write_sidecar(
            temporary / ASSESSMENT_SIDECAR_NAME,
            ASSESSMENT_NAME,
            assessment_path,
        )
        verify_modern_synthetic_recovery_assessment(temporary)
        temporary.rename(output)
    except BaseException:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise
    return output / ASSESSMENT_NAME


def verify_modern_synthetic_recovery_assessment(
    directory: Path | str,
) -> dict[str, Any]:
    """Recompute an assessment from its bound design and verified Modern runs."""

    root = Path(directory).expanduser().resolve()
    payload = _read_json(root / ASSESSMENT_NAME, "Synthetic recovery assessment")
    _verify_sidecar(root, ASSESSMENT_NAME, ASSESSMENT_SIDECAR_NAME)
    if payload.get("assessment_version") != ASSESSMENT_VERSION:
        raise ModernSyntheticRecoveryError("Unsupported synthetic recovery assessment version")
    if set(path.name for path in root.iterdir() if path.is_file()) != {
        ASSESSMENT_NAME,
        ASSESSMENT_SIDECAR_NAME,
        ASSESSMENT_HTML_NAME,
    }:
        raise ModernSyntheticRecoveryError("Synthetic recovery assessment inventory differs")
    arms = payload.get("arms")
    if not isinstance(arms, list) or [arm.get("arm_id") for arm in arms] != list(ARM_IDS):
        raise ModernSyntheticRecoveryError("Synthetic recovery assessment arms differ")
    design_root = Path(payload["design"]["directory"]).resolve()
    if sha256_file(design_root / DESIGN_NAME) != payload["design"]["sha256"]:
        raise ModernSyntheticRecoveryError("Synthetic recovery assessment design binding differs")
    recomputed = _assessment_payload(
        design_root,
        Path(arms[0]["run_directory"]).resolve(),
        Path(arms[1]["run_directory"]).resolve(),
        created_at=payload["created_at"],
    )
    if recomputed != payload:
        raise ModernSyntheticRecoveryError("Synthetic recovery assessment recomputation differs")
    if (root / ASSESSMENT_HTML_NAME).read_text(encoding="utf-8") != _render_html(payload):
        raise ModernSyntheticRecoveryError("Synthetic recovery HTML report differs")
    return payload
