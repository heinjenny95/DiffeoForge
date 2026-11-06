"""Opt-in independent Modern momenta fits on one fixed reference basis."""

from __future__ import annotations

import csv
import json
import math
import re
import shutil
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, fields, replace
from importlib.resources import files
from pathlib import Path, PurePosixPath
from typing import Any

import jsonschema
import numpy as np
import torch
from referencing import Registry, Resource

from diffeoforge import __version__
from diffeoforge.config import ConfigurationError, validate_input_paths
from diffeoforge.engine import flow_points, shoot
from diffeoforge.engine.atlas_optimizer import (
    AtlasCycleCheckpoint,
    AtlasOptimizationCancelled,
    AtlasOptimizationRecord,
    AtlasOptimizationResult,
    AtlasOptimizerResumeState,
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
from diffeoforge.modern_checkpoint import (
    CHECKPOINT_VERSION,
    ModernCheckpointError,
    load_modern_checkpoint_resume_state,
    verify_modern_cycle_checkpoint,
    write_modern_cycle_checkpoint,
)
from diffeoforge.modern_checkpoint import (
    MANIFEST_NAME as CHECKPOINT_MANIFEST,
)
from diffeoforge.modern_checkpoint import (
    SIDECAR_NAME as CHECKPOINT_SIDECAR,
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
CONTINUATION_VERSION = "0.2"
SCIENTIFIC_BOUNDARY = (
    "Independent momentum fits against a frozen template and fixed control points. "
    "This job does not estimate an atlas or PCA, qualify biological accuracy, "
    "or publish resumable optimizer checkpoints."
)
_SOURCE_CONFIG = "config/source.yaml"
_EFFECTIVE_CONFIG = "config/effective-config.json"
_TEMPLATE = "input/template.vtk"
_CONTROLS = "input/control-points.txt"
_CHECKPOINT = "continuation/checkpoint"
_PARENT = "continuation/parent"
_SUFFIX = "continuation/suffix-history.json"
_CONTINUATION_BOUNDARY = (
    "Independent singleton momentum fitting against a frozen template and fixed control points. "
    "A completed segment can continue within the original cycle cap. "
    "This job provides no atlas, PCA, biological qualification or abandoned-run recovery."
)
_TRACE_FIELDS = {field.name for field in fields(AtlasOptimizationRecord)}
_WORK_FIELDS = (
    "cycles_completed",
    "total_line_search_evaluations",
    "objective_evaluations",
    "gradient_evaluations",
    "candidate_gradient_evaluations",
)
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


def _optimizer_policy(config: dict[str, Any], phase: str | None = None) -> dict[str, Any]:
    return {
        "mode": "independent_momenta",
        "max_cycles_per_subject": config["optimization"]["max_cycles"],
        "initial_momenta": "checkpoint" if phase == "successor" else "zeros",
        "checkpoint_policy": {
            None: "none",
            "segment": "terminal_segment",
            "successor": "sealed_parent",
        }[phase],
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


@dataclass(frozen=True)
class _ContinuationSeed:
    momenta: torch.Tensor
    state: AtlasOptimizerResumeState
    history: list[dict[str, Any]]
    optimizer: dict[str, Any]


def _work_summary(result: AtlasOptimizationResult) -> dict[str, Any]:
    return {
        **{key: getattr(result, key) for key in _WORK_FIELDS},
        "termination_reason": result.termination_reason,
        "converged": result.converged,
    }


def _combined_work(prefix: dict[str, Any], suffix: dict[str, Any]) -> dict[str, Any]:
    return suffix | {key: prefix[key] + suffix[key] for key in _WORK_FIELDS}


def _combined_history(
    prefix: list[dict[str, Any]], suffix: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    offset = len(prefix) - 1
    return prefix + [row | {"cycle": row["cycle"] + offset} for row in suffix[1:]]


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
    *,
    checkpoint_callback: Callable[[AtlasCycleCheckpoint], None] | None = None,
    seed: _ContinuationSeed | None = None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    targets = (
        (
            torch.tensor(mesh.vertices, dtype=torch.float64, device="cpu"),
            torch.tensor(mesh.triangles, dtype=torch.int64, device="cpu"),
        ),
    )
    initial_momenta = (
        torch.zeros((1, len(controls), 3), dtype=torch.float64, device="cpu")
        if seed is None
        else seed.momenta
    )
    result = optimize_atlas(
        template,
        triangles,
        targets,
        controls,
        initial_momenta,
        **optimizer_arguments,
        progress_callback=progress,
        cancel_requested=cancel_requested,
        checkpoint_callback=checkpoint_callback,
        resume_state=None if seed is None else seed.state,
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
    history = [asdict(record) for record in result.history]
    work = _work_summary(result)
    if seed is not None:
        _write_json_exclusive(root / _SUFFIX, history)
        history = _combined_history(seed.history, history)
    _write_json_exclusive(root / paths["history_path"], history)
    return {
        "label": label,
        **paths,
        "optimizer": work if seed is None else _combined_work(seed.optimizer, work),
    }, None if seed is None else work


def run_modern_fixed_reference(
    config_path: Path | str,
    *,
    destination: Path | str,
    progress_callback: ProgressCallback | None = None,
    cancel_requested: Callable[[], bool] | None = None,
    created_at: str | None = None,
    segment_cycles: int | None = None,
) -> Path:
    """Run independent CPU fits, or an explicit first segment of one fit."""
    _validate_callbacks(progress_callback, cancel_requested)
    source = Path(config_path).expanduser().resolve()
    config = load_modern_workflow_config(source)
    _validate_recipe(config)
    _check_cancel(cancel_requested)
    inputs = validate_input_paths(config, source, minimum_subject_count=1)
    subjects = sorted(inputs.subjects, key=lambda path: path.name.casefold())
    for subject in subjects:
        _check_label(subject.name)
    if segment_cycles is not None:
        if len(subjects) != 1:
            raise ConfigurationError("A fixed-reference segment requires exactly one subject")
        _check_segment_cap(segment_cycles, config["optimization"]["max_cycles"])
    initialization = config["initialization"]["control_points"]
    control_source = _resolve_from_config(initialization["path"], source)
    return _run_fixed_reference(
        config,
        source,
        inputs.template,
        control_source,
        [(subject.name, subject) for subject in subjects],
        destination,
        progress_callback,
        cancel_requested,
        created_at,
        segment_cycles=segment_cycles,
    )


def continue_modern_fixed_reference(
    parent: Path | str,
    *,
    destination: Path | str,
    progress_callback: ProgressCallback | None = None,
    cancel_requested: Callable[[], bool] | None = None,
    created_at: str | None = None,
) -> Path:
    """Continue a verified singleton segment within its original cycle cap."""
    _validate_callbacks(progress_callback, cancel_requested)
    source = Path(parent).expanduser()
    manifest = _verify_modern_fixed_reference(source, cancel_requested, private_staging=False)
    continuation = manifest.get("continuation", {})
    if continuation.get("phase") != "segment":
        raise ModernFixedReferenceError("Continuation requires a planned fixed-reference segment")
    if continuation["checkpoint_path"] is None:
        raise ModernFixedReferenceError("The fixed-reference segment already converged")
    source = source.resolve()
    if Path(destination).expanduser().resolve().is_relative_to(source):
        raise ConfigurationError("A fixed-reference successor cannot be inside its parent")
    config = _read_json(source / _EFFECTIVE_CONFIG)
    subject = manifest["input"]["subjects"][0]
    return _run_fixed_reference(
        config,
        source / _SOURCE_CONFIG,
        source / _TEMPLATE,
        source / _CONTROLS,
        [(subject["label"], source / subject["path"])],
        destination,
        progress_callback,
        cancel_requested,
        created_at,
        segment_cycles=continuation["segment_cycle_cap"],
        parent=(source, manifest),
    )


def _validate_callbacks(
    progress: ProgressCallback | None, cancel: Callable[[], bool] | None
) -> None:
    if progress is not None and not callable(progress):
        raise TypeError("progress_callback must be callable or None")
    if cancel is not None and not callable(cancel):
        raise TypeError("cancel_requested must be callable or None")


def _check_segment_cap(segment: int, total: int) -> None:
    if type(segment) is not int or not 1 <= segment < total:
        raise ConfigurationError(
            "Segment cycle cap must be positive and below the original cycle cap"
        )


def _engine_provenance(config: dict[str, Any]) -> dict[str, Any]:
    runtime = config["runtime"]
    pairwise = pairwise_evaluation_from_config(config)
    return {
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
    }


def _run_fixed_reference(
    config: dict[str, Any],
    source: Path,
    template_source: Path,
    control_source: Path,
    subjects: list[tuple[str, Path]],
    destination: Path | str,
    progress_callback: ProgressCallback | None,
    cancel_requested: Callable[[], bool] | None,
    created_at: str | None,
    *,
    segment_cycles: int | None,
    parent: tuple[Path, dict[str, Any]] | None = None,
) -> Path:
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
    engine = _engine_provenance(config)
    if parent is not None and parent[1]["engine"] != engine:
        raise ModernFixedReferenceError(
            "Fixed-reference continuation runtime differs from the segment"
        )
    phase = "successor" if parent is not None else "segment" if segment_cycles is not None else None
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
        seed = None
        continuation: dict[str, Any] = {}
        if parent is not None:
            parent_root, parent_manifest = parent
            embedded = temporary / _PARENT
            for path in (
                MANIFEST_NAME,
                SIDECAR_NAME,
                *(entry["path"] for entry in parent_manifest["artifacts"]),
            ):
                _check_cancel(cancel_requested)
                _copy_exclusive(parent_root / path, embedded / path)
            checked_parent = _verify_modern_fixed_reference(
                embedded,
                cancel_requested,
                private_staging=False,
                require_segment=True,
            )
            if checked_parent != parent_manifest:
                raise ModernFixedReferenceError("Fixed-reference segment changed during staging")
            seed = _read_seed(embedded, checked_parent)
            source = embedded / _SOURCE_CONFIG
            template_source = embedded / _TEMPLATE
            control_source = embedded / _CONTROLS
            label, _ = subjects[0]
            subjects = [(label, embedded / _target_path(1))]
            continuation = {
                "phase": "successor",
                "segment_cycle_cap": segment_cycles,
                "parent_path": _PARENT,
                "parent_manifest_sha256": sha256_file(embedded / MANIFEST_NAME),
                "resumed_from_cycle": seed.optimizer["cycles_completed"],
                "remaining_cycle_cap": config["optimization"]["max_cycles"]
                - seed.optimizer["cycles_completed"],
                "suffix_history_path": _SUFFIX,
                "resume_validation": _resume_validation(config),
            }
        elif segment_cycles is not None:
            continuation = {
                "phase": "segment",
                "segment_cycle_cap": segment_cycles,
                "checkpoint_path": None,
                "checkpoint_manifest_sha256": None,
            }
        _copy_exclusive(source, temporary / _SOURCE_CONFIG)
        if load_modern_workflow_config(temporary / _SOURCE_CONFIG) != config:
            raise ModernFixedReferenceError("Source configuration changed during staging")
        _write_json_exclusive(temporary / _EFFECTIVE_CONFIG, config)
        _copy_exclusive(template_source, temporary / _TEMPLATE)
        _copy_exclusive(control_source, temporary / _CONTROLS)
        template = _checked_mesh(temporary, _TEMPLATE, settings)
        initialization = config["initialization"]["control_points"]
        control_values = _read_control_point_rows(temporary / _CONTROLS, initialization["count"])
        input_subjects = []
        for index, (label, subject) in enumerate(subjects, 1):
            _check_cancel(cancel_requested)
            path = _target_path(index)
            _copy_exclusive(subject, temporary / path)
            mesh = _checked_mesh(temporary, path, settings)
            input_subjects.append({"label": label, **_mesh_record(path, mesh)})

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
        if seed is not None:
            optimizer_arguments["max_cycles"] = continuation["remaining_cycle_cap"]
        elif segment_cycles is not None:
            optimizer_arguments["max_cycles"] = segment_cycles

        def checkpoint_cycle(checkpoint: AtlasCycleCheckpoint) -> None:
            if (
                checkpoint.record.cycle != segment_cycles
                or checkpoint.completed_cycle_termination_reason
            ):
                return
            _check_cancel(cancel_requested)
            label = input_subjects[0]["label"]
            written = write_modern_cycle_checkpoint(
                temporary / _CHECKPOINT,
                checkpoint,
                triangle_tensor,
                [label],
                _checkpoint_binding(temporary, config, label, ENGINE_IMPLEMENTATION_VERSION),
                created_at=timestamp,
            )
            continuation["checkpoint_path"] = _CHECKPOINT
            continuation["checkpoint_manifest_sha256"] = sha256_file(written / CHECKPOINT_MANIFEST)

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
                        if seed is not None:
                            if event.cycle == 0:
                                return
                            event = replace(
                                event, cycle=event.cycle + seed.optimizer["cycles_completed"]
                            )
                        progress_callback(label, index, len(subjects), event)

                result, suffix = _fit_subject(
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
                    checkpoint_callback=checkpoint_cycle if phase == "segment" else None,
                    seed=seed,
                )
                result_subjects.append(result)
                if suffix is not None:
                    continuation["suffix_optimizer"] = suffix
        _check_cancel(cancel_requested)
        paths = sorted(
            path
            for path in temporary.rglob("*")
            if path.is_file() and path.relative_to(temporary).as_posix() not in _PRIVATE_ONLY
        )
        manifest = {
            "fixed_reference_version": FORMAT_VERSION if phase is None else CONTINUATION_VERSION,
            "created_at": timestamp,
            "project": {"name": config["project"]["name"]},
            "engine": engine,
            "config": {"source_path": _SOURCE_CONFIG, "effective_path": _EFFECTIVE_CONFIG},
            "input": {
                "units": config["input"]["units"],
                "template": _mesh_record(_TEMPLATE, template),
                "control_points": {"path": _CONTROLS, "count": len(controls)},
                "subjects": input_subjects,
            },
            "optimization": _optimizer_policy(config, phase),
            "subjects": result_subjects,
            "artifacts": [_artifact(temporary, path) for path in paths],
            "scientific_boundary": SCIENTIFIC_BOUNDARY if phase is None else _CONTINUATION_BOUNDARY,
        }
        if phase is not None:
            manifest["continuation"] = continuation
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


def _checkpoint_binding(
    root: Path,
    config: dict[str, Any],
    label: str,
    implementation: str,
) -> dict[str, Any]:
    def bound(path: str) -> dict[str, str]:
        return {"path": path, "sha256": sha256_file(root / path)}

    return {
        "engine_implementation": implementation,
        "source_config": bound(_SOURCE_CONFIG),
        "effective_config": bound(_EFFECTIVE_CONFIG),
        "template_input": bound(_TEMPLATE),
        "subjects": [{"label": label, **bound(_target_path(1))}],
        "block_order": ["momenta"],
        "momenta_updates_per_cycle": 1,
        "subject_batch_size": config["optimization"].get("subject_batch_size"),
        "subject_batch_workers": 1,
        "max_cycles": config["optimization"]["max_cycles"],
    }


def _read_seed(root: Path, parent: dict[str, Any]) -> _ContinuationSeed:
    checkpoint = root / _CHECKPOINT
    manifest = _read_json(checkpoint / CHECKPOINT_MANIFEST)
    subject = parent["subjects"][0]
    count = parent["input"]["control_points"]["count"]
    return _ContinuationSeed(
        torch.from_numpy(
            _read_momenta_rows(
                checkpoint / manifest["state"]["momenta"]["path"],
                (subject["label"],),
                count,
            )
        ),
        load_modern_checkpoint_resume_state(checkpoint),
        _read_json(root / subject["history_path"]),
        subject["optimizer"],
    )


def _resume_validation(config: dict[str, Any]) -> dict[str, int]:
    return {
        "objective_evaluations": 1
        + int(config["optimization"].get("subject_batch_size") is not None),
        "gradient_evaluations": 1,
    }


def _checked_entries(root: Path) -> tuple[Path, ...]:
    entries = tuple(root.rglob("*"))
    resolved_root = root.resolve()
    if any(
        path.is_symlink() or path.resolve() != resolved_root / path.relative_to(root)
        for path in entries
    ):
        raise ModernFixedReferenceError("Redirected paths are forbidden in fixed-reference jobs")
    return entries


def _check_inventory(
    root: Path,
    artifacts: list[dict[str, Any]],
    expected: set[str],
    cancel_requested: Callable[[], bool] | None,
    *,
    private_staging: bool,
    entries: tuple[Path, ...] | None = None,
) -> None:
    if entries is None:
        entries = _checked_entries(root)
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
    *,
    cycle_cap: int | None = None,
    baseline: float | None = None,
    initializations: int = 1,
) -> None:
    cycles = summary["cycles_completed"]
    optimizer = config["optimization"]
    cap = optimizer["max_cycles"] if cycle_cap is None else cycle_cap
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
            initial_objective = history[0]["objective"] if baseline is None else baseline
            cumulative = abs(row["objective"] - initial_objective)
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
    objectives = initializations + evaluations
    if optimizer.get("subject_batch_size") is not None:
        objectives += gradients
    if (
        evaluations != summary["total_line_search_evaluations"]
        or not accepted <= candidates <= evaluations
        or gradients != initializations + candidates
        or summary["objective_evaluations"] != objectives
    ):
        raise ModernFixedReferenceError(f"Optimizer work counters differ for {label}")


def verify_modern_fixed_reference(directory: Path | str) -> dict[str, Any]:
    """Check the immutable fixed-reference job without rerunning optimization."""
    return _verify_modern_fixed_reference(directory, None, private_staging=False)


def _check_segment_checkpoint(
    root: Path,
    manifest: dict[str, Any],
    checkpoint: dict[str, Any] | None,
    config: dict[str, Any],
    template: TriangleMesh,
    controls: np.ndarray,
    momenta: np.ndarray,
    history: list[dict[str, Any]],
) -> None:
    subject = manifest["subjects"][0]
    continuation = manifest["continuation"]
    if subject["optimizer"]["converged"]:
        if checkpoint is not None or continuation["checkpoint_manifest_sha256"] is not None:
            raise ModernFixedReferenceError(
                "A converged fixed-reference segment cannot be continued"
            )
        return
    if checkpoint is None:
        raise ModernFixedReferenceError(
            "Capped fixed-reference segment lacks its terminal checkpoint"
        )
    directory = root / _CHECKPOINT
    label = subject["label"]
    state = checkpoint["state"]
    optimizer = checkpoint["optimizer_state"]
    if (
        checkpoint["checkpoint_version"] != CHECKPOINT_VERSION
        or checkpoint["created_at"] != manifest["created_at"]
        or sha256_file(directory / CHECKPOINT_MANIFEST)
        != continuation["checkpoint_manifest_sha256"]
        or checkpoint["binding"]
        != _checkpoint_binding(
            root,
            config,
            label,
            manifest["engine"]["implementation_version"],
        )
        or checkpoint["cycle"] != continuation["segment_cycle_cap"]
        or checkpoint["record"] != history[-1]
        or optimizer["initial_cycle_objective"] != history[0]["objective"]
        or optimizer["prior_cycle_objective"] != history[-2]["objective"]
        or optimizer["current_cycle_objective"] != history[-1]["objective"]
        or optimizer["completed_cycle_termination_reason"] is not None
        or optimizer["reusable_gradient"] is None
    ):
        raise ModernFixedReferenceError(
            "Fixed-reference checkpoint identity or decision history differs"
        )
    checkpoint_template = read_vtk_polydata(directory / state["template"]["path"])
    count = len(controls)
    checkpoint_controls = _read_control_point_rows(
        directory / state["control_points"]["path"], count
    )
    checkpoint_momenta = _read_momenta_rows(directory / state["momenta"]["path"], (label,), count)
    if (
        checkpoint_template.vertices != template.vertices
        or checkpoint_template.triangles != template.triangles
        or checkpoint_controls.tobytes() != controls.tobytes()
        or checkpoint_momenta.tobytes() != momenta.tobytes()
    ):
        raise ModernFixedReferenceError("Fixed-reference checkpoint basis or momenta differ")


def _check_successor(
    root: Path,
    manifest: dict[str, Any],
    parent: dict[str, Any],
    config: dict[str, Any],
    history: list[dict[str, Any]],
) -> None:
    parent_root = root / _PARENT
    original = parent["subjects"][0]
    subject = manifest["subjects"][0]
    continuation = manifest["continuation"]
    parent_continuation = parent["continuation"]
    prefix_work = original["optimizer"]
    suffix_work = continuation["suffix_optimizer"]
    original_cap = config["optimization"]["max_cycles"]
    resumed = continuation["resumed_from_cycle"]
    remaining = continuation["remaining_cycle_cap"]
    if (
        parent_continuation["checkpoint_path"] is None
        or parent["engine"] != manifest["engine"]
        or parent["input"] != manifest["input"]
        or parent["optimization"]["max_cycles_per_subject"] != original_cap
        or sha256_file(parent_root / MANIFEST_NAME) != continuation["parent_manifest_sha256"]
        or continuation["segment_cycle_cap"] != parent_continuation["segment_cycle_cap"]
        or type(resumed) is not int
        or resumed != prefix_work["cycles_completed"]
        or type(remaining) is not int
        or remaining != original_cap - resumed
        or continuation["resume_validation"] != _resume_validation(config)
    ):
        raise ModernFixedReferenceError(
            "Fixed-reference successor differs from its sealed parent or budget"
        )
    for path in (_SOURCE_CONFIG, _EFFECTIVE_CONFIG, _TEMPLATE, _CONTROLS, _target_path(1)):
        if sha256_file(root / path) != sha256_file(parent_root / path):
            raise ModernFixedReferenceError(
                f"Fixed-reference successor changed frozen file: {path}"
            )
    prefix = _read_json(parent_root / original["history_path"])
    suffix = _read_json(root / _SUFFIX)
    _check_trace(
        subject["label"],
        suffix,
        suffix_work,
        config,
        cycle_cap=remaining,
        baseline=prefix[0]["objective"],
    )
    expected_initial = prefix[-1] | {
        "cycle": 0,
        "block": None,
        "status": "initial",
        "gradient_norm": None,
        "accepted_step_size": None,
        "line_search_evaluations": 0,
    }
    if (
        suffix[0] != expected_initial
        or history != _combined_history(prefix, suffix)
        or subject["optimizer"] != _combined_work(prefix_work, suffix_work)
    ):
        raise ModernFixedReferenceError(
            "Fixed-reference successor decisions or work differ from its segments"
        )


def _verify_modern_fixed_reference(
    directory: Path | str,
    cancel_requested: Callable[[], bool] | None,
    *,
    private_staging: bool,
    require_segment: bool = False,
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
    if not isinstance(manifest, dict):
        raise ModernFixedReferenceError("Fixed-reference manifest must be an object")
    resources = files("diffeoforge.schema")
    base_name = "modern-fixed-reference-run-v0.1.json"
    base = json.loads(resources.joinpath(base_name).read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(base)
    if manifest.get("fixed_reference_version") == CONTINUATION_VERSION:
        resource = resources.joinpath("modern-fixed-reference-run-v0.2.json")
        schema = json.loads(resource.read_text(encoding="utf-8"))
        registry = Registry().with_resource(
            "https://diffeoforge.org/schema/" + base_name,
            Resource.from_contents(base),
        )
        validator = jsonschema.Draft202012Validator(schema, registry=registry)
    try:
        validator.validate(manifest)
    except jsonschema.ValidationError as error:
        raise ModernFixedReferenceError(
            f"Invalid fixed-reference manifest: {error.message}"
        ) from error
    _timestamp(manifest["created_at"])
    continuation = manifest.get("continuation", {})
    phase = continuation.get("phase")
    if require_segment and phase != "segment":
        raise ModernFixedReferenceError("A fixed-reference successor requires an embedded segment")
    boundary = SCIENTIFIC_BOUNDARY if phase is None else _CONTINUATION_BOUNDARY
    if manifest["scientific_boundary"] != boundary:
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
    entries = None if phase is None else _checked_entries(root)
    checkpoint = None
    parent = None
    if phase == "segment" and continuation["checkpoint_path"] is not None:
        _check_cancel(cancel_requested)
        try:
            checkpoint = verify_modern_cycle_checkpoint(root / _CHECKPOINT, workflow_root=root)
        except ModernCheckpointError as error:
            raise ModernFixedReferenceError(
                f"Invalid fixed-reference checkpoint: {error}"
            ) from error
        expected.update(
            f"{_CHECKPOINT}/{path}"
            for path in (
                CHECKPOINT_MANIFEST,
                CHECKPOINT_SIDECAR,
                *(entry["path"] for entry in checkpoint["artifacts"]),
            )
        )
    if phase == "successor":
        parent = _verify_modern_fixed_reference(
            root / _PARENT,
            cancel_requested,
            private_staging=False,
            require_segment=True,
        )
        expected.update(
            f"{_PARENT}/{path}"
            for path in (
                MANIFEST_NAME,
                SIDECAR_NAME,
                *(entry["path"] for entry in parent["artifacts"]),
            )
        )
        expected.add(_SUFFIX)
    _check_inventory(
        root,
        manifest["artifacts"],
        expected,
        cancel_requested,
        private_staging=private_staging,
        entries=entries,
    )

    config = _read_json(root / _EFFECTIVE_CONFIG)
    validate_modern_workflow_config(config)
    _validate_recipe(config)
    if phase is not None:
        _check_segment_cap(continuation["segment_cycle_cap"], config["optimization"]["max_cycles"])
    if load_modern_workflow_config(root / _SOURCE_CONFIG) != config:
        raise ModernFixedReferenceError("Fixed-reference source and effective configuration differ")
    if (
        manifest["optimization"] != _optimizer_policy(config, phase)
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
    controls = _read_control_point_rows(root / _CONTROLS, count)
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
        momenta = _read_momenta_rows(root / subject["momenta_path"], (label,), count)
        history = _read_json(root / subject["history_path"])
        _check_trace(
            label,
            history,
            subject["optimizer"],
            config,
            cycle_cap=continuation["segment_cycle_cap"] if phase == "segment" else None,
            initializations=2 if phase == "successor" else 1,
        )
        if phase == "segment":
            _check_segment_checkpoint(
                root, manifest, checkpoint, config, template, controls, momenta, history
            )
        if parent is not None:
            _check_successor(root, manifest, parent, config, history)
    return manifest
