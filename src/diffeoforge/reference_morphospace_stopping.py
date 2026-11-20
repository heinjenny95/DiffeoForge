"""Shared LDDMM stopping metric and retained native atlas evidence."""

from __future__ import annotations

import hashlib
import math
import re
from importlib.resources import files
from pathlib import Path
from typing import TYPE_CHECKING

from diffeoforge._atlas_distance_metric import (
    CHECK_INTERVAL,
    COHORT_THRESHOLD_PERCENT,
    SUBJECT_THRESHOLD_PERCENT,
    WINDOW_ITERATIONS,
    compare_distances,
    distance_matrix,
)
from diffeoforge.config import ConfigurationError
from diffeoforge.mesh import sha256_file
from diffeoforge.reference_atlas_stop import MORPHOSPACE_STABILITY, OPTIMIZER_CONVERGENCE
from diffeoforge.reference_morphospace_native import REPORT_NAME, manifest_subject_labels
from diffeoforge.strict_json import load_strict_json_object

if TYPE_CHECKING:
    from diffeoforge.result_report import RunReport

__all__ = [
    "CHECK_INTERVAL", "COHORT_THRESHOLD_PERCENT", "SUBJECT_THRESHOLD_PERCENT",
    "WINDOW_ITERATIONS", "compare_distances", "distance_matrix", "metric_source",
    "read_morphospace_stability",
]

_REASONS = {
    "backend_failure", "cancelled", "iteration_limit", "line_search_exhausted",
    "morphospace_stable", "native_tolerance", "numerical_failure", "optimizer_callback",
}
_EXPORTS = {"complete", "failed", "not_started", "pending"}


def metric_source() -> str:
    """Return the exact source to evaluate in an isolated native runtime namespace."""
    return files("diffeoforge").joinpath("_atlas_distance_metric.py").read_text(encoding="utf-8")


def _require(condition, detail):
    if not condition:
        raise ConfigurationError(f"Saved morphospace stability evidence {detail}.")


