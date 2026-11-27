"""Hash-bound post-processing recovery, without re-running or editing atlases.

Export only writes a separately chosen new bundle. Adoption requires every
planned run to be terminal, excluding the live legacy desktop writer (which
predates recovery and has no inter-process ledger lock).
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from pathlib import Path

from diffeoforge import reference_validation_metrics
from diffeoforge.atomic_io import write_text_safely
from diffeoforge.config import load_config
from diffeoforge.mesh import sha256_file
from diffeoforge.reference_validation_metrics import (
    VALIDATION_METRIC_VERSION,
    collect_reference_validation_run_evidence,
)
from diffeoforge.reference_validation_study import (
    VALIDATION_MANIFEST,
    ReferenceValidationStudyError,
    ReferenceValidationStudySnapshot,
    ValidationStudyRunState,
    _append_event,
    _canonical_json,
    _evidence_from_manifest,
    _finalize_study,
    _load_events,
    _relative,
    _safe_path,
    load_reference_validation_study,
    validation_study_writer_lock,
)
from diffeoforge.result_report import collect_run_report

RECOVERY_VERSION = "0.1"
_CORE_FILES = (
    "manifest.json",
    "manifest.sha256",
    "result.json",
    "output-inventory.json",
    "events.jsonl",
    "logs/convergence.csv",
    "logs/deformetrica.log",
)


def _state(snapshot: ReferenceValidationStudySnapshot, run_id: str) -> ValidationStudyRunState:
    for state in snapshot.runs:
        if state.run_id == run_id:
            return state
    raise ReferenceValidationStudyError(f"Unknown frozen validation run: {run_id}")


def _implementation_sha256() -> str:
    return sha256_file(Path(reference_validation_metrics.__file__))


def _binding(snapshot: ReferenceValidationStudySnapshot, state: ValidationStudyRunState) -> dict:
    if state.status != "failed" or state.run_directory is None:
        raise ReferenceValidationStudyError("Recovery requires a terminal failed validation run")
    root, run = snapshot.study_directory, state.run_directory
    report = collect_run_report(run)
    if report.result.get("status") != "completed" or report.result.get("return_code") != 0:
        raise ReferenceValidationStudyError("Recovery requires a successfully completed backend")
    failures = [check.label for check in report.checks if check.status != "pass"]
    if failures:
        raise ReferenceValidationStudyError(f"Recovery integrity checks failed: {failures}")
    if report.manifest["source_config"]["sha256"] != sha256_file(state.config_path):
        raise ReferenceValidationStudyError(
            "Completed run is not bound to its frozen configuration"
        )
    frozen = load_config(state.config_path)
    if any(
        report.manifest["effective_config"][key] != frozen[key]
        for key in ("model", "optimization", "runtime")
    ):
        raise ReferenceValidationStudyError(
            "Completed run parameters differ from the frozen design"
        )
    for record in report.manifest["protected_artifacts"]:
        path = _safe_path(run, record["path"])
        if sha256_file(path) != record["sha256"]:
            raise ReferenceValidationStudyError(f"Protected run artifact changed: {path}")
    expected_subjects = next(
        set(cohort.subject_filenames)
        for cohort in snapshot.plan.cohorts
        if cohort.cohort_id == state.cohort_id
    )
    observed_subjects = [
        Path(str(record["source_path"])).name
        for record in report.manifest["inputs"]
        if record["role"] == "subject"
    ]
    if (
        len(observed_subjects) != len(expected_subjects)
        or set(observed_subjects) != expected_subjects
    ):
        raise ReferenceValidationStudyError("Completed run subjects differ from the frozen cohort")
    subject_hashes = {subject.filename: subject.sha256 for subject in snapshot.plan.subjects}
    templates = [record for record in report.manifest["inputs"] if record["role"] == "template"]
    if len(templates) != 1:
        raise ReferenceValidationStudyError("Completed run must bind exactly one frozen template")
    for record in report.manifest["inputs"]:
        if record["role"] not in {"template", "subject"}:
            continue
        expected = (
            snapshot.plan.template_sha256
            if record["role"] == "template"
            else subject_hashes[Path(str(record["source_path"])).name]
        )
        if (
            record["geometry"]["sha256"] != expected
            or sha256_file(_safe_path(run, record["staged_path"])) != expected
        ):
            raise ReferenceValidationStudyError(
                "Completed run input differs from the frozen design"
            )
    events = _load_events(root)
    latest = next(event for event in reversed(events) if event.get("run_id") == state.run_id)
    if latest["event"] != "run_failed":
        raise ReferenceValidationStudyError("Validation run changed during evidence recovery")
    return {
        "study_id": snapshot.study_id,
        "study_directory": str(root),
        "manifest_sha256": sha256_file(root / VALIDATION_MANIFEST),
        "plan_fingerprint": snapshot.plan.fingerprint,
        "run_id": state.run_id,
        "finalist_id": state.finalist_id,
        "cohort_id": state.cohort_id,
        "attempt": state.attempts,
        "run_directory": _relative(root, run),
        "failed_event_hash": latest["event_hash"],
        "original_error": state.error,
        "core_artifact_sha256": {name: sha256_file(run / name) for name in _CORE_FILES},
        "subject_filenames": sorted(expected_subjects),
    }


def _validate_evidence(value: dict, binding: dict) -> None:
    evidence = _evidence_from_manifest(value)
    if evidence.as_manifest() != value or any(
        value[key] != binding[key] for key in ("run_id", "finalist_id", "cohort_id")
    ):
        raise ReferenceValidationStudyError("Recovered evidence identity or fields differ")
    if value["completed"] is not True or type(value["converged"]) is not bool:
        raise ReferenceValidationStudyError("Recovered evidence must describe a completed backend")
    if type(value["invalid_face_count"]) is not int or value["invalid_face_count"] < 0:
        raise ReferenceValidationStudyError("Recovered geometry count is invalid")
    if sorted(value["subject_residual_p95"]) != binding["subject_filenames"]:
        raise ReferenceValidationStudyError(
            "Recovered per-subject evidence differs from the cohort"
        )
    metrics = [value[key] for key in ("external_residual_p95", "distortion_p95", "runtime_seconds")]
    metrics.extend(value["subject_residual_p95"].values())
    if any(
        type(item) not in (float, int) or not math.isfinite(item) or item < 0 for item in metrics
    ):
        raise ReferenceValidationStudyError("Recovered metrics must be finite and nonnegative")
    run = _safe_path(Path(binding["study_directory"]), binding["run_directory"])
    atlas = Path(str(value["atlas_path"])).resolve()
    if not atlas.is_relative_to(run / "output") or not atlas.is_file():
        raise ReferenceValidationStudyError("Recovered atlas is outside the verified run output")


def export_reference_validation_evidence_recovery(
    study_directory: Path | str,
    run_id: str,
    output: Path | str,
    *,
    progress_callback: Callable[[str, int, int], None] | None = None,
) -> Path:
    """Create one new hash-bound sidecar; never write into the source study."""
    snapshot = load_reference_validation_study(study_directory)
    destination = Path(output).expanduser().resolve()
    if destination.is_relative_to(snapshot.study_directory):
        raise ReferenceValidationStudyError("Recovery output must be outside the source study")
    if destination.exists() or destination.with_suffix(destination.suffix + ".sha256").exists():
        raise ReferenceValidationStudyError(f"Recovery output already exists: {destination}")
    state = _state(snapshot, run_id)
    binding = _binding(snapshot, state)
    implementation = _implementation_sha256()
    evidence = collect_reference_validation_run_evidence(
        state.run_directory,
        run_id=run_id,
        finalist_id=state.finalist_id,
        cohort_id=state.cohort_id,
        progress_callback=progress_callback,
    ).as_manifest()
    _validate_evidence(evidence, binding)
    fresh = load_reference_validation_study(snapshot.study_directory)
    if (
        _binding(fresh, _state(fresh, run_id)) != binding
        or _implementation_sha256() != implementation
    ):
        raise ReferenceValidationStudyError("Recovery source changed while evidence was computed")
    value = {
        "recovery_version": RECOVERY_VERSION,
        "metric_version": VALIDATION_METRIC_VERSION,
        "metric_implementation_sha256": implementation,
        "operation": "postprocessing_only_no_atlas_execution",
        "source": binding,
        "evidence": evidence,
        "limitations": [
            "Same deterministic vertex/triangle samples and p95 estimand; scale-stable numerics.",
            "Computed evidence is not automatic geometric or biological approval.",
            "Source study is unchanged; adoption requires every planned run to be terminal.",
        ],
    }
    write_text_safely(destination, _canonical_json(value, indent=2), overwrite=False)
    write_text_safely(
        destination.with_suffix(destination.suffix + ".sha256"),
        sha256_file(destination) + "\n",
        overwrite=False,
    )
    return destination


def adopt_reference_validation_evidence_recovery(
    study_directory: Path | str,
    recovery: Path | str,
    *,
    expected_sha256: str,
) -> ReferenceValidationStudySnapshot:
    """Append audited completion for the same attempt, only after execution ends."""
    root = Path(study_directory).expanduser().resolve()
    with validation_study_writer_lock(root):
        return _adopt_recovery(root, recovery, expected_sha256=expected_sha256)


def _adopt_recovery(
    root: Path,
    recovery: Path | str,
    *,
    expected_sha256: str,
) -> ReferenceValidationStudySnapshot:
    recovery_path = Path(recovery).expanduser().resolve()
    if sha256_file(recovery_path) != expected_sha256:
        raise ReferenceValidationStudyError("Recovery SHA-256 differs from the expected digest")
    value = json.loads(recovery_path.read_text(encoding="utf-8"))
    if (
        value.get("recovery_version") != RECOVERY_VERSION
        or value.get("metric_version") != VALIDATION_METRIC_VERSION
        or value.get("metric_implementation_sha256") != _implementation_sha256()
        or value.get("operation") != "postprocessing_only_no_atlas_execution"
    ):
        raise ReferenceValidationStudyError("Recovery version or implementation binding differs")
    snapshot = load_reference_validation_study(root)
    if any(state.status in {"pending", "orphaned"} for state in snapshot.runs):
        raise ReferenceValidationStudyError(
            "Recovery adoption is blocked while runs are pending or active; let execution finish"
        )
    events = _load_events(root)
    source = value["source"]
    state = _state(snapshot, source["run_id"])
    if state.status == "completed":
        existing = [
            event
            for event in events
            if event.get("run_id") == state.run_id
            and event.get("recovery_sha256") == expected_sha256
        ]
        if existing:
            if snapshot.status != "completed" and all(
                item.status == "completed" for item in snapshot.runs
            ):
                return _finalize_study(root)
            return snapshot
        raise ReferenceValidationStudyError("Completed validation evidence will not be overwritten")
    if _binding(snapshot, state) != source:
        raise ReferenceValidationStudyError("Recovery no longer matches its frozen source")
    _validate_evidence(value["evidence"], source)
    if _load_events(root) != events:
        raise ReferenceValidationStudyError(
            "Study ledger changed during adoption; nothing was appended"
        )
    _append_event(
        root,
        "run_completed",
        {
            "run_id": state.run_id,
            "finalist_id": state.finalist_id,
            "cohort_id": state.cohort_id,
            "attempt": state.attempts,
            "run_directory": source["run_directory"],
            "evidence": value["evidence"],
            "metric_version": VALIDATION_METRIC_VERSION,
            "recovery_sha256": expected_sha256,
            "recovered_from_failed_event_hash": source["failed_event_hash"],
            "recovery_operation": "postprocessing_only_no_atlas_execution",
        },
    )
    updated = load_reference_validation_study(root)
    if all(state.status == "completed" for state in updated.runs):
        return _finalize_study(root)
    return updated
