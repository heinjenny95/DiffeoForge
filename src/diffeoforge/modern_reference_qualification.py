"""Prospective fixed-reference qualification of the experimental Modern Engine."""

from __future__ import annotations

import copy
import csv
import json
import math
import re
import shutil
import tempfile
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from html import escape
from itertools import pairwise
from pathlib import Path, PurePosixPath
from typing import Any

import numpy as np
import yaml

from diffeoforge.config import ConfigurationError
from diffeoforge.engine.execution import ENGINE_IMPLEMENTATION_VERSION
from diffeoforge.mesh import inspect_vtk, read_vtk_polydata, sha256_file
from diffeoforge.mesh_quality import (
    MeshQualitySettings,
    assess_triangle_mesh,
    mesh_quality_failures,
)
from diffeoforge.modern_bundle import MANIFEST_NAME as BUNDLE_MANIFEST_NAME
from diffeoforge.modern_bundle import verify_modern_atlas_bundle
from diffeoforge.modern_checkpoint import (
    CHECKPOINT_VERSION,
    verify_modern_cycle_checkpoint,
)
from diffeoforge.modern_checkpoint import (
    MANIFEST_NAME as CHECKPOINT_MANIFEST_NAME,
)
from diffeoforge.modern_workflow import (
    CONFIG_MARKER,
    CONFIG_VERSION,
    _read_momenta_rows,
    validate_modern_workflow_config,
    verify_modern_workflow,
)
from diffeoforge.modern_workflow import (
    MANIFEST_NAME as WORKFLOW_MANIFEST_NAME,
)
from diffeoforge.reference_pca import (
    read_deformetrica_control_points,
    read_deformetrica_momenta,
)
from diffeoforge.reference_validation_metrics import (
    symmetric_vertex_to_surface_distances,
)
from diffeoforge.result_report import collect_run_report

LEGACY_DESIGN_VERSION = "0.2"
DESIGN_VERSION = "0.6"
FULL_ATLAS_DESIGN_VERSION = "0.8"
FULL_ATLAS_CONTINUATION_DESIGN_VERSION = "0.9"
LEGACY_CONTINUATION_DESIGN_VERSION = "0.3"
PREVIOUS_CONTINUATION_DESIGN_VERSION = "0.4"
PREVIOUS_EXACT_CONTINUATION_DESIGN_VERSION = "0.5"
CONTINUATION_DESIGN_VERSION = "0.7"
CONTINUATION_DESIGN_VERSIONS = {
    LEGACY_CONTINUATION_DESIGN_VERSION,
    PREVIOUS_CONTINUATION_DESIGN_VERSION,
    PREVIOUS_EXACT_CONTINUATION_DESIGN_VERSION,
    CONTINUATION_DESIGN_VERSION,
    FULL_ATLAS_CONTINUATION_DESIGN_VERSION,
}
ENGINE_BOUND_CONTINUATION_VERSIONS = {
    PREVIOUS_CONTINUATION_DESIGN_VERSION,
    PREVIOUS_EXACT_CONTINUATION_DESIGN_VERSION,
    CONTINUATION_DESIGN_VERSION,
    FULL_ATLAS_CONTINUATION_DESIGN_VERSION,
}
EXACT_CONTINUATION_DESIGN_VERSIONS = {
    PREVIOUS_EXACT_CONTINUATION_DESIGN_VERSION,
    CONTINUATION_DESIGN_VERSION,
    FULL_ATLAS_CONTINUATION_DESIGN_VERSION,
}
SUPPORTED_DESIGN_VERSIONS = frozenset(
    {
        "0.1",
        LEGACY_DESIGN_VERSION,
        DESIGN_VERSION,
        FULL_ATLAS_DESIGN_VERSION,
        *CONTINUATION_DESIGN_VERSIONS,
    }
)
DESIGN_JSON_NAME = "modern-reference-qualification-design.json"
DESIGN_SIDECAR_NAME = "modern-reference-qualification-design.sha256"
DESIGN_HTML_NAME = "modern-reference-qualification-design.html"
CONFIG_NAME = "modern-fixed-reference.yaml"
FULL_ATLAS_CONFIG_NAME = "modern-full-atlas.yaml"
ASSESSMENT_JSON_NAME = "modern-reference-qualification-assessment.json"
ASSESSMENT_SIDECAR_NAME = "modern-reference-qualification-assessment.sha256"
ASSESSMENT_HTML_NAME = "modern-reference-qualification-assessment.html"


class ModernReferenceQualificationError(RuntimeError):
    """Raised when prospective comparison evidence is incomplete or inconsistent."""


QualificationMetricProgress = Callable[[int, int, str], None]


