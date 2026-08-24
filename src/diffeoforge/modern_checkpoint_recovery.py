"""Prospective successors from abandoned Modern complete-cycle checkpoints."""

from __future__ import annotations

import csv
import json
import math
import shutil
import uuid
from datetime import UTC, datetime
from html import escape
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from diffeoforge.config import ConfigurationError
from diffeoforge.engine.execution import ENGINE_IMPLEMENTATION_VERSION
from diffeoforge.mesh import sha256_file
from diffeoforge.modern_bundle import verify_modern_atlas_bundle
from diffeoforge.modern_checkpoint import (
    CHECKPOINT_VERSION,
    verify_modern_cycle_checkpoint,
)
from diffeoforge.modern_checkpoint import (
    MANIFEST_NAME as CHECKPOINT_MANIFEST_NAME,
)
from diffeoforge.modern_workflow import (
    CONFIG_MARKER,
    _read_control_point_rows,
    _read_momenta_rows,
    validate_modern_workflow_config,
    verify_modern_workflow,
)
from diffeoforge.private_runs import MARKER_NAME, discover_private_runs

RECOVERY_VERSION = "0.2"
SUPPORTED_RECOVERY_VERSIONS = {"0.1", RECOVERY_VERSION}
PLAN_NAME = "modern-checkpoint-recovery.json"
SIDECAR_NAME = "modern-checkpoint-recovery.sha256"
HTML_NAME = "modern-checkpoint-recovery.html"
CONFIG_NAME = "modern-checkpoint-recovery.yaml"
SCIENTIFIC_BOUNDARY = (
    "A checkpoint recovery is a sequential successor from one abandoned private run, "
    "not an independent replicate or publication of the abandoned directory. It preserves "
    "the latest verified complete-cycle state and never recovers a partial cycle or in-memory "
    "line-search graph. It does not prove convergence, biological validity, or production "
    "suitability."
)


class ModernCheckpointRecoveryError(RuntimeError):
    """Raised when an abandoned Modern checkpoint cannot be recovered safely."""


