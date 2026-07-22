"""Resumable execution of frozen optimizer scaling designs."""

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

from diffeoforge.mesh import sha256_file
from diffeoforge.modern_optimizer_benchmark import (
    REPORT_CSV_NAME,
    REPORT_HTML_NAME,
    REPORT_JSON_NAME,
    ModernOptimizerBenchmarkError,
    benchmark_modern_optimizer,
    verify_modern_optimizer_benchmark_report,
)
from diffeoforge.modern_optimizer_benchmark_design import (
    DESIGN_JSON_NAME,
    collect_modern_optimizer_benchmark_design,
    verify_modern_optimizer_benchmark_design,
)
from diffeoforge.modern_optimizer_benchmark_progress import (
    OptimizerStudyProgressCallback,
    OptimizerStudyProgressCondition,
    OptimizerStudyProgressEvent,
    OptimizerStudyProgressObserverError,
    OptimizerStudyProgressStatus,
)

STUDY_RUN_VERSION = "0.1"
STATE_NAME = "optimizer-study-state.json"
EVENTS_NAME = "events.jsonl"
MANIFEST_NAME = "optimizer-study-run.json"
MANIFEST_SIDECAR_NAME = "optimizer-study-run.sha256"
DESIGN_DIRECTORY_NAME = "design"
SOURCE_CONFIG_NAME = "source-config.yaml"
CONDITIONS_DIRECTORY_NAME = "conditions"
LOCK_NAME = ".active.lock"
SCIENTIFIC_BOUNDARY = (
    "This run preserves every separate raw multi-cycle optimizer benchmark in its frozen "
    "subject-by-cycle order. It performs no automatic comparison, winner selection, ETA model, "
    "convergence assessment, scaling extrapolation, Deformetrica comparison, safe-preset "
    "selection, or 300-subject feasibility test."
)

class ModernOptimizerBenchmarkStudyError(RuntimeError):
    """Raised when a frozen optimizer study cannot run or verify safely."""


def _manifest_schema() -> dict[str, Any]:
    resource = files("diffeoforge.schema").joinpath(
        "modern-optimizer-benchmark-study-run-v0.1.json"
    )
    return json.loads(resource.read_text(encoding="utf-8"))


def _timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def _json_text(value: dict[str, Any]) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def _design_sha256(design: dict[str, Any]) -> str:
    return hashlib.sha256(_json_text(design).encode()).hexdigest()


def _write_text_atomic(path: Path, value: str) -> None:
    temporary = path.with_name(f".{path.name}.tmp-{uuid.uuid4().hex}")
    try:
        temporary.write_text(value, encoding="utf-8", newline="\n")
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    _write_text_atomic(path, _json_text(value))


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
        raise ModernOptimizerBenchmarkStudyError("Optimizer study event log is invalid") from error
    return records


