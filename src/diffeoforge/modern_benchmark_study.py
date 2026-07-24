"""Resumable execution of frozen paired benchmark designs."""

from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import shutil
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path
from typing import Any

import jsonschema
import psutil

from diffeoforge.atomic_io import replace_atomically
from diffeoforge.mesh import sha256_file
from diffeoforge.modern_benchmark import (
    REPORT_CSV_NAME,
    REPORT_HTML_NAME,
    REPORT_JSON_NAME,
    ModernBenchmarkError,
    benchmark_modern_objective,
    verify_modern_benchmark_report,
)
from diffeoforge.modern_benchmark_design import (
    DESIGN_JSON_NAME,
    collect_modern_benchmark_design,
    verify_modern_benchmark_design,
)
from diffeoforge.modern_benchmark_progress import (
    StudyProgressCallback,
    StudyProgressCondition,
    StudyProgressEvent,
    StudyProgressObserverError,
    StudyProgressStatus,
)

STUDY_RUN_VERSION = "0.1"
STATE_NAME = "study-state.json"
EVENTS_NAME = "events.jsonl"
MANIFEST_NAME = "study-run.json"
MANIFEST_SIDECAR_NAME = "study-run.sha256"
DESIGN_DIRECTORY_NAME = "design"
SOURCE_CONFIG_NAME = "source-config.yaml"
CONDITIONS_DIRECTORY_NAME = "conditions"
LOCK_NAME = ".active.lock"
SCIENTIFIC_BOUNDARY = (
    "This run preserves separate raw objective/gradient benchmark reports in a frozen paired "
    "order. It performs no automatic comparison, winner selection, speedup or significance "
    "calculation, safe-preset selection, peak-memory inference, full-workflow measurement, "
    "scaling extrapolation, or 300-subject feasibility test."
)


class ModernBenchmarkStudyError(RuntimeError):
    """Raised when a frozen benchmark study cannot run or verify safely."""


def _manifest_schema() -> dict[str, Any]:
    resource = files("diffeoforge.schema").joinpath("modern-benchmark-study-run-v0.1.json")
    return json.loads(resource.read_text(encoding="utf-8"))


def _timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def _json_bytes(value: dict[str, Any]) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def _design_sha256(design: dict[str, Any]) -> str:
    return hashlib.sha256(_json_bytes(design).encode()).hexdigest()


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    _write_text_atomic(path, _json_bytes(value))


