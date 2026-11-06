"""Opt-in independent Modern momenta fits on one fixed reference basis."""

from __future__ import annotations

import csv
import json
import math
import re
import shutil
import uuid
from collections.abc import Callable
from dataclasses import asdict, fields
from importlib.resources import files
from pathlib import Path, PurePosixPath
from typing import Any

import jsonschema
import numpy as np
import torch

from diffeoforge import __version__
from diffeoforge.config import ConfigurationError, validate_input_paths
from diffeoforge.engine import flow_points, shoot
from diffeoforge.engine.atlas_optimizer import (
    AtlasOptimizationCancelled,
    AtlasOptimizationRecord,
    optimize_atlas,
)
from diffeoforge.engine.execution import ENGINE_IMPLEMENTATION_VERSION
from diffeoforge.mesh import TriangleMesh, read_vtk_polydata, sha256_file, write_vtk_polydata
from diffeoforge.mesh_quality import (
    MeshQualitySettings,
    assess_triangle_mesh,
    compare_triangle_meshes,
    enforce_deformation_quality,
    enforce_mesh_quality,
)
from diffeoforge.modern_workflow import (
    _artifact,
    _copy_exclusive,
    _read_control_point_rows,
    _read_momenta_rows,
    _resolve_from_config,
    _timestamp,
    _write_json_exclusive,
    configure_modern_torch_runtime,
    load_modern_workflow_config,
    modern_optimizer_arguments,
    pairwise_evaluation_from_config,
    validate_modern_workflow_config,
)
from diffeoforge.private_runs import (
    LEASE_NAME,
    MARKER_NAME,
    PrivateRunLease,
    acquire_private_run_lease,
    discover_private_runs,
)

MANIFEST_NAME = "fixed-reference-manifest.json"
SIDECAR_NAME = "fixed-reference-manifest.sha256"
FORMAT_VERSION = "0.1"
SCIENTIFIC_BOUNDARY = (
    "Independent momentum fits against a frozen template and fixed control points. "
    "This job does not estimate an atlas or PCA, qualify biological accuracy, "
    "or publish resumable optimizer checkpoints."
)
_SOURCE_CONFIG = "config/source.yaml"
_EFFECTIVE_CONFIG = "config/effective-config.json"
_TEMPLATE = "input/template.vtk"
_CONTROLS = "input/control-points.txt"
_TRACE_FIELDS = {field.name for field in fields(AtlasOptimizationRecord)}
_PRIVATE_ONLY = {MARKER_NAME, LEASE_NAME}
_STAGING_NAME = re.compile(r"^\..+\.tmp-[0-9a-f]{32}$", re.IGNORECASE)
ProgressCallback = Callable[[str, int, int, AtlasOptimizationRecord], None]


class ModernFixedReferenceError(RuntimeError):
    """A fixed-reference job could not be published or verified."""


class ModernFixedReferenceCancelled(ModernFixedReferenceError):
    """The job was cancelled before publication."""


def _validate_recipe(config: dict[str, Any]) -> None:
    optimizer = config["optimization"]
    initialization = config["initialization"]
    if config["runtime"]["device"] != "cpu":
        raise ConfigurationError("Modern fixed-reference jobs require runtime.device=cpu")
    if config["preprocessing"]["procrustes"]["enabled"]:
        raise ConfigurationError(
            "Modern fixed-reference jobs require disabled Procrustes alignment"
        )
    if initialization["control_points"]["method"] != "file":
        raise ConfigurationError("Modern fixed-reference jobs require explicit control points")
    if initialization["momenta"] != "zeros":
        raise ConfigurationError("Modern fixed-reference jobs require zero initial momenta")
    if (
        optimizer["block_order"] != ["momenta"]
        or optimizer.get("momenta_updates_per_cycle", 1) != 1
    ):
        raise ConfigurationError("Modern fixed-reference jobs require one momenta update per cycle")
    if type(optimizer["max_cycles"]) is not int or optimizer["max_cycles"] < 1:
        raise ConfigurationError(
            "Modern fixed-reference jobs require a positive cycle cap per subject"
        )
    if (
        optimizer.get("subject_batch_size") not in (None, 1)
        or optimizer.get("subject_batch_workers", 1) != 1
    ):
        raise ConfigurationError("Modern fixed-reference jobs execute one subject at a time")
    if optimizer.get("resume_state") is not None:
        raise ConfigurationError("Modern fixed-reference job recovery is unsupported")


