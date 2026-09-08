"""Resumable execution and reporting for DiffeoForge Validation Lab."""

from __future__ import annotations

import copy
import hashlib
import html
import json
import os
import shutil
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

import yaml

from diffeoforge.atomic_io import write_text_safely
from diffeoforge.config import load_config, validate_input_paths, validate_schema
from diffeoforge.desktop.reference_execution_controller import (
    ReferenceExecutionController,
    ReferenceExecutionControllerResult,
)
from diffeoforge.desktop.reference_prelaunch import DesktopReferenceLaunchRequest
from diffeoforge.desktop.reference_worker_protocol import DesktopReferenceWorkerEvent
from diffeoforge.mesh import sha256_file
from diffeoforge.reference_calibration_study import (
    STUDY_EVENTS as CALIBRATION_EVENTS,
)
from diffeoforge.reference_calibration_study import (
    STUDY_MANIFEST as CALIBRATION_MANIFEST,
)
from diffeoforge.reference_calibration_study import (
    assess_reference_calibration_snapshot,
    load_reference_calibration_study,
)
from diffeoforge.reference_runtime import launcher_identity
from diffeoforge.reference_validation import (
    ReferenceValidationAssessment,
    ReferenceValidationError,
    ReferenceValidationPlan,
    ValidationFinalist,
    ValidationRunEvidence,
    assess_reference_validation,
    build_reference_validation_plan,
    extend_reference_validation_plan,
    reference_validation_plan_from_manifest,
)
from diffeoforge.reference_validation_metrics import (
    collect_reference_validation_run_evidence,
)

VALIDATION_STUDY_VERSION = "0.1"
VALIDATION_EVENT_VERSION = "0.1"
VALIDATION_MANIFEST = "validation-study.json"
VALIDATION_DIGEST = "validation-study.sha256"
VALIDATION_EVENTS = "events.jsonl"
VALIDATION_REPORT_JSON = "report/validation-report.json"
VALIDATION_REPORT_HTML = "report/validation-report.html"
ValidationEventCallback = Callable[[Mapping[str, object]], None]
_INHERITED_RUN_CORE_ARTIFACTS = (
    "manifest.json",
    "result.json",
    "output-inventory.json",
)


class ReferenceValidationStudyError(ReferenceValidationError):
    """Raised when a Validation Lab study is invalid or cannot progress."""


class _Controller(Protocol):
    def run(
        self,
        *,
        event_callback: Callable[[DesktopReferenceWorkerEvent], None] | None = None,
    ) -> ReferenceExecutionControllerResult: ...

    def request_cancel(self) -> bool: ...


ControllerFactory = Callable[[DesktopReferenceLaunchRequest], _Controller]


@contextmanager
def validation_study_writer_lock(root: Path) -> Iterator[None]:
    """Exclude current-version runners/adopters; stale locks fail closed."""
    path = root / ".validation-writer.lock"
    token = f"{os.getpid()} {uuid4().hex}\n"
    try:
        handle = path.open("x", encoding="utf-8")
    except FileExistsError as error:
        raise ReferenceValidationStudyError(
            "Another validation writer owns this study. Never remove its lock while active; "
            "a crash-left lock requires an explicit idle-process check."
        ) from error
    try:
        with handle:
            handle.write(token)
            handle.flush()
            os.fsync(handle.fileno())
        yield
    finally:
        if path.is_file() and path.read_text(encoding="utf-8") == token:
            path.unlink()


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
    return hashlib.sha256(_canonical_json(value).encode()).hexdigest()


def _write_json(path: Path, value: object, *, overwrite: bool) -> None:
    write_text_safely(path, _canonical_json(value, indent=2), overwrite=overwrite)


def _write_yaml(path: Path, value: Mapping[str, Any], *, overwrite: bool) -> None:
    write_text_safely(
        path,
        yaml.safe_dump(dict(value), sort_keys=False, allow_unicode=True),
        overwrite=overwrite,
    )


def _relative(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as error:
        raise ReferenceValidationStudyError(
            f"Validation path escapes its study directory: {path}"
        ) from error


def _safe_path(root: Path, value: object) -> Path:
    relative = Path(str(value))
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise ReferenceValidationStudyError(f"Unsafe validation-study path: {relative}")
    path = root.joinpath(*relative.parts).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ReferenceValidationStudyError(
            f"Validation-study path escapes its root: {relative}"
        )
    return path


def _copy_bound(source: Path, destination: Path, expected_sha256: str) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise ReferenceValidationStudyError(
            f"Validation input destination already exists: {destination}"
        )
    shutil.copy2(source, destination)
    if sha256_file(destination) != expected_sha256:
        destination.unlink(missing_ok=True)
        raise ReferenceValidationStudyError(
            f"Validation input copy did not preserve bytes: {source}"
        )


def _link_or_copy_bound(source: Path, destination: Path, expected_sha256: str) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)
    if sha256_file(destination) != expected_sha256:
        destination.unlink(missing_ok=True)
        raise ReferenceValidationStudyError(
            f"Validation cohort copy did not preserve bytes: {source}"
        )


def _load_events(root: Path) -> tuple[dict[str, Any], ...]:
    path = root / VALIDATION_EVENTS
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise ReferenceValidationStudyError(
            f"Could not read validation event ledger: {error}"
        ) from error
    previous_hash: str | None = None
    events: list[dict[str, Any]] = []
    for index, line in enumerate(lines):
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            raise ReferenceValidationStudyError(
                f"Invalid validation event JSON at line {index + 1}"
            ) from error
        recorded_hash = record.pop("event_hash", None)
        if record.get("sequence") != index or record.get("previous_hash") != previous_hash:
            raise ReferenceValidationStudyError(
                f"Validation event chain is broken at line {index + 1}"
            )
        expected = _canonical_hash(record)
        record["event_hash"] = recorded_hash
        if recorded_hash != expected:
            raise ReferenceValidationStudyError(
                f"Validation event hash differs at line {index + 1}"
            )
        previous_hash = str(recorded_hash)
        events.append(record)
    if not events or events[0].get("event") != "study_created":
        raise ReferenceValidationStudyError(
            "Validation event ledger does not start with study_created"
        )
    return tuple(events)