def _append_event(root: Path, event: str, **details: Any) -> None:
    sequence = len(_event_records(root)) + 1
    record = {"created_at": _timestamp(), "event": event, **details, "sequence": sequence}
    with (root / EVENTS_NAME).open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _verify_event_prefix(root: Path, completed_ids: list[str], *, complete: bool) -> None:
    records = _event_records(root)
    if not records or records[0].get("event") != "study_created":
        raise ModernOptimizerBenchmarkStudyError(
            "Optimizer study event log does not start with creation"
        )
    if [record.get("sequence") for record in records] != list(range(1, len(records) + 1)):
        raise ModernOptimizerBenchmarkStudyError(
            "Optimizer study event sequence is not contiguous"
        )
    if any(
        not isinstance(record.get("created_at"), str)
        or not isinstance(record.get("event"), str)
        for record in records
    ):
        raise ModernOptimizerBenchmarkStudyError("Optimizer study event records are malformed")
    observed_completed = [
        record.get("condition_id")
        for record in records
        if record.get("event") == "condition_completed"
    ]
    expected_completed = completed_ids if complete else completed_ids[: len(observed_completed)]
    if observed_completed != expected_completed:
        raise ModernOptimizerBenchmarkStudyError(
            "Completed optimizer events differ from verified reports"
        )
    if complete and records[-1].get("event") != "study_completed":
        raise ModernOptimizerBenchmarkStudyError(
            "Optimizer study event log does not end with completion"
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
        raise ModernOptimizerBenchmarkStudyError("Optimizer study state has unexpected fields")
    if state["study_run_version"] != STUDY_RUN_VERSION:
        raise ModernOptimizerBenchmarkStudyError("Optimizer study state version is unsupported")
    if state["status"] not in {"initialized", "running", "interrupted", "complete"}:
        raise ModernOptimizerBenchmarkStudyError("Optimizer study state status is invalid")
    if (
        state["design_sha256"] != _design_sha256(design)
        or state["source_config_sha256"] != design["source_config"]["sha256"]
    ):
        raise ModernOptimizerBenchmarkStudyError(
            "Optimizer study state identity differs from the design"
        )
    condition_ids = [condition["condition_id"] for condition in design["conditions"]]
    completed = state["completed_condition_ids"]
    if not isinstance(completed, list) or completed != condition_ids[: len(completed)]:
        raise ModernOptimizerBenchmarkStudyError(
            "Completed optimizer conditions are not a frozen-order prefix"
        )
    active = state["active_condition_id"]
    if active is not None and active not in condition_ids:
        raise ModernOptimizerBenchmarkStudyError("Active optimizer condition is unknown")
    if not isinstance(state["updated_at"], str) or not state["updated_at"]:
        raise ModernOptimizerBenchmarkStudyError("Optimizer study timestamp is invalid")


def _read_state(root: Path, design: dict[str, Any]) -> dict[str, Any]:
    try:
        state = json.loads((root / STATE_NAME).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ModernOptimizerBenchmarkStudyError(
            "Optimizer study state is missing or invalid"
        ) from error
    _validate_state(state, design)
    return state


def _save_state(root: Path, state: dict[str, Any], design: dict[str, Any]) -> None:
    state["updated_at"] = _timestamp()
    _validate_state(state, design)
    _write_json_atomic(root / STATE_NAME, state)


def _fresh_design_for_config(design: dict[str, Any], config_path: Path) -> dict[str, Any]:
    protocol = design["protocol"]
    return collect_modern_optimizer_benchmark_design(
        config_path,
        subject_counts=protocol["subject_counts"],
        cycle_caps=protocol["cycle_caps"],
        repeats_per_condition=protocol["repeats_per_condition"],
        warmup_runs=protocol["warmup_runs_per_repeat"],
        order_seed=protocol["order_seed"],
        created_at=design["created_at"],
    )


def _verify_config_identity(design: dict[str, Any], config_path: Path) -> None:
    if _fresh_design_for_config(design, config_path) != design:
        raise ModernOptimizerBenchmarkStudyError(
            "Current source config, software, or complete input inventory differs from design"
        )


def _condition_directory(root: Path, condition: dict[str, Any]) -> Path:
    relative = Path(condition["output_directory"])
    if (
        relative.is_absolute()
        or not relative.parts
        or relative.parts[0] != CONDITIONS_DIRECTORY_NAME
        or ".." in relative.parts
    ):
        raise ModernOptimizerBenchmarkStudyError(
            "Optimizer condition output path escapes the study run"
        )
    return root.joinpath(*relative.parts)


def _verify_condition_report(
    root: Path, design: dict[str, Any], condition: dict[str, Any]
) -> dict[str, Any]:
    try:
        report = verify_modern_optimizer_benchmark_report(
            _condition_directory(root, condition)
        )
    except (ModernOptimizerBenchmarkError, OSError) as error:
        raise ModernOptimizerBenchmarkStudyError(
            f"Optimizer condition {condition['condition_id']} is invalid: {error}"
        ) from error
    if report["source_config"] != design["source_config"]:
        raise ModernOptimizerBenchmarkStudyError(
            "Optimizer condition source config differs from frozen design"
        )
    count = condition["subject_count"]
    expected_input = {
        "template": design["input"]["template"],
        "subjects": design["input"]["subjects"][:count],
        "available_subject_count": design["input"]["available_subject_count"],
        "selected_subject_count": count,
        "selection": design["input"]["selection"],
    }
    if report["input"] != expected_input:
        raise ModernOptimizerBenchmarkStudyError(
            "Optimizer condition input inventory differs from frozen design"
        )
    frozen = design["configuration"]
    config = report["configuration"]
    expected_fixed = {
        "source_max_cycles": frozen["source_max_cycles"],
        "measured_max_cycles": condition["cycle_cap"],
        "block_order": frozen["block_order"],
        "momenta_step_size": frozen["momenta_step_size"],
        "template_step_size": frozen["template_step_size"],
        "control_points_step_size": frozen["control_points_step_size"],
        "backtracking_factor": frozen["backtracking_factor"],
        "armijo_constant": frozen["armijo_constant"],
        "gradient_tolerance": frozen["gradient_tolerance"],
        "minimum_step_size": frozen["minimum_step_size"],
        "max_line_search_iterations": frozen["max_line_search_iterations"],
        "pairwise_evaluation": frozen["pairwise_evaluation"],
        "threads": frozen["threads"],
        "random_seed": frozen["random_seed"],
        "warmup_runs_per_repeat": design["protocol"]["warmup_runs_per_repeat"],
        "repeats": design["protocol"]["repeats_per_condition"],
        "rss_sampling_interval_ms": 5.0,
        "process_isolation": "fresh multiprocessing spawn process per repeat",
        "prepared_target_cache": (
            "target geometry and target self-term prepared once per fresh process"
        ),
    }
    if config != expected_fixed:
        raise ModernOptimizerBenchmarkStudyError(
            "Optimizer condition protocol differs from frozen design"
        )
    return report


def _existing_condition_ids(root: Path, design: dict[str, Any]) -> list[str]:
    conditions_root = root / CONDITIONS_DIRECTORY_NAME
    expected_names = {
        Path(condition["output_directory"]).name for condition in design["conditions"]
    }
    observed = {path.name for path in conditions_root.iterdir()}
    if observed - expected_names:
        raise ModernOptimizerBenchmarkStudyError(
            f"Optimizer conditions contain unexpected entries: {sorted(observed - expected_names)}"
        )
    existing = []
    missing_seen = False
    for condition in design["conditions"]:
        path = _condition_directory(root, condition)
        if path.exists():
            if missing_seen:
                raise ModernOptimizerBenchmarkStudyError(
                    "Optimizer reports exist outside frozen order"
                )
            _verify_condition_report(root, design, condition)
            existing.append(condition["condition_id"])
        else:
            missing_seen = True
    return existing


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
        _write_json_atomic(temporary / STATE_NAME, _initial_state(design))
        (temporary / EVENTS_NAME).write_text("", encoding="utf-8", newline="\n")
        temporary.rename(destination)
    except Exception:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise
    _append_event(destination, "study_created")


def _verify_scaffold(
    root: Path, external_design: dict[str, Any], config_path: Path
) -> dict[str, Any]:
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
        raise ModernOptimizerBenchmarkStudyError(
            "Optimizer study scaffold is incomplete or unexpected"
        )
    copied = verify_modern_optimizer_benchmark_design(root / DESIGN_DIRECTORY_NAME)
    if copied != external_design:
        raise ModernOptimizerBenchmarkStudyError(
            "Copied optimizer design differs from selected design"
        )
    source_hash = external_design["source_config"]["sha256"]
    if (
        sha256_file(root / SOURCE_CONFIG_NAME) != source_hash
        or sha256_file(config_path) != source_hash
    ):
        raise ModernOptimizerBenchmarkStudyError(
            "Source configuration bytes differ from frozen optimizer design"
        )
    return _read_state(root, external_design)


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
            raise ModernOptimizerBenchmarkStudyError(
                "Optimizer study execution lock is unreadable"
            ) from error
        if existing.get("host") != platform.node():
            raise ModernOptimizerBenchmarkStudyError(
                "Optimizer study lock belongs to another host"
            )
        try:
            process = psutil.Process(existing["pid"])
            active = math.isclose(
                process.create_time(), existing["process_create_time"], abs_tol=0.01
            )
        except (psutil.Error, KeyError, TypeError, ValueError):
            active = False
        if active:
            raise ModernOptimizerBenchmarkStudyError(
                "Another process is executing this optimizer study"
            )
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


def _lock_observation(root: Path) -> dict[str, Any]:
    path = root / LOCK_NAME
    if not path.exists():
        return {"status": "absent", "host": None, "pid": None}
    try:
        owner = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ModernOptimizerBenchmarkStudyError(
            "Optimizer study execution lock is unreadable"
        ) from error
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


def _build_manifest(root: Path, design: dict[str, Any]) -> dict[str, Any]:
    condition_records = []
    for condition in design["conditions"]:
        directory = _condition_directory(root, condition)
        _verify_condition_report(root, design, condition)
        condition_records.append(
            {
                "sequence": condition["sequence"],
                "condition_id": condition["condition_id"],
                "subject_count": condition["subject_count"],
                "cycle_cap": condition["cycle_cap"],
                "report_directory": condition["output_directory"],
                "artifacts": {
                    REPORT_JSON_NAME: sha256_file(directory / REPORT_JSON_NAME),
                    REPORT_CSV_NAME: sha256_file(directory / REPORT_CSV_NAME),
                    REPORT_HTML_NAME: sha256_file(directory / REPORT_HTML_NAME),
                },
            }
        )
    return {
        "optimizer_study_run_version": STUDY_RUN_VERSION,
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
        raise ModernOptimizerBenchmarkStudyError(
            f"Optimizer study manifest schema failed at {location}: {error.message}"
        ) from error


def _publish_manifest(root: Path, design: dict[str, Any]) -> dict[str, Any]:
    manifest_path = root / MANIFEST_NAME
    sidecar_path = root / MANIFEST_SIDECAR_NAME
    if sidecar_path.exists() and not manifest_path.exists():
        raise ModernOptimizerBenchmarkStudyError(
            "Optimizer study manifest sidecar exists without its manifest"
        )
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        _validate_manifest(manifest)
        expected = _build_manifest(root, design)
        expected["completed_at"] = manifest["completed_at"]
        if manifest != expected:
            raise ModernOptimizerBenchmarkStudyError(
                "Existing optimizer study manifest differs from artifacts"
            )
    else:
        manifest = _build_manifest(root, design)
        _validate_manifest(manifest)
        _write_json_atomic(manifest_path, manifest)
    expected_sidecar = f"{sha256_file(manifest_path)}  {MANIFEST_NAME}\n"
    if sidecar_path.exists():
        if sidecar_path.read_text(encoding="utf-8") != expected_sidecar:
            raise ModernOptimizerBenchmarkStudyError(
                "Optimizer study manifest sidecar does not match"
            )
    else:
        _write_text_atomic(sidecar_path, expected_sidecar)
    return manifest


def verify_modern_optimizer_benchmark_study_run(directory: Path | str) -> dict[str, Any]:
    """Verify a completed study and every separate raw optimizer report."""

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
    observed = {path.name for path in root.iterdir()} if root.is_dir() else set()
    if observed != expected_entries and observed != expected_entries | {LOCK_NAME}:
        raise ModernOptimizerBenchmarkStudyError(
            "Completed optimizer study has unexpected files"
        )
    design = verify_modern_optimizer_benchmark_design(root / DESIGN_DIRECTORY_NAME)
    if sha256_file(root / SOURCE_CONFIG_NAME) != design["source_config"]["sha256"]:
        raise ModernOptimizerBenchmarkStudyError(
            "Copied source config differs from frozen optimizer design"
        )
    state = _read_state(root, design)
    expected_ids = [condition["condition_id"] for condition in design["conditions"]]
    if (
        state["status"] != "complete"
        or state["active_condition_id"] is not None
        or state["completed_condition_ids"] != expected_ids
        or _existing_condition_ids(root, design) != expected_ids
    ):
        raise ModernOptimizerBenchmarkStudyError("Optimizer study is not complete")
    manifest_path = root / MANIFEST_NAME
    expected_sidecar = f"{sha256_file(manifest_path)}  {MANIFEST_NAME}\n"
    if (root / MANIFEST_SIDECAR_NAME).read_text(encoding="utf-8") != expected_sidecar:
        raise ModernOptimizerBenchmarkStudyError(
            "Optimizer study manifest SHA-256 sidecar does not match"
        )
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ModernOptimizerBenchmarkStudyError(
            "Optimizer study manifest is not valid JSON"
        ) from error
    _validate_manifest(manifest)
    expected = _build_manifest(root, design)
    expected["completed_at"] = manifest["completed_at"]
    if manifest != expected:
        raise ModernOptimizerBenchmarkStudyError(
            "Optimizer study manifest differs from artifacts"
        )
    _verify_event_prefix(root, expected_ids, complete=True)
    return manifest


def inspect_modern_optimizer_benchmark_study_run(
    directory: Path | str,
) -> dict[str, Any]:
    """Strictly inspect partial or complete optimizer evidence without changing it."""

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
        raise ModernOptimizerBenchmarkStudyError(
            "Optimizer study scaffold is incomplete or unexpected"
        )
    design = verify_modern_optimizer_benchmark_design(root / DESIGN_DIRECTORY_NAME)
    if sha256_file(root / SOURCE_CONFIG_NAME) != design["source_config"]["sha256"]:
        raise ModernOptimizerBenchmarkStudyError(
            "Copied source config differs from frozen optimizer design"
        )
    state = _read_state(root, design)
    existing_ids = _existing_condition_ids(root, design)
    state_ids = state["completed_condition_ids"]
    if state_ids != existing_ids[: len(state_ids)]:
        raise ModernOptimizerBenchmarkStudyError(
            "Optimizer state claims completed condition evidence that is missing"
        )
    _verify_event_prefix(root, existing_ids, complete=False)
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
        verify_modern_optimizer_benchmark_study_run(root)
        manifest_verified = True
    next_condition = (
        design["conditions"][len(existing_ids)]
        if len(existing_ids) < len(design["conditions"])
        else None
    )
    return {
        "optimizer_study_run_version": STUDY_RUN_VERSION,
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
                "cycle_cap": next_condition["cycle_cap"],
            }
        ),
        "completion_manifest_status": manifest_status,
        "completion_manifest_verified": manifest_verified,
        "lock": _lock_observation(root),
        "scientific_boundary": SCIENTIFIC_BOUNDARY,
    }


def default_modern_optimizer_benchmark_study_path(design_directory: Path | str) -> Path:
    root = Path(design_directory).expanduser().resolve()
    return root.parent / f"{root.name}.run"


def run_modern_optimizer_benchmark_study(
    design_directory: Path | str,
    config_path: Path | str,
    *,
    destination: Path | str | None = None,
    progress_callback: OptimizerStudyProgressCallback | None = None,
) -> Path:
    """Execute or resume all frozen conditions without comparing them."""

    if progress_callback is not None and not callable(progress_callback):
        raise TypeError("progress_callback must be callable or None")
    progress_sequence = 0

    def emit(
        status: OptimizerStudyProgressStatus,
        message: str,
        completed: int,
        total: int,
        condition: dict[str, Any] | None = None,
    ) -> None:
        nonlocal progress_sequence
        if progress_callback is None:
            return
        event = OptimizerStudyProgressEvent(
            sequence=progress_sequence,
            status=status,
            message=message,
            completed_conditions=completed,
            total_conditions=total,
            condition=(
                None
                if condition is None
                else OptimizerStudyProgressCondition.from_design(condition)
            ),
        )
        try:
            progress_callback(
                event
            )
        except Exception as error:
            raise OptimizerStudyProgressObserverError(
                f"Optimizer study progress observer failed: {error}"
            ) from error
        progress_sequence += 1

    design_root = Path(design_directory).expanduser().resolve()
    source = Path(config_path).expanduser().resolve()
    design = verify_modern_optimizer_benchmark_design(design_root)
    _verify_config_identity(design, source)
    output = (
        default_modern_optimizer_benchmark_study_path(design_root)
        if destination is None
        else Path(destination).expanduser().resolve()
    )
    _create_run_root(output, design_root, source, design)
    with _study_lock(output):
        state = _verify_scaffold(output, design, source)
        total = len(design["conditions"])
        if state["status"] == "complete":
            verify_modern_optimizer_benchmark_study_run(output)
            emit(
                "study_already_complete",
                "The frozen optimizer study is already complete and verified.",
                total,
                total,
            )
            return output
        existing_ids = _existing_condition_ids(output, design)
        state_ids = state["completed_condition_ids"]
        if state_ids != existing_ids[: len(state_ids)]:
            raise ModernOptimizerBenchmarkStudyError(
                "Optimizer state claims report evidence that is missing"
            )
        event_completed = [
            record.get("condition_id")
            for record in _event_records(output)
            if record.get("event") == "condition_completed"
        ]
        if event_completed != existing_ids[: len(event_completed)]:
            raise ModernOptimizerBenchmarkStudyError(
                "Optimizer completed events differ from frozen report order"
            )
        by_id = {condition["condition_id"]: condition for condition in design["conditions"]}
        for condition_id in existing_ids[len(event_completed) :]:
            condition = by_id[condition_id]
            _append_event(
                output,
                "condition_completed",
                condition_id=condition_id,
                condition_sequence=condition["sequence"],
                reconciled_after_interruption=True,
            )
            emit(
                "condition_reconciled",
                "A previously published raw report was strictly verified and reconciled.",
                condition["sequence"],
                total,
                condition,
            )
        if state_ids != existing_ids:
            state["completed_condition_ids"] = existing_ids
            state["active_condition_id"] = None
            _save_state(output, state, design)
        state["status"] = "running"
        _save_state(output, state, design)
        lifecycle_status: OptimizerStudyProgressStatus = (
            "study_started" if not existing_ids else "study_resumed"
        )
        emit(
            lifecycle_status,
            (
                "The frozen optimizer study started."
                if lifecycle_status == "study_started"
                else "The frozen optimizer study resumed after strict prefix verification."
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
            emit(
                "condition_started",
                "A frozen optimizer condition started.",
                condition["sequence"] - 1,
                total,
                condition,
            )
            try:
                benchmark_modern_optimizer(
                    source,
                    subject_count=condition["subject_count"],
                    max_cycles=condition["cycle_cap"],
                    repeats=design["protocol"]["repeats_per_condition"],
                    warmup_runs=design["protocol"]["warmup_runs_per_repeat"],
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
                emit(
                    "study_interrupted",
                    "The optimizer study stopped before this condition was published.",
                    condition["sequence"] - 1,
                    total,
                    condition,
                )
                raise ModernOptimizerBenchmarkStudyError(
                    f"Optimizer study interrupted in {condition['condition_id']}: {error}"
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
                "A raw optimizer condition report was published and strictly verified.",
                condition["sequence"],
                total,
                condition,
            )

        _publish_manifest(output, design)
        events = _event_records(output)
        if not events or events[-1].get("event") != "study_completed":
            _append_event(output, "study_completed", conditions=total)
        state["status"] = "complete"
        state["active_condition_id"] = None
        _save_state(output, state, design)
        verify_modern_optimizer_benchmark_study_run(output)
        emit(
            "study_completed",
            "Every frozen optimizer condition and the completion manifest verified.",
            total,
            total,
        )
    return output
