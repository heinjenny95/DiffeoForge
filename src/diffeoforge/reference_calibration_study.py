"""Resumable execution of transparent Deformetrica pilot calibration.

The scientific design remains sequential because each selected parameter family
is locked before the next family is varied.  The standard runner can execute all
four stages in one operation and make explicitly provisional, reproducible
recommendations from the declared priorities and automatic evidence.  A manual
stage-by-stage review route remains available.
"""

from __future__ import annotations

import copy
import hashlib
import html
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
CALIBRATION_REPORT_JSON = "selected/pilot-calibration-report.json"
CALIBRATION_REPORT_HTML = "selected/pilot-calibration-report.html"
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
    report_json_path: Path | None
    report_html_path: Path | None


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
                "DiffeoForge may use its published balanced score for an automatic "
                "provisional recommendation, but never represents that score as "
                "automatic anatomical approval or final scientific validation."
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
        final_event = final_events[-1]
        final_config = _safe_study_path(root, final_event["final_config"])
        if (
            not final_config.is_file()
            or sha256_file(final_config) != final_event["final_config_sha256"]
        ):
            raise ReferenceCalibrationStudyError(
                "Final calibrated configuration changed or is absent"
            )
        report_json: Path | None = None
        report_html: Path | None = None
        for key, digest_key, label in (
            ("report_json", "report_json_sha256", "JSON calibration report"),
            ("report_html", "report_html_sha256", "HTML calibration report"),
        ):
            if key not in final_event:
                continue
            report_path = _safe_study_path(root, final_event[key])
            if (
                not report_path.is_file()
                or sha256_file(report_path) != final_event.get(digest_key)
            ):
                raise ReferenceCalibrationStudyError(f"{label} changed or is absent")
            if key == "report_json":
                report_json = report_path
            else:
                report_html = report_path
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
            report_json_path=report_json,
            report_html_path=report_html,
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
        report_json_path=None,
        report_html_path=None,
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

    def run_complete_automatic_pilot(
        self,
        *,
        event_callback: StudyEventCallback | None = None,
    ) -> ReferenceCalibrationStudySnapshot:
        """Run every remaining stage and record provisional automatic selections.

        Candidate generation is already centered on the researcher's declared
        surface-detail and deformation-scale priorities.  At each stage this route
        selects the eligible Pareto candidate with the lowest published weighted
        comparison score.  The event ledger records that this was an automatic,
        provisional recommendation rather than a researcher anatomy approval.
        """

        while True:
            snapshot = load_reference_calibration_study(self.study_directory)
            if snapshot.status == "completed" or self._cancel_requested:
                return snapshot
            if snapshot.status != "awaiting_review":
                snapshot = self.run_current_stage(event_callback=event_callback)
                if self._cancel_requested:
                    return snapshot
            if snapshot.status != "awaiting_review":
                continue
            incomplete = [
                candidate.candidate_id
                for candidate in snapshot.candidates
                if candidate.status != "completed"
            ]
            if incomplete:
                raise ReferenceCalibrationStudyError(
                    "Automatic pilot calibration paused because not every candidate "
                    "completed successfully. Retry the pilot after reviewing: "
                    + ", ".join(incomplete)
                )
            stage_id = snapshot.current_stage.stage_id if snapshot.current_stage else ""
            updated, assessment = select_reference_calibration_stage_automatically(
                self.study_directory
            )
            selected_id = updated.selected_candidate_ids.get(stage_id, "")
            if event_callback is not None:
                event_callback(
                    {
                        "event": "automatic_stage_selected",
                        "stage_id": stage_id,
                        "candidate_id": selected_id,
                        "balanced_candidate_id": assessment.balanced_candidate_id,
                        "completed_stage_count": len(updated.selected_candidate_ids),
                        "stage_count": len(updated.plan.stages),
                    }
                )
            if updated.status == "completed":
                return updated


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
                review_approved=visual_approvals.get(candidate.candidate_id),
                notes=((candidate.error,) if candidate.error else ()),
            )
        )
    return tuple(evidence)


