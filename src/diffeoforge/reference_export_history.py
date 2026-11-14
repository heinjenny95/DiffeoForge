"""Read-only provenance for an export-only successor's original optimizer history."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from diffeoforge.analysis.reference_convergence_visualization import (
    ReferenceStopEvidence,
    detect_reference_stop_evidence,
)
from diffeoforge.config import ConfigurationError
from diffeoforge.mesh import sha256_file
from diffeoforge.result_report import ConvergenceRow, RunReport, _load_convergence
from diffeoforge.runs import _verify_existing_convergence
from diffeoforge.strict_json import load_strict_json_object

DECLARATION_PATH = "resume/final-export-recovery.json"
STATE_VERIFICATION_PATH = "output/final-export-state-verification.json"


@dataclass(frozen=True)
class ExportHistory:
    declaration: Mapping[str, Any]
    rows: tuple[ConvergenceRow, ...]
    stop: ReferenceStopEvidence
    duration_seconds: float | None


def read_export_history(
    declaration_path: Path,
    state_path: Path,
    source_result_path: Path,
    convergence_path: Path,
    native_log_path: Path,
    *,
    maximum_iterations: int,
) -> ExportHistory:
    """Verify copied history against its protected native log and unchanged-state receipt."""
    paths = (declaration_path, state_path, source_result_path, convergence_path, native_log_path)
    if any(path.is_symlink() or not path.is_file() for path in paths):
        raise ConfigurationError("Export recovery history is missing or symbolic")
    declaration = load_strict_json_object(
        declaration_path.read_bytes(), declaration_path, label="Export declaration"
    )
    state = load_strict_json_object(
        state_path.read_bytes(), state_path, label="Export state receipt"
    )
    source_result = load_strict_json_object(
        source_result_path.read_bytes(), source_result_path, label="Original run result"
    )
    iteration = declaration.get("checkpoint_iteration")
    if (
        declaration.get("schema_version") != "0.1"
        or declaration.get("operation") != "saved_state_final_export"
        or isinstance(iteration, bool)
        or not isinstance(iteration, int)
        or iteration < 0
        or state.get("operation") != "saved_state_final_export"
        or state.get("optimization_executed") is not False
        or state.get("parameters_unchanged") is not True
        or state.get("original_native_writer_used") is not True
        or state.get("all_flow_timepoints_retained") is not True
        or isinstance(state.get("checkpoint_iteration"), bool)
        or state.get("checkpoint_iteration") != iteration
    ):
        raise ConfigurationError("Export recovery lacks unchanged-state postconditions")
    if (
        sha256_file(source_result_path) != declaration.get("source_result_sha256")
        or sha256_file(native_log_path) != declaration.get("native_stop_log_sha256")
        or source_result.get("status") not in {"failed", "interrupted"}
        or source_result.get("run_id") != declaration.get("source_run_id")
    ):
        raise ConfigurationError("Export recovery source history hashes or identity differ")
    _verify_existing_convergence(native_log_path, convergence_path)
    rows = _load_convergence(convergence_path)
    if not rows or any(b.iteration <= a.iteration for a, b in zip(rows, rows[1:], strict=False)):
        raise ConfigurationError("Export recovery requires an ordered original objective history")
    log = native_log_path.read_text(encoding="utf-8", errors="replace")
    stop = detect_reference_stop_evidence(
        log, final_iteration=rows[-1].iteration, maximum_iterations=maximum_iterations
    )
    if declaration.get("native_stop") == "native_tolerance":
        matches = stop.signal == "tolerance_threshold"
    else:
        matches = (
            declaration.get("native_stop") == "iteration_limit"
            and iteration == maximum_iterations
            and (
                "Maximum number of iterations reached" in log
                or (
                    rows[-1].iteration == iteration
                    and "DiffeoForge final mesh export started" in log
                )
            )
            and stop.signal != "tolerance_threshold"
            and "number of line search loops exceeded" not in log.casefold()
        )
        if matches:
            stop = detect_reference_stop_evidence(
                "", final_iteration=iteration, maximum_iterations=maximum_iterations
            )
    if not matches or not rows[-1].iteration <= iteration <= rows[-1].iteration + 1:
        raise ConfigurationError("Export recovery stop does not match the saved iteration")
    try:
        raw_duration = source_result.get("duration_seconds")
        duration = None if raw_duration is None else float(raw_duration)
    except (KeyError, TypeError, ValueError) as error:
        raise ConfigurationError("Original run duration is missing") from error
    if duration is not None and (not math.isfinite(duration) or duration < 0):
        raise ConfigurationError("Original run duration must be finite and nonnegative")
    note = (
        f" Retained original-run evidence: saved iteration {iteration} was exported "
        "without any additional optimizer iterations."
    )
    return ExportHistory(
        declaration,
        rows,
        ReferenceStopEvidence(stop.signal, stop.summary + note, stop.final_state_visibility + note),
        duration,
    )


def verified_export_history(run: Path, report: RunReport) -> tuple[ExportHistory, dict[str, Path]]:
    """Require run-bound declaration/checkpoint/receipt before using an earlier curve."""
    declaration_path = run / DECLARATION_PATH
    protected = {item["path"]: item for item in report.manifest.get("protected_artifacts", [])}
    for relative in (DECLARATION_PATH, "resume/source-checkpoint.p"):
        record = protected.get(relative)
        path = run / relative
        if (
            record is None
            or path.is_symlink()
            or not path.is_file()
            or path.stat().st_size != record["bytes"]
            or sha256_file(path) != record["sha256"]
        ):
            raise ConfigurationError("Export recovery declaration/checkpoint is not protected")
    declaration = load_strict_json_object(
        declaration_path.read_bytes(), declaration_path, label="Export declaration"
    )
    if protected["resume/source-checkpoint.p"]["sha256"] != declaration.get("checkpoint_sha256"):
        raise ConfigurationError("Export recovery checkpoint binding differs")
    source = Path(str(declaration.get("source_run_path", "")))
    if (
        not source.is_absolute()
        or source.is_symlink()
        or source.name != declaration.get("source_run_id")
    ):
        raise ConfigurationError("Export recovery source path is invalid")
    native_relative = PurePosixPath(str(declaration.get("native_stop_log", "")))
    if native_relative.is_absolute() or ".." in native_relative.parts or not native_relative.parts:
        raise ConfigurationError("Export recovery native log path escapes its source")
    paths = {
        "declaration": declaration_path,
        "state_verification": run / STATE_VERIFICATION_PATH,
        "source_result": source / "result.json",
        "convergence": source / "logs/convergence.csv",
        "terminal_log": source.joinpath(*native_relative.parts),
    }
    inventory = {"output/" + item["path"]: item for item in report.inventory}
    receipt = inventory.get(STATE_VERIFICATION_PATH)
    if receipt is None or sha256_file(paths["state_verification"]) != receipt["sha256"]:
        raise ConfigurationError("Export recovery state receipt is not inventoried")
    for relative, key in (
        ("manifest.json", "source_manifest_sha256"),
        ("output/deformetrica-state.p", "checkpoint_sha256"),
    ):
        path = source / relative
        if path.is_symlink() or not path.is_file() or sha256_file(path) != declaration.get(key):
            raise ConfigurationError("Export recovery original source binding differs")
    history = read_export_history(
        paths["declaration"],
        paths["state_verification"],
        paths["source_result"],
        paths["convergence"],
        paths["terminal_log"],
        maximum_iterations=int(
            report.manifest["effective_config"]["optimization"]["max_iterations"]
        ),
    )
    return history, paths