def _write_text_atomic(path: Path, value: str) -> None:
    temporary = path.with_name(f".{path.name}.tmp-{uuid.uuid4().hex}")
    try:
        temporary.write_text(value, encoding="utf-8", newline="\n")
        replace_atomically(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _append_event(root: Path, event: str, **details: Any) -> None:
    path = root / EVENTS_NAME
    sequence = len(_event_records(root)) + 1
    record = {"created_at": _timestamp(), "event": event, **details, "sequence": sequence}
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _event_records(root: Path) -> list[dict[str, Any]]:
    path = root / EVENTS_NAME
    if not path.exists():
        return []
    records = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ValueError("event is not an object")
                records.append(value)
    except (OSError, json.JSONDecodeError, ValueError) as error:
        raise ModernBenchmarkStudyError("Study event log is invalid") from error
    return records


def _verify_events(root: Path, design: dict[str, Any]) -> None:
    records = _event_records(root)
    if not records or records[0].get("event") != "study_created":
        raise ModernBenchmarkStudyError("Study event log does not start with creation")
    if records[-1].get("event") != "study_completed":
        raise ModernBenchmarkStudyError("Study event log does not end with completion")
    if [record.get("sequence") for record in records] != list(range(1, len(records) + 1)):
        raise ModernBenchmarkStudyError("Study event sequence is not contiguous")
    if any(
        not isinstance(record.get("created_at"), str)
        or not isinstance(record.get("event"), str)
        for record in records
    ):
        raise ModernBenchmarkStudyError("Study event records are malformed")
    completed = [
        record.get("condition_id")
        for record in records
        if record.get("event") == "condition_completed"
    ]
    expected = [condition["condition_id"] for condition in design["conditions"]]
    if completed != expected:
        raise ModernBenchmarkStudyError("Completed event order differs from the frozen design")


def _verify_partial_events(
    root: Path, design: dict[str, Any], existing_ids: list[str]
) -> None:
    records = _event_records(root)
    if not records or records[0].get("event") != "study_created":
        raise ModernBenchmarkStudyError("Study event log does not start with creation")
    if [record.get("sequence") for record in records] != list(range(1, len(records) + 1)):
        raise ModernBenchmarkStudyError("Study event sequence is not contiguous")
    completed = [
        record.get("condition_id")
        for record in records
        if record.get("event") == "condition_completed"
    ]
    if completed != existing_ids[: len(completed)]:
        raise ModernBenchmarkStudyError(
            "Completed events and condition reports differ from frozen order"
        )


def _initial_state(design: dict[str, Any]) -> dict[str, Any]:
    return {
        "study_run_version": STUDY_RUN_VERSION,
        "status": "initialized",
        "design_sha256": _design_sha256(design),
        "source_config_sha256": design["source_config"]["sha256"],
        "completed_condition_ids": [],
        "active_condition_id": None,
        "updated_at": _timestamp(),
    }


def _validate_state(state: dict[str, Any], design: dict[str, Any]) -> None:
    expected_keys = {
        "study_run_version",
        "status",
        "design_sha256",
        "source_config_sha256",
        "completed_condition_ids",
        "active_condition_id",
        "updated_at",
    }
    if not isinstance(state, dict) or set(state) != expected_keys:
        raise ModernBenchmarkStudyError("Study state has unexpected fields")
    if state["study_run_version"] != STUDY_RUN_VERSION:
        raise ModernBenchmarkStudyError("Study state version is unsupported")
    if state["status"] not in {"initialized", "running", "interrupted", "complete"}:
        raise ModernBenchmarkStudyError("Study state status is invalid")
    source_sha256 = design["source_config"]["sha256"]
    if (
        state["design_sha256"] != _design_sha256(design)
        or state["source_config_sha256"] != source_sha256
    ):
        raise ModernBenchmarkStudyError("Study state source identity differs from the design")
    condition_ids = [condition["condition_id"] for condition in design["conditions"]]
    completed = state["completed_condition_ids"]
    if not isinstance(completed, list) or completed != condition_ids[: len(completed)]:
        raise ModernBenchmarkStudyError("Completed study conditions are not a frozen-order prefix")
    active = state["active_condition_id"]
    if active is not None and active not in condition_ids:
        raise ModernBenchmarkStudyError("Active study condition is unknown")
    if not isinstance(state["updated_at"], str) or not state["updated_at"]:
        raise ModernBenchmarkStudyError("Study state timestamp is invalid")


def _read_state(root: Path, design: dict[str, Any]) -> dict[str, Any]:
    try:
        state = json.loads((root / STATE_NAME).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ModernBenchmarkStudyError("Study state is missing or invalid") from error
    _validate_state(state, design)
    return state


def _save_state(root: Path, state: dict[str, Any], design: dict[str, Any]) -> None:
    state["updated_at"] = _timestamp()
    _validate_state(state, design)
    _write_json_atomic(root / STATE_NAME, state)


def _fresh_design_for_config(design: dict[str, Any], config_path: Path) -> dict[str, Any]:
    protocol = design["protocol"]
    return collect_modern_benchmark_design(
        config_path,
        subject_counts=protocol["subject_counts"],
        repeats_per_condition=protocol["repeats_per_condition"],
        warmup_evaluations=protocol["warmup_evaluations_per_repeat"],
        order_seed=protocol["order_seed"],
        created_at=design["created_at"],
    )


def _verify_config_identity(design: dict[str, Any], config_path: Path) -> None:
    if _fresh_design_for_config(design, config_path) != design:
        raise ModernBenchmarkStudyError(
            "Current source configuration, software, or input inventory differs from the design"
        )


def _condition_directory(root: Path, condition: dict[str, Any]) -> Path:
    relative = Path(condition["output_directory"])
    if (
        relative.is_absolute()
        or relative.parts[0] != CONDITIONS_DIRECTORY_NAME
        or ".." in relative.parts
    ):
        raise ModernBenchmarkStudyError("Condition output path escapes the study run")
    return root.joinpath(*relative.parts)


def _verify_condition_report(
    root: Path,
    design: dict[str, Any],
    condition: dict[str, Any],
) -> dict[str, Any]:
    try:
        report = verify_modern_benchmark_report(_condition_directory(root, condition))
    except ModernBenchmarkError as error:
        raise ModernBenchmarkStudyError(
            f"Condition report {condition['condition_id']} is invalid: {error}"
        ) from error
    count = condition["subject_count"]
    if report["source_config"] != design["source_config"]:
        raise ModernBenchmarkStudyError("Condition source config differs from the frozen design")
    expected_input = {
        "template": design["input"]["template"],
        "subjects": design["input"]["subjects"][:count],
        "available_subject_count": design["input"]["available_subject_count"],
        "selected_subject_count": count,
        "selection": design["input"]["selection"],
    }
    if report["input"] != expected_input:
        raise ModernBenchmarkStudyError("Condition input inventory differs from the frozen design")
    config = report["configuration"]
    frozen = design["configuration"]
    expected_configuration = {
        "gradient_block": frozen["gradient_block"],
        "control_points": frozen["control_points"],
        "timepoints": frozen["timepoints"],
        "attachment_type": frozen["attachment_type"],
        "shooting_integrator": frozen["shooting_integrator"],
        "flow_integrator": frozen["flow_integrator"],
        "threads": frozen["threads"],
        "random_seed": frozen["random_seed"],
        "warmup_evaluations_per_repeat": design["protocol"][
            "warmup_evaluations_per_repeat"
        ],
        "repeats": design["protocol"]["repeats_per_condition"],
        "rss_sampling_interval_ms": config["rss_sampling_interval_ms"],
        "process_isolation": config["process_isolation"],
        "pairwise_evaluation": frozen["pairwise_evaluation"],
        "tile_autograd_strategy": condition["tile_autograd_strategy"],
    }
    if config != expected_configuration:
        raise ModernBenchmarkStudyError("Condition protocol differs from the frozen design")
    return report


def _existing_condition_ids(root: Path, design: dict[str, Any]) -> list[str]:
    conditions_root = root / CONDITIONS_DIRECTORY_NAME
    expected = {
        Path(condition["output_directory"]).name: condition["condition_id"]
        for condition in design["conditions"]
    }
    observed_names = {path.name for path in conditions_root.iterdir()}
    unknown = observed_names - set(expected)
    if unknown:
        raise ModernBenchmarkStudyError(
            f"Study conditions directory contains unexpected entries: {sorted(unknown)}"
        )
    existing = []
    missing_seen = False
    for condition in design["conditions"]:
        path = _condition_directory(root, condition)
        if path.exists():
            if missing_seen:
                raise ModernBenchmarkStudyError("Condition reports exist outside frozen order")
            _verify_condition_report(root, design, condition)
            existing.append(condition["condition_id"])
        else:
            missing_seen = True
    return existing


def _reconcile_completed_events(
    root: Path, design: dict[str, Any], existing_ids: list[str]
) -> None:
    records = _event_records(root)
    completed = [
        record.get("condition_id")
        for record in records
        if record.get("event") == "condition_completed"
    ]
    if completed != existing_ids[: len(completed)]:
        raise ModernBenchmarkStudyError(
            "Completed events and condition reports differ from frozen order"
        )
    by_id = {condition["condition_id"]: condition for condition in design["conditions"]}
    for condition_id in existing_ids[len(completed) :]:
        condition = by_id[condition_id]
        _append_event(
            root,
            "condition_completed",
            condition_id=condition_id,
            condition_sequence=condition["sequence"],
            reconciled_after_interruption=True,
        )


def _create_run_root(
    destination: Path,
    design_directory: Path,
    config_path: Path,
    design: dict[str, Any],
) -> None:
    if destination.exists():
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.parent / f".{destination.name}.tmp-{uuid.uuid4().hex}"
    temporary.mkdir()
    try:
        shutil.copytree(design_directory, temporary / DESIGN_DIRECTORY_NAME)
        shutil.copyfile(config_path, temporary / SOURCE_CONFIG_NAME)
        (temporary / CONDITIONS_DIRECTORY_NAME).mkdir()
        state = _initial_state(design)
        _write_json_atomic(temporary / STATE_NAME, state)
        (temporary / EVENTS_NAME).write_text("", encoding="utf-8", newline="\n")
        temporary.rename(destination)
    except Exception:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise
    _append_event(destination, "study_created")


def _verify_run_scaffold(
    root: Path,
    external_design: dict[str, Any],
    config_path: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    required = {
        DESIGN_DIRECTORY_NAME,
        SOURCE_CONFIG_NAME,
        CONDITIONS_DIRECTORY_NAME,
        STATE_NAME,
        EVENTS_NAME,
    }
    allowed = required | {MANIFEST_NAME, MANIFEST_SIDECAR_NAME, LOCK_NAME}
    if not root.is_dir() or not required.issubset({path.name for path in root.iterdir()}):
        raise ModernBenchmarkStudyError("Study run scaffold is incomplete")
    unexpected = {path.name for path in root.iterdir()} - allowed
    if unexpected:
        raise ModernBenchmarkStudyError(f"Study run has unexpected entries: {sorted(unexpected)}")
    copied_design = verify_modern_benchmark_design(root / DESIGN_DIRECTORY_NAME)
    if copied_design != external_design:
        raise ModernBenchmarkStudyError("Copied study design differs from the selected design")
    source_hash = external_design["source_config"]["sha256"]
    copied_hash = sha256_file(root / SOURCE_CONFIG_NAME)
    if copied_hash != source_hash or sha256_file(config_path) != source_hash:
        raise ModernBenchmarkStudyError("Source configuration bytes differ from the frozen design")
    state = _read_state(root, external_design)
    return copied_design, state


@contextmanager
def _study_lock(root: Path) -> Iterator[None]:
    path = root / LOCK_NAME
    owner = {
        "token": uuid.uuid4().hex,
        "pid": os.getpid(),
        "process_create_time": psutil.Process().create_time(),
        "host": platform.node(),
    }
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ModernBenchmarkStudyError("Study execution lock is unreadable") from error
        if existing.get("host") != platform.node():
            raise ModernBenchmarkStudyError(
                "Study execution lock belongs to another host and cannot be recovered safely"
            )
        active = False
        try:
            process = psutil.Process(existing["pid"])
            active = math.isclose(
                process.create_time(), existing["process_create_time"], abs_tol=0.01
            )
        except (psutil.Error, KeyError, TypeError, ValueError):
            active = False
        if active:
            raise ModernBenchmarkStudyError("Another process is executing this study")
        path.unlink()
    try:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(owner, handle, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        yield
    finally:
        if path.exists():
            try:
                observed = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                observed = None
            if isinstance(observed, dict) and observed.get("token") == owner["token"]:
                path.unlink()


def _build_manifest(root: Path, design: dict[str, Any]) -> dict[str, Any]:
    condition_records = []
    for condition in design["conditions"]:
        directory = _condition_directory(root, condition)
        _verify_condition_report(root, design, condition)
        relative = condition["output_directory"]
        condition_records.append(
            {
                "sequence": condition["sequence"],
                "condition_id": condition["condition_id"],
                "pair_id": condition["pair_id"],
                "subject_count": condition["subject_count"],
                "tile_autograd_strategy": condition["tile_autograd_strategy"],
                "report_directory": relative,
                "artifacts": {
                    REPORT_JSON_NAME: sha256_file(directory / REPORT_JSON_NAME),
                    REPORT_CSV_NAME: sha256_file(directory / REPORT_CSV_NAME),
                    REPORT_HTML_NAME: sha256_file(directory / REPORT_HTML_NAME),
                },
            }
        )
    return {
        "study_run_version": STUDY_RUN_VERSION,
        "status": "complete",
        "completed_at": _timestamp(),
        "design": {
            "path": f"{DESIGN_DIRECTORY_NAME}/{DESIGN_JSON_NAME}",
            "sha256": sha256_file(root / DESIGN_DIRECTORY_NAME / DESIGN_JSON_NAME),
        },
        "source_config": {
            "path": SOURCE_CONFIG_NAME,
            "sha256": sha256_file(root / SOURCE_CONFIG_NAME),
        },
        "conditions": condition_records,
        "analysis_performed": False,
        "scientific_boundary": SCIENTIFIC_BOUNDARY,
    }


def _validate_manifest(manifest: dict[str, Any]) -> None:
    try:
        jsonschema.Draft202012Validator(_manifest_schema()).validate(manifest)
    except jsonschema.ValidationError as error:
        location = ".".join(str(part) for part in error.absolute_path) or "document"
        raise ModernBenchmarkStudyError(
            f"Study run manifest schema validation failed at {location}: {error.message}"
        ) from error


def _publish_manifest(root: Path, design: dict[str, Any]) -> dict[str, Any]:
    manifest_path = root / MANIFEST_NAME
    sidecar_path = root / MANIFEST_SIDECAR_NAME
    if sidecar_path.exists() and not manifest_path.exists():
        raise ModernBenchmarkStudyError("Study manifest sidecar exists without its manifest")
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise ModernBenchmarkStudyError("Existing study manifest is not valid JSON") from error
        _validate_manifest(manifest)
        expected = _build_manifest(root, design)
        expected["completed_at"] = manifest["completed_at"]
        if manifest != expected:
            raise ModernBenchmarkStudyError("Existing study manifest differs from its artifacts")
    else:
        manifest = _build_manifest(root, design)
        _validate_manifest(manifest)
        _write_json_atomic(manifest_path, manifest)
    expected_sidecar = f"{sha256_file(manifest_path)}  {MANIFEST_NAME}\n"
    if sidecar_path.exists():
        if sidecar_path.read_text(encoding="utf-8") != expected_sidecar:
            raise ModernBenchmarkStudyError("Existing study manifest sidecar does not match")
    else:
        _write_text_atomic(sidecar_path, expected_sidecar)
    return manifest


def verify_modern_benchmark_study_run(directory: Path | str) -> dict[str, Any]:
    """Verify a complete study run and every separate raw report."""

    root = Path(directory).expanduser().resolve()
    expected_entries = {
        DESIGN_DIRECTORY_NAME,
        SOURCE_CONFIG_NAME,
        CONDITIONS_DIRECTORY_NAME,
        STATE_NAME,
        EVENTS_NAME,
        MANIFEST_NAME,
        MANIFEST_SIDECAR_NAME,
    }
    observed_entries = (
        frozenset(path.name for path in root.iterdir()) if root.is_dir() else frozenset()
    )
    allowed_entry_sets = {
        frozenset(expected_entries),
        frozenset(expected_entries | {LOCK_NAME}),
    }
    if observed_entries not in allowed_entry_sets:
        raise ModernBenchmarkStudyError("Completed study run has unexpected files")
    design = verify_modern_benchmark_design(root / DESIGN_DIRECTORY_NAME)
    if sha256_file(root / SOURCE_CONFIG_NAME) != design["source_config"]["sha256"]:
        raise ModernBenchmarkStudyError("Copied source config differs from the frozen design")
    state = _read_state(root, design)
    if state["status"] != "complete" or state["active_condition_id"] is not None:
        raise ModernBenchmarkStudyError("Study run is not complete")
    expected_ids = [condition["condition_id"] for condition in design["conditions"]]
    if state["completed_condition_ids"] != expected_ids:
        raise ModernBenchmarkStudyError("Study state does not contain every frozen condition")
    if _existing_condition_ids(root, design) != expected_ids:
        raise ModernBenchmarkStudyError("Study condition evidence is incomplete")
    manifest_path = root / MANIFEST_NAME
    expected_sidecar = f"{sha256_file(manifest_path)}  {MANIFEST_NAME}\n"
    if (root / MANIFEST_SIDECAR_NAME).read_text(encoding="utf-8") != expected_sidecar:
        raise ModernBenchmarkStudyError("Study run manifest SHA-256 sidecar does not match")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ModernBenchmarkStudyError("Study run manifest is not valid JSON") from error
    _validate_manifest(manifest)
    expected = _build_manifest(root, design)
    expected["completed_at"] = manifest["completed_at"]
    if manifest != expected:
        raise ModernBenchmarkStudyError("Study run manifest differs from its artifacts")
    _verify_events(root, design)
    return manifest


def _lock_observation(root: Path) -> dict[str, Any]:
    path = root / LOCK_NAME
    if not path.exists():
        return {"status": "absent", "host": None, "pid": None}
    try:
        owner = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ModernBenchmarkStudyError("Study execution lock is unreadable") from error
    host = owner.get("host")
    pid = owner.get("pid")
    if host != platform.node():
        status = "foreign-host"
    else:
        try:
            process = psutil.Process(pid)
            active = math.isclose(
                process.create_time(), owner["process_create_time"], abs_tol=0.01
            )
        except (psutil.Error, KeyError, TypeError, ValueError):
            active = False
        status = "active" if active else "stale"
    return {"status": status, "host": host, "pid": pid}


def inspect_modern_benchmark_study_run(directory: Path | str) -> dict[str, Any]:
    """Strictly inspect partial or complete study evidence without changing it."""

    root = Path(directory).expanduser().resolve()
    required = {
        DESIGN_DIRECTORY_NAME,
        SOURCE_CONFIG_NAME,
        CONDITIONS_DIRECTORY_NAME,
        STATE_NAME,
        EVENTS_NAME,
    }
    allowed = required | {MANIFEST_NAME, MANIFEST_SIDECAR_NAME, LOCK_NAME}
    observed = {path.name for path in root.iterdir()} if root.is_dir() else set()
    if not required.issubset(observed) or observed - allowed:
        raise ModernBenchmarkStudyError("Study run scaffold is incomplete or unexpected")
    design = verify_modern_benchmark_design(root / DESIGN_DIRECTORY_NAME)
    if sha256_file(root / SOURCE_CONFIG_NAME) != design["source_config"]["sha256"]:
        raise ModernBenchmarkStudyError("Copied source config differs from the frozen design")
    state = _read_state(root, design)
    existing_ids = _existing_condition_ids(root, design)
    state_ids = state["completed_condition_ids"]
    if state_ids != existing_ids[: len(state_ids)]:
        raise ModernBenchmarkStudyError(
            "Study state claims completed condition evidence that is missing"
        )
    _verify_partial_events(root, design, existing_ids)
    manifest_files = [
        name for name in (MANIFEST_NAME, MANIFEST_SIDECAR_NAME) if (root / name).exists()
    ]
    if len(manifest_files) == 1:
        manifest_status = "partial"
    elif len(manifest_files) == 2:
        manifest_status = "present"
    else:
        manifest_status = "absent"
    manifest_verified = False
    if state["status"] == "complete":
        verify_modern_benchmark_study_run(root)
        manifest_verified = True
    next_condition = (
        design["conditions"][len(existing_ids)]
        if len(existing_ids) < len(design["conditions"])
        else None
    )
    return {
        "study_run_version": STUDY_RUN_VERSION,
        "status": state["status"],
        "total_condition_count": len(design["conditions"]),
        "state_completed_condition_count": len(state_ids),
        "verified_report_count": len(existing_ids),
        "reconciliation_required": len(existing_ids) > len(state_ids),
        "active_condition_id": state["active_condition_id"],
        "next_condition": (
            None
            if next_condition is None
            else {
                "sequence": next_condition["sequence"],
                "condition_id": next_condition["condition_id"],
                "subject_count": next_condition["subject_count"],
                "tile_autograd_strategy": next_condition["tile_autograd_strategy"],
            }
        ),
        "completion_manifest_status": manifest_status,
        "completion_manifest_verified": manifest_verified,
        "lock": _lock_observation(root),
        "scientific_boundary": SCIENTIFIC_BOUNDARY,
    }


def default_modern_benchmark_study_path(design_directory: Path | str) -> Path:
    root = Path(design_directory).expanduser().resolve()
    return root.parent / f"{root.name}.run"


def run_modern_benchmark_study(
    design_directory: Path | str,
    config_path: Path | str,
    *,
    destination: Path | str | None = None,
    progress_callback: StudyProgressCallback | None = None,
) -> Path:
    """Execute or resume all frozen conditions without comparing them."""

    if progress_callback is not None and not callable(progress_callback):
        raise TypeError("progress_callback must be callable or None")
    progress_sequence = 0

    def emit(
        status: StudyProgressStatus,
        message: str,
        completed: int,
        total: int,
        condition: dict[str, Any] | None = None,
    ) -> None:
        nonlocal progress_sequence
        if progress_callback is None:
            return
        event = StudyProgressEvent(
            sequence=progress_sequence,
            status=status,
            message=message,
            completed_conditions=completed,
            total_conditions=total,
            condition=(
                None if condition is None else StudyProgressCondition.from_design(condition)
            ),
        )
        try:
            progress_callback(event)
        except Exception as error:
            raise StudyProgressObserverError(
                f"Benchmark study progress observer failed: {error}"
            ) from error
        progress_sequence += 1

    design_root = Path(design_directory).expanduser().resolve()
    source = Path(config_path).expanduser().resolve()
    design = verify_modern_benchmark_design(design_root)
    _verify_config_identity(design, source)
    output = (
        default_modern_benchmark_study_path(design_root)
        if destination is None
        else Path(destination).expanduser().resolve()
    )
    _create_run_root(output, design_root, source, design)
    with _study_lock(output):
        _, state = _verify_run_scaffold(output, design, source)
        total = len(design["conditions"])
        if state["status"] == "complete":
            emit(
                "study_already_complete",
                "Study was already complete; all evidence was reverified",
                total,
                total,
            )
            verify_modern_benchmark_study_run(output)
            return output
        previous_status = state["status"]
        existing_ids = _existing_condition_ids(output, design)
        state_ids = state["completed_condition_ids"]
        if state_ids != existing_ids[: len(state_ids)]:
            raise ModernBenchmarkStudyError(
                "Study state claims completed condition evidence that is missing"
            )
        _reconcile_completed_events(output, design, existing_ids)
        for condition in design["conditions"][len(state_ids) : len(existing_ids)]:
            emit(
                "condition_reconciled",
                "Valid condition report was reconciled after interruption",
                condition["sequence"],
                total,
                condition,
            )
        if state_ids != existing_ids:
            state["completed_condition_ids"] = existing_ids
            state["active_condition_id"] = None
            _save_state(output, state, design)
            _append_event(output, "completed_reports_reconciled", count=len(existing_ids))
        state["status"] = "running"
        _save_state(output, state, design)
        lifecycle_status = (
            "study_started"
            if previous_status == "initialized" and not existing_ids
            else "study_resumed"
        )
        emit(
            lifecycle_status,
            (
                "Frozen benchmark study started"
                if lifecycle_status == "study_started"
                else "Frozen benchmark study resumed from verified evidence"
            ),
            len(existing_ids),
            total,
        )
        for condition in design["conditions"][len(existing_ids) :]:
            state["active_condition_id"] = condition["condition_id"]
            _save_state(output, state, design)
            _append_event(
                output,
                "condition_started",
                condition_id=condition["condition_id"],
                condition_sequence=condition["sequence"],
            )
            try:
                emit(
                    "condition_started",
                    "Frozen benchmark condition started",
                    condition["sequence"] - 1,
                    total,
                    condition,
                )
                benchmark_modern_objective(
                    source,
                    subject_count=condition["subject_count"],
                    repeats=design["protocol"]["repeats_per_condition"],
                    warmup_evaluations=design["protocol"][
                        "warmup_evaluations_per_repeat"
                    ],
                    tile_autograd_strategy=condition["tile_autograd_strategy"],
                    destination=_condition_directory(output, condition),
                )
                _verify_condition_report(output, design, condition)
            except Exception as error:
                state["status"] = "interrupted"
                state["active_condition_id"] = None
                _save_state(output, state, design)
                _append_event(
                    output,
                    "condition_failed",
                    condition_id=condition["condition_id"],
                    error_type=type(error).__name__,
                    message=str(error),
                )
                if not isinstance(error, StudyProgressObserverError):
                    emit(
                        "study_interrupted",
                        f"Study interrupted: {error}",
                        condition["sequence"] - 1,
                        total,
                        condition,
                    )
                raise ModernBenchmarkStudyError(
                    f"Study interrupted in {condition['condition_id']}: {error}"
                ) from error
            state["completed_condition_ids"].append(condition["condition_id"])
            state["active_condition_id"] = None
            _save_state(output, state, design)
            _append_event(
                output,
                "condition_completed",
                condition_id=condition["condition_id"],
                condition_sequence=condition["sequence"],
            )
            emit(
                "condition_completed",
                "Frozen benchmark condition completed and verified",
                condition["sequence"],
                total,
                condition,
            )
        _publish_manifest(output, design)
        events = _event_records(output)
        if not events or events[-1].get("event") != "study_completed":
            _append_event(output, "study_completed", conditions=len(design["conditions"]))
        state["status"] = "complete"
        state["active_condition_id"] = None
        _save_state(output, state, design)
        emit(
            "study_completed",
            "Frozen benchmark study completed and verified",
            total,
            total,
        )
        verify_modern_benchmark_study_run(output)
    return output