def _final_configuration(
    root: Path,
    manifest: Mapping[str, Any],
    selected_values: Mapping[str, float],
    selected_candidate_ids: Mapping[str, str],
    selection_modes: Mapping[str, str],
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
        "selection_modes": dict(selection_modes),
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


_PARAMETER_REPORT_GUIDANCE: dict[str, tuple[str, str]] = {
    "attachment_kernel_width": (
        "Surface-matching detail width",
        "Smaller values follow finer surface detail but can follow mesh texture or "
        "noise. Larger values emphasize broader, smoother shape agreement.",
    ),
    "deformation_kernel_width": (
        "Deformation spread",
        "Smaller values allow changes to remain more local and flexible. Larger "
        "values spread motion more smoothly and globally.",
    ),
    "initial_control_point_spacing": (
        "Initial control-point spacing",
        "Smaller spacing creates a denser, more flexible and more expensive control "
        "grid. Larger spacing creates a sparser, smoother grid.",
    ),
    "noise_std": (
        "Fit-versus-regularity weight",
        "Smaller values push harder toward the observed surfaces. Larger values "
        "permit more mismatch in exchange for smoother deformation.",
    ),
    "timepoints": (
        "Numerical time points",
        "More points calculate the deformation path more finely but usually increase "
        "runtime. This controls numerical accuracy, not anatomical flexibility.",
    ),
}


def _selection_reason(
    assessment: CalibrationStageAssessment,
    selected_candidate_id: str,
) -> str:
    selected = next(
        candidate
        for candidate in assessment.candidates
        if candidate.candidate_id == selected_candidate_id
    )
    score = selected.balanced_score
    score_text = "not available" if score is None else f"{score:.6g}"
    return (
        "Automatically retained the eligible Pareto candidate with the lowest "
        f"published weighted comparison score ({score_text}). The tested candidates "
        "were centered on the researcher's previously declared biological priorities."
    )


def _calibration_report_payload(
    root: Path,
    manifest: Mapping[str, Any],
    plan: ReferenceCalibrationPlan,
    events: tuple[dict[str, Any], ...],
    selected_values: Mapping[str, float],
    selected_candidate_ids: Mapping[str, str],
    final_config: Path,
) -> dict[str, object]:
    source = load_config(_safe_study_path(root, manifest["source_config"]["copy"]))
    recommendation = (
        source.get("project", {})
        .get("parameter_provenance", {})
        .get("recommendation", {})
    )
    declared_priorities = {
        "surface_detail_intent": recommendation.get(
            "surface_detail_intent", "not recorded"
        ),
        "deformation_scale_intent": recommendation.get(
            "deformation_scale_intent", "not recorded"
        ),
        "smallest_relevant_feature": plan.smallest_relevant_feature,
    }
    selection_events = {
        str(event["stage_id"]): event
        for event in events
        if event["event"] == "stage_selected"
    }
    stages: list[dict[str, object]] = []
    for stage in plan.stages:
        selected_id = selected_candidate_ids[stage.stage_id]
        selected = next(
            candidate
            for candidate in stage.candidates
            if candidate.candidate_id == selected_id
        )
        event = selection_events[stage.stage_id]
        assessment = event.get("assessment", {})
        assessment_candidates = {
            str(candidate["candidate_id"]): candidate
            for candidate in assessment.get("candidates", [])
        }
        alternatives = []
        for candidate in stage.candidates:
            candidate_assessment = assessment_candidates.get(candidate.candidate_id, {})
            alternatives.append(
                {
                    "candidate_id": candidate.candidate_id,
                    "label": candidate.label,
                    "parameter_values": candidate.values,
                    "eligible": candidate_assessment.get("eligible"),
                    "pareto_optimal": candidate_assessment.get("pareto_optimal"),
                    "balanced_score": candidate_assessment.get("balanced_score"),
                    "rejection_reasons": candidate_assessment.get(
                        "rejection_reasons", []
                    ),
                    "selected": candidate.candidate_id == selected_id,
                }
            )
        stages.append(
            {
                "stage_id": stage.stage_id,
                "title": stage.title,
                "selected_candidate_id": selected_id,
                "selected_label": selected.label,
                "selected_parameter_values": selected.values,
                "selection_mode": event.get("selection_mode", "researcher_manual"),
                "selection_reason": event.get(
                    "selection_reason",
                    "The researcher explicitly selected this candidate.",
                ),
                "balanced_candidate_id": assessment.get("balanced_candidate_id"),
                "metric_weights": assessment.get("metric_weights", {}),
                "alternatives": alternatives,
            }
        )
    parameters = []
    for name in (
        "attachment_kernel_width",
        "deformation_kernel_width",
        "initial_control_point_spacing",
        "noise_std",
        "timepoints",
    ):
        title, meaning = _PARAMETER_REPORT_GUIDANCE[name]
        value = selected_values[name]
        parameters.append(
            {
                "name": name,
                "title": title,
                "value": int(value) if name == "timepoints" else float(value),
                "unit": None if name == "timepoints" else plan.coordinate_unit,
                "meaning": meaning,
            }
        )
    return {
        "report_version": "0.1",
        "study_id": manifest["study_id"],
        "plan_fingerprint": plan.fingerprint,
        "status": "provisional_pilot_recommendation",
        "summary": (
            "All four staged pilot comparisons completed. The reported parameter set "
            "is an automatic provisional recommendation, not a claim of anatomical "
            "correctness or final scientific validation."
        ),
        "coordinate_unit": plan.coordinate_unit,
        "pilot_subjects": [
            subject.filename for subject in plan.selected_pilot_subjects
        ],
        "declared_priorities": declared_priorities,
        "recommended_parameters": parameters,
        "stage_decisions": stages,
        "final_configuration": _relative_path(root, final_config),
        "full_cohort_confirmation_required": True,
        "next_steps": list(plan.final_confirmation_required),
        "limitations": list(plan.limitations),
    }


def _format_report_value(value: object, unit: object) -> str:
    if isinstance(value, int):
        rendered = str(value)
    else:
        rendered = f"{float(value):.8g}"
    return rendered if not unit else f"{rendered} {unit}"


def _calibration_report_html(report: Mapping[str, object]) -> str:
    parameters = report["recommended_parameters"]
    stages = report["stage_decisions"]
    priorities = report["declared_priorities"]
    parameter_rows = "".join(
        "<tr>"
        f"<td><strong>{html.escape(str(item['title']))}</strong></td>"
        f"<td>{html.escape(_format_report_value(item['value'], item['unit']))}</td>"
        f"<td>{html.escape(str(item['meaning']))}</td>"
        "</tr>"
        for item in parameters
    )
    rendered_stages: list[str] = []
    for item in stages:
        alternative_rows: list[str] = []
        for candidate in item["alternatives"]:
            values = ", ".join(
                f"{name}={float(value):.8g}"
                for name, value in candidate["parameter_values"].items()
            )
            score = candidate["balanced_score"]
            score_text = "not available" if score is None else f"{float(score):.6g}"
            alternative_rows.append(
                "<tr>"
                f"<td>{html.escape(str(candidate['label']))}</td>"
                f"<td>{html.escape(values)}</td>"
                f"<td>{'yes' if candidate['eligible'] else 'no'}</td>"
                f"<td>{score_text}</td>"
                "</tr>"
            )
        alternatives = "".join(alternative_rows)
        rendered_stages.append(
            "<section class='card'>"
            f"<h3>{html.escape(str(item['title']))}</h3>"
            f"<p><strong>Recommended option:</strong> "
            f"{html.escape(str(item['selected_label']))} "
            f"(<code>{html.escape(str(item['selected_candidate_id']))}</code>)</p>"
            f"<p>{html.escape(str(item['selection_reason']))}</p>"
            "<details><summary>See all tested alternatives and scores</summary>"
            "<p>The balanced score is only comparable within this stage; lower is "
            "favored by the published weighting.</p>"
            "<table><thead><tr><th>Option</th><th>Values</th><th>Passed automatic "
            "checks</th><th>Balanced score</th></tr></thead>"
            f"<tbody>{alternatives}</tbody></table></details>"
            "</section>"
        )
    stage_rows = "".join(rendered_stages)
    next_steps = "".join(
        f"<li>{html.escape(str(item))}</li>" for item in report["next_steps"]
    )
    limitations = "".join(
        f"<li>{html.escape(str(item))}</li>" for item in report["limitations"]
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>DiffeoForge pilot calibration report</title>
<style>
body{{font-family:Segoe UI,Arial,sans-serif;max-width:1100px;margin:36px auto;
padding:0 24px;color:#103b3b;line-height:1.45}}
h1,h2,h3{{color:#073c3b}}
.notice{{background:#e3f6ef;border-left:5px solid #13856f;padding:14px 18px}}
table{{border-collapse:collapse;width:100%}}
th,td{{border:1px solid #c8d9d7;padding:10px;text-align:left;vertical-align:top}}
th{{background:#eef5f4}}
.card{{border:1px solid #c8d9d7;border-radius:8px;padding:10px 16px;margin:12px 0}}
code{{background:#eef5f4;padding:2px 5px}}
.footer{{color:#526c6a;font-size:.9em;margin-top:30px}}
</style></head><body>
<h1>DiffeoForge pilot calibration report</h1>
<p class="notice"><strong>Provisional recommendation.</strong>
{html.escape(str(report['summary']))}</p>
<h2>Your declared priorities</h2>
<p>Surface detail: <strong>{html.escape(str(priorities['surface_detail_intent']))}</strong><br>
Deformation scale: <strong>{html.escape(str(priorities['deformation_scale_intent']))}</strong></p>
<h2>Recommended parameters</h2>
<table><thead><tr><th>Parameter</th><th>Recommended value</th><th>What it changes</th></tr></thead>
<tbody>{parameter_rows}</tbody></table>
<h2>How DiffeoForge reached this recommendation</h2>
<p>Each candidate set was centered on your declared priorities. Among candidates
that passed the automatic validity checks, DiffeoForge retained the Pareto option
with the lowest published weighted comparison score. No automatic score proves
anatomical correctness.</p>
{stage_rows}
<h2>Required next steps</h2><ol>{next_steps}</ol>
<h2>Limitations</h2><ul>{limitations}</ul>
<p class="footer">Study ID: {html.escape(str(report['study_id']))}<br>
Plan fingerprint: <code>{html.escape(str(report['plan_fingerprint']))}</code></p>
</body></html>"""


def _write_calibration_report(
    root: Path,
    manifest: Mapping[str, Any],
    plan: ReferenceCalibrationPlan,
    events: tuple[dict[str, Any], ...],
    selected_values: Mapping[str, float],
    selected_candidate_ids: Mapping[str, str],
    final_config: Path,
) -> tuple[Path, Path]:
    report = _calibration_report_payload(
        root,
        manifest,
        plan,
        events,
        selected_values,
        selected_candidate_ids,
        final_config,
    )
    json_path = root / CALIBRATION_REPORT_JSON
    html_path = root / CALIBRATION_REPORT_HTML
    _write_json(json_path, report, overwrite=False)
    write_text_safely(
        html_path,
        _calibration_report_html(report),
        overwrite=False,
    )
    return json_path, html_path


def load_reference_calibration_report(
    study_directory: Path | str,
) -> dict[str, Any]:
    """Load the verified machine-readable final pilot report."""

    snapshot = load_reference_calibration_study(study_directory)
    if snapshot.status != "completed" or snapshot.report_json_path is None:
        raise ReferenceCalibrationStudyError(
            "The calibration study has no completed recommendation report"
        )
    return _read_json(snapshot.report_json_path, "pilot calibration report")


def _record_reference_calibration_stage_selection(
    study_directory: Path | str,
    *,
    visual_approvals: Mapping[str, bool],
    selected_candidate_id: str,
    selection_mode: str,
    selection_reason: str,
) -> tuple[ReferenceCalibrationStudySnapshot, CalibrationStageAssessment]:
    """Record one verified stage selection and advance the immutable study."""

    root = Path(study_directory).expanduser().resolve()
    snapshot = load_reference_calibration_study(root)
    if snapshot.status != "awaiting_review" or snapshot.current_stage is None:
        raise ReferenceCalibrationStudyError(
            "The current calibration stage is not awaiting review"
        )
    candidate_ids = {
        candidate.candidate_id for candidate in snapshot.candidates
    }
    unexpected_review_ids = set(visual_approvals) - candidate_ids
    if unexpected_review_ids:
        raise ReferenceCalibrationStudyError(
            "Optional visual-QC decisions contain unknown candidates: "
            + ", ".join(sorted(unexpected_review_ids))
        )
    if any(not isinstance(value, bool) for value in visual_approvals.values()):
        raise ReferenceCalibrationStudyError(
            "Optional visual-QC decisions must be true or false when recorded"
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
            "visual_review_policy": "optional",
            "visual_review_status": {
                candidate.candidate_id: (
                    "passed"
                    if visual_approvals.get(candidate.candidate_id) is True
                    else (
                        "failed"
                        if visual_approvals.get(candidate.candidate_id) is False
                        else "not_performed"
                    )
                )
                for candidate in snapshot.candidates
            },
            "assessment": assessment.as_manifest(),
            "selection_mode": selection_mode,
            "selection_reason": selection_reason,
            "researcher_decision": selection_mode == "researcher_manual",
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
        events = _load_events(root)
        decision_event_hash = str(events[-1]["event_hash"])
        selection_modes = {
            str(event["stage_id"]): str(
                event.get("selection_mode", "researcher_manual")
            )
            for event in events
            if event["event"] == "stage_selected"
        }
        final_path = _final_configuration(
            root,
            manifest,
            selected_values,
            selected_candidates,
            selection_modes,
            decision_event_hash,
        )
        report_json, report_html = _write_calibration_report(
            root,
            manifest,
            snapshot.plan,
            events,
            selected_values,
            selected_candidates,
            final_path,
        )
        _append_event(
            root,
            "study_completed",
            {
                "selected_candidate_ids": selected_candidates,
                "selected_values": selected_values,
                "final_config": _relative_path(root, final_path),
                "final_config_sha256": sha256_file(final_path),
                "report_json": _relative_path(root, report_json),
                "report_json_sha256": sha256_file(report_json),
                "report_html": _relative_path(root, report_html),
                "report_html_sha256": sha256_file(report_html),
                "full_cohort_confirmation_required": True,
            },
        )
    return load_reference_calibration_study(root), assessment


def record_reference_calibration_stage_review(
    study_directory: Path | str,
    *,
    visual_approvals: Mapping[str, bool],
    selected_candidate_id: str,
) -> tuple[ReferenceCalibrationStudySnapshot, CalibrationStageAssessment]:
    """Record optional visual QC and advance one researcher-selected stage."""

    return _record_reference_calibration_stage_selection(
        study_directory,
        visual_approvals=visual_approvals,
        selected_candidate_id=selected_candidate_id,
        selection_mode="researcher_manual",
        selection_reason=(
            "The researcher explicitly selected this candidate after reviewing the "
            "available automatic evidence and optional visual QC."
        ),
    )


def select_reference_calibration_stage_automatically(
    study_directory: Path | str,
) -> tuple[ReferenceCalibrationStudySnapshot, CalibrationStageAssessment]:
    """Advance one stage using the transparent provisional balanced recommendation."""

    root = Path(study_directory).expanduser().resolve()
    snapshot = load_reference_calibration_study(root)
    if snapshot.status != "awaiting_review" or snapshot.current_stage is None:
        raise ReferenceCalibrationStudyError(
            "The current calibration stage is not ready for automatic selection"
        )
    if any(candidate.status != "completed" for candidate in snapshot.candidates):
        raise ReferenceCalibrationStudyError(
            "Automatic selection requires every declared candidate to complete"
        )
    assessment = assess_calibration_stage(
        snapshot.plan,
        stage_id=snapshot.current_stage.stage_id,
        evidence=_stage_evidence(snapshot, {}),
    )
    selected_candidate_id = assessment.balanced_candidate_id
    if selected_candidate_id is None:
        reasons = []
        for candidate in assessment.candidates:
            reasons.extend(candidate.rejection_reasons)
        raise ReferenceCalibrationStudyError(
            "Automatic pilot calibration found no eligible candidate in stage "
            f"{snapshot.current_stage.stage_id!r}: "
            + "; ".join(dict.fromkeys(reasons))
        )
    return _record_reference_calibration_stage_selection(
        root,
        visual_approvals={},
        selected_candidate_id=selected_candidate_id,
        selection_mode="automatic_provisional_balanced_score",
        selection_reason=_selection_reason(assessment, selected_candidate_id),
    )