def _optimizer_policy(config: dict[str, Any]) -> dict[str, Any]:
    return {
        "mode": "independent_momenta",
        "max_cycles_per_subject": config["optimization"]["max_cycles"],
        "initial_momenta": "zeros",
        "checkpoint_policy": "none",
    }


def _check_cancel(cancel_requested: Callable[[], bool] | None) -> None:
    if cancel_requested is not None:
        requested = cancel_requested()
        if not isinstance(requested, bool):
            raise TypeError("cancel_requested must return bool")
        if requested:
            raise ModernFixedReferenceCancelled("Modern fixed-reference job cancelled")


def _mesh_record(path: str, mesh: TriangleMesh) -> dict[str, Any]:
    return {"path": path, "points": len(mesh.vertices), "triangles": len(mesh.triangles)}


def _subject_paths(index: int) -> dict[str, str]:
    directory = f"subjects/subject-{index:04d}"
    return {
        "reconstruction_path": f"{directory}/reconstruction.vtk",
        "momenta_path": f"{directory}/momenta.csv",
        "history_path": f"{directory}/history.json",
    }


def _target_path(index: int) -> str:
    return f"input/subjects/subject-{index:04d}.vtk"


def _check_label(label: str) -> None:
    if (
        not label.lower().endswith(".vtk")
        or any(character in "/\\:" or ord(character) < 32 for character in label)
        or Path(label).name != label
    ):
        raise ModernFixedReferenceError(f"Unsafe fixed-reference subject label: {label!r}")


def _checked_mesh(root: Path, path: str, settings: MeshQualitySettings) -> TriangleMesh:
    mesh = read_vtk_polydata(root / path)
    quality = assess_triangle_mesh(mesh.vertices, mesh.triangles)
    if quality.zero_area_faces:
        raise ModernFixedReferenceError(f"Zero-area triangles in {path}")
    enforce_mesh_quality(path, quality, settings)
    return mesh


def _check_deformation(
    label: str,
    reference: TriangleMesh,
    fitted: TriangleMesh,
    settings: MeshQualitySettings,
) -> None:
    if fitted.triangles != reference.triangles or len(fitted.vertices) != len(reference.vertices):
        raise ModernFixedReferenceError(f"Reconstruction connectivity differs for {label}")
    quality = compare_triangle_meshes(
        reference.vertices,
        reference.triangles,
        fitted.vertices,
        fitted.triangles,
    )
    enforce_deformation_quality(label, quality, settings)