def _write_json_exclusive(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
        handle.write("\n")


def _copy_exclusive(source: Path, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as input_handle, destination.open("xb") as output_handle:
        shutil.copyfileobj(input_handle, output_handle)
    return destination


def _copy_tree(source: Path, destination: Path) -> Path:
    if (
        source.is_symlink()
        or not source.is_dir()
        or any(path.is_symlink() for path in source.rglob("*"))
    ):
        raise ModernReferenceQualificationError(
            "Qualification continuation checkpoint is invalid or symbolic"
        )
    shutil.copytree(source, destination)
    return destination


def _artifact(root: Path, path: Path) -> dict[str, object]:
    return {
        "path": path.relative_to(root).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def _safe_relative(root: Path, value: object, label: str) -> Path:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ModernReferenceQualificationError(f"{label} is not a POSIX-style path")
    relative = PurePosixPath(value)
    if relative.is_absolute() or "." in relative.parts or ".." in relative.parts:
        raise ModernReferenceQualificationError(f"{label} is unsafe: {value!r}")
    path = root.joinpath(*relative.parts)
    if not path.is_file() or path.is_symlink():
        raise ModernReferenceQualificationError(f"{label} is missing or symbolic: {value}")
    return path


def _safe_directory(root: Path, value: object, label: str) -> Path:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ModernReferenceQualificationError(f"{label} is not a POSIX-style path")
    relative = PurePosixPath(value)
    if relative.is_absolute() or "." in relative.parts or ".." in relative.parts:
        raise ModernReferenceQualificationError(f"{label} is unsafe: {value!r}")
    path = root.joinpath(*relative.parts)
    if not path.is_dir() or path.is_symlink():
        raise ModernReferenceQualificationError(f"{label} is missing or symbolic: {value}")
    return path


def _output_artifact(run: Path, record: dict[str, Any]) -> Path:
    relative = PurePosixPath(str(record["path"]))
    if relative.is_absolute() or "." in relative.parts or ".." in relative.parts:
        raise ModernReferenceQualificationError("Reference inventory contains an unsafe path")
    path = run / "output" / Path(*relative.parts)
    if (
        not path.is_file()
        or path.is_symlink()
        or path.stat().st_size != int(record["bytes"])
        or sha256_file(path) != str(record["sha256"])
    ):
        raise ModernReferenceQualificationError(
            f"Reference output differs from its verified inventory: {relative}"
        )
    return path


def _one_inventory_record(records: tuple[Any, ...], marker: str, label: str) -> dict[str, Any]:
    matches = [dict(record) for record in records if marker in PurePosixPath(record["path"]).name]
    if len(matches) != 1:
        raise ModernReferenceQualificationError(
            f"Completed reference run must contain exactly one {label}; found {len(matches)}"
        )
    return matches[0]


def _reconstruction_subject(filename: str) -> str:
    marker = "__subject_"
    if marker not in filename or not filename.casefold().endswith(".vtk"):
        raise ModernReferenceQualificationError(
            f"Could not identify reference reconstruction subject: {filename}"
        )
    return filename.split(marker, 1)[1][:-4]


def _preferred_subject_names(manifest: dict[str, Any]) -> tuple[str, ...]:
    try:
        records = manifest["effective_config"]["project"]["parameter_provenance"]["recommendation"][
            "calibration_plan"
        ]["selected_pilot_subjects"]
    except (KeyError, TypeError):
        return ()
    if not isinstance(records, list):
        return ()
    names = tuple(
        str(record["filename"])
        for record in records
        if isinstance(record, dict) and isinstance(record.get("filename"), str)
    )
    return names if len(names) == len(set(names)) else ()


def _screen_subject_candidates(
    run: Path,
    subject_inputs: dict[str, Any],
    candidate_names: tuple[str, ...],
    selection_roles: dict[str, str],
    *,
    subject_count: int,
    settings: MeshQualitySettings,
) -> tuple[tuple[str, ...], tuple[dict[str, Any], ...]]:
    """Select the first quality-eligible subjects without inspecting Modern results."""

    selected: list[str] = []
    excluded: list[dict[str, Any]] = []
    for name in candidate_names:
        source_record = subject_inputs[name]
        staged_value = str(source_record["staged_path"])
        staged_relative = PurePosixPath(staged_value)
        if (
            "\\" in staged_value
            or staged_relative.is_absolute()
            or "." in staged_relative.parts
            or ".." in staged_relative.parts
        ):
            raise ModernReferenceQualificationError(
                f"Protected reference subject has an unsafe staged path: {name}"
            )
        staged = run / Path(*staged_relative.parts)
        expected_hash = str(source_record["geometry"]["sha256"])
        if not staged.is_file() or staged.is_symlink() or sha256_file(staged) != expected_hash:
            raise ModernReferenceQualificationError(
                f"Protected reference subject differs from its manifest: {name}"
            )
        mesh = read_vtk_polydata(staged)
        quality = assess_triangle_mesh(mesh.vertices, mesh.triangles)
        failures = mesh_quality_failures(quality, settings)
        if failures:
            excluded.append(
                {
                    "filename": name,
                    "selection_role": selection_roles[name],
                    "failed_gates": list(failures),
                    "source_quality": quality.as_manifest(),
                }
            )
            continue
        selected.append(name)
        if len(selected) == subject_count:
            break
    if len(selected) != subject_count:
        raise ModernReferenceQualificationError(
            "Reference cohort does not contain enough subjects that pass the declared "
            f"Modern mesh-quality gates: requested {subject_count}, found {len(selected)}"
        )
    return tuple(selected), tuple(excluded)


def _render_design_html(design: dict[str, Any]) -> str:
    subjects = "".join(
        f"<li><code>{escape(record['filename'])}</code> — {escape(record['selection_role'])}</li>"
        for record in design["subjects"]
    )
    gates = "".join(
        f"<li><strong>{escape(key)}</strong>: {escape(str(value))}</li>"
        for key, value in sorted(design["decision_gates"].items())
    )
    quality_screening = design.get("protocol", {}).get("quality_screening")
    quality_section = ""
    if isinstance(quality_screening, dict):
        exclusions = quality_screening.get("excluded_candidates", [])
        exclusion_rows = "".join(
            f"<li><code>{escape(str(record['filename']))}</code> — "
            f"{escape(', '.join(str(value) for value in record['failed_gates']))}</li>"
            for record in exclusions
        )
        quality_section = (
            "\n<h2>Prospective mesh-quality screening</h2>"
            f"<p>{len(exclusions)} candidate(s) were excluded before any Modern "
            "optimization result existed.</p>"
            f"<ul>{exclusion_rows}</ul>"
        )
    continuation = design.get("protocol", {}).get("continuation")
    expected_engine = design.get("modern_workflow", {}).get(
        "expected_engine_implementation"
    )
    engine_section = (
        ""
        if not isinstance(expected_engine, str)
        else (
            "\n<p>Expected Modern Engine implementation: "
            f"<code>{escape(expected_engine)}</code>.</p>"
        )
    )
    continuation_section = ""
    if design.get("design_version") in ENGINE_BOUND_CONTINUATION_VERSIONS and isinstance(
        continuation, dict
    ):
        continuation_section = (
            "\n<h2>Continuation binding</h2><ul>"
            f"<li>Parent engine implementation: "
            f"<code>{escape(str(continuation['parent_engine_implementation']))}</code></li>"
            f"<li>Expected successor engine implementation: "
            f"<code>{escape(str(continuation['expected_engine_implementation']))}</code></li>"
            f"<li>Parent final objective: {float(continuation['parent_final_objective']):.12g}</li>"
            "</ul>"
        )
    full_atlas = design.get("protocol", {}).get("qualification_scope") == "full_atlas"
    title = (
        "Prospective Modern Engine full-atlas qualification"
        if full_atlas
        else "Prospective Modern Engine fixed-reference qualification"
    )
    parameter_statement = (
        "Subject momenta, template vertices, and control points may change. The initial "
        "template, selected cohort, numerical model, and final Deformetrica atlas evidence "
        "are copied and hash-bound. Internal objective values are not treated as "
        "cross-engine equivalents."
        if full_atlas
        else "Only subject momenta may change. The Deformetrica estimated template and "
        "control points are copied, hashed, and fixed. Internal objective values are not "
        "treated as cross-engine equivalents."
    )
    return f"""<!doctype html>
<html lang="en"><meta charset="utf-8"><title>Modern reference qualification</title>
<style>body{{font:16px system-ui;max-width:980px;margin:2rem auto;line-height:1.45}}
code{{background:#eef4f3;padding:.1rem .25rem}} .warning{{background:#fff4cf;padding:1rem}}</style>
<h1>{escape(title)}</h1>
<p class="warning">No Modern Engine result existed when this design was frozen. These are
engineering non-inferiority gates, not evidence of biological validity or production readiness.</p>
<h2>Controlled comparison</h2><p>{escape(design["protocol"]["comparison"])}</p>
<p>{escape(parameter_statement)}</p>
<h2>Subjects ({len(design["subjects"])})</h2><ol>{subjects}</ol>{quality_section}\
{continuation_section}
<h2>Predeclared gates</h2><ul>{gates}</ul>
<p>Modern configuration: <code>{escape(design["modern_workflow"]["config_path"])}</code></p>\
{engine_section}
</html>\n"""


def create_modern_reference_qualification(
    reference_run: Path | str,
    destination: Path | str,
    *,
    subject_count: int = 5,
    max_cycles: int = 3,
    threads: int = 4,
    tile_size: int = 64,
    optimizer_direction: str = "steepest",
    lbfgs_history_size: int = 10,
    lbfgs_initial_step_size: float = 1.0,
    line_search_condition: str = "armijo",
    strong_wolfe_curvature_constant: float = 0.9,
    strong_wolfe_maximum_step_size: float = 10.0,
    subject_batch_size: int | None = None,
    runtime_device: str = "cpu",
    qualification_scope: str = "fixed_reference",
    created_at: str | None = None,
) -> Path:
    """Freeze a no-results-yet comparison against one completed Deformetrica atlas."""

    for name, value, minimum in (
        ("subject_count", subject_count, 2),
        ("max_cycles", max_cycles, 1),
        ("threads", threads, 1),
        ("tile_size", tile_size, 1),
        ("lbfgs_history_size", lbfgs_history_size, 1),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
            raise ValueError(f"{name} must be an integer of at least {minimum}")
    if subject_batch_size is not None and (
        isinstance(subject_batch_size, bool)
        or not isinstance(subject_batch_size, int)
        or subject_batch_size < 1
    ):
        raise ValueError("subject_batch_size must be an integer of at least 1 or None")
    if runtime_device not in {"cpu", "cuda"}:
        raise ValueError("runtime_device must be cpu or cuda")
    if qualification_scope not in {"fixed_reference", "full_atlas"}:
        raise ValueError("qualification_scope must be fixed_reference or full_atlas")
    if optimizer_direction not in {"steepest", "lbfgs"}:
        raise ValueError("optimizer_direction must be steepest or lbfgs")
    if line_search_condition not in {"armijo", "strong_wolfe"}:
        raise ValueError("line_search_condition must be armijo or strong_wolfe")
    if line_search_condition == "strong_wolfe" and optimizer_direction != "lbfgs":
        raise ValueError("line_search_condition=strong_wolfe requires optimizer_direction=lbfgs")
    if (
        isinstance(lbfgs_initial_step_size, bool)
        or not isinstance(lbfgs_initial_step_size, (int, float))
        or not math.isfinite(float(lbfgs_initial_step_size))
        or float(lbfgs_initial_step_size) <= 0.0
    ):
        raise ValueError("lbfgs_initial_step_size must be finite and greater than zero")
    if (
        isinstance(strong_wolfe_curvature_constant, bool)
        or not isinstance(strong_wolfe_curvature_constant, (int, float))
        or not 0.0001 < float(strong_wolfe_curvature_constant) < 1.0
    ):
        raise ValueError(
            "strong_wolfe_curvature_constant must be finite, greater than the Armijo "
            "constant 0.0001, and smaller than one"
        )
    if (
        isinstance(strong_wolfe_maximum_step_size, bool)
        or not isinstance(strong_wolfe_maximum_step_size, (int, float))
        or not math.isfinite(float(strong_wolfe_maximum_step_size))
        or float(strong_wolfe_maximum_step_size) < float(lbfgs_initial_step_size)
    ):
        raise ValueError(
            "strong_wolfe_maximum_step_size must be finite and not smaller than "
            "lbfgs_initial_step_size"
        )
    run = Path(reference_run).expanduser().resolve()
    report = collect_run_report(run)
    if report.result.get("status") != "completed" or any(
        check.status != "pass" for check in report.checks
    ):
        raise ModernReferenceQualificationError(
            "Reference run is not completed with all independent evidence checks passing"
        )
    subject_inputs = {
        Path(str(record["staged_path"])).name: record
        for record in report.manifest["inputs"]
        if record.get("role") == "subject"
    }
    if subject_count > len(subject_inputs):
        raise ValueError(
            f"subject_count cannot exceed the {len(subject_inputs)} reference subjects"
        )
    if qualification_scope == "full_atlas" and subject_count != len(subject_inputs):
        raise ValueError(
            "full_atlas qualification must use the complete Deformetrica reference cohort; "
            f"requested {subject_count}, reference contains {len(subject_inputs)}"
        )
    preferred = [
        name for name in _preferred_subject_names(dict(report.manifest)) if name in subject_inputs
    ]
    remaining = sorted(set(subject_inputs) - set(preferred), key=str.casefold)
    candidate_names = tuple(preferred + remaining)
    selection_role = {
        name: "pre-results geometry-diverse Deformetrica pilot subject"
        if name in preferred
        else "deterministic filename-order fill"
        for name in candidate_names
    }

    quality_settings = MeshQualitySettings(require_single_component=True)
    selected_names, excluded_candidates = _screen_subject_candidates(
        run,
        subject_inputs,
        candidate_names,
        selection_role,
        subject_count=subject_count,
        settings=quality_settings,
    )

    template_record = _one_inventory_record(
        report.inventory,
        "__EstimatedParameters__Template_",
        "estimated template",
    )
    initial_template_inputs = [
        dict(record) for record in report.manifest["inputs"] if record.get("role") == "template"
    ]
    if len(initial_template_inputs) != 1:
        raise ModernReferenceQualificationError(
            "Completed reference run must contain exactly one staged initial template"
        )
    initial_template_input = initial_template_inputs[0]
    control_record = _one_inventory_record(
        report.inventory,
        "__EstimatedParameters__ControlPoints.txt",
        "control-point file",
    )
    momenta_record = _one_inventory_record(
        report.inventory,
        "__EstimatedParameters__Momenta.txt",
        "momenta file",
    )
    momenta = read_deformetrica_momenta(_output_artifact(run, momenta_record))
    control_count = int(momenta.shape[1])
    read_deformetrica_control_points(
        _output_artifact(run, control_record), expected_count=control_count
    )
    reconstructions: dict[str, tuple[dict[str, Any], Path]] = {}
    for record_value in report.inventory:
        record = dict(record_value)
        name = PurePosixPath(str(record["path"])).name
        if "__Reconstruction__" not in name or not name.casefold().endswith(".vtk"):
            continue
        subject = _reconstruction_subject(name)
        if subject in reconstructions:
            raise ModernReferenceQualificationError(
                f"Reference run contains duplicate reconstruction for {subject}"
            )
        reconstructions[subject] = (record, _output_artifact(run, record))
    if any(name not in reconstructions for name in selected_names):
        raise ModernReferenceQualificationError(
            "Reference reconstructions do not cover the prospectively selected subjects"
        )

    destination_path = Path(destination).expanduser().resolve()
    if destination_path.exists():
        raise FileExistsError(
            f"Qualification design destination already exists: {destination_path}"
        )
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination_path.parent / f".{destination_path.name}.tmp-{uuid.uuid4().hex}"
    temporary.mkdir()
    try:
        copied_template = _copy_exclusive(
            _output_artifact(run, template_record),
            temporary / "inputs" / "reference-template.vtk",
        )
        initial_template_value = str(initial_template_input["staged_path"])
        initial_template_relative = PurePosixPath(initial_template_value)
        if (
            "\\" in initial_template_value
            or initial_template_relative.is_absolute()
            or "." in initial_template_relative.parts
            or ".." in initial_template_relative.parts
        ):
            raise ModernReferenceQualificationError(
                "Protected reference initial template has an unsafe staged path"
            )
        initial_template_source = run / Path(*initial_template_relative.parts)
        initial_template_hash = str(initial_template_input["geometry"]["sha256"])
        if (
            not initial_template_source.is_file()
            or initial_template_source.is_symlink()
            or sha256_file(initial_template_source) != initial_template_hash
        ):
            raise ModernReferenceQualificationError(
                "Protected reference initial template differs from its manifest"
            )
        copied_initial_template = _copy_exclusive(
            initial_template_source,
            temporary / "inputs" / "initial-template.vtk",
        )
        copied_controls = _copy_exclusive(
            _output_artifact(run, control_record),
            temporary / "inputs" / "reference-control-points.txt",
        )
        subject_rows: list[dict[str, Any]] = []
        for name in selected_names:
            source_record = subject_inputs[name]
            staged = run / Path(*PurePosixPath(str(source_record["staged_path"])).parts)
            expected_hash = str(source_record["geometry"]["sha256"])
            if not staged.is_file() or staged.is_symlink() or sha256_file(staged) != expected_hash:
                raise ModernReferenceQualificationError(
                    f"Protected reference subject differs from its manifest: {name}"
                )
            subject_copy = _copy_exclusive(staged, temporary / "inputs" / "subjects" / name)
            subject_mesh = read_vtk_polydata(staged)
            source_quality = assess_triangle_mesh(
                subject_mesh.vertices,
                subject_mesh.triangles,
            )
            reference_copy = _copy_exclusive(
                reconstructions[name][1],
                temporary / "reference-reconstructions" / name,
            )
            subject_rows.append(
                {
                    "filename": name,
                    "selection_role": selection_role[name],
                    "source": _artifact(temporary, subject_copy),
                    "source_quality": source_quality.as_manifest(),
                    "reference_reconstruction": _artifact(temporary, reference_copy),
                }
            )

        effective = report.manifest["effective_config"]
        model = effective["model"]
        optimization = effective["optimization"]
        noise_std = float(model["noise_std"])
        output = destination_path.parent / f"{destination_path.name}-modern-run"
        full_atlas = qualification_scope == "full_atlas"
        config = {
            "schema_version": CONFIG_VERSION,
            "project": {
                "name": (
                    f"{effective['project']['name']}-modern-full-atlas"
                    if full_atlas
                    else f"{effective['project']['name']}-modern-fixed-reference"
                )
            },
            "input": {
                "directory": "inputs/subjects",
                "subject_pattern": "*.vtk",
                "template": (
                    "inputs/initial-template.vtk" if full_atlas else "inputs/reference-template.vtk"
                ),
                "units": effective["input"]["units"],
            },
            "preprocessing": {
                "procrustes": {
                    "enabled": False,
                    "landmarks_file": None,
                    "scale_to_unit_centroid_size": True,
                    "allow_reflection": False,
                    "tolerance": 1e-10,
                    "max_iterations": 100,
                }
            },
            "quality_control": quality_settings.as_manifest(),
            "initialization": {
                "control_points": (
                    {
                        "method": "farthest_template_vertices",
                        "count": control_count,
                    }
                    if full_atlas
                    else {
                        "method": "file",
                        "count": control_count,
                        "path": "inputs/reference-control-points.txt",
                    }
                ),
                "momenta": "zeros",
            },
            "model": {
                "attachment": {
                    "type": model["attachment"]["type"],
                    "kernel_width": float(model["attachment"]["kernel_width"]),
                },
                "deformation": {
                    "kernel_width": float(model["deformation"]["kernel_width"]),
                    "timepoints": int(model["deformation"]["timepoints"]),
                    "shooting_integrator": ("rk2" if model["deformation"]["use_rk2"] else "euler"),
                    "flow_integrator": "deformetrica_heun",
                },
                "noise_variance": noise_std**2,
            },
            "optimization": {
                "max_cycles": max_cycles,
                "block_order": (
                    ["momenta", "template", "control_points"] if full_atlas else ["momenta"]
                ),
                "momenta_updates_per_cycle": 2 if full_atlas else 1,
                "momenta_step_size": float(optimization["initial_step_size"]),
                "template_step_size": 0.01,
                "control_points_step_size": 0.01,
                "backtracking_factor": 0.5,
                "armijo_constant": 0.0001,
                "gradient_tolerance": 0.0,
                "minimum_step_size": 1e-12,
                "max_line_search_iterations": int(optimization["max_line_search_iterations"]),
                "step_initialization": "previous_accepted",
                "direction_update": optimizer_direction,
                "lbfgs_history_size": lbfgs_history_size,
                "lbfgs_curvature_tolerance": 1e-12,
                "lbfgs_initial_step_size": float(lbfgs_initial_step_size),
                "line_search_condition": line_search_condition,
                "strong_wolfe_curvature_constant": float(strong_wolfe_curvature_constant),
                "strong_wolfe_maximum_step_size": float(strong_wolfe_maximum_step_size),
                "relative_objective_tolerance": float(optimization["convergence_tolerance"]),
                "subject_batch_size": subject_batch_size,
                "subject_batch_workers": 1,
                "shared_step_scaling": ("inverse_subject_count" if full_atlas else "none"),
                "checkpoint_interval_cycles": 5,
                "checkpoint_retention": "latest",
            },
            "analysis": {
                "pca_components": None,
                "deformation_standard_deviations": 2.0,
                "deformation_components": min(3, subject_count - 1),
            },
            "runtime": {
                "device": runtime_device,
                "precision": "float64",
                "threads": threads,
                "random_seed": int(effective["runtime"]["random_seed"]),
                "pairwise_evaluation": {
                    "mode": "blockwise",
                    "query_tile_size": tile_size,
                    "source_tile_size": tile_size,
                    "autograd_strategy": "recompute",
                },
            },
            "output": {"directory": str(output)},
        }
        validate_modern_workflow_config(config)
        config_path = temporary / (FULL_ATLAS_CONFIG_NAME if full_atlas else CONFIG_NAME)
        with config_path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(CONFIG_MARKER + "\n")
            yaml.safe_dump(config, handle, sort_keys=False, allow_unicode=True)

        timestamp = created_at or datetime.now(UTC).isoformat()
        design: dict[str, Any] = {
            "design_version": (FULL_ATLAS_DESIGN_VERSION if full_atlas else DESIGN_VERSION),
            "created_at": timestamp,
            "status": "prospective_no_modern_results",
            "source_reference": {
                "run_directory": str(run),
                "manifest_sha256": sha256_file(run / "manifest.json"),
                "result_sha256": sha256_file(run / "result.json"),
                "output_inventory_sha256": sha256_file(run / "output-inventory.json"),
                "reference_duration_seconds": float(report.result["duration_seconds"]),
            },
            "protocol": {
                "qualification_scope": qualification_scope,
                "comparison": (
                    (
                        "Estimate a complete Modern atlas from the same staged initial "
                        "template and preselected cohort as the completed Deformetrica atlas; "
                        "optimize subject momenta, template vertices, and shared control "
                        "points, then compare externally observable templates and "
                        "reconstructions."
                    )
                    if full_atlas
                    else (
                        "Register the same preselected subjects to the completed Deformetrica "
                        "estimated template, using its exact estimated control points; optimize "
                        "Modern Engine momenta only."
                    )
                ),
                "subject_selection": (
                    "Reuse the pre-results geometry-diverse calibration pilot order when "
                    "available, exclude candidates that fail the declared Modern mesh-quality "
                    "gates before computation, then fill deterministically by filename."
                ),
                "quality_screening": {
                    "timing": "before_any_modern_optimization_result",
                    "settings": quality_settings.as_manifest(),
                    "excluded_candidates": list(excluded_candidates),
                },
                "internal_objective_comparison": "forbidden_across_engines",
                "stopping_semantics": {
                    "source": "Deformetrica 4.3 gradient_ascent convergence_tolerance",
                    "modern_mapping": "relative_objective_tolerance",
                    "formula": (
                        "abs(current_objective - previous_cycle_objective) < tolerance * "
                        "abs(current_objective - initial_objective)"
                    ),
                    "absolute_gradient_tolerance": "disabled; gradient norms remain diagnostic",
                },
                "modern_result_existed_at_freeze": False,
            },
            "fixed_reference": {
                "template": _artifact(temporary, copied_template),
                "control_points": _artifact(temporary, copied_controls),
                "control_point_count": control_count,
            },
            "initialization": {
                "template": _artifact(temporary, copied_initial_template),
                "control_points": (
                    {
                        "method": "farthest_template_vertices",
                        "count": control_count,
                    }
                    if full_atlas
                    else {
                        "method": "fixed_deformetrica_estimate",
                        "count": control_count,
                    }
                ),
                "momenta": "zeros",
            },
            "subjects": subject_rows,
            "modern_workflow": {
                "config_path": config_path.name,
                "config_sha256": sha256_file(config_path),
                "expected_destination": str(output),
                "optimized_blocks": (
                    ["momenta", "template", "control_points"] if full_atlas else ["momenta"]
                ),
                "max_cycles": max_cycles,
                "pairwise_autograd_strategy": "recompute",
                "expected_engine_implementation": ENGINE_IMPLEMENTATION_VERSION,
            },
            "decision_gates": {
                "modern_workflow_verification": "pass",
                "modern_optimizer_converged": True,
                "pooled_external_residual_ratio_maximum": 1.20,
                "subject_external_residual_ratio_maximum": 1.25,
                "minimum_subject_pass_fraction": 0.80,
                "cross_engine_reconstruction_p95_over_template_diagonal_maximum": 0.05,
                **(
                    {
                        "cross_engine_template_p95_over_reference_diagonal_maximum": 0.05,
                    }
                    if full_atlas
                    else {}
                ),
            },
            "scientific_boundary": (
                (
                    "This full-atlas comparison is a prospective engineering non-inferiority "
                    "gate for one initialization, cohort, and parameterization. It does not "
                    "prove biological validity, global optimality, PCA stability, GPU parity, "
                    "or readiness for 300 specimens."
                )
                if full_atlas
                else (
                    "This fixed-reference pilot isolates registration behavior. Its thresholds "
                    "are prospective engineering non-inferiority gates, not proof of optimizer "
                    "equivalence, atlas equivalence, biological validity, convergence, GPU "
                    "parity, or readiness for 300 specimens."
                )
            ),
        }
        html_path = temporary / DESIGN_HTML_NAME
        html_path.write_text(_render_design_html(design), encoding="utf-8", newline="\n")
        inventory_paths = sorted(
            path
            for path in temporary.rglob("*")
            if path.is_file() and path.name not in {DESIGN_JSON_NAME, DESIGN_SIDECAR_NAME}
        )
        design["artifacts"] = [_artifact(temporary, path) for path in inventory_paths]
        design_path = temporary / DESIGN_JSON_NAME
        _write_json_exclusive(design_path, design)
        (temporary / DESIGN_SIDECAR_NAME).write_text(
            f"{sha256_file(design_path)}  {DESIGN_JSON_NAME}\n",
            encoding="ascii",
            newline="\n",
        )
        verify_modern_reference_qualification_design(temporary)
        temporary.rename(destination_path)
    except Exception:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise
    return destination_path


def create_modern_reference_qualification_continuation(
    design_directory: Path | str,
    parent_modern_run: Path | str,
    destination: Path | str,
    *,
    max_cycles: int = 10,
    threads: int | None = None,
    created_at: str | None = None,
) -> Path:
    """Freeze an immutable successor that starts from a verified Modern result."""

    if isinstance(max_cycles, bool) or not isinstance(max_cycles, int) or max_cycles < 1:
        raise ValueError("max_cycles must be an integer of at least 1")
    if threads is not None and (
        isinstance(threads, bool) or not isinstance(threads, int) or threads < 1
    ):
        raise ValueError("threads must be an integer of at least 1 or None")
    source_root = Path(design_directory).expanduser().resolve()
    source_design = verify_modern_reference_qualification_design(source_root)
    full_atlas = (
        source_design.get("protocol", {}).get("qualification_scope") == "full_atlas"
    )
    parent_root = Path(parent_modern_run).expanduser().resolve()
    parent_workflow = verify_modern_workflow(parent_root)
    parent_source_config = _safe_relative(
        parent_root,
        parent_workflow["config"]["source_path"],
        "Parent Modern source config",
    )
    if sha256_file(parent_source_config) != source_design["modern_workflow"]["config_sha256"]:
        raise ModernReferenceQualificationError(
            "Parent Modern run was not created from the supplied frozen qualification"
        )
    bundle_value = str(parent_workflow["result_bundle"]["path"])
    bundle_relative = PurePosixPath(bundle_value)
    if (
        "\\" in bundle_value
        or bundle_relative.is_absolute()
        or "." in bundle_relative.parts
        or ".." in bundle_relative.parts
    ):
        raise ModernReferenceQualificationError("Parent Modern bundle path is unsafe")
    parent_bundle_root = parent_root / Path(*bundle_relative.parts)
    parent_bundle = verify_modern_atlas_bundle(parent_bundle_root)
    if parent_bundle["optimizer"]["converged"]:
        raise ModernReferenceQualificationError(
            "Parent Modern optimizer already converged; no continuation is required"
        )
    expected_subjects = {record["filename"] for record in source_design["subjects"]}
    if {record["label"] for record in parent_bundle["subjects"]} != expected_subjects:
        raise ModernReferenceQualificationError(
            "Parent Modern subjects differ from the frozen qualification"
        )
    completed_cycles = int(parent_bundle["optimizer"]["cycles_completed"])
    checkpoint_records = parent_workflow.get("optimizer_checkpoints", [])
    if (
        completed_cycles < 1
        or not checkpoint_records
        or checkpoint_records[-1]["cycle"] != completed_cycles
    ):
        raise ModernReferenceQualificationError(
            "Parent Modern run has no final complete-cycle checkpoint"
        )
    checkpoint_value = str(checkpoint_records[-1]["path"])
    checkpoint_relative = PurePosixPath(checkpoint_value)
    if (
        "\\" in checkpoint_value
        or checkpoint_relative.is_absolute()
        or "." in checkpoint_relative.parts
        or ".." in checkpoint_relative.parts
    ):
        raise ModernReferenceQualificationError("Parent checkpoint path is unsafe")
    checkpoint_root = parent_root / Path(*checkpoint_relative.parts)
    checkpoint = verify_modern_cycle_checkpoint(
        checkpoint_root,
        workflow_root=parent_root,
    )
    if checkpoint["checkpoint_version"] != CHECKPOINT_VERSION:
        raise ModernReferenceQualificationError(
            "Parent checkpoint predates exact L-BFGS and objective-baseline serialization"
        )
    if checkpoint["binding"]["engine_implementation"] != ENGINE_IMPLEMENTATION_VERSION:
        raise ModernReferenceQualificationError("Parent checkpoint engine differs")
    parent_effective_path = _safe_relative(
        parent_root,
        parent_workflow["config"]["effective_path"],
        "Parent Modern effective config",
    )
    parent_effective = json.loads(parent_effective_path.read_text(encoding="utf-8"))
    if not isinstance(parent_effective, dict):
        raise ModernReferenceQualificationError("Parent effective config is not an object")
    validate_modern_workflow_config(parent_effective)

    if threads is not None and threads != int(parent_effective["runtime"]["threads"]):
        raise ModernReferenceQualificationError(
            "Exact qualification continuation requires the parent thread count"
        )
    last_steps = {
        block: float(value)
        for block, value in checkpoint["optimizer_state"]["next_step_sizes"].items()
    }

    destination_path = Path(destination).expanduser().resolve()
    if destination_path.exists():
        raise FileExistsError(
            f"Qualification continuation destination already exists: {destination_path}"
        )
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination_path.parent / f".{destination_path.name}.tmp-{uuid.uuid4().hex}"
    temporary.mkdir()
    try:
        source_config_relative = str(source_design["modern_workflow"]["config_path"])
        for record in source_design["artifacts"]:
            relative = str(record["path"])
            if relative in {source_config_relative, DESIGN_HTML_NAME}:
                continue
            source = _safe_relative(source_root, relative, "Source qualification artifact")
            _copy_exclusive(source, temporary / Path(*PurePosixPath(relative).parts))
        embedded_checkpoint = _copy_tree(
            checkpoint_root,
            temporary / "lineage" / "checkpoint",
        )
        embedded = verify_modern_cycle_checkpoint(embedded_checkpoint)
        copied_effective = _copy_exclusive(
            parent_effective_path,
            temporary / "lineage" / "source-effective-config.json",
        )
        state = embedded["state"]
        checkpoint_template = _safe_relative(
            embedded_checkpoint,
            state["template"]["path"],
            "Embedded checkpoint template",
        )
        checkpoint_controls = _safe_relative(
            embedded_checkpoint,
            state["control_points"]["path"],
            "Embedded checkpoint controls",
        )
        copied_momenta = _safe_relative(
            embedded_checkpoint,
            state["momenta"]["path"],
            "Embedded checkpoint momenta",
        )
        subject_labels = tuple(sorted(expected_subjects))
        try:
            _read_momenta_rows(
                copied_momenta,
                subject_labels,
                int(source_design["fixed_reference"]["control_point_count"]),
            )
        except ConfigurationError as error:
            raise ModernReferenceQualificationError(
                f"Parent momenta cannot initialize the successor: {error}"
            ) from error

        config = copy.deepcopy(parent_effective)
        config["schema_version"] = "0.5"
        config["project"]["name"] = f"{config['project']['name']}-continuation"
        config["input"]["template"] = checkpoint_template.relative_to(temporary).as_posix()
        config["initialization"]["control_points"] = {
            "method": "file",
            "count": int(state["control_points"]["count"]),
            "path": checkpoint_controls.relative_to(temporary).as_posix(),
        }
        config["initialization"]["momenta"] = {
            "method": "file",
            "path": copied_momenta.relative_to(temporary).as_posix(),
        }
        config["optimization"]["max_cycles"] = max_cycles
        config["optimization"]["resume_state"] = {
            "checkpoint_directory": embedded_checkpoint.relative_to(temporary).as_posix(),
            "checkpoint_manifest_sha256": sha256_file(
                embedded_checkpoint / CHECKPOINT_MANIFEST_NAME
            ),
            "source_effective_config": copied_effective.relative_to(temporary).as_posix(),
            "source_effective_config_sha256": sha256_file(copied_effective),
        }
        output = destination_path.parent / f"{destination_path.name}-modern-run"
        config["output"]["directory"] = str(output)
        validate_modern_workflow_config(config)
        config_path = temporary / (
            FULL_ATLAS_CONFIG_NAME if full_atlas else CONFIG_NAME
        )
        with config_path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(CONFIG_MARKER + "\n")
            yaml.safe_dump(config, handle, sort_keys=False, allow_unicode=True)

        design = copy.deepcopy(source_design)
        design["design_version"] = (
            FULL_ATLAS_CONTINUATION_DESIGN_VERSION
            if full_atlas
            else CONTINUATION_DESIGN_VERSION
        )
        design["created_at"] = created_at or datetime.now(UTC).isoformat()
        design["protocol"]["comparison"] = (
            source_design["protocol"]["comparison"]
            + " Continue from the exact parent complete-cycle optimizer state without "
            + (
                "changing the cohort, model, or initialization lineage."
                if full_atlas
                else "changing the fixed geometric reference."
            )
        )
        design["protocol"]["continuation"] = {
            "parent_design_sha256": sha256_file(source_root / DESIGN_JSON_NAME),
            "parent_workflow_manifest_sha256": sha256_file(parent_root / WORKFLOW_MANIFEST_NAME),
            "parent_bundle_manifest_sha256": sha256_file(parent_bundle_root / BUNDLE_MANIFEST_NAME),
            "parent_termination_reason": parent_bundle["optimizer"]["termination_reason"],
            "parent_cycles_completed": parent_bundle["optimizer"]["cycles_completed"],
            "parent_final_objective": parent_bundle["optimizer"]["final_objective"],
            "parent_engine_implementation": parent_workflow["engine"].get("implementation_version"),
            "expected_engine_implementation": ENGINE_IMPLEMENTATION_VERSION,
            "initial_momenta": _artifact(temporary, copied_momenta),
            "derived_initial_step_sizes": last_steps,
            "checkpoint_path": embedded_checkpoint.relative_to(temporary).as_posix(),
            "checkpoint_manifest_sha256": sha256_file(
                embedded_checkpoint / CHECKPOINT_MANIFEST_NAME
            ),
            "source_effective_config": _artifact(temporary, copied_effective),
            "derivation": "exact state serialized in the parent final cycle checkpoint",
        }
        design["modern_workflow"] = {
            **design["modern_workflow"],
            "config_path": config_path.name,
            "config_sha256": sha256_file(config_path),
            "expected_destination": str(output),
            "max_cycles": max_cycles,
            "step_initialization": config["optimization"].get("step_initialization", "fixed"),
            "expected_engine_implementation": ENGINE_IMPLEMENTATION_VERSION,
        }
        design["scientific_boundary"] += (
            " This successor is a sequential optimization pilot whose parent result and "
            "derived starting state are hash-bound; it remains non-independent evidence."
        )
        html_path = temporary / DESIGN_HTML_NAME
        html_path.write_text(_render_design_html(design), encoding="utf-8", newline="\n")
        inventory_paths = sorted(
            path
            for path in temporary.rglob("*")
            if path.is_file() and path.name not in {DESIGN_JSON_NAME, DESIGN_SIDECAR_NAME}
        )
        design["artifacts"] = [_artifact(temporary, path) for path in inventory_paths]
        design_path = temporary / DESIGN_JSON_NAME
        _write_json_exclusive(design_path, design)
        (temporary / DESIGN_SIDECAR_NAME).write_text(
            f"{sha256_file(design_path)}  {DESIGN_JSON_NAME}\n",
            encoding="ascii",
            newline="\n",
        )
        verify_modern_reference_qualification_design(temporary)
        temporary.rename(destination_path)
    except Exception:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise
    return destination_path


def verify_modern_reference_qualification_design(
    design_directory: Path | str,
) -> dict[str, Any]:
    """Verify the frozen design, copied inputs, config, hashes, and deterministic HTML."""

    root = Path(design_directory).expanduser().resolve()
    manifest_path = root / DESIGN_JSON_NAME
    sidecar_path = root / DESIGN_SIDECAR_NAME
    if not root.is_dir() or root.is_symlink() or not manifest_path.is_file():
        raise ModernReferenceQualificationError("Qualification design is missing or symbolic")
    expected_sidecar = f"{sha256_file(manifest_path)}  {DESIGN_JSON_NAME}"
    if (
        not sidecar_path.is_file()
        or sidecar_path.read_text(encoding="ascii").strip() != expected_sidecar
    ):
        raise ModernReferenceQualificationError("Qualification design SHA-256 sidecar differs")
    try:
        design = json.loads(manifest_path.read_text(encoding="utf-8", errors="strict"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ModernReferenceQualificationError(
            f"Qualification design is unreadable: {error}"
        ) from error
    if (
        not isinstance(design, dict)
        or design.get("design_version") not in SUPPORTED_DESIGN_VERSIONS
        or design.get("status") != "prospective_no_modern_results"
        or design.get("protocol", {}).get("modern_result_existed_at_freeze") is not False
    ):
        raise ModernReferenceQualificationError("Qualification design identity is invalid")
    declared: set[str] = set()
    for record in design.get("artifacts", []):
        path = _safe_relative(root, record.get("path"), "Qualification artifact")
        relative = path.relative_to(root).as_posix()
        if relative in declared:
            raise ModernReferenceQualificationError(f"Duplicate qualification artifact: {relative}")
        declared.add(relative)
        if path.stat().st_size != record.get("bytes") or sha256_file(path) != record.get("sha256"):
            raise ModernReferenceQualificationError(f"Qualification artifact differs: {relative}")
    actual = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path.name not in {DESIGN_JSON_NAME, DESIGN_SIDECAR_NAME}
    }
    if actual != declared:
        raise ModernReferenceQualificationError("Qualification artifact inventory differs")
    config_path = _safe_relative(
        root,
        design["modern_workflow"]["config_path"],
        "Modern workflow config",
    )
    if sha256_file(config_path) != design["modern_workflow"]["config_sha256"]:
        raise ModernReferenceQualificationError("Modern workflow config hash differs")
    try:
        config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        validate_modern_workflow_config(config)
    except (OSError, UnicodeError, yaml.YAMLError, ConfigurationError) as error:
        raise ModernReferenceQualificationError(
            f"Modern workflow config is invalid: {error}"
        ) from error
    qualification_scope = design.get("protocol", {}).get("qualification_scope", "fixed_reference")
    full_atlas = qualification_scope == "full_atlas"
    if design.get("design_version") in {
        FULL_ATLAS_DESIGN_VERSION,
        FULL_ATLAS_CONTINUATION_DESIGN_VERSION,
    }:
        if qualification_scope != "full_atlas":
            raise ModernReferenceQualificationError("Full-atlas qualification scope is missing")
        expected_blocks = ["momenta", "template", "control_points"]
        if design.get("design_version") == FULL_ATLAS_DESIGN_VERSION:
            if config["initialization"]["control_points"]["method"] != (
                "farthest_template_vertices"
            ):
                raise ModernReferenceQualificationError(
                    "Full-atlas qualification must initialize deterministic control points"
                )
            initial_template = _safe_relative(
                root,
                design["initialization"]["template"]["path"],
                "Full-atlas initial template",
            )
            if (
                Path(config["input"]["template"]).as_posix()
                != initial_template.relative_to(root).as_posix()
            ):
                raise ModernReferenceQualificationError(
                    "Full-atlas configuration does not use the frozen initial template"
                )
        elif config["initialization"]["control_points"].get("method") != "file":
            raise ModernReferenceQualificationError(
                "Full-atlas continuation must initialize checkpoint control points"
            )
        if config["optimization"].get("shared_step_scaling") != "inverse_subject_count":
            raise ModernReferenceQualificationError(
                "Full-atlas qualification must scale shared starter steps by cohort size"
            )
    else:
        if qualification_scope not in {None, "fixed_reference"}:
            raise ModernReferenceQualificationError(
                "Fixed-reference qualification scope is invalid"
            )
        expected_blocks = ["momenta"]
    if config["optimization"]["block_order"] != expected_blocks:
        raise ModernReferenceQualificationError(
            "Qualification optimized blocks differ from its declared scope"
        )
    if config["runtime"]["pairwise_evaluation"].get("autograd_strategy") != "recompute":
        raise ModernReferenceQualificationError("Qualification must declare recompute autograd")
    expected_momenta_updates = 2 if full_atlas else 1
    if config["optimization"].get("momenta_updates_per_cycle", 1) != expected_momenta_updates:
        raise ModernReferenceQualificationError(
            "Modern reference qualification momenta schedule differs from its scope"
        )
    if config["optimization"].get("subject_batch_workers", 1) != 1:
        raise ModernReferenceQualificationError(
            "Modern reference qualification requires one subject-batch worker"
        )
    if design.get("design_version") in {
        DESIGN_VERSION,
        FULL_ATLAS_DESIGN_VERSION,
    }:
        expected_engine = design["modern_workflow"].get("expected_engine_implementation")
        if (
            not isinstance(expected_engine, str)
            or re.fullmatch(r"[0-9]+\.[0-9]+", expected_engine) is None
            or config["schema_version"] != CONFIG_VERSION
        ):
            raise ModernReferenceQualificationError(
                "Qualification expected-engine binding is invalid"
            )
    if design.get("design_version") in {
        LEGACY_DESIGN_VERSION,
        DESIGN_VERSION,
        FULL_ATLAS_DESIGN_VERSION,
        *CONTINUATION_DESIGN_VERSIONS,
    }:
        quality_settings = MeshQualitySettings.from_mapping(config["quality_control"])
        for record in design.get("subjects", []):
            subject_path = _safe_relative(
                root,
                record["source"]["path"],
                "Qualification subject",
            )
            subject_mesh = read_vtk_polydata(subject_path)
            source_quality = assess_triangle_mesh(
                subject_mesh.vertices,
                subject_mesh.triangles,
            )
            failures = mesh_quality_failures(source_quality, quality_settings)
            if failures:
                raise ModernReferenceQualificationError(
                    "Qualification subject fails its prospective mesh-quality gates: "
                    f"{record['filename']}: {', '.join(failures)}"
                )
            if source_quality.as_manifest() != record.get("source_quality"):
                raise ModernReferenceQualificationError(
                    f"Qualification subject quality evidence differs: {record['filename']}"
                )
    if design.get("design_version") in CONTINUATION_DESIGN_VERSIONS:
        continuation = design.get("protocol", {}).get("continuation")
        if not isinstance(continuation, dict):
            raise ModernReferenceQualificationError("Continuation lineage is missing")
        for name in (
            "parent_design_sha256",
            "parent_workflow_manifest_sha256",
            "parent_bundle_manifest_sha256",
        ):
            value = continuation.get(name)
            if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
                raise ModernReferenceQualificationError(
                    f"Continuation lineage hash is invalid: {name}"
                )
        if design.get("design_version") in ENGINE_BOUND_CONTINUATION_VERSIONS:
            for name in (
                "parent_engine_implementation",
                "expected_engine_implementation",
            ):
                value = continuation.get(name)
                if not isinstance(value, str) or re.fullmatch(r"[0-9]+\.[0-9]+", value) is None:
                    raise ModernReferenceQualificationError(
                        f"Continuation engine lineage is invalid: {name}"
                    )
            parent_final = continuation.get("parent_final_objective")
            if (
                isinstance(parent_final, bool)
                or not isinstance(parent_final, (int, float))
                or not math.isfinite(float(parent_final))
            ):
                raise ModernReferenceQualificationError(
                    "Continuation parent final objective is invalid"
                )
            workflow_expected_engine = design["modern_workflow"].get(
                "expected_engine_implementation"
            )
            if (
                design.get("design_version")
                in {
                    CONTINUATION_DESIGN_VERSION,
                    FULL_ATLAS_CONTINUATION_DESIGN_VERSION,
                }
                and workflow_expected_engine
                != continuation["expected_engine_implementation"]
            ) or (
                design.get("design_version")
                not in {
                    CONTINUATION_DESIGN_VERSION,
                    FULL_ATLAS_CONTINUATION_DESIGN_VERSION,
                }
                and workflow_expected_engine
                not in (None, continuation["expected_engine_implementation"])
            ):
                raise ModernReferenceQualificationError(
                    "Continuation expected-engine bindings differ"
                )
        momenta_config = config["initialization"]["momenta"]
        if not isinstance(momenta_config, dict) or momenta_config.get("method") != "file":
            raise ModernReferenceQualificationError("Continuation must declare file momenta")
        if (
            design.get("design_version") not in EXACT_CONTINUATION_DESIGN_VERSIONS
            and config["optimization"].get("step_initialization") != "previous_accepted"
        ):
            raise ModernReferenceQualificationError(
                "Legacy continuation must declare previous-accepted steps"
            )
        momenta_path = _safe_relative(
            root,
            momenta_config["path"],
            "Continuation initial momenta",
        )
        if _artifact(root, momenta_path) != continuation.get("initial_momenta"):
            raise ModernReferenceQualificationError("Continuation initial-momenta evidence differs")
        try:
            _read_momenta_rows(
                momenta_path,
                tuple(sorted(record["filename"] for record in design["subjects"])),
                int(design["fixed_reference"]["control_point_count"]),
            )
        except ConfigurationError as error:
            raise ModernReferenceQualificationError(
                f"Continuation initial momenta are invalid: {error}"
            ) from error
        if design.get("design_version") in EXACT_CONTINUATION_DESIGN_VERSIONS:
            checkpoint_root = _safe_directory(
                root,
                continuation.get("checkpoint_path"),
                "Continuation checkpoint",
            )
            checkpoint_manifest = checkpoint_root / CHECKPOINT_MANIFEST_NAME
            if sha256_file(checkpoint_manifest) != continuation.get("checkpoint_manifest_sha256"):
                raise ModernReferenceQualificationError(
                    "Continuation checkpoint manifest hash differs"
                )
            try:
                checkpoint = verify_modern_cycle_checkpoint(checkpoint_root)
            except Exception as error:
                raise ModernReferenceQualificationError(
                    f"Continuation checkpoint is invalid: {error}"
                ) from error
            if (
                checkpoint["checkpoint_version"] != CHECKPOINT_VERSION
                or checkpoint["binding"]["engine_implementation"]
                != continuation["parent_engine_implementation"]
            ):
                raise ModernReferenceQualificationError("Continuation checkpoint identity differs")
            source_effective_record = continuation.get("source_effective_config")
            if not isinstance(source_effective_record, dict):
                raise ModernReferenceQualificationError(
                    "Continuation source effective config evidence is missing"
                )
            source_effective_path = _safe_relative(
                root,
                source_effective_record.get("path"),
                "Continuation source effective config",
            )
            if _artifact(root, source_effective_path) != source_effective_record:
                raise ModernReferenceQualificationError(
                    "Continuation source effective config evidence differs"
                )
            try:
                source_effective = json.loads(
                    source_effective_path.read_text(encoding="utf-8", errors="strict")
                )
                validate_modern_workflow_config(source_effective)
            except (
                OSError,
                UnicodeError,
                json.JSONDecodeError,
                ConfigurationError,
            ) as error:
                raise ModernReferenceQualificationError(
                    f"Continuation source effective config is invalid: {error}"
                ) from error
            resume_state = config["optimization"].get("resume_state")
            expected_resume_state = {
                "checkpoint_directory": checkpoint_root.relative_to(root).as_posix(),
                "checkpoint_manifest_sha256": sha256_file(checkpoint_manifest),
                "source_effective_config": source_effective_path.relative_to(root).as_posix(),
                "source_effective_config_sha256": sha256_file(source_effective_path),
            }
            if resume_state != expected_resume_state:
                raise ModernReferenceQualificationError(
                    "Continuation optimizer-resume binding differs"
                )
            state_momenta = _safe_relative(
                checkpoint_root,
                checkpoint["state"]["momenta"]["path"],
                "Continuation checkpoint momenta",
            )
            if momenta_path != state_momenta:
                raise ModernReferenceQualificationError(
                    "Continuation initial momenta differ from checkpoint state"
                )
            state_template = _safe_relative(
                checkpoint_root,
                checkpoint["state"]["template"]["path"],
                "Continuation checkpoint template",
            )
            configured_template = _safe_relative(
                root,
                config["input"]["template"],
                "Continuation configured template",
            )
            if configured_template != state_template:
                raise ModernReferenceQualificationError(
                    "Continuation initial template differs from checkpoint state"
                )
            state_controls = _safe_relative(
                checkpoint_root,
                checkpoint["state"]["control_points"]["path"],
                "Continuation checkpoint control points",
            )
            control_config = config["initialization"]["control_points"]
            if not isinstance(control_config, dict) or control_config.get("method") != "file":
                raise ModernReferenceQualificationError(
                    "Continuation must declare file control points"
                )
            configured_controls = _safe_relative(
                root,
                control_config["path"],
                "Continuation configured control points",
            )
            if configured_controls != state_controls:
                raise ModernReferenceQualificationError(
                    "Continuation initial control points differ from checkpoint state"
                )
    observed_html = (root / DESIGN_HTML_NAME).read_text(encoding="utf-8")
    expected_html = _render_design_html(design)
    if observed_html != expected_html:
        mismatch = next(
            (
                index
                for index, (observed, expected) in enumerate(
                    zip(observed_html, expected_html, strict=False)
                )
                if observed != expected
            ),
            min(len(observed_html), len(expected_html)),
        )
        raise ModernReferenceQualificationError(
            "Qualification review HTML differs from deterministic regeneration "
            f"at character {mismatch}: observed "
            f"{observed_html[mismatch : mismatch + 40]!r}; expected "
            f"{expected_html[mismatch : mismatch + 40]!r}"
        )
    return design


def _quantile(values: np.ndarray) -> float:
    return float(np.quantile(values, 0.95, method="linear"))


def _ratio(numerator: float, denominator: float) -> float:
    if denominator <= np.finfo(float).eps:
        return 1.0 if numerator <= np.finfo(float).eps else math.inf
    return numerator / denominator


def _validate_metric_workers(metric_workers: int) -> int:
    if isinstance(metric_workers, bool) or not isinstance(metric_workers, int):
        raise TypeError("Qualification metric workers must be an integer")
    if not 1 <= metric_workers <= 8:
        raise ValueError("Qualification metric workers must be between 1 and 8")
    return metric_workers


def _qualification_subject_metrics(
    design_root: Path,
    record: dict[str, Any],
    modern_reconstruction_path: Path,
    subject_limit: float,
) -> tuple[dict[str, Any], np.ndarray, np.ndarray, np.ndarray]:
    """Measure one frozen subject without changing deterministic report order."""

    name = record["filename"]
    target = read_vtk_polydata(
        _safe_relative(design_root, record["source"]["path"], "Qualification subject")
    )
    reference_reconstruction = read_vtk_polydata(
        _safe_relative(
            design_root,
            record["reference_reconstruction"]["path"],
            "Reference reconstruction",
        )
    )
    modern_reconstruction = read_vtk_polydata(modern_reconstruction_path)
    reference_distances = symmetric_vertex_to_surface_distances(
        target, reference_reconstruction
    )
    modern_distances = symmetric_vertex_to_surface_distances(target, modern_reconstruction)
    cross_distances = symmetric_vertex_to_surface_distances(
        reference_reconstruction, modern_reconstruction
    )
    reference_p95 = _quantile(reference_distances)
    modern_p95 = _quantile(modern_distances)
    ratio = _ratio(modern_p95, reference_p95)
    return (
        {
            "filename": name,
            "reference_external_residual_p95": reference_p95,
            "modern_external_residual_p95": modern_p95,
            "modern_to_reference_residual_ratio": ratio,
            "cross_engine_reconstruction_p95": _quantile(cross_distances),
            "subject_gate_pass": ratio <= subject_limit,
        },
        reference_distances,
        modern_distances,
        cross_distances,
    )


def _optimizer_trajectory_evidence(
    history_rows: list[dict[str, str]],
) -> dict[str, Any]:
    """Normalize the verified optimizer CSV into explicit convergence evidence."""

    records: list[dict[str, Any]] = []
    allowed_statuses = {"initial", "accepted", "stationary", "failed"}
    try:
        for index, row in enumerate(history_rows):
            status = row["status"]
            cycle = int(row["cycle"])
            objective = float(row["objective"])
            attachment = float(row["attachment"])
            regularity = float(row["regularity"])
            gradient_text = row["gradient_norm"]
            step_text = row["accepted_step_size"]
            line_search_evaluations = int(row["line_search_evaluations"])
            gradient_norm = None if not gradient_text else float(gradient_text)
            accepted_step_size = None if not step_text else float(step_text)
            if (
                status not in allowed_statuses
                or cycle < 0
                or line_search_evaluations < 0
                or not all(math.isfinite(value) for value in (objective, attachment, regularity))
                or (
                    gradient_norm is not None
                    and (not math.isfinite(gradient_norm) or gradient_norm < 0.0)
                )
                or (
                    accepted_step_size is not None
                    and (not math.isfinite(accepted_step_size) or accepted_step_size <= 0.0)
                )
            ):
                raise ValueError("invalid optimizer history value")
            block = row["block"] or None
            if index == 0:
                if cycle != 0 or status != "initial" or block is not None:
                    raise ValueError("invalid initial optimizer history record")
            elif cycle < 1 or block not in {"momenta", "template", "control_points"}:
                raise ValueError("invalid optimizer decision history record")
            records.append(
                {
                    "cycle": cycle,
                    "block": block,
                    "status": status,
                    "objective": objective,
                    "attachment": attachment,
                    "regularity": regularity,
                    "gradient_norm": gradient_norm,
                    "accepted_step_size": accepted_step_size,
                    "line_search_evaluations": line_search_evaluations,
                }
            )
    except (KeyError, TypeError, ValueError) as error:
        raise ModernReferenceQualificationError(
            "Modern optimizer history contains invalid convergence evidence"
        ) from error
    objectives = [record["objective"] for record in records]
    gradient_norms = [
        record["gradient_norm"] for record in records if record["gradient_norm"] is not None
    ]
    decisions = records[1:]
    return {
        "initial_objective": objectives[0],
        "final_objective": objectives[-1],
        "objective_gain": objectives[-1] - objectives[0],
        "objective_nondecreasing": all(later >= earlier for earlier, later in pairwise(objectives)),
        "decision_count": len(decisions),
        "accepted_decisions": sum(record["status"] == "accepted" for record in decisions),
        "stationary_decisions": sum(record["status"] == "stationary" for record in decisions),
        "failed_decisions": sum(record["status"] == "failed" for record in decisions),
        "minimum_observed_gradient_norm": min(gradient_norms) if gradient_norms else None,
        "final_observed_gradient_norm": gradient_norms[-1] if gradient_norms else None,
        "records": records,
    }


def _render_assessment_html(assessment: dict[str, Any]) -> str:
    def optional_number(value: float | None) -> str:
        return "n/a" if value is None else f"{value:.6g}"

    rows = "".join(
        "<tr>"
        f"<td><code>{escape(row['filename'])}</code></td>"
        f"<td>{row['reference_external_residual_p95']:.6g}</td>"
        f"<td>{row['modern_external_residual_p95']:.6g}</td>"
        f"<td>{row['modern_to_reference_residual_ratio']:.4g}</td>"
        f"<td>{escape(str(row['subject_gate_pass']).lower())}</td></tr>"
        for row in assessment["subjects"]
    )
    optimizer = assessment.get("optimizer")
    trajectory = None if not isinstance(optimizer, dict) else optimizer.get("trajectory")
    trajectory_rows = (
        ""
        if not isinstance(trajectory, dict)
        else "".join(
            "<tr>"
            f"<td>{record['cycle']}</td>"
            f"<td>{escape(str(record['status']))}</td>"
            f"<td>{record['objective']:.12g}</td>"
            f"<td>{optional_number(record['gradient_norm'])}</td>"
            f"<td>{optional_number(record['accepted_step_size'])}</td>"
            f"<td>{record['line_search_evaluations']}</td></tr>"
            for record in trajectory["records"]
        )
    )
    trajectory_html = (
        ""
        if not isinstance(trajectory, dict)
        else (
            f"<li>Objective gain: {trajectory['objective_gain']:.12g}; "
            "non-decreasing: "
            f"{escape(str(trajectory['objective_nondecreasing']).lower())}</li>"
            f"<li>Accepted/stationary/failed decisions: "
            f"{trajectory['accepted_decisions']}/{trajectory['stationary_decisions']}/"
            f"{trajectory['failed_decisions']}</li>"
            f"<li>Final observed gradient norm: "
            f"{optional_number(trajectory['final_observed_gradient_norm'])}</li>"
        )
    )
    optimizer_html = (
        ""
        if not isinstance(optimizer, dict)
        else (
            "<h2>Verified optimizer evidence</h2><ul>"
            f"<li>Engine implementation: {escape(str(optimizer['engine_implementation']))}</li>"
            f"<li>Termination: {escape(str(optimizer['termination_reason']))}; "
            f"converged: {escape(str(optimizer['converged']).lower())}; "
            f"cycles: {optimizer['cycles_completed']}</li>"
            f"<li>Line-search evaluations: {optimizer['total_line_search_evaluations']}</li>"
            f"<li>Final objective: {optimizer['final_objective']:.12g}</li>"
            f"{trajectory_html}</ul>"
            + (
                ""
                if not trajectory_rows
                else (
                    "<h3>Optimizer trajectory</h3><table><thead><tr>"
                    "<th>Cycle</th><th>Status</th><th>Objective</th><th>Gradient norm</th>"
                    "<th>Accepted step</th><th>Line-search evaluations</th></tr></thead>"
                    f"<tbody>{trajectory_rows}</tbody></table>"
                )
            )
        )
    )
    continuation = assessment.get("continuation_verification")
    continuation_html = (
        ""
        if not isinstance(continuation, dict)
        else (
            "<h2>Continuation binding</h2><ul>"
            f"<li>Parent final objective: {continuation['parent_final_objective']:.12g}</li>"
            f"<li>Successor initial objective: "
            f"{continuation['successor_initial_objective']:.12g}</li>"
            "<li>Initial objective matches the hash-bound parent: true</li></ul>"
        )
    )
    template_metric = assessment.get("metrics", {}).get(
        "cross_engine_template_p95_over_reference_diagonal"
    )
    template_html = (
        ""
        if template_metric is None
        else (
            "<h2>Estimated-template comparison</h2><p>Symmetric surface-distance p95 "
            f"/ reference-template diagonal: {float(template_metric):.6g}</p>"
        )
    )
    return f"""<!doctype html><html lang="en"><meta charset="utf-8">
<title>Modern fixed-reference qualification assessment</title>
<style>body{{font:16px system-ui;max-width:1080px;margin:2rem auto;line-height:1.45}}
table{{border-collapse:collapse}}td,th{{border:1px solid #ccd;padding:.4rem}}
.result{{font-size:1.3rem;font-weight:700}}</style>
<h1>Modern Engine fixed-reference qualification assessment</h1>
<p class="result">Engineering gate result: {escape(assessment["decision"]["status"])}</p>
<p>{escape(assessment["scientific_boundary"])}</p>
{optimizer_html}{continuation_html}{template_html}
<table><thead><tr><th>Subject</th><th>Reference p95</th><th>Modern p95</th>
<th>ratio</th><th>subject gate</th></tr></thead><tbody>{rows}</tbody></table>
</html>\n"""


def assess_modern_reference_qualification(
    design_directory: Path | str,
    modern_run: Path | str,
    destination: Path | str,
    *,
    created_at: str | None = None,
    metric_workers: int = 1,
    progress_callback: QualificationMetricProgress | None = None,
) -> Path:
    """Compare independently verified reconstructions with common external metrics."""

    metric_workers = _validate_metric_workers(metric_workers)

    design_root = Path(design_directory).expanduser().resolve()
    design = verify_modern_reference_qualification_design(design_root)
    modern_root = Path(modern_run).expanduser().resolve()
    workflow = verify_modern_workflow(modern_root)
    expected_engine = design["modern_workflow"].get("expected_engine_implementation")
    if (
        expected_engine is not None
        and workflow["engine"].get("implementation_version") != expected_engine
    ):
        raise ModernReferenceQualificationError(
            "Modern run engine implementation differs from its frozen design"
        )
    source_config = modern_root / Path(*PurePosixPath(workflow["config"]["source_path"]).parts)
    if sha256_file(source_config) != design["modern_workflow"]["config_sha256"]:
        raise ModernReferenceQualificationError(
            "Modern run was not created from the frozen qualification configuration"
        )
    bundle_root = modern_root / Path(*PurePosixPath(workflow["result_bundle"]["path"]).parts)
    bundle = verify_modern_atlas_bundle(bundle_root)
    history_path = _safe_relative(
        bundle_root,
        bundle["optimizer"]["history_path"],
        "Modern optimizer history",
    )
    try:
        with history_path.open(encoding="utf-8", newline="") as handle:
            history_rows = list(csv.DictReader(handle))
    except (OSError, UnicodeError, csv.Error) as error:
        raise ModernReferenceQualificationError(
            f"Modern optimizer history is unreadable: {error}"
        ) from error
    if not history_rows or history_rows[0].get("status") != "initial":
        raise ModernReferenceQualificationError(
            "Modern optimizer history does not begin with its initial state"
        )
    trajectory_evidence = _optimizer_trajectory_evidence(history_rows)
    final_record = trajectory_evidence["records"][-1]
    for history_name, bundle_name in (
        ("objective", "final_objective"),
        ("attachment", "final_attachment"),
        ("regularity", "final_regularity"),
    ):
        if not math.isclose(
            float(final_record[history_name]),
            float(bundle["optimizer"][bundle_name]),
            rel_tol=1e-12,
            abs_tol=1e-12,
        ):
            raise ModernReferenceQualificationError(
                "Modern optimizer history final components differ from the verified bundle"
            )
    if sum(
        int(record["line_search_evaluations"]) for record in trajectory_evidence["records"]
    ) != int(bundle["optimizer"]["total_line_search_evaluations"]):
        raise ModernReferenceQualificationError(
            "Modern optimizer history line-search count differs from the verified bundle"
        )
    continuation_verification = None
    if design.get("design_version") in ENGINE_BOUND_CONTINUATION_VERSIONS:
        continuation = design["protocol"]["continuation"]
        expected_implementation = continuation["expected_engine_implementation"]
        observed_implementation = workflow["engine"].get("implementation_version")
        if observed_implementation != expected_implementation:
            raise ModernReferenceQualificationError(
                "Continuation run engine implementation differs from its frozen design"
            )
        parent_final = float(continuation["parent_final_objective"])
        successor_initial = float(history_rows[0]["objective"])
        tolerance = max(1e-12, abs(parent_final) * 1e-12)
        if not math.isclose(
            successor_initial,
            parent_final,
            rel_tol=1e-12,
            abs_tol=tolerance,
        ):
            raise ModernReferenceQualificationError(
                "Continuation successor initial objective differs from the parent final objective"
            )
        continuation_verification = {
            "parent_engine_implementation": continuation["parent_engine_implementation"],
            "successor_engine_implementation": observed_implementation,
            "parent_final_objective": parent_final,
            "successor_initial_objective": successor_initial,
            "initial_objective_matches": True,
        }
    modern_reconstructions = {
        record["label"]: bundle_root / Path(*PurePosixPath(record["reconstruction_path"]).parts)
        for record in bundle["subjects"]
    }
    expected_names = {record["filename"] for record in design["subjects"]}
    if set(modern_reconstructions) != expected_names:
        raise ModernReferenceQualificationError(
            "Modern run subject labels differ from the prospective design"
        )
    template_path = _safe_relative(
        design_root,
        design["fixed_reference"]["template"]["path"],
        "Fixed reference template",
    )
    template_diagonal = inspect_vtk(template_path).bounding_box_diagonal
    qualification_scope = design.get("protocol", {}).get("qualification_scope", "fixed_reference")
    cross_template_normalized: float | None = None
    if qualification_scope == "full_atlas":
        modern_template_path = _safe_relative(
            bundle_root,
            bundle["template"]["path"],
            "Modern estimated template",
        )
        reference_template_mesh = read_vtk_polydata(template_path)
        modern_template_mesh = read_vtk_polydata(modern_template_path)
        cross_template_normalized = (
            _quantile(
                symmetric_vertex_to_surface_distances(
                    reference_template_mesh,
                    modern_template_mesh,
                )
            )
            / template_diagonal
        )
    subject_rows: list[dict[str, Any]] = []
    reference_parts: list[np.ndarray] = []
    modern_parts: list[np.ndarray] = []
    cross_parts: list[np.ndarray] = []
    subject_limit = float(design["decision_gates"]["subject_external_residual_ratio_maximum"])
    records = list(design["subjects"])

    def measure(
        record: dict[str, Any],
    ) -> tuple[dict[str, Any], np.ndarray, np.ndarray, np.ndarray]:
        return _qualification_subject_metrics(
            design_root,
            record,
            modern_reconstructions[record["filename"]],
            subject_limit,
        )

    worker_count = min(metric_workers, len(records))
    if worker_count == 1:
        measured = map(measure, records)
        executor = None
    else:
        executor = ThreadPoolExecutor(
            max_workers=worker_count,
            thread_name_prefix="qualification-metric",
        )
        measured = executor.map(measure, records)
    try:
        for completed, result in enumerate(measured, start=1):
            subject_row, reference_distances, modern_distances, cross_distances = result
            subject_rows.append(subject_row)
            reference_parts.append(reference_distances)
            modern_parts.append(modern_distances)
            cross_parts.append(cross_distances)
            if progress_callback is not None:
                progress_callback(completed, len(records), subject_row["filename"])
    finally:
        if executor is not None:
            executor.shutdown(wait=True, cancel_futures=True)
    pooled_reference = _quantile(np.concatenate(reference_parts))
    pooled_modern = _quantile(np.concatenate(modern_parts))
    pooled_ratio = _ratio(pooled_modern, pooled_reference)
    cross_normalized = _quantile(np.concatenate(cross_parts)) / template_diagonal
    pass_fraction = sum(row["subject_gate_pass"] for row in subject_rows) / len(subject_rows)
    gates = design["decision_gates"]
    gate_results = {
        "modern_workflow_verification": True,
        "modern_optimizer_converged": bool(bundle["optimizer"]["converged"]),
        "pooled_external_residual_ratio": pooled_ratio
        <= float(gates["pooled_external_residual_ratio_maximum"]),
        "minimum_subject_pass_fraction": pass_fraction
        >= float(gates["minimum_subject_pass_fraction"]),
        "cross_engine_reconstruction_distance": cross_normalized
        <= float(gates["cross_engine_reconstruction_p95_over_template_diagonal_maximum"]),
        **(
            {
                "cross_engine_template_distance": cross_template_normalized
                <= float(gates["cross_engine_template_p95_over_reference_diagonal_maximum"])
            }
            if cross_template_normalized is not None
            else {}
        ),
    }
    converged = gate_results["modern_optimizer_converged"]
    decision_status = (
        "inconclusive_not_converged"
        if not converged
        else ("pass" if all(gate_results.values()) else "fail")
    )
    assessment: dict[str, Any] = {
        "assessment_version": "0.3",
        "created_at": created_at or datetime.now(UTC).isoformat(),
        "design": {
            "path": str(design_root),
            "sha256": sha256_file(design_root / DESIGN_JSON_NAME),
        },
        "modern_run": {
            "path": str(modern_root),
            "workflow_manifest_sha256": sha256_file(modern_root / "workflow-manifest.json"),
        },
        "optimizer": {
            "engine_implementation": workflow["engine"].get("implementation_version"),
            "termination_reason": bundle["optimizer"]["termination_reason"],
            "converged": bundle["optimizer"]["converged"],
            "cycles_completed": bundle["optimizer"]["cycles_completed"],
            "total_line_search_evaluations": bundle["optimizer"]["total_line_search_evaluations"],
            "final_objective": bundle["optimizer"]["final_objective"],
            "final_attachment": bundle["optimizer"]["final_attachment"],
            "final_regularity": bundle["optimizer"]["final_regularity"],
            "history_sha256": sha256_file(history_path),
            "trajectory": trajectory_evidence,
        },
        **(
            {}
            if continuation_verification is None
            else {"continuation_verification": continuation_verification}
        ),
        "metrics": {
            "method": "deterministic sampled symmetric vertex-to-triangle surface distance",
            "pooled_reference_external_residual_p95": pooled_reference,
            "pooled_modern_external_residual_p95": pooled_modern,
            "pooled_modern_to_reference_residual_ratio": pooled_ratio,
            "subject_pass_fraction": pass_fraction,
            "cross_engine_reconstruction_p95_over_template_diagonal": cross_normalized,
            **(
                {
                    "cross_engine_template_p95_over_reference_diagonal": (
                        cross_template_normalized
                    ),
                }
                if cross_template_normalized is not None
                else {}
            ),
        },
        "subjects": subject_rows,
        "decision": {
            "status": decision_status,
            "gate_results": gate_results,
            "predeclared_gates": gates,
        },
        "scientific_boundary": design["scientific_boundary"],
    }
    output = Path(destination).expanduser().resolve()
    if output.exists():
        raise FileExistsError(f"Qualification assessment destination already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.parent / f".{output.name}.tmp-{uuid.uuid4().hex}"
    temporary.mkdir()
    try:
        json_path = temporary / ASSESSMENT_JSON_NAME
        _write_json_exclusive(json_path, assessment)
        (temporary / ASSESSMENT_HTML_NAME).write_text(
            _render_assessment_html(assessment), encoding="utf-8", newline="\n"
        )
        (temporary / ASSESSMENT_SIDECAR_NAME).write_text(
            f"{sha256_file(json_path)}  {ASSESSMENT_JSON_NAME}\n",
            encoding="ascii",
            newline="\n",
        )
        temporary.rename(output)
    except Exception:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise
    return output


def verify_modern_reference_qualification_assessment(
    assessment_directory: Path | str,
    *,
    metric_workers: int = 1,
    progress_callback: QualificationMetricProgress | None = None,
) -> dict[str, Any]:
    """Recompute and strictly verify one published qualification assessment."""

    metric_workers = _validate_metric_workers(metric_workers)

    root = Path(assessment_directory).expanduser().resolve()
    expected_names = {
        ASSESSMENT_JSON_NAME,
        ASSESSMENT_SIDECAR_NAME,
        ASSESSMENT_HTML_NAME,
    }
    if (
        not root.is_dir()
        or root.is_symlink()
        or {path.name for path in root.iterdir()} != expected_names
    ):
        raise ModernReferenceQualificationError(
            "Qualification assessment directory has unexpected files"
        )
    json_path = root / ASSESSMENT_JSON_NAME
    expected_sidecar = f"{sha256_file(json_path)}  {ASSESSMENT_JSON_NAME}"
    sidecar_path = root / ASSESSMENT_SIDECAR_NAME
    if (
        not sidecar_path.is_file()
        or sidecar_path.is_symlink()
        or sidecar_path.read_text(encoding="ascii").strip() != expected_sidecar
    ):
        raise ModernReferenceQualificationError("Qualification assessment SHA-256 sidecar differs")
    try:
        assessment = json.loads(json_path.read_text(encoding="utf-8", errors="strict"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ModernReferenceQualificationError(
            f"Qualification assessment is unreadable: {error}"
        ) from error
    if (
        not isinstance(assessment, dict)
        or assessment.get("assessment_version") not in {"0.1", "0.2", "0.3"}
        or not isinstance(assessment.get("created_at"), str)
        or not assessment["created_at"]
    ):
        raise ModernReferenceQualificationError("Qualification assessment identity is invalid")
    try:
        design_path = Path(assessment["design"]["path"])
        modern_run = Path(assessment["modern_run"]["path"])
    except (KeyError, TypeError) as error:
        raise ModernReferenceQualificationError(
            "Qualification assessment source binding is invalid"
        ) from error

    with tempfile.TemporaryDirectory(
        prefix="diffeoforge-qualification-assessment-verify-",
    ) as temporary_value:
        expected_root = Path(temporary_value) / "expected"
        assess_modern_reference_qualification(
            design_path,
            modern_run,
            expected_root,
            created_at=assessment["created_at"],
            metric_workers=metric_workers,
            progress_callback=progress_callback,
        )
        expected = json.loads((expected_root / ASSESSMENT_JSON_NAME).read_text(encoding="utf-8"))
        if assessment["assessment_version"] == "0.1":
            expected["assessment_version"] = "0.1"
            expected.pop("optimizer", None)
            expected.pop("continuation_verification", None)
        elif assessment["assessment_version"] == "0.2":
            expected["assessment_version"] = "0.2"
            expected["optimizer"].pop("trajectory", None)
        if assessment != expected:
            raise ModernReferenceQualificationError(
                "Qualification assessment differs from deterministic recomputation"
            )
        expected_html = _render_assessment_html(expected)
    observed_html = (root / ASSESSMENT_HTML_NAME).read_text(
        encoding="utf-8",
        errors="strict",
    )
    if observed_html != expected_html:
        raise ModernReferenceQualificationError(
            "Qualification assessment HTML differs from deterministic regeneration"
        )
    return assessment