def _append_event(root: Path, event: str, payload: Mapping[str, object]) -> dict[str, Any]:
    events = _load_events(root) if (root / VALIDATION_EVENTS).exists() else ()
    record: dict[str, Any] = {
        "event_version": VALIDATION_EVENT_VERSION,
        "sequence": len(events),
        "previous_hash": events[-1]["event_hash"] if events else None,
        "event": event,
        **dict(payload),
    }
    record["event_hash"] = _canonical_hash(record)
    try:
        with (root / VALIDATION_EVENTS).open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(_canonical_json(record) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as error:
        raise ReferenceValidationStudyError(
            f"Could not append validation event: {error}"
        ) from error
    return record


def _validation_configuration(
    source: Mapping[str, Any],
    *,
    root: Path,
    config_directory: Path,
    template_copy: Path,
    cohort_directory: Path,
    finalist_values: Mapping[str, float],
    run_id: str,
    maximum_iterations: int,
    template_diagonal: float,
) -> dict[str, Any]:
    config = copy.deepcopy(dict(source))
    config["project"]["name"] = f"{source['project']['name']} validation {run_id}"
    config["input"]["directory"] = os.path.relpath(
        cohort_directory, config_directory
    ).replace("\\", "/")
    config["input"]["template"] = os.path.relpath(
        template_copy, config_directory
    ).replace("\\", "/")
    config["input"]["subject_pattern"] = "*.vtk"
    config["output"]["directory"] = "./runs"
    config["optimization"]["max_iterations"] = maximum_iterations
    targets = {
        "attachment_kernel_width": ("attachment", "kernel_width"),
        "deformation_kernel_width": ("deformation", "kernel_width"),
        "initial_control_point_spacing": (
            "deformation",
            "initial_control_point_spacing",
        ),
    }
    for name, raw_value in finalist_values.items():
        value = float(raw_value)
        if name == "noise_std":
            config["model"]["noise_std"] = value
        elif name == "timepoints":
            config["model"]["deformation"]["timepoints"] = int(value)
        else:
            group, key = targets[name]
            config["model"][group][key] = value
        if name != "timepoints":
            config["project"]["parameter_provenance"]["ratios"][name] = (
                value / template_diagonal
            )
            config["project"]["parameter_provenance"]["sources"][name] = (
                "absolute_override"
            )
    validate_schema(config)
    return config


@dataclass(frozen=True)
class ValidationStudyRunState:
    run_id: str
    finalist_id: str
    cohort_id: str
    status: str
    config_path: Path
    run_directory: Path | None
    attempts: int
    evidence: ValidationRunEvidence | None
    error: str | None


@dataclass(frozen=True)
class ReferenceValidationStudySnapshot:
    study_directory: Path
    study_id: str
    plan: ReferenceValidationPlan
    status: str
    runs: tuple[ValidationStudyRunState, ...]
    event_count: int
    assessment: ReferenceValidationAssessment | None
    report_json_path: Path | None
    report_html_path: Path | None

    @property
    def completed_run_count(self) -> int:
        return sum(run.status == "completed" for run in self.runs)


def create_reference_validation_study(
    config_path: Path | str,
    study_directory: Path | str,
    *,
    holdout_fraction: float = 0.20,
    resample_count: int = 5,
    resample_fraction: float = 0.80,
    maximum_iterations: int | None = None,
) -> ReferenceValidationStudySnapshot:
    """Freeze the complete Validation Lab design without starting a process."""

    source_path = Path(config_path).expanduser().resolve()
    source_config = load_config(source_path)
    inputs = validate_input_paths(source_config, source_path)
    plan = build_reference_validation_plan(
        source_path,
        holdout_fraction=holdout_fraction,
        resample_count=resample_count,
        resample_fraction=resample_fraction,
    )
    iterations = (
        int(source_config["optimization"]["max_iterations"])
        if maximum_iterations is None
        else maximum_iterations
    )
    if isinstance(iterations, bool) or not isinstance(iterations, int) or iterations < 1:
        raise ReferenceValidationStudyError("maximum_iterations must be positive")
    root = Path(study_directory).expanduser().resolve()
    if root.exists():
        raise ReferenceValidationStudyError(
            f"Validation study destination already exists: {root}"
        )
    root.mkdir(parents=True)
    try:
        source_copy = root / "source" / "atlas-calibrated.yaml"
        _copy_bound(source_path, source_copy, plan.source_config_sha256)
        template_copy = root / "inputs" / "template" / inputs.template.name
        _copy_bound(inputs.template, template_copy, plan.template_sha256)
        source_subjects = {path.name: path for path in inputs.subjects}
        subject_records: list[dict[str, object]] = []
        master_directory = root / "inputs" / "subjects"
        for subject in plan.subjects:
            source_subject = source_subjects.get(subject.filename)
            if source_subject is None or sha256_file(source_subject) != subject.sha256:
                raise ReferenceValidationStudyError(
                    f"Validation subject changed after planning: {subject.filename}"
                )
            destination = master_directory / subject.filename
            _copy_bound(source_subject, destination, subject.sha256)
            subject_records.append(
                {
                    "filename": subject.filename,
                    "copy": _relative(root, destination),
                    "sha256": subject.sha256,
                    "role": subject.role,
                }
            )

        cohort_directories: dict[str, Path] = {}
        for cohort in plan.cohorts:
            cohort_directory = root / "cohorts" / cohort.cohort_id
            cohort_directories[cohort.cohort_id] = cohort_directory
            for name in cohort.subject_filenames:
                record = next(item for item in subject_records if item["filename"] == name)
                _link_or_copy_bound(
                    _safe_path(root, record["copy"]),
                    cohort_directory / name,
                    str(record["sha256"]),
                )

        finalist_by_id = {item.finalist_id: item for item in plan.finalists}
        run_records: list[dict[str, object]] = []
        for spec in plan.run_specs:
            config_directory = root / "run-specs" / spec.run_id
            config_directory.mkdir(parents=True)
            config = _validation_configuration(
                source_config,
                root=root,
                config_directory=config_directory,
                template_copy=template_copy,
                cohort_directory=cohort_directories[spec.cohort_id],
                finalist_values=finalist_by_id[spec.finalist_id].values,
                run_id=spec.run_id,
                maximum_iterations=iterations,
                template_diagonal=plan.template_diagonal,
            )
            candidate_config = config_directory / "atlas.yaml"
            _write_yaml(candidate_config, config, overwrite=False)
            run_records.append(
                {
                    **spec.as_manifest(),
                    "config": _relative(root, candidate_config),
                    "config_sha256": sha256_file(candidate_config),
                }
            )
        manifest = {
            "study_version": VALIDATION_STUDY_VERSION,
            "study_id": f"reference-validation-{uuid4().hex[:12]}",
            "plan_fingerprint": plan.fingerprint,
            "plan": plan.as_manifest(),
            "maximum_iterations": iterations,
            "launcher": launcher_identity(source_config["runtime"]["launcher"]),
            "source_config": {
                "original_path": str(source_path),
                "copy": _relative(root, source_copy),
                "sha256": sha256_file(source_copy),
            },
            "inputs": {
                "template": {
                    "copy": _relative(root, template_copy),
                    "sha256": sha256_file(template_copy),
                },
                "subjects": subject_records,
            },
            "runs": run_records,
            "scientific_boundary": (
                "A robust result means stable preference within the frozen finalist "
                "search space. It is not a universal optimum and does not replace "
                "heldout registration or anatomy-specific validation."
            ),
        }
        _write_json(root / VALIDATION_MANIFEST, manifest, overwrite=False)
        write_text_safely(
            root / VALIDATION_DIGEST,
            sha256_file(root / VALIDATION_MANIFEST) + "\n",
            overwrite=False,
        )
        _append_event(
            root,
            "study_created",
            {
                "study_id": manifest["study_id"],
                "plan_fingerprint": plan.fingerprint,
                "manifest_sha256": sha256_file(root / VALIDATION_MANIFEST),
                "run_count": len(plan.run_specs),
            },
        )
    except BaseException:
        if root.is_dir():
            shutil.rmtree(root)
        raise
    return load_reference_validation_study(root)


def _run_core_artifact_hashes(run_directory: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for relative in _INHERITED_RUN_CORE_ARTIFACTS:
        path = run_directory / relative
        if not path.is_file():
            raise ReferenceValidationStudyError(
                f"Inherited validation run lacks {relative}: {run_directory}"
            )
        hashes[relative] = sha256_file(path)
    return hashes


def _refinement_finalist(
    parent: ReferenceValidationStudySnapshot,
    refinement_study_directory: Path | str,
) -> tuple[ValidationFinalist, dict[str, object]]:
    refinement = load_reference_calibration_study(refinement_study_directory)
    assessment = assess_reference_calibration_snapshot(refinement)
    if (
        not assessment.automatic_selection_allowed
        or assessment.search_range_status != "bounded"
        or assessment.balanced_candidate_id is None
    ):
        raise ReferenceValidationStudyError(
            "Width refinement must have an automatic, bounded pilot preference"
        )
    assert refinement.current_stage is not None
    candidate = next(
        (
            item
            for item in refinement.current_stage.candidates
            if item.candidate_id == assessment.balanced_candidate_id
        ),
        None,
    )
    if candidate is None:
        raise ReferenceValidationStudyError(
            "Preferred width-refinement candidate is absent from its frozen stage"
        )
    if parent.assessment is None or parent.assessment.recommended_finalist_id is None:
        raise ReferenceValidationStudyError(
            "Parent Validation Lab has no preferred finalist to refine"
        )
    base = next(
        (
            item
            for item in parent.plan.finalists
            if item.finalist_id == parent.assessment.recommended_finalist_id
        ),
        None,
    )
    if base is None or not set(candidate.values).issubset(base.values):
        raise ReferenceValidationStudyError(
            "Width refinement parameters do not match the parent finalist schema"
        )
    values = base.values
    values.update({name: float(value) for name, value in candidate.values.items()})
    finalist = ValidationFinalist(
        finalist_id="width-refined",
        label="Axis-refined width finalist",
        parameter_values=tuple(sorted(values.items())),
        relationship_to_pilot=(
            f"Pilot candidate {candidate.candidate_id} from a bounded, axis-separated "
            f"width refinement of parent finalist {base.finalist_id}."
        ),
    )
    refinement_root = refinement.study_directory
    source = {
        "study_directory": str(refinement_root),
        "study_id": refinement.study_id,
        "plan_fingerprint": refinement.plan.fingerprint,
        "assessment_fingerprint": assessment.fingerprint,
        "balanced_candidate_id": candidate.candidate_id,
        "candidate_values": dict(sorted(candidate.values.items())),
        "manifest_sha256": sha256_file(refinement_root / CALIBRATION_MANIFEST),
        "events_sha256": sha256_file(refinement_root / CALIBRATION_EVENTS),
    }
    return finalist, source


def create_reference_validation_width_refinement_extension_study(
    parent_study_directory: Path | str,
    refinement_study_directory: Path | str,
    study_directory: Path | str,
    *,
    maximum_iterations: int | None = None,
) -> ReferenceValidationStudySnapshot:
    """Reuse a completed Validation Lab and add only one pilot-refined finalist."""

    parent = load_reference_validation_study(parent_study_directory)
    if parent.status != "completed" or parent.assessment is None:
        raise ReferenceValidationStudyError(
            "Width-refinement validation requires a completed parent Validation Lab"
        )
    parent_root = parent.study_directory
    parent_manifest = _verify_manifest(parent_root)
    parent_events = _load_events(parent_root)
    finalist, refinement_source = _refinement_finalist(
        parent, refinement_study_directory
    )
    plan = extend_reference_validation_plan(parent.plan, finalist)
    iterations = (
        int(parent_manifest["maximum_iterations"])
        if maximum_iterations is None
        else maximum_iterations
    )
    if isinstance(iterations, bool) or not isinstance(iterations, int) or iterations < 1:
        raise ReferenceValidationStudyError("maximum_iterations must be positive")
    root = Path(study_directory).expanduser().resolve()
    if root.exists():
        raise ReferenceValidationStudyError(
            f"Validation study destination already exists: {root}"
        )
    root.mkdir(parents=True)
    try:
        source_record = parent_manifest["source_config"]
        source_path = _safe_path(parent_root, source_record["copy"])
        source_copy = root / "source" / "atlas-calibrated.yaml"
        _copy_bound(source_path, source_copy, str(source_record["sha256"]))
        source_config = load_config(source_copy)

        template_record = parent_manifest["inputs"]["template"]
        template_path = _safe_path(parent_root, template_record["copy"])
        template_copy = root / "inputs" / "template" / template_path.name
        _copy_bound(template_path, template_copy, str(template_record["sha256"]))

        subject_records: list[dict[str, object]] = []
        for record in parent_manifest["inputs"]["subjects"]:
            source_subject = _safe_path(parent_root, record["copy"])
            destination = root / "inputs" / "subjects" / str(record["filename"])
            _copy_bound(source_subject, destination, str(record["sha256"]))
            subject_records.append(
                {
                    "filename": record["filename"],
                    "copy": _relative(root, destination),
                    "sha256": record["sha256"],
                    "role": record["role"],
                }
            )

        subject_by_name = {
            str(record["filename"]): record for record in subject_records
        }
        cohort_directories: dict[str, Path] = {}
        for cohort in plan.cohorts:
            cohort_directory = root / "cohorts" / cohort.cohort_id
            cohort_directories[cohort.cohort_id] = cohort_directory
            for name in cohort.subject_filenames:
                record = subject_by_name[name]
                _link_or_copy_bound(
                    _safe_path(root, record["copy"]),
                    cohort_directory / name,
                    str(record["sha256"]),
                )

        parent_run_records = {
            str(record["run_id"]): record for record in parent_manifest["runs"]
        }
        parent_run_states = {run.run_id: run for run in parent.runs}
        parent_completion_events = {
            str(event["run_id"]): event
            for event in parent_events
            if event["event"] == "run_completed"
        }
        finalist_by_id = {item.finalist_id: item for item in plan.finalists}
        run_records: list[dict[str, object]] = []
        inherited_runs: list[dict[str, object]] = []
        for spec in plan.run_specs:
            config_directory = root / "run-specs" / spec.run_id
            config_directory.mkdir(parents=True)
            candidate_config = config_directory / "atlas.yaml"
            if spec.run_id in parent_run_records:
                parent_record = parent_run_records[spec.run_id]
                _copy_bound(
                    _safe_path(parent_root, parent_record["config"]),
                    candidate_config,
                    str(parent_record["config_sha256"]),
                )
                state = parent_run_states[spec.run_id]
                completion = parent_completion_events[spec.run_id]
                if state.run_directory is None or state.evidence is None:
                    raise ReferenceValidationStudyError(
                        f"Parent validation run is not reusable: {spec.run_id}"
                    )
                inherited_runs.append(
                    {
                        "run_id": spec.run_id,
                        "source_run_directory": str(state.run_directory),
                        "source_event_hash": completion["event_hash"],
                        "core_artifact_sha256": _run_core_artifact_hashes(
                            state.run_directory
                        ),
                        "evidence": state.evidence.as_manifest(),
                    }
                )
            else:
                config = _validation_configuration(
                    source_config,
                    root=root,
                    config_directory=config_directory,
                    template_copy=template_copy,
                    cohort_directory=cohort_directories[spec.cohort_id],
                    finalist_values=finalist_by_id[spec.finalist_id].values,
                    run_id=spec.run_id,
                    maximum_iterations=iterations,
                    template_diagonal=plan.template_diagonal,
                )
                _write_yaml(candidate_config, config, overwrite=False)
            run_records.append(
                {
                    **spec.as_manifest(),
                    "config": _relative(root, candidate_config),
                    "config_sha256": sha256_file(candidate_config),
                }
            )

        manifest = {
            "study_version": VALIDATION_STUDY_VERSION,
            "study_id": f"reference-validation-extension-{uuid4().hex[:12]}",
            "plan_fingerprint": plan.fingerprint,
            "plan": plan.as_manifest(),
            "maximum_iterations": iterations,
            "launcher": parent_manifest["launcher"],
            "source_config": {
                "original_path": str(source_path),
                "copy": _relative(root, source_copy),
                "sha256": sha256_file(source_copy),
            },
            "inputs": {
                "template": {
                    "copy": _relative(root, template_copy),
                    "sha256": sha256_file(template_copy),
                },
                "subjects": subject_records,
            },
            "runs": run_records,
            "extension_source": {
                "study_directory": str(parent_root),
                "study_id": parent.study_id,
                "plan_fingerprint": parent.plan.fingerprint,
                "manifest_sha256": sha256_file(parent_root / VALIDATION_MANIFEST),
                "events_sha256": sha256_file(parent_root / VALIDATION_EVENTS),
            },
            "pilot_refinement_source": refinement_source,
            "inherited_runs": inherited_runs,
            "scientific_boundary": (
                "This successor compares one bounded pilot-derived width finalist "
                "against the unchanged parent finalists on the identical frozen "
                "training and resampling cohorts. Heldout confirmation remains separate."
            ),
        }
        _write_json(root / VALIDATION_MANIFEST, manifest, overwrite=False)
        write_text_safely(
            root / VALIDATION_DIGEST,
            sha256_file(root / VALIDATION_MANIFEST) + "\n",
            overwrite=False,
        )
        _append_event(
            root,
            "study_created",
            {
                "study_id": manifest["study_id"],
                "plan_fingerprint": plan.fingerprint,
                "manifest_sha256": sha256_file(root / VALIDATION_MANIFEST),
                "run_count": len(plan.run_specs),
                "inherited_run_count": len(inherited_runs),
            },
        )
        for inherited in inherited_runs:
            _append_event(
                root,
                "run_inherited",
                {
                    "run_id": inherited["run_id"],
                    "source_event_hash": inherited["source_event_hash"],
                },
            )
    except BaseException:
        shutil.rmtree(root, ignore_errors=True)
        raise
    return load_reference_validation_study(root)


def _verify_manifest(root: Path) -> dict[str, Any]:
    try:
        manifest = json.loads((root / VALIDATION_MANIFEST).read_text(encoding="utf-8"))
        expected = (root / VALIDATION_DIGEST).read_text(encoding="utf-8").strip()
    except (OSError, json.JSONDecodeError) as error:
        raise ReferenceValidationStudyError(
            f"Could not read validation study manifest: {error}"
        ) from error
    if sha256_file(root / VALIDATION_MANIFEST) != expected:
        raise ReferenceValidationStudyError("Validation study manifest SHA-256 differs")
    if manifest.get("study_version") != VALIDATION_STUDY_VERSION:
        raise ReferenceValidationStudyError(
            f"Unsupported validation study version: {manifest.get('study_version')}"
        )
    plan = reference_validation_plan_from_manifest(manifest["plan"])
    if manifest.get("plan_fingerprint") != plan.fingerprint:
        raise ReferenceValidationStudyError("Validation study plan binding differs")
    bound = [
        manifest["source_config"],
        manifest["inputs"]["template"],
        *manifest["inputs"]["subjects"],
        *manifest["runs"],
    ]
    for record in bound:
        key = "config" if "config" in record else "copy"
        path = _safe_path(root, record[key])
        digest_key = "config_sha256" if key == "config" else "sha256"
        if not path.is_file() or sha256_file(path) != record[digest_key]:
            raise ReferenceValidationStudyError(
                f"Validation study bound file changed or is absent: {path}"
            )
    subject_hashes = {
        str(record["filename"]): str(record["sha256"])
        for record in manifest["inputs"]["subjects"]
    }
    for cohort in plan.cohorts:
        for filename in cohort.subject_filenames:
            path = root / "cohorts" / cohort.cohort_id / filename
            if (
                filename not in subject_hashes
                or not path.is_file()
                or sha256_file(path) != subject_hashes[filename]
            ):
                raise ReferenceValidationStudyError(
                    f"Validation cohort input changed or is absent: {path}"
                )
    extension_source = manifest.get("extension_source")
    refinement_source = manifest.get("pilot_refinement_source")
    inherited = manifest.get("inherited_runs")
    extension_fields = (extension_source, refinement_source, inherited)
    if any(value is not None for value in extension_fields):
        if (
            not isinstance(extension_source, Mapping)
            or not isinstance(refinement_source, Mapping)
            or not isinstance(inherited, list)
        ):
            raise ReferenceValidationStudyError(
                "Validation extension provenance is incomplete"
            )
        parent_root = Path(
            str(extension_source.get("study_directory", ""))
        ).expanduser().resolve()
        if parent_root == root:
            raise ReferenceValidationStudyError(
                "Validation extension cannot inherit from itself"
            )
        parent = load_reference_validation_study(parent_root)
        expected_extension_source = {
            "study_directory": str(parent.study_directory),
            "study_id": parent.study_id,
            "plan_fingerprint": parent.plan.fingerprint,
            "manifest_sha256": sha256_file(parent_root / VALIDATION_MANIFEST),
            "events_sha256": sha256_file(parent_root / VALIDATION_EVENTS),
        }
        if dict(extension_source) != expected_extension_source:
            raise ReferenceValidationStudyError(
                "Parent Validation Lab provenance differs from the frozen extension"
            )
        expected_finalist, expected_refinement_source = _refinement_finalist(
            parent, str(refinement_source.get("study_directory", ""))
        )
        if dict(refinement_source) != expected_refinement_source:
            raise ReferenceValidationStudyError(
                "Width-refinement pilot provenance differs from the frozen extension"
            )
        if plan != extend_reference_validation_plan(parent.plan, expected_finalist):
            raise ReferenceValidationStudyError(
                "Validation extension plan differs from its verified parent and pilot"
            )
        parent_runs = {run.run_id: run for run in parent.runs}
        parent_events = {
            str(event["run_id"]): event
            for event in _load_events(parent_root)
            if event["event"] == "run_completed"
        }
        inherited_by_id = {
            str(record.get("run_id")): record
            for record in inherited
            if isinstance(record, Mapping)
        }
        if len(inherited_by_id) != len(inherited) or set(inherited_by_id) != set(
            parent_runs
        ):
            raise ReferenceValidationStudyError(
                "Inherited validation-run set differs from the completed parent"
            )
        for run_id, record in inherited_by_id.items():
            parent_state = parent_runs[run_id]
            parent_event = parent_events.get(run_id)
            if (
                parent_state.status != "completed"
                or parent_state.evidence is None
                or parent_state.run_directory is None
                or parent_event is None
                or record.get("source_event_hash") != parent_event["event_hash"]
                or record.get("evidence") != parent_state.evidence.as_manifest()
                or Path(str(record.get("source_run_directory", ""))).resolve()
                != parent_state.run_directory.resolve()
            ):
                raise ReferenceValidationStudyError(
                    f"Inherited validation evidence differs for {run_id}"
                )
            recorded_hashes = record.get("core_artifact_sha256")
            if (
                not isinstance(recorded_hashes, Mapping)
                or dict(recorded_hashes)
                != _run_core_artifact_hashes(parent_state.run_directory)
            ):
                raise ReferenceValidationStudyError(
                    f"Inherited validation run artifacts changed for {run_id}"
                )
    return manifest


def _evidence_from_manifest(value: Mapping[str, object]) -> ValidationRunEvidence:
    raw_subjects = value.get("subject_residual_p95", {})
    return ValidationRunEvidence(
        run_id=str(value["run_id"]),
        finalist_id=str(value["finalist_id"]),
        cohort_id=str(value["cohort_id"]),
        completed=bool(value["completed"]),
        converged=bool(value["converged"]),
        invalid_face_count=int(value["invalid_face_count"]),
        external_residual_p95=(
            None
            if value.get("external_residual_p95") is None
            else float(value["external_residual_p95"])
        ),
        distortion_p95=(
            None if value.get("distortion_p95") is None else float(value["distortion_p95"])
        ),
        runtime_seconds=(
            None
            if value.get("runtime_seconds") is None
            else float(value["runtime_seconds"])
        ),
        atlas_path=(None if value.get("atlas_path") is None else str(value["atlas_path"])),
        subject_residual_p95=tuple(
            sorted((str(name), float(metric)) for name, metric in raw_subjects.items())
        ),
    )


def load_reference_validation_study(
    study_directory: Path | str,
) -> ReferenceValidationStudySnapshot:
    root = Path(study_directory).expanduser().resolve()
    if not root.is_dir():
        raise ReferenceValidationStudyError(
            f"Validation study directory does not exist: {root}"
        )
    manifest = _verify_manifest(root)
    plan = reference_validation_plan_from_manifest(manifest["plan"])
    events = _load_events(root)
    if (
        events[0].get("study_id") != manifest["study_id"]
        or events[0].get("manifest_sha256")
        != sha256_file(root / VALIDATION_MANIFEST)
    ):
        raise ReferenceValidationStudyError(
            "Validation event ledger is bound to a different manifest"
        )
    inherited_by_id = {
        str(record["run_id"]): record
        for record in manifest.get("inherited_runs", [])
    }
    inherited_events = [event for event in events if event["event"] == "run_inherited"]
    if inherited_by_id:
        inherited_event_by_id = {
            str(event.get("run_id")): event for event in inherited_events
        }
        if (
            len(inherited_event_by_id) != len(inherited_events)
            or set(inherited_event_by_id) != set(inherited_by_id)
            or any(
                inherited_event_by_id[run_id].get("source_event_hash")
                != record["source_event_hash"]
                for run_id, record in inherited_by_id.items()
            )
        ):
            raise ReferenceValidationStudyError(
                "Inherited validation event ledger differs from its manifest"
            )
    run_states: list[ValidationStudyRunState] = []
    for record in manifest["runs"]:
        run_id = str(record["run_id"])
        starts = [
            event
            for event in events
            if event["event"] == "run_started" and event["run_id"] == run_id
        ]
        terminals = [
            event
            for event in events
            if event["event"] in {"run_completed", "run_failed", "run_interrupted"}
            and event["run_id"] == run_id
        ]
        completed = [event for event in terminals if event["event"] == "run_completed"]
        latest_terminal = terminals[-1] if terminals else None
        orphaned = bool(
            starts
            and (
                not terminals
                or starts[-1]["sequence"] > terminals[-1]["sequence"]
            )
        )
        inherited_record = inherited_by_id.get(run_id)
        if inherited_record is not None:
            if starts or terminals:
                raise ReferenceValidationStudyError(
                    f"Inherited validation run has local execution events: {run_id}"
                )
            status = "completed"
            evidence = _evidence_from_manifest(inherited_record["evidence"])
            error = None
            run_directory = Path(
                str(inherited_record["source_run_directory"])
            ).resolve()
        elif completed:
            status = "completed"
            evidence = _evidence_from_manifest(completed[-1]["evidence"])
            error = None
            run_directory = _safe_path(root, completed[-1]["run_directory"])
        elif orphaned:
            status = "orphaned"
            evidence = None
            error = "Previous process ended before recording a terminal event"
            run_directory = _safe_path(root, starts[-1]["run_directory"])
        elif latest_terminal is not None:
            status = "failed"
            evidence = None
            error = str(latest_terminal.get("error", "Validation run failed"))
            relative_run = latest_terminal.get("run_directory")
            run_directory = _safe_path(root, relative_run) if relative_run else None
        else:
            status = "pending"
            evidence = None
            error = None
            run_directory = None
        run_states.append(
            ValidationStudyRunState(
                run_id=run_id,
                finalist_id=str(record["finalist_id"]),
                cohort_id=str(record["cohort_id"]),
                status=status,
                config_path=_safe_path(root, record["config"]),
                run_directory=run_directory,
                attempts=len(starts),
                evidence=evidence,
                error=error,
            )
        )
    completion = next(
        (event for event in reversed(events) if event["event"] == "study_completed"),
        None,
    )
    assessment = None
    report_json = None
    report_html = None
    if completion is not None:
        report_json = _safe_path(root, completion["report_json"])
        report_html = _safe_path(root, completion["report_html"])
        if (
            sha256_file(report_json) != completion["report_json_sha256"]
            or sha256_file(report_html) != completion["report_html_sha256"]
        ):
            raise ReferenceValidationStudyError("Validation report bytes changed")
        assessment = assess_reference_validation(
            plan,
            tuple(
                run.evidence for run in run_states if run.evidence is not None
            ),
        )
        status = "completed"
    elif any(run.status == "orphaned" for run in run_states):
        status = "interrupted"
    elif all(run.status == "completed" for run in run_states):
        status = "awaiting_report"
    elif any(run.status == "failed" for run in run_states):
        status = "ready_to_retry"
    else:
        status = "ready"
    return ReferenceValidationStudySnapshot(
        study_directory=root,
        study_id=str(manifest["study_id"]),
        plan=plan,
        status=status,
        runs=tuple(run_states),
        event_count=len(events),
        assessment=assessment,
        report_json_path=report_json,
        report_html_path=report_html,
    )
def _report_payload(
    snapshot: ReferenceValidationStudySnapshot,
    assessment: ReferenceValidationAssessment,
) -> dict[str, object]:
    finalists = {item.finalist_id: item for item in snapshot.plan.finalists}
    return {
        "report_version": "0.1",
        "study_id": snapshot.study_id,
        "plan_fingerprint": snapshot.plan.fingerprint,
        "status": assessment.status,
        "claim_scope": (
            "Robustness within the predeclared finalist search space; not a universal "
            "or automatically biologically optimal parameter claim."
        ),
        "recommended_finalist": (
            None
            if assessment.recommended_finalist_id is None
            else finalists[assessment.recommended_finalist_id].as_manifest()
        ),
        "assessment": assessment.as_manifest(),
        "design": {
            "subject_count": snapshot.plan.subject_count,
            "training_subject_count": len(snapshot.plan.training_subjects),
            "reserved_holdout_subject_count": len(snapshot.plan.heldout_subjects),
            "resample_count": snapshot.plan.resample_count,
            "run_count": len(snapshot.plan.run_specs),
            "external_metric": (
                "Symmetric deterministic vertex-to-triangle surface-distance p95"
            ),
            "selection_rule": list(snapshot.plan.selection_rule),
        },
        "finalists": [item.as_manifest() for item in assessment.finalists],
        "warnings": list(assessment.warnings),
        "required_next_gates": list(assessment.next_gates),
        "limitations": list(snapshot.plan.limitations),
    }


def _report_html(report: Mapping[str, object]) -> str:
    assessment = report["assessment"]
    recommended = report["recommended_finalist"]
    winner = "No unique robust finalist"
    if recommended is not None:
        winner = f"{recommended['label']} ({recommended['finalist_id']})"
    finalist_rows = "".join(
        "<tr>"
        f"<td>{html.escape(str(item['finalist_id']))}</td>"
        f"<td>{float(item['group_win_fraction']):.1%}</td>"
        f"<td>{html.escape(str(item['median_external_residual_p95']))}</td>"
        f"<td>{html.escape(str(item['median_distortion_p95']))}</td>"
        f"<td>{html.escape('; '.join(item['rejection_reasons']) or 'none')}</td>"
        "</tr>"
        for item in report["finalists"]
    )
    next_steps = "".join(
        f"<li>{html.escape(str(item))}</li>" for item in report["required_next_gates"]
    )
    limitations = "".join(
        f"<li>{html.escape(str(item))}</li>" for item in report["limitations"]
    )
    warnings = "".join(
        f"<li>{html.escape(str(item))}</li>" for item in report["warnings"]
    ) or "<li>No additional numerical warning was triggered.</li>"
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>DiffeoForge Validation Lab report</title><style>
body{{font-family:Segoe UI,Arial,sans-serif;max-width:1100px;margin:36px auto;
padding:0 24px;color:#103b3b;line-height:1.45}}h1,h2{{color:#073c3b}}
.notice{{background:#e3f6ef;border-left:5px solid #13856f;padding:14px 18px}}
table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #c8d9d7;
padding:10px;text-align:left;vertical-align:top}}th{{background:#eef5f4}}
code{{background:#eef5f4;padding:2px 5px}}</style></head><body>
<h1>DiffeoForge Validation Lab report</h1>
<p class="notice"><strong>Evidence status:</strong>
{html.escape(str(assessment['confidence']))}.<br><strong>Preferred finalist:</strong>
{html.escape(winner)}</p>
<p><strong>Claim boundary:</strong> {html.escape(str(report['claim_scope']))}</p>
<h2>Frozen design</h2><p>{report['design']['training_subject_count']} training subjects;
{report['design']['reserved_holdout_subject_count']} untouched heldout subjects;
{report['design']['resample_count']} resamples; {report['design']['run_count']} atlas runs.</p>
<p>Practical error margin: {assessment['practical_error_margin']}
({html.escape(str(assessment['practical_error_margin_basis']))}).</p>
<h2>Finalist comparison</h2><table><thead><tr><th>Finalist</th><th>Cohort wins</th>
<th>Median external p95</th><th>Median distortion p95</th><th>Rejections</th></tr></thead>
<tbody>{finalist_rows}</tbody></table>
<h2>Warnings</h2><ul>{warnings}</ul><h2>Evidence still required</h2><ol>{next_steps}</ol>
<h2>Limitations</h2><ul>{limitations}</ul>
<p>Study: <code>{html.escape(str(report['study_id']))}</code><br>Plan:
<code>{html.escape(str(report['plan_fingerprint']))}</code></p></body></html>"""


def _finalize_study(root: Path) -> ReferenceValidationStudySnapshot:
    snapshot = load_reference_validation_study(root)
    if snapshot.status == "completed":
        return snapshot
    if any(run.evidence is None for run in snapshot.runs):
        raise ReferenceValidationStudyError(
            "Validation report requires every predeclared run to complete"
        )
    assessment = assess_reference_validation(
        snapshot.plan, tuple(run.evidence for run in snapshot.runs if run.evidence is not None)
    )
    report = _report_payload(snapshot, assessment)
    json_path = root / VALIDATION_REPORT_JSON
    html_path = root / VALIDATION_REPORT_HTML
    json_path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(json_path, report, overwrite=False)
    write_text_safely(html_path, _report_html(report), overwrite=False)
    _append_event(
        root,
        "study_completed",
        {
            "assessment_status": assessment.status,
            "recommended_finalist_id": assessment.recommended_finalist_id,
            "report_json": _relative(root, json_path),
            "report_json_sha256": sha256_file(json_path),
            "report_html": _relative(root, html_path),
            "report_html_sha256": sha256_file(html_path),
        },
    )
    return load_reference_validation_study(root)


def _launch_request(
    root: Path,
    manifest: Mapping[str, Any],
    state: ValidationStudyRunState,
) -> DesktopReferenceLaunchRequest:
    attempt = state.attempts + 1
    attempt_id = f"attempt-{attempt:02d}"
    destination = (state.config_path.parent / "runs" / attempt_id).resolve()
    launcher = manifest["launcher"]
    return DesktopReferenceLaunchRequest(
        request_id=f"validation-{uuid4().hex}",
        config_path=state.config_path,
        destination=destination,
        run_id=attempt_id,
        expected_config_sha256=sha256_file(state.config_path),
        launcher_engine=launcher.get("engine"),
        launcher_image=launcher.get("image"),
        launcher_type=str(launcher["type"]),
        launcher_distribution=launcher.get("distribution"),
        launcher_executable=launcher.get("executable"),
    )


class ReferenceValidationStudyRunner:
    """Execute every missing frozen run sequentially and resume safely."""

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

    def run_all(
        self,
        *,
        event_callback: ValidationEventCallback | None = None,
    ) -> ReferenceValidationStudySnapshot:
        with validation_study_writer_lock(self.study_directory):
            return self._run_all(event_callback=event_callback)

    def _run_all(
        self,
        *,
        event_callback: ValidationEventCallback | None = None,
    ) -> ReferenceValidationStudySnapshot:
        snapshot = load_reference_validation_study(self.study_directory)
        if snapshot.status == "completed":
            return snapshot
        manifest = _verify_manifest(self.study_directory)
        recovery_required: list[str] = []
        for state in snapshot.runs:
            if state.status == "completed" or self._cancel_requested:
                continue
            if state.status == "failed" and state.run_directory is not None:
                result_path = state.run_directory / "result.json"
                if result_path.is_file():
                    result = json.loads(result_path.read_text(encoding="utf-8"))
                    if result.get("status") == "completed" and result.get("return_code") == 0:
                        recovery_required.append(state.run_id)
                        if event_callback is not None:
                            event_callback({
                                "event": "evidence_recovery_required", "run_id": state.run_id,
                            })
                        continue
            request = _launch_request(self.study_directory, manifest, state)
            started = _append_event(
                self.study_directory,
                "run_started",
                {
                    "run_id": state.run_id,
                    "finalist_id": state.finalist_id,
                    "cohort_id": state.cohort_id,
                    "attempt": state.attempts + 1,
                    "request_id": request.request_id,
                    "run_directory": _relative(self.study_directory, request.destination),
                },
            )
            if event_callback is not None:
                event_callback(started)
            controller = self._controller_factory(request)
            self._active_controller = controller

            def forward(
                event: DesktopReferenceWorkerEvent,
                validation_run_id: str = state.run_id,
            ) -> None:
                if event_callback is not None:
                    event_callback(
                        {
                            "event": "worker_event",
                            "run_id": validation_run_id,
                            "worker_event": event.as_dict(),
                        }
                    )

            try:
                result = controller.run(event_callback=forward)
                if result.completed:
                    evidence = collect_reference_validation_run_evidence(
                        request.destination,
                        run_id=state.run_id,
                        finalist_id=state.finalist_id,
                        cohort_id=state.cohort_id,
                    )
                    terminal = _append_event(
                        self.study_directory,
                        "run_completed",
                        {
                            "run_id": state.run_id,
                            "finalist_id": state.finalist_id,
                            "cohort_id": state.cohort_id,
                            "attempt": state.attempts + 1,
                            "run_directory": _relative(
                                self.study_directory, request.destination
                            ),
                            "evidence": evidence.as_manifest(),
                        },
                    )
                else:
                    terminal = _append_event(
                        self.study_directory,
                        "run_interrupted",
                        {
                            "run_id": state.run_id,
                            "attempt": state.attempts + 1,
                            "run_directory": _relative(
                                self.study_directory, request.destination
                            ),
                            "error": "Validation execution was cancelled safely.",
                        },
                    )
                    self._cancel_requested = True
            except Exception as error:
                terminal = _append_event(
                    self.study_directory,
                    "run_failed",
                    {
                        "run_id": state.run_id,
                        "attempt": state.attempts + 1,
                        "run_directory": (
                            _relative(self.study_directory, request.destination)
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
        updated = load_reference_validation_study(self.study_directory)
        if recovery_required and not self._cancel_requested:
            raise ReferenceValidationStudyError(
                f"Backend already completed for {', '.join(recovery_required)}; recover evidence "
                "with reference-validation-evidence-export/adopt. These atlases were not "
                "restarted; any other pending runs were allowed to proceed."
            )
        if not self._cancel_requested and all(
            run.status == "completed" for run in updated.runs
        ):
            updated = _finalize_study(self.study_directory)
            if event_callback is not None:
                event_callback(
                    {
                        "event": "validation_completed",
                        "status": updated.assessment.status if updated.assessment else None,
                        "completed_run_count": updated.completed_run_count,
                    }
                )
        return updated