def _write_momenta(path: Path, label: str, values: torch.Tensor) -> None:
    with path.open("x", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(("subject_label", "control_point", "x", "y", "z"))
        for index, point in enumerate(values.tolist()):
            writer.writerow((label, index, *(format(value, ".17g") for value in point)))


def _fit_subject(
    root: Path,
    index: int,
    label: str,
    mesh: TriangleMesh,
    template: torch.Tensor,
    triangles: torch.Tensor,
    controls: torch.Tensor,
    optimizer_arguments: dict[str, Any],
    progress: Callable[[AtlasOptimizationRecord], None] | None,
    cancel_requested: Callable[[], bool] | None,
) -> dict[str, Any]:
    targets = (
        (
            torch.tensor(mesh.vertices, dtype=torch.float64, device="cpu"),
            torch.tensor(mesh.triangles, dtype=torch.int64, device="cpu"),
        ),
    )
    initial_momenta = torch.zeros((1, len(controls), 3), dtype=torch.float64, device="cpu")
    result = optimize_atlas(
        template,
        triangles,
        targets,
        controls,
        initial_momenta,
        **optimizer_arguments,
        progress_callback=progress,
        cancel_requested=cancel_requested,
    )
    if result.termination_reason == "line_search_failed":
        raise ModernFixedReferenceError(f"Line search failed for {label}")
    if not torch.equal(result.template_vertices, template) or not torch.equal(
        result.control_points, controls
    ):
        raise ModernFixedReferenceError(f"Fixed reference basis changed for {label}")
    _check_cancel(cancel_requested)
    width = optimizer_arguments["deformation_kernel_width"]
    tile = optimizer_arguments["gaussian_tile_plan"]
    with torch.no_grad():
        trajectory = shoot(
            controls,
            result.momenta[0],
            width,
            optimizer_arguments["number_of_time_points"],
            integrator=optimizer_arguments["shooting_integrator"],
            gaussian_tile_plan=tile,
        )
        _check_cancel(cancel_requested)
        vertices = flow_points(
            template,
            trajectory,
            width,
            integrator=optimizer_arguments["flow_integrator"],
            gaussian_tile_plan=tile,
        )[-1]
    _check_cancel(cancel_requested)
    paths = _subject_paths(index)
    reconstruction = root / paths["reconstruction_path"]
    reconstruction.parent.mkdir(parents=True)
    write_vtk_polydata(reconstruction, vertices.tolist(), triangles.tolist())
    _write_momenta(root / paths["momenta_path"], label, result.momenta[0])
    _write_json_exclusive(
        root / paths["history_path"], [asdict(record) for record in result.history]
    )
    return {
        "label": label,
        **paths,
        "optimizer": {
            "cycles_completed": result.cycles_completed,
            "termination_reason": result.termination_reason,
            "converged": result.converged,
            "total_line_search_evaluations": result.total_line_search_evaluations,
            "objective_evaluations": result.objective_evaluations,
            "gradient_evaluations": result.gradient_evaluations,
            "candidate_gradient_evaluations": result.candidate_gradient_evaluations,
        },
    }


def run_modern_fixed_reference(
    config_path: Path | str,
    *,
    destination: Path | str,
    progress_callback: ProgressCallback | None = None,
    cancel_requested: Callable[[], bool] | None = None,
    created_at: str | None = None,
) -> Path:
    """Run ordered, independent CPU fits and atomically publish the verified job."""
    if progress_callback is not None and not callable(progress_callback):
        raise TypeError("progress_callback must be callable or None")
    if cancel_requested is not None and not callable(cancel_requested):
        raise TypeError("cancel_requested must be callable or None")
    source = Path(config_path).expanduser().resolve()
    config = load_modern_workflow_config(source)
    _validate_recipe(config)
    _check_cancel(cancel_requested)
    inputs = validate_input_paths(config, source, minimum_subject_count=1)
    subjects = sorted(inputs.subjects, key=lambda path: path.name.casefold())
    for subject in subjects:
        _check_label(subject.name)
    initialization = config["initialization"]["control_points"]
    control_source = _resolve_from_config(initialization["path"], source)
    raw_output = Path(destination).expanduser()
    if raw_output.is_symlink():
        raise FileExistsError(f"Fixed-reference destination already exists: {raw_output}")
    output = raw_output.resolve()
    if _STAGING_NAME.fullmatch(output.name):
        raise ConfigurationError("Fixed-reference destination uses a reserved staging name")
    if output.exists():
        raise FileExistsError(f"Fixed-reference destination already exists: {output}")
    if discover_private_runs(output).candidates:
        raise ModernFixedReferenceError(
            "Private unpublished state already exists for this destination"
        )
    timestamp = _timestamp(created_at)
    runtime = config["runtime"]
    pairwise = pairwise_evaluation_from_config(config)
    settings = MeshQualitySettings.from_mapping(config["quality_control"])
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.parent / f".{output.name}.tmp-{uuid.uuid4().hex}"
    temporary.mkdir()
    lease: PrivateRunLease | None = None
    previous_threads = torch.get_num_threads()
    previous_determinism = torch.are_deterministic_algorithms_enabled()
    previous_warn_only = torch.is_deterministic_algorithms_warn_only_enabled()
    try:
        lease = acquire_private_run_lease(temporary, output, operation="modern_fixed_reference")
        _copy_exclusive(source, temporary / _SOURCE_CONFIG)
        if load_modern_workflow_config(temporary / _SOURCE_CONFIG) != config:
            raise ModernFixedReferenceError("Source configuration changed during staging")
        _write_json_exclusive(temporary / _EFFECTIVE_CONFIG, config)
        _copy_exclusive(inputs.template, temporary / _TEMPLATE)
        _copy_exclusive(control_source, temporary / _CONTROLS)
        template = _checked_mesh(temporary, _TEMPLATE, settings)
        control_values = _read_control_point_rows(temporary / _CONTROLS, initialization["count"])
        input_subjects = []
        for index, subject in enumerate(subjects, 1):
            _check_cancel(cancel_requested)
            path = _target_path(index)
            _copy_exclusive(subject, temporary / path)
            mesh = _checked_mesh(temporary, path, settings)
            input_subjects.append({"label": subject.name, **_mesh_record(path, mesh)})

        result_subjects = []
        template_tensor = torch.tensor(template.vertices, dtype=torch.float64, device="cpu")
        triangle_tensor = torch.tensor(template.triangles, dtype=torch.int64, device="cpu")
        controls = torch.tensor(control_values, dtype=torch.float64, device="cpu")
        model = config["model"]
        deformation, attachment = model["deformation"], model["attachment"]
        optimizer_arguments = modern_optimizer_arguments(config) | {
            "deformation_kernel_width": deformation["kernel_width"],
            "attachment_kernel_width": attachment["kernel_width"],
            "noise_variance": model["noise_variance"],
            "number_of_time_points": deformation["timepoints"],
            "attachment_type": attachment["type"],
            "shooting_integrator": deformation["shooting_integrator"],
            "flow_integrator": deformation["flow_integrator"],
            "gaussian_tile_plan": pairwise.gaussian_tile_plan,
        }
        with torch.random.fork_rng(devices=[]):
            configure_modern_torch_runtime(runtime)
            torch.use_deterministic_algorithms(True)
            for index, record in enumerate(input_subjects, 1):
                _check_cancel(cancel_requested)
                label = record["label"]

                def progress(
                    event: AtlasOptimizationRecord,
                    label: str = label,
                    index: int = index,
                ) -> None:
                    if progress_callback is not None:
                        progress_callback(label, index, len(subjects), event)

                result_subjects.append(
                    _fit_subject(
                        temporary,
                        index,
                        label,
                        read_vtk_polydata(temporary / record["path"]),
                        template_tensor,
                        triangle_tensor,
                        controls,
                        optimizer_arguments,
                        progress if progress_callback is not None else None,
                        cancel_requested,
                    )
                )
        _check_cancel(cancel_requested)
        paths = sorted(
            path
            for path in temporary.rglob("*")
            if path.is_file() and path.relative_to(temporary).as_posix() not in _PRIVATE_ONLY
        )
        manifest = {
            "fixed_reference_version": FORMAT_VERSION,
            "created_at": timestamp,
            "project": {"name": config["project"]["name"]},
            "engine": {
                "id": pairwise.engine_id,
                "implementation_version": ENGINE_IMPLEMENTATION_VERSION,
                "diffeoforge": __version__,
                "pytorch": str(torch.__version__),
                "numpy": np.__version__,
                "device": "cpu",
                "dtype": "float64",
                "deterministic_algorithms": True,
                "threads": runtime["threads"],
                "random_seed": runtime["random_seed"],
                "pairwise_evaluation": pairwise.as_manifest(),
            },
            "config": {"source_path": _SOURCE_CONFIG, "effective_path": _EFFECTIVE_CONFIG},
            "input": {
                "units": config["input"]["units"],
                "template": _mesh_record(_TEMPLATE, template),
                "control_points": {"path": _CONTROLS, "count": len(controls)},
                "subjects": input_subjects,
            },
            "optimization": _optimizer_policy(config),
            "subjects": result_subjects,
            "artifacts": [_artifact(temporary, path) for path in paths],
            "scientific_boundary": SCIENTIFIC_BOUNDARY,
        }
        manifest_path = temporary / MANIFEST_NAME
        _write_json_exclusive(manifest_path, manifest)
        with (temporary / SIDECAR_NAME).open("x", encoding="ascii", newline="\n") as stream:
            stream.write(f"{sha256_file(manifest_path)}  {MANIFEST_NAME}\n")
        _verify_modern_fixed_reference(temporary, cancel_requested, private_staging=True)
        _check_cancel(cancel_requested)
        if output.exists() or output.is_symlink():
            raise FileExistsError(f"Fixed-reference destination appeared during creation: {output}")
        lease.remove_for_publication()
        temporary.rename(output)
    except AtlasOptimizationCancelled as error:
        raise ModernFixedReferenceCancelled("Modern fixed-reference job cancelled") from error
    finally:
        try:
            if lease is not None and lease.open:
                lease.close()
            if temporary.exists():
                if temporary.is_symlink() or temporary.resolve() != temporary:
                    raise ModernFixedReferenceError("Private staging path changed during the run")
                shutil.rmtree(temporary)
        finally:
            torch.set_num_threads(previous_threads)
            torch.use_deterministic_algorithms(previous_determinism, warn_only=previous_warn_only)
    return output


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ModernFixedReferenceError(f"Invalid JSON artifact {path.name}: {error}") from error


def _check_inventory(
    root: Path,
    artifacts: list[dict[str, Any]],
    expected: set[str],
    cancel_requested: Callable[[], bool] | None,
    *,
    private_staging: bool,
) -> None:
    entries = tuple(root.rglob("*"))
    resolved_root = root.resolve()
    if any(
        path.is_symlink() or path.resolve() != resolved_root / path.relative_to(root)
        for path in entries
    ):
        raise ModernFixedReferenceError("Redirected paths are forbidden in fixed-reference jobs")
    declared = [entry["path"] for entry in artifacts]
    actual = {path.relative_to(root).as_posix() for path in entries if path.is_file()}
    actual_directories = {path.relative_to(root).as_posix() for path in entries if path.is_dir()}
    expected_directories = {
        parent.as_posix()
        for path in expected
        for parent in PurePosixPath(path).parents
        if parent != PurePosixPath(".")
    }
    administrative = {MANIFEST_NAME, SIDECAR_NAME}
    if private_staging:
        administrative.update(_PRIVATE_ONLY)
    if (
        len(set(declared)) != len(declared)
        or set(declared) != expected
        or actual != expected | administrative
        or actual_directories != expected_directories
        or len(entries) != len(actual) + len(actual_directories)
    ):
        raise ModernFixedReferenceError("Fixed-reference artifact inventory differs")
    for record in artifacts:
        _check_cancel(cancel_requested)
        path = root / record["path"]
        if path.stat().st_size != record["bytes"] or sha256_file(path) != record["sha256"]:
            raise ModernFixedReferenceError(f"Fixed-reference artifact differs: {record['path']}")


def _finite(value: object) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def _check_trace(
    label: str,
    history: object,
    summary: dict[str, Any],
    config: dict[str, Any],
) -> None:
    cycles = summary["cycles_completed"]
    optimizer = config["optimization"]
    cap = optimizer["max_cycles"]
    reason = summary["termination_reason"]
    tolerance = optimizer.get("relative_objective_tolerance")
    if (
        not isinstance(history, list)
        or len(history) != cycles + 1
        or not 1 <= cycles <= cap
        or summary["converged"] != (reason != "max_cycles")
        or (reason == "max_cycles" and cycles != cap)
        or any(
            type(value) is not int
            for key, value in summary.items()
            if key not in {"converged", "termination_reason"}
        )
    ):
        raise ModernFixedReferenceError(f"Optimizer cycle contract differs for {label}")
    observed_stop = None
    accepted = 0
    for index, row in enumerate(history):
        identity = f"{label} cycle {index}"
        if (
            not isinstance(row, dict)
            or set(row) != _TRACE_FIELDS
            or type(row["cycle"]) is not int
            or row["cycle"] != index
            or not all(_finite(row[key]) for key in ("objective", "attachment", "regularity"))
            or not isinstance(row["residuals"], list)
            or len(row["residuals"]) != 1
            or not _finite(row["residuals"][0])
            or type(row["line_search_evaluations"]) is not int
        ):
            raise ModernFixedReferenceError(f"Invalid optimizer decision for {identity}")
        if index == 0:
            if (
                row["block"] is not None
                or row["status"] != "initial"
                or row["gradient_norm"] is not None
                or row["accepted_step_size"] is not None
                or row["line_search_evaluations"] != 0
            ):
                raise ModernFixedReferenceError(
                    f"Invalid initial optimizer decision for {identity}"
                )
            continue
        if (
            row["block"] != "momenta"
            or not _finite(row["gradient_norm"])
            or row["gradient_norm"] < 0
            or row["status"] not in ("accepted", "stationary")
        ):
            raise ModernFixedReferenceError(f"Invalid momenta decision for {identity}")
        previous_objective = history[index - 1]["objective"]
        if row["status"] == "accepted":
            accepted += 1
            if (
                not _finite(row["accepted_step_size"])
                or row["accepted_step_size"] <= 0
                or not 1
                <= row["line_search_evaluations"]
                <= optimizer["max_line_search_iterations"]
                or row["objective"] < previous_objective
            ):
                raise ModernFixedReferenceError(f"Invalid accepted decision for {identity}")
            cumulative = abs(row["objective"] - history[0]["objective"])
            if (
                tolerance is not None
                and cumulative > 0
                and abs(row["objective"] - previous_objective) < tolerance * cumulative
            ):
                observed_stop = "relative_objective_tolerance"
        else:
            if (
                row["accepted_step_size"] is not None
                or row["line_search_evaluations"] != 0
                or row["objective"] != previous_objective
                or row["gradient_norm"] > optimizer["gradient_tolerance"]
            ):
                raise ModernFixedReferenceError(f"Invalid stationary decision for {identity}")
            observed_stop = "gradient_tolerance"
        if observed_stop is not None and index != cycles:
            raise ModernFixedReferenceError(
                f"Unexpected decisions after convergence for {identity}"
            )
    if (observed_stop or "max_cycles") != reason:
        raise ModernFixedReferenceError(f"Optimizer termination differs from the trace for {label}")
    evaluations = sum(row["line_search_evaluations"] for row in history)
    candidates = summary["candidate_gradient_evaluations"]
    gradients = summary["gradient_evaluations"]
    # A singleton momenta block reuses each accepted gradient. The explicitly
    # batched path recomputes the objective once while constructing each gradient.
    objectives = 1 + evaluations
    if optimizer.get("subject_batch_size") is not None:
        objectives += gradients
    if (
        evaluations != summary["total_line_search_evaluations"]
        or not accepted <= candidates <= evaluations
        or gradients != 1 + candidates
        or summary["objective_evaluations"] != objectives
    ):
        raise ModernFixedReferenceError(f"Optimizer work counters differ for {label}")


def verify_modern_fixed_reference(directory: Path | str) -> dict[str, Any]:
    """Check the immutable fixed-reference job without rerunning optimization."""
    return _verify_modern_fixed_reference(directory, None, private_staging=False)


def _verify_modern_fixed_reference(
    directory: Path | str,
    cancel_requested: Callable[[], bool] | None,
    *,
    private_staging: bool,
) -> dict[str, Any]:
    _check_cancel(cancel_requested)
    root = Path(directory).expanduser()
    if root.is_symlink() or not root.is_dir():
        raise ModernFixedReferenceError(f"Fixed-reference job is not a real directory: {root}")
    if not private_staging and _STAGING_NAME.fullmatch(root.resolve().name):
        raise ModernFixedReferenceError("Private staging is not a published fixed-reference job")
    manifest_path = root / MANIFEST_NAME
    sidecar = root / SIDECAR_NAME
    if any(not path.is_file() or path.is_symlink() for path in (manifest_path, sidecar)):
        raise ModernFixedReferenceError(
            "Fixed-reference manifest or checksum is missing or symbolic"
        )
    if sidecar.read_bytes() != f"{sha256_file(manifest_path)}  {MANIFEST_NAME}\n".encode("ascii"):
        raise ModernFixedReferenceError("Fixed-reference manifest checksum differs")
    manifest = _read_json(manifest_path)
    resource = files("diffeoforge.schema").joinpath("modern-fixed-reference-run-v0.1.json")
    schema = json.loads(resource.read_text(encoding="utf-8"))
    try:
        jsonschema.Draft202012Validator(schema).validate(manifest)
    except jsonschema.ValidationError as error:
        raise ModernFixedReferenceError(
            f"Invalid fixed-reference manifest: {error.message}"
        ) from error
    _timestamp(manifest["created_at"])
    if manifest["scientific_boundary"] != SCIENTIFIC_BOUNDARY:
        raise ModernFixedReferenceError("Fixed-reference scientific boundary differs")
    if manifest["config"] != {"source_path": _SOURCE_CONFIG, "effective_path": _EFFECTIVE_CONFIG}:
        raise ModernFixedReferenceError("Fixed-reference config paths differ")

    inputs = manifest["input"]
    subjects = manifest["subjects"]
    labels = [record["label"] for record in inputs["subjects"]]
    for label in labels:
        _check_label(label)
    folded = [label.casefold() for label in labels]
    if (
        len(set(folded)) != len(folded)
        or folded != sorted(folded)
        or labels != [record["label"] for record in subjects]
    ):
        raise ModernFixedReferenceError("Fixed-reference subject labels or order differ")
    expected = {_SOURCE_CONFIG, _EFFECTIVE_CONFIG, _TEMPLATE, _CONTROLS}
    for index, (input_record, subject) in enumerate(
        zip(inputs["subjects"], subjects, strict=True), 1
    ):
        _check_cancel(cancel_requested)
        paths = _subject_paths(index)
        target = _target_path(index)
        if input_record["path"] != target or any(
            subject[key] != path for key, path in paths.items()
        ):
            raise ModernFixedReferenceError("Fixed-reference subject paths differ")
        expected.update((target, *paths.values()))
    _check_inventory(
        root, manifest["artifacts"], expected, cancel_requested, private_staging=private_staging
    )

    config = _read_json(root / _EFFECTIVE_CONFIG)
    validate_modern_workflow_config(config)
    _validate_recipe(config)
    if load_modern_workflow_config(root / _SOURCE_CONFIG) != config:
        raise ModernFixedReferenceError("Fixed-reference source and effective configuration differ")
    if (
        manifest["optimization"] != _optimizer_policy(config)
        or manifest["project"] != {"name": config["project"]["name"]}
        or inputs["units"] != config["input"]["units"]
    ):
        raise ModernFixedReferenceError(
            "Fixed-reference manifest differs from the effective configuration"
        )
    pairwise = pairwise_evaluation_from_config(config)
    engine = manifest["engine"]
    if (
        engine["id"] != pairwise.engine_id
        or engine["pairwise_evaluation"] != pairwise.as_manifest()
        or engine["threads"] != config["runtime"]["threads"]
        or engine["random_seed"] != config["runtime"]["random_seed"]
    ):
        raise ModernFixedReferenceError("Fixed-reference runtime or pairwise provenance differs")

    count = config["initialization"]["control_points"]["count"]
    if inputs["control_points"] != {"path": _CONTROLS, "count": count}:
        raise ModernFixedReferenceError("Fixed-reference controls differ from configuration")
    _read_control_point_rows(root / _CONTROLS, count)
    settings = MeshQualitySettings.from_mapping(config["quality_control"])
    template = _checked_mesh(root, _TEMPLATE, settings)
    if inputs["template"] != _mesh_record(_TEMPLATE, template):
        raise ModernFixedReferenceError("Fixed-reference template evidence differs")
    for input_record, subject in zip(inputs["subjects"], subjects, strict=True):
        _check_cancel(cancel_requested)
        label, target = input_record["label"], input_record["path"]
        mesh = _checked_mesh(root, target, settings)
        if input_record != {"label": label, **_mesh_record(target, mesh)}:
            raise ModernFixedReferenceError(f"Fixed-reference target evidence differs for {label}")
        path = subject["reconstruction_path"]
        fitted = _checked_mesh(root, path, settings)
        _check_deformation(label, template, fitted, settings)
        _read_momenta_rows(root / subject["momenta_path"], (label,), count)
        _check_trace(
            label, _read_json(root / subject["history_path"]), subject["optimizer"], config
        )
    return manifest
