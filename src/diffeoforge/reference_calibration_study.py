"""Resumable staged execution of transparent Deformetrica pilot calibration.

The study is deliberately sequential.  Every candidate in one stage is run
automatically, then execution pauses for explicit anatomical review and a
researcher selection before the next parameter family is varied.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import shutil
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

import yaml

from diffeoforge.atomic_io import write_text_safely
from diffeoforge.config import (
    ConfigurationError,
    load_config,
    validate_input_paths,
    validate_schema,
)
from diffeoforge.desktop.reference_execution_controller import (
    ReferenceExecutionController,
    ReferenceExecutionControllerResult,
)
from diffeoforge.desktop.reference_prelaunch import DesktopReferenceLaunchRequest
from diffeoforge.desktop.reference_worker_protocol import DesktopReferenceWorkerEvent
from diffeoforge.mesh import sha256_file
from diffeoforge.reference_calibration import (
    CalibrationCandidate,
    CalibrationCandidateEvidence,
    CalibrationStage,
    CalibrationStageAssessment,
    ReferenceCalibrationPlan,
    assess_calibration_stage,
    reference_calibration_plan_from_provenance,
)
from diffeoforge.reference_calibration_metrics import (
    atlas_rms_distance,
    collect_reference_calibration_run_metrics,
)
from diffeoforge.reference_runtime import launcher_identity

STUDY_VERSION = "0.1"
EVENT_VERSION = "0.1"
STUDY_MANIFEST = "study.json"
STUDY_DIGEST = "study.sha256"
STUDY_EVENTS = "events.jsonl"
StudyEventCallback = Callable[[Mapping[str, object]], None]


class ReferenceCalibrationStudyError(ConfigurationError):
    """Raised when a calibration study is invalid or cannot progress."""


class _Controller(Protocol):
    def run(
        self,
        *,
        event_callback: Callable[[DesktopReferenceWorkerEvent], None] | None = None,
    ) -> ReferenceExecutionControllerResult: ...

    def request_cancel(self) -> bool: ...


ControllerFactory = Callable[[DesktopReferenceLaunchRequest], _Controller]


def _canonical_json(value: object, *, indent: int | None = None) -> str:
    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":") if indent is None else None,
            indent=indent,
            ensure_ascii=False,
            allow_nan=False,
        )
        + ("\n" if indent is not None else "")
    )


def _canonical_hash(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _relative_path(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as error:
        raise ReferenceCalibrationStudyError(
            f"Calibration path escapes its study directory: {path}"
        ) from error


def _safe_study_path(root: Path, relative_value: object) -> Path:
    relative = Path(str(relative_value))
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise ReferenceCalibrationStudyError(
            f"Unsafe calibration-study path: {relative}"
        )
    value = root.joinpath(*relative.parts).resolve()
    if not value.is_relative_to(root.resolve()):
        raise ReferenceCalibrationStudyError(
            f"Calibration-study path escapes its root: {relative}"
        )
    return value


def _write_json(path: Path, value: object, *, overwrite: bool) -> None:
    write_text_safely(
        path,
        _canonical_json(value, indent=2),
        overwrite=overwrite,
    )


def _write_yaml(path: Path, value: Mapping[str, Any], *, overwrite: bool) -> None:
    rendered = yaml.safe_dump(
        dict(value),
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
    )
    write_text_safely(path, rendered, overwrite=overwrite)


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ReferenceCalibrationStudyError(
            f"Could not read {label}: {path}: {error}"
        ) from error
    if not isinstance(value, dict):
        raise ReferenceCalibrationStudyError(f"{label} must be a JSON object")
    return value


def _copy_bound(source: Path, destination: Path, expected_sha256: str) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise ReferenceCalibrationStudyError(
            f"Calibration input destination already exists: {destination}"
        )
    shutil.copy2(source, destination)
    if sha256_file(destination) != expected_sha256:
        destination.unlink(missing_ok=True)
        raise ReferenceCalibrationStudyError(
            f"Calibration input copy did not preserve bytes: {source}"
        )


@dataclass(frozen=True)
class CalibrationStudyCandidateState:
    candidate_id: str
    label: str
    status: str
    config_path: Path
    run_directory: Path | None
    metrics: Mapping[str, object] | None
    error: str | None
    attempts: int


@dataclass(frozen=True)
class ReferenceCalibrationStudySnapshot:
    study_directory: Path
    study_id: str
    plan: ReferenceCalibrationPlan
    status: str
    current_stage: CalibrationStage | None
    candidates: tuple[CalibrationStudyCandidateState, ...]
    selected_values: Mapping[str, float]
    selected_candidate_ids: Mapping[str, str]
    event_count: int
    final_config_path: Path | None


def _load_events(root: Path) -> tuple[dict[str, Any], ...]:
    path = root / STUDY_EVENTS
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise ReferenceCalibrationStudyError(
            f"Could not read calibration event ledger: {error}"
        ) from error
    events: list[dict[str, Any]] = []
    previous_hash: str | None = None
    for index, line in enumerate(lines):
        try:
            event = json.loads(line)
        except json.JSONDecodeError as error:
            raise ReferenceCalibrationStudyError(
                f"Invalid calibration event JSON at line {index + 1}"
            ) from error
        if not isinstance(event, dict):
            raise ReferenceCalibrationStudyError(
                f"Calibration event line {index + 1} is not an object"
            )
        recorded_hash = event.pop("event_hash", None)
        if event.get("sequence") != index or event.get("previous_hash") != previous_hash:
            raise ReferenceCalibrationStudyError(
                f"Calibration event chain is broken at line {index + 1}"
            )
        expected_hash = _canonical_hash(event)
        event["event_hash"] = recorded_hash
        if recorded_hash != expected_hash:
            raise ReferenceCalibrationStudyError(
                f"Calibration event hash differs at line {index + 1}"
            )
        previous_hash = str(recorded_hash)
        events.append(event)
    if not events or events[0].get("event") != "study_created":
        raise ReferenceCalibrationStudyError(
            "Calibration event ledger does not start with study_created"
        )
    return tuple(events)


def _append_event(root: Path, event: str, payload: Mapping[str, object]) -> dict[str, Any]:
    events = _load_events(root) if (root / STUDY_EVENTS).exists() else ()
    record: dict[str, Any] = {
        "event_version": EVENT_VERSION,
        "sequence": len(events),
        "previous_hash": events[-1]["event_hash"] if events else None,
        "event": event,
        **dict(payload),
    }
    record["event_hash"] = _canonical_hash(record)
    path = root / STUDY_EVENTS
    try:
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(_canonical_json(record) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as error:
        raise ReferenceCalibrationStudyError(
            f"Could not append calibration event: {error}"
        ) from error
    return record


def _find_plan(config: Mapping[str, Any]) -> ReferenceCalibrationPlan:
    try:
        provenance = config["project"]["parameter_provenance"]["recommendation"][
            "calibration_plan"
        ]
    except (KeyError, TypeError) as error:
        raise ReferenceCalibrationStudyError(
            "The project has no transparent calibration plan. Analyze aligned "
            "meshes and create the plan first."
        ) from error
    if not isinstance(provenance, Mapping):
        raise ReferenceCalibrationStudyError(
            "The stored calibration plan is not a mapping"
        )
    return reference_calibration_plan_from_provenance(provenance)


def _candidate_configuration(
    source_config: Mapping[str, Any],
    *,
    root: Path,
    candidate_directory: Path,
    template_relative: str,
    subject_directory_relative: str,
    selected_values: Mapping[str, float],
    candidate: CalibrationCandidate,
    template_diagonal: float,
    pilot_max_iterations: int,
) -> dict[str, Any]:
    config = copy.deepcopy(dict(source_config))
    values = dict(selected_values)
    values.update(candidate.values)
    config["project"]["name"] = (
        f"{source_config['project']['name']} calibration {candidate.candidate_id}"
    )
    config["input"]["directory"] = os.path.relpath(
        root / subject_directory_relative,
        candidate_directory,
    ).replace("\\", "/")
    config["input"]["template"] = os.path.relpath(
        root / template_relative,
        candidate_directory,
    ).replace("\\", "/")
    config["input"]["subject_pattern"] = "*.vtk"
    config["output"]["directory"] = "./runs"
    config["optimization"]["max_iterations"] = pilot_max_iterations
    parameter_targets = {
        "attachment_kernel_width": ("attachment", "kernel_width"),
        "deformation_kernel_width": ("deformation", "kernel_width"),
        "initial_control_point_spacing": (
            "deformation",
            "initial_control_point_spacing",
        ),
    }
    for name, value in values.items():
        normalized = float(value)
        if name == "noise_std":
            config["model"]["noise_std"] = normalized
        elif name == "timepoints":
            config["model"]["deformation"]["timepoints"] = int(normalized)
        elif name in parameter_targets:
            group, key = parameter_targets[name]
            config["model"][group][key] = normalized
        else:
            raise ReferenceCalibrationStudyError(
                f"Unsupported calibration parameter: {name}"
            )
        if name != "timepoints":
            config["project"]["parameter_provenance"]["ratios"][name] = (
                normalized / template_diagonal
            )
            config["project"]["parameter_provenance"]["sources"][name] = (
                "absolute_override"
            )
    validate_schema(config)
    return config


def _prepare_stage(
    root: Path,
    manifest: Mapping[str, Any],
    plan: ReferenceCalibrationPlan,
    stage: CalibrationStage,
    selected_values: Mapping[str, float],
) -> dict[str, object]:
    source_config = load_config(_safe_study_path(root, manifest["source_config"]["copy"]))
    stage_directory = root / "stages" / f"{stage.order:02d}-{stage.stage_id}"
    records: list[dict[str, object]] = []
    for candidate in stage.candidates:
        candidate_directory = stage_directory / candidate.candidate_id
        candidate_directory.mkdir(parents=True, exist_ok=False)
        config = _candidate_configuration(
            source_config,
            root=root,
            candidate_directory=candidate_directory,
            template_relative=str(manifest["inputs"]["template"]["copy"]),
            subject_directory_relative=str(manifest["inputs"]["subject_directory"]),
            selected_values=selected_values,
            candidate=candidate,
            template_diagonal=float(manifest["template_diagonal"]),
            pilot_max_iterations=int(manifest["pilot_max_iterations"]),
        )
        config_path = candidate_directory / "atlas.yaml"
        _write_yaml(config_path, config, overwrite=False)
        records.append(
            {
                "candidate_id": candidate.candidate_id,
                "config": _relative_path(root, config_path),
                "config_sha256": sha256_file(config_path),
                "parameter_values": candidate.values,
                "locked_values": dict(selected_values),
            }
        )
    return _append_event(
        root,
        "stage_prepared",
        {
            "stage_id": stage.stage_id,
            "stage_order": stage.order,
            "candidates": records,
        },
    )


def create_reference_calibration_study(
    config_path: Path | str,
    study_directory: Path | str,
    *,
    pilot_max_iterations: int = 150,
) -> ReferenceCalibrationStudySnapshot:
    """Create an immutable-input staged study without launching Deformetrica."""

    if (
        isinstance(pilot_max_iterations, bool)
        or not isinstance(pilot_max_iterations, int)
        or pilot_max_iterations < 1
    ):
        raise ValueError("pilot_max_iterations must be a positive integer")
    source = Path(config_path).expanduser().resolve()
    config = load_config(source)
    plan = _find_plan(config)
    inputs = validate_input_paths(config, source)
    by_name = {path.name: path for path in inputs.subjects}
    selected_paths: list[Path] = []
    for selected in plan.selected_pilot_subjects:
        path = by_name.get(selected.filename)
        if path is None:
            raise ReferenceCalibrationStudyError(
                f"Selected pilot subject is absent: {selected.filename}"
            )
        if sha256_file(path) != selected.sha256:
            raise ReferenceCalibrationStudyError(
                f"Selected pilot subject changed after planning: {selected.filename}"
            )
        selected_paths.append(path)
    if sha256_file(inputs.template) != plan.template_sha256:
        raise ReferenceCalibrationStudyError(
            "Template bytes changed after calibration planning"
        )
    root = Path(study_directory).expanduser().resolve()
    if root.exists():
        raise ReferenceCalibrationStudyError(
            f"Calibration study destination already exists: {root}"
        )
    root.mkdir(parents=True)
    try:
        source_copy = root / "source" / "atlas.yaml"
        _copy_bound(source, source_copy, sha256_file(source))
        template_copy = root / "inputs" / "template" / inputs.template.name
        _copy_bound(inputs.template, template_copy, plan.template_sha256)
        subject_records: list[dict[str, object]] = []
        for selected, path in zip(
            plan.selected_pilot_subjects, selected_paths, strict=True
        ):
            destination = root / "inputs" / "subjects" / path.name
            _copy_bound(path, destination, selected.sha256)
            subject_records.append(
                {
                    "filename": path.name,
                    "copy": _relative_path(root, destination),
                    "sha256": selected.sha256,
                }
            )
        template_diagonal = float(
            config["model"]["attachment"]["kernel_width"]
        ) / float(
            config["project"]["parameter_provenance"]["ratios"][
                "attachment_kernel_width"
            ]
        )
        if not math.isfinite(template_diagonal) or template_diagonal <= 0:
            raise ReferenceCalibrationStudyError(
                "Could not reconstruct the template diagonal from project provenance"
            )
        launcher = launcher_identity(config["runtime"]["launcher"])
        manifest: dict[str, object] = {
            "study_version": STUDY_VERSION,
            "study_id": f"reference-calibration-{uuid4().hex[:12]}",
            "plan_fingerprint": plan.fingerprint,
            "plan": plan.provenance,
            "pilot_max_iterations": pilot_max_iterations,
            "template_diagonal": template_diagonal,
            "launcher": launcher,
            "source_config": {
                "original_path": str(source),
                "copy": _relative_path(root, source_copy),
                "sha256": sha256_file(source_copy),
            },
            "inputs": {
                "template": {
                    "copy": _relative_path(root, template_copy),
                    "sha256": plan.template_sha256,
                },
                "subject_directory": "inputs/subjects",
                "subjects": subject_records,
                "full_cohort": {
                    "directory": str(inputs.input_directory),
                    "template": str(inputs.template),
                    "subject_pattern": str(config["input"]["subject_pattern"]),
                },
            },
            "scientific_boundary": (
                "DiffeoForge executes and measures predeclared candidates, but never "
                "turns its balanced score into automatic anatomical approval."
            ),
        }
        _write_json(root / STUDY_MANIFEST, manifest, overwrite=False)
        write_text_safely(
            root / STUDY_DIGEST,
            sha256_file(root / STUDY_MANIFEST) + "\n",
            overwrite=False,
        )
        _append_event(
            root,
            "study_created",
            {
                "study_id": manifest["study_id"],
                "plan_fingerprint": plan.fingerprint,
                "manifest_sha256": sha256_file(root / STUDY_MANIFEST),
            },
        )
        _prepare_stage(root, manifest, plan, plan.stages[0], {})
    except BaseException:
        shutil.rmtree(root, ignore_errors=True)
        raise
    return load_reference_calibration_study(root)


def _verify_manifest(root: Path) -> dict[str, Any]:
    manifest_path = root / STUDY_MANIFEST
    manifest = _read_json(manifest_path, "calibration study manifest")
    try:
        expected = (root / STUDY_DIGEST).read_text(encoding="utf-8").strip()
    except OSError as error:
        raise ReferenceCalibrationStudyError(
            f"Could not read calibration study digest: {error}"
        ) from error
    if sha256_file(manifest_path) != expected:
        raise ReferenceCalibrationStudyError(
            "Calibration study manifest SHA-256 does not match"
        )
    if manifest.get("study_version") != STUDY_VERSION:
        raise ReferenceCalibrationStudyError(
            f"Unsupported calibration study version: {manifest.get('study_version')}"
        )
    plan_value = manifest.get("plan")
    if not isinstance(plan_value, Mapping):
        raise ReferenceCalibrationStudyError(
            "Calibration study does not contain a plan"
        )
    plan = reference_calibration_plan_from_provenance(plan_value)
    if manifest.get("plan_fingerprint") != plan.fingerprint:
        raise ReferenceCalibrationStudyError(
            "Calibration study plan binding differs"
        )
    bound_files = [
        manifest["source_config"],
        manifest["inputs"]["template"],
        *manifest["inputs"]["subjects"],
    ]
    for record in bound_files:
        path = _safe_study_path(root, record["copy"])
        if not path.is_file() or sha256_file(path) != record["sha256"]:
            raise ReferenceCalibrationStudyError(
                f"Calibration study input changed or is absent: {path}"
            )
    return manifest


def _prepared_candidates(
    root: Path,
    events: tuple[dict[str, Any], ...],
    stage_id: str,
) -> dict[str, dict[str, Any]]:
    prepared = [
        event
        for event in events
        if event["event"] == "stage_prepared" and event["stage_id"] == stage_id
    ]
    if len(prepared) != 1:
        raise ReferenceCalibrationStudyError(
            f"Calibration stage {stage_id!r} is not prepared exactly once"
        )
    records = {record["candidate_id"]: record for record in prepared[0]["candidates"]}
    for record in records.values():
        config = _safe_study_path(root, record["config"])
        if not config.is_file() or sha256_file(config) != record["config_sha256"]:
            raise ReferenceCalibrationStudyError(
                f"Calibration candidate configuration changed: {config}"
            )
    return records


def _selected_state(
    events: tuple[dict[str, Any], ...],
) -> tuple[dict[str, float], dict[str, str]]:
    values: dict[str, float] = {}
    candidates: dict[str, str] = {}
    for event in events:
        if event["event"] == "stage_selected":
            candidates[str(event["stage_id"])] = str(event["candidate_id"])
            values.update(
                {
                    str(name): float(value)
                    for name, value in event["parameter_values"].items()
                }
            )
    return values, candidates


def load_reference_calibration_study(
    study_directory: Path | str,
) -> ReferenceCalibrationStudySnapshot:
    """Verify and reconstruct one study exclusively from bound bytes and events."""

    root = Path(study_directory).expanduser().resolve()
    if not root.is_dir():
        raise ReferenceCalibrationStudyError(
            f"Calibration study directory does not exist: {root}"
        )
    manifest = _verify_manifest(root)
    plan = reference_calibration_plan_from_provenance(manifest["plan"])
    events = _load_events(root)
    if (
        events[0]["study_id"] != manifest["study_id"]
        or events[0]["manifest_sha256"] != sha256_file(root / STUDY_MANIFEST)
    ):
        raise ReferenceCalibrationStudyError(
            "Calibration event ledger is bound to a different manifest"
        )
    selected_values, selected_candidates = _selected_state(events)
    final_events = [event for event in events if event["event"] == "study_completed"]
    if final_events:
        final_config = _safe_study_path(root, final_events[-1]["final_config"])
        if (
            not final_config.is_file()
            or sha256_file(final_config) != final_events[-1]["final_config_sha256"]
        ):
            raise ReferenceCalibrationStudyError(
                "Final calibrated configuration changed or is absent"
            )
        return ReferenceCalibrationStudySnapshot(
            study_directory=root,
            study_id=str(manifest["study_id"]),
            plan=plan,
            status="completed",
            current_stage=None,
            candidates=(),
            selected_values=selected_values,
            selected_candidate_ids=selected_candidates,
            event_count=len(events),
            final_config_path=final_config,
        )
    stage = plan.stages[len(selected_candidates)]
    prepared = _prepared_candidates(root, events, stage.stage_id)
    candidate_states: list[CalibrationStudyCandidateState] = []
    for candidate in stage.candidates:
        candidate_events = [
            event
            for event in events
            if event.get("stage_id") == stage.stage_id
            and event.get("candidate_id") == candidate.candidate_id
        ]
        completed = [
            event for event in candidate_events if event["event"] == "candidate_completed"
        ]
        failures = [
            event
            for event in candidate_events
            if event["event"] in {"candidate_failed", "candidate_interrupted"}
        ]
        starts = [
            event for event in candidate_events if event["event"] == "candidate_started"
        ]
        latest = (completed or failures or starts or [None])[-1]
        if completed:
            status = "completed"
        elif failures:
            status = (
                "interrupted"
                if failures[-1]["event"] == "candidate_interrupted"
                else "failed"
            )
        elif starts:
            status = "orphaned"
        else:
            status = "pending"
        candidate_states.append(
            CalibrationStudyCandidateState(
                candidate_id=candidate.candidate_id,
                label=candidate.label,
                status=status,
                config_path=_safe_study_path(
                    root, prepared[candidate.candidate_id]["config"]
                ),
                run_directory=(
                    None
                    if latest is None or latest.get("run_directory") is None
                    else _safe_study_path(root, latest["run_directory"])
                ),
                metrics=(completed[-1]["metrics"] if completed else None),
                error=(
                    None
                    if completed
                    else (
                        str(failures[-1].get("error"))
                        if failures
                        else (
                            "The previous DiffeoForge process ended before recording a "
                            "terminal candidate event; retry creates a new immutable attempt."
                            if starts
                            else None
                        )
                    )
                ),
                attempts=len(starts),
            )
        )
    awaiting = any(
        event["event"] == "stage_awaiting_review"
        and event["stage_id"] == stage.stage_id
        for event in events
    )
    status = (
        "awaiting_review"
        if awaiting
        else (
            "running"
            if any(item.status == "orphaned" for item in candidate_states)
            else "ready"
        )
    )
    return ReferenceCalibrationStudySnapshot(
        study_directory=root,
        study_id=str(manifest["study_id"]),
        plan=plan,
        status=status,
        current_stage=stage,
        candidates=tuple(candidate_states),
        selected_values=selected_values,
        selected_candidate_ids=selected_candidates,
        event_count=len(events),
        final_config_path=None,
    )


def _launch_request(
    root: Path,
    manifest: Mapping[str, Any],
    candidate: CalibrationStudyCandidateState,
) -> DesktopReferenceLaunchRequest:
    attempt = candidate.attempts + 1
    run_id = f"pilot-attempt-{attempt:02d}"
    destination = (candidate.config_path.parent / "runs" / run_id).resolve()
    launcher = manifest["launcher"]
    return DesktopReferenceLaunchRequest(
        request_id=f"calibration-{uuid4().hex}",
        config_path=candidate.config_path,
        destination=destination,
        run_id=run_id,
        expected_config_sha256=sha256_file(candidate.config_path),
        launcher_engine=launcher.get("engine"),
        launcher_image=launcher.get("image"),
        launcher_type=str(launcher["type"]),
        launcher_distribution=launcher.get("distribution"),
        launcher_executable=launcher.get("executable"),
    )


class ReferenceCalibrationStudyRunner:
    """Run every pending candidate in the current stage using one controller each."""

    def __init__(
        self,
        study_directory: Path | str,
        *,
        controller_factory: ControllerFactory = ReferenceExecutionController,
    ) -> None:
        self.study_directory = Path(study_directory).expanduser().resolve()
        self._controller_factory = controller_factory
        self._active_controller: _Controller | None = None
        self._cancel_requested = False

    def request_cancel(self) -> bool:
        if self._cancel_requested:
            return False
        self._cancel_requested = True
        if self._active_controller is not None:
            self._active_controller.request_cancel()
        return True

    def run_current_stage(
        self,
        *,
        event_callback: StudyEventCallback | None = None,
    ) -> ReferenceCalibrationStudySnapshot:
        snapshot = load_reference_calibration_study(self.study_directory)
        if snapshot.status == "completed":
            raise ReferenceCalibrationStudyError(
                "Calibration study is already complete"
            )
        if snapshot.status == "awaiting_review" and all(
            candidate.status == "completed"
            for candidate in snapshot.candidates
        ):
            return snapshot
        manifest = _verify_manifest(self.study_directory)
        assert snapshot.current_stage is not None
        for candidate in snapshot.candidates:
            if candidate.status == "completed":
                continue
            if self._cancel_requested:
                break
            request = _launch_request(self.study_directory, manifest, candidate)
            started = _append_event(
                self.study_directory,
                "candidate_started",
                {
                    "stage_id": snapshot.current_stage.stage_id,
                    "candidate_id": candidate.candidate_id,
                    "attempt": candidate.attempts + 1,
                    "request_id": request.request_id,
                    "run_directory": _relative_path(
                        self.study_directory, request.destination
                    ),
                },
            )
            if event_callback is not None:
                event_callback(started)
            controller = self._controller_factory(request)
            self._active_controller = controller

            def forward(
                event: DesktopReferenceWorkerEvent,
                candidate_id: str = candidate.candidate_id,
            ) -> None:
                if event_callback is not None:
                    event_callback(
                        {
                            "event": "candidate_worker_event",
                            "stage_id": snapshot.current_stage.stage_id,
                            "candidate_id": candidate_id,
                            "worker_event": event.as_dict(),
                        }
                    )

            try:
                result = controller.run(event_callback=forward)
                if result.completed:
                    metrics = collect_reference_calibration_run_metrics(
                        request.destination
                    )
                    terminal = _append_event(
                        self.study_directory,
                        "candidate_completed",
                        {
                            "stage_id": snapshot.current_stage.stage_id,
                            "candidate_id": candidate.candidate_id,
                            "attempt": candidate.attempts + 1,
                            "run_directory": _relative_path(
                                self.study_directory, request.destination
                            ),
                            "metrics": metrics.as_manifest(),
                        },
                    )
                else:
                    terminal = _append_event(
                        self.study_directory,
                        "candidate_interrupted",
                        {
                            "stage_id": snapshot.current_stage.stage_id,
                            "candidate_id": candidate.candidate_id,
                            "attempt": candidate.attempts + 1,
                            "run_directory": _relative_path(
                                self.study_directory, request.destination
                            ),
                            "error": (
                                "Candidate execution was cancelled. Starting the stage "
                                "again retains completed candidates and creates a new "
                                "immutable attempt for this candidate."
                            ),
                        },
                    )
                    self._cancel_requested = True
            except Exception as error:
                terminal = _append_event(
                    self.study_directory,
                    "candidate_failed",
                    {
                        "stage_id": snapshot.current_stage.stage_id,
                        "candidate_id": candidate.candidate_id,
                        "attempt": candidate.attempts + 1,
                        "run_directory": (
                            _relative_path(self.study_directory, request.destination)
                            if request.destination.exists()
                            else None
                        ),
                        "error": str(error),
                    },
                )
            finally:
                self._active_controller = None
            if event_callback is not None:
                event_callback(terminal)
        updated = load_reference_calibration_study(self.study_directory)
        if not self._cancel_requested and all(
            candidate.status in {"completed", "failed"}
            for candidate in updated.candidates
        ):
            events = _load_events(self.study_directory)
            assert updated.current_stage is not None
            if not any(
                event["event"] == "stage_awaiting_review"
                and event["stage_id"] == updated.current_stage.stage_id
                for event in events
            ):
                review = _append_event(
                    self.study_directory,
                    "stage_awaiting_review",
                    {
                        "stage_id": updated.current_stage.stage_id,
                        "completed_candidates": [
                            candidate.candidate_id
                            for candidate in updated.candidates
                            if candidate.status == "completed"
                        ],
                        "failed_candidates": [
                            candidate.candidate_id
                            for candidate in updated.candidates
                            if candidate.status == "failed"
                        ],
                    },
                )
                if event_callback is not None:
                    event_callback(review)
        return load_reference_calibration_study(self.study_directory)


def _relative_difference(first: float, second: float) -> float:
    return abs(first - second) / max(abs(first), abs(second), 1e-15)


def _stage_evidence(
    snapshot: ReferenceCalibrationStudySnapshot,
    visual_approvals: Mapping[str, bool],
) -> tuple[CalibrationCandidateEvidence, ...]:
    completed = {
        candidate.candidate_id: candidate
        for candidate in snapshot.candidates
        if candidate.status == "completed" and candidate.metrics is not None
    }
    assert snapshot.current_stage is not None
    numerical: dict[str, tuple[float, float, float]] = {}
    if snapshot.current_stage.kind == "integration_accuracy":
        ordered = [
            candidate
            for candidate in snapshot.candidates
            if candidate.candidate_id in completed
        ]
        for index, candidate in enumerate(ordered):
            neighbor = ordered[index + 1] if index + 1 < len(ordered) else (
                ordered[index - 1] if index else None
            )
            if neighbor is None:
                continue
            first = candidate.metrics
            second = neighbor.metrics
            assert first is not None and second is not None
            numerical[candidate.candidate_id] = (
                atlas_rms_distance(first["atlas_path"], second["atlas_path"]),
                _relative_difference(
                    float(first["attachment_objective_magnitude"])
                    + float(first["deformation_energy"]),
                    float(second["attachment_objective_magnitude"])
                    + float(second["deformation_energy"]),
                ),
                _relative_difference(
                    float(first["residual_p95"]),
                    float(second["residual_p95"]),
                ),
            )
    evidence: list[CalibrationCandidateEvidence] = []
    for candidate in snapshot.candidates:
        metrics = candidate.metrics
        comparison = numerical.get(candidate.candidate_id)
        evidence.append(
            CalibrationCandidateEvidence(
                candidate_id=candidate.candidate_id,
                completed=metrics is not None,
                converged=bool(metrics and metrics["converged"]),
                invalid_face_count=(
                    int(metrics["invalid_face_count"]) if metrics else 0
                ),
                residual_p95=(
                    float(metrics["residual_p95"]) if metrics else None
                ),
                deformation_energy=(
                    float(metrics["deformation_energy"]) if metrics else None
                ),
                distortion_p95=(
                    float(metrics["distortion_p95"]) if metrics else None
                ),
                runtime_seconds=(
                    float(metrics["runtime_seconds"]) if metrics else None
                ),
                resampling_sensitivity=(
                    float(metrics["resampling_sensitivity"]) if metrics else None
                ),
                numerical_atlas_rms=(
                    comparison[0] if comparison is not None else None
                ),
                objective_relative_difference=(
                    comparison[1] if comparison is not None else None
                ),
                residual_relative_difference=(
                    comparison[2] if comparison is not None else None
                ),
                review_approved=bool(
                    visual_approvals.get(candidate.candidate_id, False)
                ),
                notes=((candidate.error,) if candidate.error else ()),
            )
        )
    return tuple(evidence)


def _final_configuration(
    root: Path,
    manifest: Mapping[str, Any],
    selected_values: Mapping[str, float],
    selected_candidate_ids: Mapping[str, str],
    decision_event_hash: str,
) -> Path:
    source = load_config(_safe_study_path(root, manifest["source_config"]["copy"]))
    config = copy.deepcopy(dict(source))
    config["input"]["directory"] = str(
        manifest["inputs"]["full_cohort"]["directory"]
    )
    config["input"]["template"] = str(
        manifest["inputs"]["full_cohort"]["template"]
    )
    config["input"]["subject_pattern"] = str(
        manifest["inputs"]["full_cohort"]["subject_pattern"]
    )
    targets = {
        "attachment_kernel_width": ("attachment", "kernel_width"),
        "deformation_kernel_width": ("deformation", "kernel_width"),
        "initial_control_point_spacing": (
            "deformation",
            "initial_control_point_spacing",
        ),
    }
    for name, value in selected_values.items():
        if name == "noise_std":
            config["model"]["noise_std"] = value
        elif name == "timepoints":
            config["model"]["deformation"]["timepoints"] = int(value)
        else:
            group, key = targets[name]
            config["model"][group][key] = value
        if name != "timepoints":
            config["project"]["parameter_provenance"]["ratios"][name] = (
                value / float(manifest["template_diagonal"])
            )
            config["project"]["parameter_provenance"]["sources"][name] = (
                "absolute_override"
            )
    config["project"]["parameter_provenance"]["recommendation"][
        "calibration_result"
    ] = {
        "version": "0.1",
        "status": "completed",
        "study_id": str(manifest["study_id"]),
        "plan_fingerprint": str(manifest["plan_fingerprint"]),
        "study_manifest_sha256": sha256_file(root / STUDY_MANIFEST),
        "decision_event_hash": decision_event_hash,
        "selected_candidate_ids": dict(selected_candidate_ids),
        "selected_values": {
            name: int(value) if name == "timepoints" else float(value)
            for name, value in selected_values.items()
        },
        "full_cohort_confirmation_required": True,
    }
    validate_schema(config)
    final_path = root / "selected" / "atlas-calibrated.yaml"
    final_path.parent.mkdir(parents=True, exist_ok=False)
    _write_yaml(final_path, config, overwrite=False)
    return final_path


def record_reference_calibration_stage_review(
    study_directory: Path | str,
    *,
    visual_approvals: Mapping[str, bool],
    selected_candidate_id: str,
) -> tuple[ReferenceCalibrationStudySnapshot, CalibrationStageAssessment]:
    """Record explicit visual approvals and advance one reviewed stage."""

    root = Path(study_directory).expanduser().resolve()
    snapshot = load_reference_calibration_study(root)
    if snapshot.status != "awaiting_review" or snapshot.current_stage is None:
        raise ReferenceCalibrationStudyError(
            "The current calibration stage is not awaiting review"
        )
    evidence = _stage_evidence(snapshot, visual_approvals)
    assessment = assess_calibration_stage(
        snapshot.plan,
        stage_id=snapshot.current_stage.stage_id,
        evidence=evidence,
    )
    selected_assessment = next(
        (
            candidate
            for candidate in assessment.candidates
            if candidate.candidate_id == selected_candidate_id
        ),
        None,
    )
    if selected_assessment is None:
        raise ReferenceCalibrationStudyError(
            f"Unknown candidate selection: {selected_candidate_id}"
        )
    if not selected_assessment.eligible:
        raise ReferenceCalibrationStudyError(
            "Selected candidate is not eligible: "
            + "; ".join(selected_assessment.rejection_reasons)
        )
    selected = next(
        candidate
        for candidate in snapshot.current_stage.candidates
        if candidate.candidate_id == selected_candidate_id
    )
    _append_event(
        root,
        "stage_selected",
        {
            "stage_id": snapshot.current_stage.stage_id,
            "candidate_id": selected_candidate_id,
            "parameter_values": selected.values,
            "visual_approvals": dict(visual_approvals),
            "assessment": assessment.as_manifest(),
            "researcher_decision": True,
        },
    )
    manifest = _verify_manifest(root)
    selected_values, selected_candidates = _selected_state(_load_events(root))
    if snapshot.current_stage.order < len(snapshot.plan.stages):
        next_stage = snapshot.plan.stages[snapshot.current_stage.order]
        _prepare_stage(
            root,
            manifest,
            snapshot.plan,
            next_stage,
            selected_values,
        )
    else:
        decision_event_hash = str(_load_events(root)[-1]["event_hash"])
        final_path = _final_configuration(
            root,
            manifest,
            selected_values,
            selected_candidates,
            decision_event_hash,
        )
        _append_event(
            root,
            "study_completed",
            {
                "selected_candidate_ids": selected_candidates,
                "selected_values": selected_values,
                "final_config": _relative_path(root, final_path),
                "final_config_sha256": sha256_file(final_path),
                "full_cohort_confirmation_required": True,
            },
        )
    return load_reference_calibration_study(root), assessment