def _write_json_exclusive(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
        handle.write("\n")


def _copy_exclusive(source: Path, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as input_handle, destination.open("xb") as output_handle:
        shutil.copyfileobj(input_handle, output_handle)
    return destination


def _artifact(root: Path, path: Path) -> dict[str, object]:
    return {
        "path": path.relative_to(root).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def _safe_path(root: Path, value: object, label: str, *, directory: bool = False) -> Path:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ModernCheckpointRecoveryError(f"{label} is not a POSIX-style path")
    relative = PurePosixPath(value)
    if relative.is_absolute() or "." in relative.parts or ".." in relative.parts:
        raise ModernCheckpointRecoveryError(f"{label} is unsafe: {value!r}")
    path = root.joinpath(*relative.parts)
    try:
        resolved = path.resolve(strict=True)
    except OSError as error:
        raise ModernCheckpointRecoveryError(f"{label} cannot be resolved: {value}") from error
    if not resolved.is_relative_to(root):
        raise ModernCheckpointRecoveryError(f"{label} escapes the recovery directory")
    valid = path.is_dir() if directory else path.is_file()
    if not valid or path.is_symlink():
        kind = "directory" if directory else "file"
        raise ModernCheckpointRecoveryError(f"{label} {kind} is missing or symbolic: {value}")
    return path


def _copy_tree(source: Path, destination: Path) -> None:
    if not source.is_dir() or source.is_symlink():
        raise ModernCheckpointRecoveryError("Checkpoint source is not a real directory")
    for path in sorted(source.rglob("*")):
        if path.is_symlink():
            raise ModernCheckpointRecoveryError("Checkpoint source contains a symbolic link")
        if path.is_file():
            _copy_exclusive(path, destination / path.relative_to(source))


def _render_html(plan: dict[str, Any]) -> str:
    subjects = "".join(
        f"<li><code>{escape(record['label'])}</code></li>" for record in plan["subjects"]
    )
    return f"""<!doctype html><html lang="en"><meta charset="utf-8">
<title>Modern checkpoint recovery plan</title>
<style>body{{font:16px system-ui;max-width:960px;margin:2rem auto;line-height:1.45}}
code{{overflow-wrap:anywhere}}.warning{{padding:1rem;background:#fff4ce}}</style>
<h1>Prospective Modern checkpoint recovery</h1>
<p class="warning">{escape(plan["scientific_boundary"])}</p>
<p>Status: <strong>{escape(plan["status"])}</strong></p>
<p>Abandoned private source: <code>{escape(plan["source"]["private_directory"])}</code></p>
<p>Recovered complete cycle: {plan["source"]["checkpoint_cycle"]} of
{plan["source"]["original_cycle_cap"]}.</p>
<p>Successor cycle cap: {plan["continuation"]["max_cycles"]}.</p>
<h2>Subjects ({len(plan["subjects"])})</h2><ol>{subjects}</ol>
<p>Frozen config: <code>{escape(plan["config"]["path"])}</code></p>
</html>\n"""


def _abandoned_private_directory(path: Path) -> dict[str, Any]:
    marker_path = path / MARKER_NAME
    try:
        marker = json.loads(marker_path.read_text(encoding="utf-8", errors="strict"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ModernCheckpointRecoveryError(
            f"Abandoned private-run marker is unreadable: {error}"
        ) from error
    if (
        not isinstance(marker, dict)
        or not isinstance(marker.get("destination"), str)
        or marker.get("operation") != "modern_workflow"
    ):
        raise ModernCheckpointRecoveryError("Abandoned private-run marker is invalid")
    discovery = discover_private_runs(marker["destination"])
    matching = [candidate for candidate in discovery.candidates if candidate.path == path]
    if len(matching) != 1 or matching[0].status != "abandoned":
        status = "not found" if not matching else matching[0].status
        raise ModernCheckpointRecoveryError(
            f"Private run is not a verified abandoned candidate: {status}"
        )
    return marker


def create_modern_checkpoint_recovery(
    private_directory: Path | str,
    destination: Path | str,
    *,
    max_cycles: int | None = None,
    threads: int | None = None,
    created_at: str | None = None,
) -> Path:
    """Freeze a no-results-yet successor from the latest abandoned checkpoint."""

    if max_cycles is not None and (
        isinstance(max_cycles, bool) or not isinstance(max_cycles, int) or max_cycles < 0
    ):
        raise ValueError("max_cycles must be an integer of at least 0 or None")
    if threads is not None and (
        isinstance(threads, bool) or not isinstance(threads, int) or threads < 1
    ):
        raise ValueError("threads must be an integer of at least 1 or None")
    private = Path(private_directory).expanduser().resolve()
    _abandoned_private_directory(private)
    checkpoint_roots = sorted(
        (private / "checkpoints").glob("cycle-[0-9][0-9][0-9][0-9][0-9][0-9]")
    )
    if not checkpoint_roots:
        raise ModernCheckpointRecoveryError("Abandoned private run has no cycle checkpoint")
    checkpoints = [
        verify_modern_cycle_checkpoint(path, workflow_root=private) for path in checkpoint_roots
    ]
    checkpoint_cycles = [checkpoint["cycle"] for checkpoint in checkpoints]
    if checkpoint_cycles != sorted(set(checkpoint_cycles)):
        raise ModernCheckpointRecoveryError("Abandoned checkpoint cycle sequence is invalid")
    checkpoint_root = checkpoint_roots[-1]
    checkpoint = checkpoints[-1]
    if checkpoint["checkpoint_version"] != CHECKPOINT_VERSION:
        raise ModernCheckpointRecoveryError(
            "Checkpoint predates exact L-BFGS and objective-baseline serialization"
        )
    binding = checkpoint["binding"]
    if binding["engine_implementation"] != ENGINE_IMPLEMENTATION_VERSION:
        raise ModernCheckpointRecoveryError(
            "Recovery requires the same Modern engine implementation as the checkpoint"
        )
    effective_source = _safe_path(
        private,
        binding["effective_config"]["path"],
        "Bound effective config",
    )
    try:
        effective = json.loads(effective_source.read_text(encoding="utf-8", errors="strict"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ModernCheckpointRecoveryError(f"Effective config is unreadable: {error}") from error
    if not isinstance(effective, dict):
        raise ModernCheckpointRecoveryError("Effective config is not an object")
    validate_modern_workflow_config(effective)
    interval = int(effective["optimization"].get("checkpoint_interval_cycles", 1))
    retention = str(effective["optimization"].get("checkpoint_retention", "all"))
    if retention == "all":
        expected_checkpoint_cycles = [
            cycle for cycle in range(1, checkpoint["cycle"] + 1) if cycle % interval == 0
        ]
        if (
            checkpoint["cycle"] == binding["max_cycles"]
            or checkpoint["optimizer_state"]["completed_cycle_termination_reason"] is not None
        ) and checkpoint["cycle"] not in expected_checkpoint_cycles:
            expected_checkpoint_cycles.append(checkpoint["cycle"])
        if checkpoint_cycles != expected_checkpoint_cycles:
            raise ModernCheckpointRecoveryError(
                "Abandoned checkpoint cycle sequence differs from its persistence policy"
            )
    if threads is not None and threads != int(effective["runtime"]["threads"]):
        raise ModernCheckpointRecoveryError(
            "Exact recovery requires the source thread count; --threads may only repeat it"
        )
    remaining = int(binding["max_cycles"]) - int(checkpoint["cycle"])
    successor_cycles = max(0, remaining) if max_cycles is None else max_cycles

    output = Path(destination).expanduser().resolve()
    if output.exists():
        raise FileExistsError(f"Modern recovery destination exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.parent / f".{output.name}.tmp-{uuid.uuid4().hex}"
    temporary.mkdir()
    try:
        embedded_checkpoint = temporary / "lineage" / "checkpoint"
        _copy_tree(checkpoint_root, embedded_checkpoint)
        source_config = _safe_path(
            private,
            binding["source_config"]["path"],
            "Bound source config",
        )
        source_copy = _copy_exclusive(source_config, temporary / "lineage" / "source.yaml")
        effective_copy = _copy_exclusive(
            effective_source,
            temporary / "lineage" / "effective.json",
        )
        template_input = _safe_path(
            private,
            binding["template_input"]["path"],
            "Bound template input",
        )
        template_input_copy = _copy_exclusive(
            template_input,
            temporary / "lineage" / "template-input.vtk",
        )
        subject_records = []
        for record in binding["subjects"]:
            label = record["label"]
            if Path(label).name != label or label in {".", ".."}:
                raise ModernCheckpointRecoveryError(f"Unsafe subject label: {label!r}")
            subject = _safe_path(private, record["path"], f"Bound subject {label}")
            copied = _copy_exclusive(subject, temporary / "inputs" / "subjects" / label)
            subject_records.append({"label": label, "effective_mesh": _artifact(temporary, copied)})

        embedded = verify_modern_cycle_checkpoint(embedded_checkpoint)
        state = embedded["state"]
        _safe_path(
            embedded_checkpoint,
            state["template"]["path"],
            "Embedded checkpoint template",
        )
        checkpoint_controls = _safe_path(
            embedded_checkpoint,
            state["control_points"]["path"],
            "Embedded checkpoint controls",
        )
        checkpoint_momenta = _safe_path(
            embedded_checkpoint,
            state["momenta"]["path"],
            "Embedded checkpoint momenta",
        )
        labels = tuple(record["label"] for record in subject_records)
        _read_control_point_rows(checkpoint_controls, int(state["control_points"]["count"]))
        _read_momenta_rows(
            checkpoint_momenta,
            labels,
            int(state["control_points"]["count"]),
        )
        config = json.loads(json.dumps(effective, allow_nan=False))
        config["schema_version"] = "0.5"
        config["project"]["name"] = f"{config['project']['name']}-checkpoint-recovery"
        config["input"] = {
            "directory": "inputs/subjects",
            "subject_pattern": "*.vtk",
            "template": state["template"]["path"].replace("state/", "lineage/checkpoint/state/"),
            "units": effective["input"]["units"],
        }
        config["preprocessing"]["procrustes"] = {
            "enabled": False,
            "landmarks_file": None,
            "scale_to_unit_centroid_size": True,
            "allow_reflection": False,
            "tolerance": 1e-10,
            "max_iterations": 100,
        }
        config["initialization"] = {
            "control_points": {
                "method": "file",
                "count": int(state["control_points"]["count"]),
                "path": state["control_points"]["path"].replace(
                    "state/", "lineage/checkpoint/state/"
                ),
            },
            "momenta": {
                "method": "file",
                "path": state["momenta"]["path"].replace("state/", "lineage/checkpoint/state/"),
            },
        }
        config["optimization"]["max_cycles"] = successor_cycles
        config["optimization"]["resume_state"] = {
            "checkpoint_directory": "lineage/checkpoint",
            "checkpoint_manifest_sha256": sha256_file(
                embedded_checkpoint / CHECKPOINT_MANIFEST_NAME
            ),
            "source_effective_config": "lineage/effective.json",
            "source_effective_config_sha256": sha256_file(effective_copy),
        }
        successor_output = output.parent / f"{output.name}-modern-run"
        config["output"]["directory"] = str(successor_output)
        validate_modern_workflow_config(config)
        config_path = temporary / CONFIG_NAME
        with config_path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(CONFIG_MARKER + "\n")
            yaml.safe_dump(config, handle, sort_keys=False, allow_unicode=True)

        plan: dict[str, Any] = {
            "recovery_version": RECOVERY_VERSION,
            "created_at": created_at or datetime.now(UTC).isoformat(),
            "status": "prospective_no_successor_result",
            "source": {
                "private_directory": str(private),
                "private_marker_sha256": sha256_file(private / MARKER_NAME),
                "checkpoint_cycle": int(checkpoint["cycle"]),
                "checkpoint_manifest_sha256": sha256_file(
                    checkpoint_root / CHECKPOINT_MANIFEST_NAME
                ),
                "original_cycle_cap": int(binding["max_cycles"]),
                "checkpoint_objective": float(checkpoint["record"]["objective"]),
            },
            "lineage": {
                "checkpoint_path": "lineage/checkpoint",
                "source_config": _artifact(temporary, source_copy),
                "effective_config": _artifact(temporary, effective_copy),
                "template_input": _artifact(temporary, template_input_copy),
            },
            "subjects": subject_records,
            "continuation": {
                "max_cycles": successor_cycles,
                "step_initialization": config["optimization"]["step_initialization"],
                "initial_step_sizes": checkpoint["optimizer_state"]["next_step_sizes"],
            },
            "config": {
                "path": CONFIG_NAME,
                "sha256": sha256_file(config_path),
                "expected_destination": str(successor_output),
                "expected_engine_implementation": binding["engine_implementation"],
            },
            "scientific_boundary": SCIENTIFIC_BOUNDARY,
        }
        html_path = temporary / HTML_NAME
        html_path.write_text(_render_html(plan), encoding="utf-8", newline="\n")
        inventory = sorted(
            path
            for path in temporary.rglob("*")
            if path.is_file() and path not in {temporary / PLAN_NAME, temporary / SIDECAR_NAME}
        )
        plan["artifacts"] = [_artifact(temporary, path) for path in inventory]
        plan_path = temporary / PLAN_NAME
        _write_json_exclusive(plan_path, plan)
        (temporary / SIDECAR_NAME).write_text(
            f"{sha256_file(plan_path)}  {PLAN_NAME}\n",
            encoding="ascii",
            newline="\n",
        )
        verify_modern_checkpoint_recovery(temporary)
        temporary.rename(output)
    except Exception:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise
    return output


def verify_modern_checkpoint_recovery(directory: Path | str) -> dict[str, Any]:
    """Verify a frozen recovery plan without relying on the abandoned source."""

    root = Path(directory).expanduser().resolve()
    plan_path = root / PLAN_NAME
    sidecar = root / SIDECAR_NAME
    if root.is_symlink() or not root.is_dir() or not plan_path.is_file() or not sidecar.is_file():
        raise ModernCheckpointRecoveryError("Modern recovery plan files are missing")
    if any(path.is_symlink() for path in root.rglob("*")):
        raise ModernCheckpointRecoveryError("Modern recovery plans must not contain symbolic links")
    expected_sidecar = f"{sha256_file(plan_path)}  {PLAN_NAME}"
    if sidecar.read_text(encoding="ascii").strip() != expected_sidecar:
        raise ModernCheckpointRecoveryError("Modern recovery plan sidecar differs")
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8", errors="strict"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ModernCheckpointRecoveryError(
            f"Modern recovery plan is unreadable: {error}"
        ) from error
    if not isinstance(plan, dict) or set(plan) != {
        "recovery_version",
        "created_at",
        "status",
        "source",
        "lineage",
        "subjects",
        "continuation",
        "config",
        "scientific_boundary",
        "artifacts",
    }:
        raise ModernCheckpointRecoveryError("Modern recovery plan fields differ")
    if (
        plan["recovery_version"] not in SUPPORTED_RECOVERY_VERSIONS
        or plan["status"] != "prospective_no_successor_result"
        or plan["scientific_boundary"] != SCIENTIFIC_BOUNDARY
    ):
        raise ModernCheckpointRecoveryError("Modern recovery plan identity differs")
    declared: set[str] = set()
    for record in plan["artifacts"]:
        path = _safe_path(root, record.get("path"), "Recovery artifact")
        relative = path.relative_to(root).as_posix()
        if relative in declared:
            raise ModernCheckpointRecoveryError("Modern recovery artifact is duplicated")
        declared.add(relative)
        if path.stat().st_size != record.get("bytes") or sha256_file(path) != record.get("sha256"):
            raise ModernCheckpointRecoveryError(f"Modern recovery artifact differs: {relative}")
    actual = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path not in {plan_path, sidecar}
    }
    if actual != declared:
        raise ModernCheckpointRecoveryError("Modern recovery artifact inventory differs")
    checkpoint_root = root / plan["lineage"]["checkpoint_path"]
    checkpoint = verify_modern_cycle_checkpoint(checkpoint_root)
    if (
        plan["recovery_version"] == RECOVERY_VERSION
        and checkpoint["checkpoint_version"] != CHECKPOINT_VERSION
    ):
        raise ModernCheckpointRecoveryError("Embedded checkpoint version differs")
    if (
        checkpoint["cycle"] != plan["source"]["checkpoint_cycle"]
        or sha256_file(checkpoint_root / CHECKPOINT_MANIFEST_NAME)
        != plan["source"]["checkpoint_manifest_sha256"]
        or checkpoint["binding"]["engine_implementation"]
        != plan["config"]["expected_engine_implementation"]
    ):
        raise ModernCheckpointRecoveryError("Embedded checkpoint lineage differs")
    binding = checkpoint["binding"]
    for name in ("source_config", "effective_config", "template_input"):
        copied = _safe_path(root, plan["lineage"][name]["path"], f"Recovery {name}")
        if (
            _artifact(root, copied) != plan["lineage"][name]
            or sha256_file(copied) != binding[name]["sha256"]
        ):
            raise ModernCheckpointRecoveryError(f"Recovery lineage differs: {name}")
    labels = tuple(record["label"] for record in plan["subjects"])
    if labels != tuple(record["label"] for record in binding["subjects"]):
        raise ModernCheckpointRecoveryError("Recovery subject identity/order differs")
    for record, bound in zip(plan["subjects"], binding["subjects"], strict=True):
        subject = _safe_path(root, record["effective_mesh"]["path"], "Recovery subject")
        if (
            _artifact(root, subject) != record["effective_mesh"]
            or sha256_file(subject) != bound["sha256"]
        ):
            raise ModernCheckpointRecoveryError(f"Recovery subject differs: {record['label']}")
    config_path = _safe_path(root, plan["config"]["path"], "Recovery config")
    if sha256_file(config_path) != plan["config"]["sha256"]:
        raise ModernCheckpointRecoveryError("Modern recovery config hash differs")
    try:
        config = yaml.safe_load(config_path.read_text(encoding="utf-8", errors="strict"))
        validate_modern_workflow_config(config)
    except (OSError, UnicodeError, yaml.YAMLError, ConfigurationError) as error:
        raise ModernCheckpointRecoveryError(
            f"Modern recovery config is invalid: {error}"
        ) from error
    state = checkpoint["state"]
    blocks = tuple(checkpoint["binding"]["block_order"])
    declared_steps = plan["continuation"].get("initial_step_sizes")
    is_exact_state = plan["recovery_version"] == RECOVERY_VERSION
    expected_schema_version = "0.5" if is_exact_state else "0.4"
    if (
        config["schema_version"] != expected_schema_version
        or config["input"]["directory"] != "inputs/subjects"
        or config["input"]["subject_pattern"] != "*.vtk"
        or config["input"]["template"]
        != state["template"]["path"].replace("state/", "lineage/checkpoint/state/")
        or config["preprocessing"]["procrustes"]["enabled"] is not False
        or config["initialization"]["control_points"]["path"]
        != state["control_points"]["path"].replace("state/", "lineage/checkpoint/state/")
        or config["initialization"]["control_points"]["count"] != state["control_points"]["count"]
        or config["initialization"]["momenta"]["path"]
        != state["momenta"]["path"].replace("state/", "lineage/checkpoint/state/")
        or config["output"]["directory"] != plan["config"]["expected_destination"]
        or config["optimization"]["max_cycles"] != plan["continuation"]["max_cycles"]
        or config["optimization"]["block_order"] != list(blocks)
        or config["optimization"].get("momenta_updates_per_cycle", 1)
        != binding.get("momenta_updates_per_cycle", 1)
        or config["optimization"]["step_initialization"]
        != plan["continuation"]["step_initialization"]
        or declared_steps != checkpoint["optimizer_state"]["next_step_sizes"]
    ):
        raise ModernCheckpointRecoveryError("Modern recovery config semantics differ")
    if is_exact_state:
        expected_resume = {
            "checkpoint_directory": plan["lineage"]["checkpoint_path"],
            "checkpoint_manifest_sha256": plan["source"]["checkpoint_manifest_sha256"],
            "source_effective_config": plan["lineage"]["effective_config"]["path"],
            "source_effective_config_sha256": plan["lineage"]["effective_config"]["sha256"],
        }
        if config["optimization"].get("resume_state") != expected_resume:
            raise ModernCheckpointRecoveryError("Modern recovery resume state differs")
    elif any(
        config["optimization"][f"{block}_step_size"] != declared_steps[block] for block in blocks
    ):
        raise ModernCheckpointRecoveryError("Modern recovery legacy step state differs")
    observed_html = (root / HTML_NAME).read_text(encoding="utf-8", errors="strict")
    if observed_html != _render_html(plan):
        raise ModernCheckpointRecoveryError("Modern recovery HTML differs")
    return plan


def verify_modern_checkpoint_recovery_run(
    plan_directory: Path | str,
    successor_run: Path | str,
) -> dict[str, Any]:
    """Verify a successor and its initial objective against the recovered checkpoint."""

    plan_root = Path(plan_directory).expanduser().resolve()
    plan = verify_modern_checkpoint_recovery(plan_root)
    run_root = Path(successor_run).expanduser().resolve()
    workflow = verify_modern_workflow(run_root)
    source_config = _safe_path(run_root, workflow["config"]["source_path"], "Run source config")
    if sha256_file(source_config) != plan["config"]["sha256"]:
        raise ModernCheckpointRecoveryError("Recovery run source config differs")
    if workflow["engine"].get("implementation_version") != plan["config"].get(
        "expected_engine_implementation"
    ):
        raise ModernCheckpointRecoveryError("Recovery run engine implementation differs")
    bundle_root = _safe_path(
        run_root,
        workflow["result_bundle"]["path"],
        "Recovery run bundle",
        directory=True,
    )
    bundle = verify_modern_atlas_bundle(bundle_root)
    labels = tuple(record["label"] for record in bundle["subjects"])
    if labels != tuple(record["label"] for record in plan["subjects"]):
        raise ModernCheckpointRecoveryError("Recovery run subject identity/order differs")
    history = _safe_path(
        bundle_root,
        bundle["optimizer"]["history_path"],
        "Recovery optimizer history",
    )
    try:
        with history.open(encoding="utf-8", errors="strict", newline="") as handle:
            reader = csv.DictReader(handle)
            first = next(reader)
    except (OSError, UnicodeError, csv.Error, StopIteration) as error:
        raise ModernCheckpointRecoveryError(
            f"Recovery optimizer history is unreadable: {error}"
        ) from error
    if first.get("cycle") != "0" or first.get("status") != "initial":
        raise ModernCheckpointRecoveryError("Recovery optimizer history has no initial row")
    try:
        initial_objective = float(first["objective"])
    except (KeyError, TypeError, ValueError) as error:
        raise ModernCheckpointRecoveryError(
            "Recovery optimizer initial objective is invalid"
        ) from error
    checkpoint_objective = float(plan["source"]["checkpoint_objective"])
    tolerance = max(1e-12, abs(checkpoint_objective) * 1e-12)
    if not math.isclose(
        initial_objective,
        checkpoint_objective,
        rel_tol=1e-12,
        abs_tol=tolerance,
    ):
        raise ModernCheckpointRecoveryError(
            "Recovery run initial objective differs from the checkpoint"
        )
    return {
        "plan": plan,
        "workflow": workflow,
        "bundle": bundle,
        "initial_objective": initial_objective,
        "checkpoint_objective": checkpoint_objective,
        "initial_objective_matches": True,
    }