def _number(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def _is_digest(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _observation_metrics(row, labels, window):
    cohort, maximum, subjects, worst = (row.get(key) for key in (
        "cohort_percent", "max_subject_percent", "subject_percent", "worst_subjects",
    ))
    if row.get("status") == "unavailable":
        _require(cohort is None and maximum is None and subjects is None and worst == []
                 and row.get("stable") is False, "contains inconsistent unavailable measurements")
        return
    _require(row.get("status") == "measured" and _number(cohort) and cohort >= 0
             and _number(maximum) and isinstance(subjects, list) and len(subjects) == len(labels)
             and all(_number(value) and value >= 0 for value in subjects)
             and maximum == max(subjects)
             and worst == [label for label, value in zip(labels, subjects, strict=True)
                           if value == maximum], "contains invalid distance measurements")
    stable = (row["window_iterations"] == window and cohort < COHORT_THRESHOLD_PERCENT
              and maximum < SUBJECT_THRESHOLD_PERCENT)
    _require(row.get("stable") is stable, "contains an inconsistent stability decision")


def _verify_window(row, labels, window, iteration, checkpoint, checkpoint_by_iteration):
    _require(isinstance(row, dict), "has a missing or invalid comparison window")
    previous = min((key for key in checkpoint_by_iteration if key >= iteration - window),
                   default=None)
    span = iteration - previous if previous is not None else 0
    saved_previous = row.get("previous_iteration")
    _require(saved_previous == previous and type(saved_previous) is type(previous)
             and type(row.get("window_iterations")) is int and row["window_iterations"] == span
             and row.get("previous_checkpoint") == checkpoint_by_iteration.get(previous),
             "has an invalid comparison window")
    if row.get("status") == "measured":
        _require(checkpoint is not None and checkpoint_by_iteration.get(previous) is not None,
                 "contains distances without two retained checkpoints")
    _observation_metrics(row, labels, window)


def read_morphospace_stability(
    run_directory: str | Path, *, verified_run_report: RunReport | None = None,
) -> dict | None:
    """Read accepted-state diagnostics, optionally reusing a freshly verified run report."""
    from diffeoforge.runs import (
        EXECUTION_CHECKPOINT_PATH,
        _read_manifest,
        _read_output_inventory,
    )

    run = Path(run_directory).resolve()
    output = run / "output"
    path = output / REPORT_NAME
    if not path.exists() and not path.is_symlink():
        return None
    _require(not output.is_symlink() and path.is_file() and not path.is_symlink(),
             "is not a regular retained report")
    payload = path.read_bytes()
    report = load_strict_json_object(payload, path, label="Morphospace stability report")
    manifest = _read_manifest(run)
    config = manifest["effective_config"]
    policy = config["project"].get("atlas_stop")
    labels = manifest_subject_labels(manifest)
    width = config["model"]["deformation"]["kernel_width"]
    origin = report.get("joint_origin_iteration")
    _require(type(report.get("version")) is int and report["version"] == 1
             and policy is not None and report.get("policy") == policy
             and report.get("subject_labels") == list(labels)
             and len(labels) >= 2 and len(set(labels)) == len(labels)
             and _number(report.get("deformation_kernel_width"))
             and report["deformation_kernel_width"] == width
             and type(origin) is int and origin >= 0, "does not match the prepared run")
    _require("terminal" in report and isinstance(report.get("observations"), list),
             "has no observation and terminal record")

    result, records = None, None
    result_path = run / "result.json"
    if result_path.exists() or result_path.is_symlink():
        _require(result_path.is_file() and not result_path.is_symlink(), "has a linked run result")
        result = load_strict_json_object(result_path.read_bytes(), result_path, label="Run result")
        _require(result.get("run_id") == manifest["run_id"], "is paired with another run result")
        _, inventory = _read_output_inventory(run, result)
        records = inventory["files"]
    if verified_run_report is not None:
        _require(records is not None and verified_run_report.run_directory == run
                 and manifest == verified_run_report.manifest
                 and result == verified_run_report.result
                 and tuple(records) == verified_run_report.inventory and verified_run_report.checks
                 and all(check.status == "pass" for check in verified_run_report.checks),
                 "does not match the previously verified run report")

    def verify_inventory_record(relative, byte_count, digest):
        if records is None:
            return
        matches = [record for record in records
                   if isinstance(record, dict) and record.get("path") == relative]
        _require(matches == [{"path": relative, "bytes": byte_count, "sha256": digest}],
                 f"does not match the terminal output inventory for {relative}")

    fields = output / "morphospace-checkpoints"
    _require(not fields.is_symlink(), "points to a linked checkpoint directory")

    def verify_artifact(relative, digest):
        artifact = output / relative
        _require(_is_digest(digest) and artifact.is_file() and not artifact.is_symlink()
                 and artifact.resolve().is_relative_to(output.resolve()),
                 f"has a missing or invalid {relative}")
        before = artifact.stat()
        if verified_run_report is None:
            actual = sha256_file(artifact)
            after = artifact.stat()
            _require(actual == digest and before.st_size == after.st_size
                     and before.st_mtime_ns == after.st_mtime_ns,
                     f"has a checksum mismatch for {relative}")
        verify_inventory_record(relative, before.st_size, digest)

    window, interval = policy["window_iterations"], policy["check_interval"]
    long_window = policy.get("long_window_iterations")
    checkpoint_by_iteration = {}
    last_iteration = None
    rows = report["observations"]
    terminal = report["terminal"]
    for index, row in enumerate(rows):
        _require(isinstance(row, dict), "has an invalid observation record")
        iteration = row.get("iteration")
        _require(type(iteration) is int and (iteration == origin if index == 0 else
                 iteration > last_iteration), "contains an invalid accepted iteration")
        is_terminal_observation = index == len(rows) - 1
        scheduled = origin + index * interval
        _require(iteration == scheduled or (is_terminal_observation and iteration < scheduled),
                 "contains an observation outside the saved check cadence")
        _require(_number(row.get("objective")) and _number(row.get("weighted_fit_error")),
                 "has an invalid accepted objective or weighted fit error")
        checkpoint = row.get("checkpoint")
        if checkpoint is not None:
            relative = f"morphospace-checkpoints/iteration-{iteration}.npz"
            _require(isinstance(checkpoint, dict) and checkpoint.get("path") == relative,
                     "contains an invalid accepted checkpoint path")
            verify_artifact(relative, checkpoint.get("sha256"))
        _verify_window(row, labels, window, iteration, checkpoint, checkpoint_by_iteration)
        if long_window is not None:
            _verify_window(row.get("long_window"), labels, long_window, iteration, checkpoint,
                           checkpoint_by_iteration)
        checkpoint_by_iteration[iteration] = checkpoint
        last_iteration = iteration

    if terminal is not None:
        _require(isinstance(terminal, dict), "has an invalid terminal record")
        reason, export = terminal.get("reason"), terminal.get("export")
        _require(isinstance(reason, str) and reason in _REASONS
                 and isinstance(export, str) and export in _EXPORTS
                 and type(terminal.get("iteration")) is int
                 and terminal["iteration"] == (last_iteration if rows else origin),
                 "has an inconsistent terminal iteration or reason")
        if reason == "morphospace_stable":
            _require(policy["mode"] == MORPHOSPACE_STABILITY and rows and rows[-1]["stable"],
                     "does not support the reported automatic stop")
            if long_window is not None and last_iteration - origin >= long_window:
                _require(rows[-1]["long_window"]["stable"],
                         "does not support the reported automatic stop over the longer window")
        if reason == "native_tolerance":
            _require(policy["mode"] == OPTIMIZER_CONVERGENCE,
                     "has a native tolerance stop in morphospace mode")
        digest = terminal.get("checkpoint_sha256")
        if rows or digest is not None or export == "complete":
            verify_artifact(EXECUTION_CHECKPOINT_PATH.relative_to("output").as_posix(), digest)

    if result is not None and result.get("status") == "completed":
        _require(terminal is not None and terminal["export"] == "complete",
                 "has no completed accepted-state export")
    verify_inventory_record(REPORT_NAME, len(payload), hashlib.sha256(payload).hexdigest())
    return report
