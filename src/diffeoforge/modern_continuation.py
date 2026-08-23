"""Prospective, hash-bound continuation plans for completed Modern workflows."""

from __future__ import annotations

import csv
import json
import math
import re
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
from diffeoforge.modern_bundle import MANIFEST_NAME as BUNDLE_MANIFEST_NAME
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
    pairwise_evaluation_from_config,
    validate_modern_workflow_config,
    verify_modern_workflow,
)
from diffeoforge.modern_workflow import (
    MANIFEST_NAME as WORKFLOW_MANIFEST_NAME,
)

PLAN_VERSION = "0.2"
SUPPORTED_PLAN_VERSIONS = {"0.1", PLAN_VERSION}
PLAN_NAME = "modern-continuation-plan.json"
PLAN_SIDECAR_NAME = "modern-continuation-plan.sha256"
PLAN_HTML_NAME = "modern-continuation-plan.html"
CONFIG_NAME = "modern-continuation.yaml"
SCIENTIFIC_BOUNDARY = (
    "A Modern continuation is a sequential optimization successor, not an independent "
    "replicate. It preserves and hash-binds the verified parent's effective targets, "
    "final template, final control points, final momenta, model, and runtime plan. It "
    "does not prove convergence, optimizer equivalence, biological validity, GPU parity, "
    "or production suitability."
)


class ModernContinuationError(RuntimeError):
    """Raised when a Modern continuation cannot be frozen or verified safely."""


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


def _copy_tree(source: Path, destination: Path) -> Path:
    if (
        source.is_symlink()
        or not source.is_dir()
        or any(path.is_symlink() for path in source.rglob("*"))
    ):
        raise ModernContinuationError("Continuation checkpoint source is invalid or symbolic")
    shutil.copytree(source, destination)
    return destination


def _artifact(root: Path, path: Path) -> dict[str, object]:
    return {
        "path": path.relative_to(root).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def _safe_path(root: Path, value: object, label: str, *, directory: bool = False) -> Path:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ModernContinuationError(f"{label} is not a POSIX-style path")
    relative = PurePosixPath(value)
    if relative.is_absolute() or "." in relative.parts or ".." in relative.parts:
        raise ModernContinuationError(f"{label} is unsafe: {value!r}")
    path = root.joinpath(*relative.parts)
    try:
        resolved = path.resolve(strict=True)
    except OSError as error:
        raise ModernContinuationError(f"{label} cannot be resolved: {value}") from error
    if not resolved.is_relative_to(root):
        raise ModernContinuationError(f"{label} escapes the continuation directory")
    valid = path.is_dir() if directory else path.is_file()
    if not valid or path.is_symlink():
        kind = "directory" if directory else "file"
        raise ModernContinuationError(f"{label} {kind} is missing or symbolic: {value}")
    return path


def _json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8", errors="strict"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ModernContinuationError(f"{label} is unreadable JSON: {error}") from error
    if not isinstance(value, dict):
        raise ModernContinuationError(f"{label} must be a JSON object")
    return value


def _control_point_rows(path: Path, expected_count: int) -> tuple[tuple[str, str, str], ...]:
    try:
        with path.open(encoding="utf-8", errors="strict", newline="") as handle:
            rows = list(csv.reader(handle))
    except (OSError, UnicodeError, csv.Error) as error:
        raise ModernContinuationError(f"Control-point CSV is unreadable: {error}") from error
    if not rows or rows[0] != ["control_point", "x", "y", "z"]:
        raise ModernContinuationError("Control-point CSV header differs")
    if len(rows) - 1 != expected_count:
        raise ModernContinuationError("Control-point CSV row count differs")
    values: list[tuple[str, str, str]] = []
    for index, row in enumerate(rows[1:]):
        if len(row) != 4 or row[0] != str(index):
            raise ModernContinuationError(
                f"Control-point CSV index/order differs at row {index + 2}"
            )
        try:
            point = tuple(float(value) for value in row[1:])
        except ValueError as error:
            raise ModernContinuationError(
                f"Control-point CSV row {index + 2} contains a non-number"
            ) from error
        if not all(math.isfinite(value) for value in point):
            raise ModernContinuationError(
                f"Control-point CSV row {index + 2} contains a non-finite value"
            )
        values.append((row[1], row[2], row[3]))
    return tuple(values)


def _write_control_points(path: Path, rows: tuple[tuple[str, str, str], ...]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(" ".join(row) + "\n")
    return path


def _history(path: Path) -> tuple[dict[str, str], ...]:
    try:
        with path.open(encoding="utf-8", errors="strict", newline="") as handle:
            reader = csv.DictReader(handle)
            rows = tuple(dict(row) for row in reader)
    except (OSError, UnicodeError, csv.Error) as error:
        raise ModernContinuationError(f"Optimizer history is unreadable: {error}") from error
    required = {
        "cycle",
        "block",
        "status",
        "objective",
        "accepted_step_size",
        "line_search_evaluations",
    }
    if not rows or reader.fieldnames is None or not required <= set(reader.fieldnames):
        raise ModernContinuationError("Optimizer history columns are incomplete")
    if rows[0]["cycle"] != "0" or rows[0]["status"] != "initial":
        raise ModernContinuationError("Optimizer history does not begin with its initial state")
    return rows


def _last_steps(settings: dict[str, Any], rows: tuple[dict[str, str], ...]) -> dict[str, float]:
    blocks = tuple(settings["block_order"])
    steps = {block: float(settings[f"{block}_step_size"]) for block in blocks}
    for row in rows:
        block = row["block"]
        value = row["accepted_step_size"]
        if row["status"] == "accepted" and block in steps and value:
            step = float(value)
            if not math.isfinite(step) or step <= 0:
                raise ModernContinuationError("Optimizer history contains an invalid step")
            steps[block] = step
    return steps


def _render_html(plan: dict[str, Any]) -> str:
    subjects = "".join(
        f"<li><code>{escape(record['label'])}</code></li>" for record in plan["subjects"]
    )
    steps = "".join(
        f"<li><code>{escape(block)}</code>: "
        f"{plan['continuation']['initial_step_sizes'][block]:.12g}</li>"
        for block in plan["continuation"]["optimized_blocks"]
    )
    return f"""<!doctype html><html lang="en"><meta charset="utf-8">
<title>Modern atlas continuation plan</title>
<style>body{{font:16px system-ui;max-width:960px;margin:2rem auto;line-height:1.45}}
code{{overflow-wrap:anywhere}}.warning{{padding:1rem;background:#fff4ce}}</style>
<h1>Prospective Modern atlas continuation</h1>
<p class="warning">{escape(plan["scientific_boundary"])}</p>
<p>Status: <strong>{escape(plan["status"])}</strong></p>
<p>Parent termination: <code>{escape(plan["parent"]["termination_reason"])}</code> after
{plan["parent"]["cycles_completed"]} cycle(s).</p>
<p>Successor cycle cap: {plan["continuation"]["max_cycles"]}; strategy:
<code>{escape(plan["continuation"]["step_initialization"])}</code>.</p>
<h2>Derived initial step sizes</h2><ul>{steps}</ul>
<h2>Subjects ({len(plan["subjects"])})</h2><ol>{subjects}</ol>
<p>Frozen config: <code>{escape(plan["config"]["path"])}</code></p>
</html>\n"""


def create_modern_continuation(
    parent_run: Path | str,
    destination: Path | str,
    *,
    max_cycles: int = 10,
    threads: int | None = None,
    created_at: str | None = None,
) -> Path:
    """Freeze a no-results-yet successor from one verified, non-converged run."""

    if isinstance(max_cycles, bool) or not isinstance(max_cycles, int) or max_cycles < 1:
        raise ValueError("max_cycles must be an integer of at least 1")
    if threads is not None and (
        isinstance(threads, bool) or not isinstance(threads, int) or threads < 1
    ):
        raise ValueError("threads must be an integer of at least 1 or None")
    parent_root = Path(parent_run).expanduser().resolve()
    workflow = verify_modern_workflow(parent_root)
    bundle_root = _safe_path(
        parent_root,
        workflow["result_bundle"]["path"],
        "Parent bundle",
        directory=True,
    )
    bundle = verify_modern_atlas_bundle(bundle_root)
    if bundle["optimizer"]["converged"]:
        raise ModernContinuationError(
            "Parent Modern optimizer already converged; continuation is not required"
        )
    effective_path = _safe_path(
        parent_root,
        workflow["config"]["effective_path"],
        "Parent effective config",
    )
    effective = _json_object(effective_path, "Parent effective config")
    settings = dict(bundle["optimizer"]["settings"])
    completed_cycles = int(bundle["optimizer"]["cycles_completed"])
    checkpoint_records = workflow.get("optimizer_checkpoints", [])
    if (
        completed_cycles < 1
        or not checkpoint_records
        or checkpoint_records[-1]["cycle"] != completed_cycles
    ):
        raise ModernContinuationError(
            "Parent run has no final complete-cycle checkpoint for exact continuation"
        )
    checkpoint_root = _safe_path(
        parent_root,
        checkpoint_records[-1]["path"],
        "Parent final checkpoint",
        directory=True,
    )
    checkpoint = verify_modern_cycle_checkpoint(
        checkpoint_root,
        workflow_root=parent_root,
    )
    if checkpoint["checkpoint_version"] != CHECKPOINT_VERSION:
        raise ModernContinuationError(
            "Parent checkpoint predates exact L-BFGS and objective-baseline serialization"
        )
    if checkpoint["binding"]["engine_implementation"] != ENGINE_IMPLEMENTATION_VERSION:
        raise ModernContinuationError("Parent checkpoint engine implementation differs")
    last_steps = {
        block: float(value)
        for block, value in checkpoint["optimizer_state"]["next_step_sizes"].items()
    }
    labels = tuple(record["label"] for record in bundle["subjects"])
    workflow_labels = tuple(record["label"] for record in workflow["input"]["subjects"])
    if labels != workflow_labels:
        raise ModernContinuationError("Parent workflow and bundle subject order differs")
    control_count = int(checkpoint["state"]["control_points"]["count"])
    if threads is not None and threads != int(effective["runtime"]["threads"]):
        raise ModernContinuationError(
            "Exact continuation requires the parent thread count; --threads may only repeat it"
        )

    destination_path = Path(destination).expanduser().resolve()
    if destination_path.exists():
        raise FileExistsError(f"Modern continuation destination exists: {destination_path}")
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination_path.parent / f".{destination_path.name}.tmp-{uuid.uuid4().hex}"
    temporary.mkdir()
    try:
        embedded_checkpoint = _copy_tree(
            checkpoint_root,
            temporary / "lineage" / "checkpoint",
        )
        embedded = verify_modern_cycle_checkpoint(embedded_checkpoint)
        source_effective_copy = _copy_exclusive(
            effective_path,
            temporary / "lineage" / "source-effective-config.json",
        )
        state = embedded["state"]
        template_copy = _safe_path(
            embedded_checkpoint,
            state["template"]["path"],
            "Embedded checkpoint template",
        )
        control_copy = _safe_path(
            embedded_checkpoint,
            state["control_points"]["path"],
            "Embedded checkpoint controls",
        )
        momenta_copy = _safe_path(
            embedded_checkpoint,
            state["momenta"]["path"],
            "Embedded checkpoint momenta",
        )
        subject_records: list[dict[str, object]] = []
        for record in workflow["input"]["subjects"]:
            label = str(record["label"])
            if Path(label).name != label or label in {".", ".."}:
                raise ModernContinuationError(f"Unsafe parent subject label: {label!r}")
            source_value = record["aligned_path"] or record["raw_path"]
            source = _safe_path(parent_root, source_value, f"Parent subject {label}")
            copied = _copy_exclusive(source, temporary / "inputs" / "subjects" / label)
            subject_records.append({"label": label, "effective_mesh": _artifact(temporary, copied)})

        optimization = dict(effective["optimization"])
        optimization["max_cycles"] = max_cycles
        optimization["resume_state"] = {
            "checkpoint_directory": "lineage/checkpoint",
            "checkpoint_manifest_sha256": sha256_file(
                embedded_checkpoint / CHECKPOINT_MANIFEST_NAME
            ),
            "source_effective_config": "lineage/source-effective-config.json",
            "source_effective_config_sha256": sha256_file(source_effective_copy),
        }
        runtime = dict(effective["runtime"])
        runtime["pairwise_evaluation"] = pairwise_evaluation_from_config(effective).as_manifest()
        output = destination_path.parent / f"{destination_path.name}-modern-run"
        config = {
            "schema_version": "0.5",
            "project": {"name": f"{workflow['project']['name']}-continuation"},
            "input": {
                "directory": "inputs/subjects",
                "subject_pattern": "*.vtk",
                "template": template_copy.relative_to(temporary).as_posix(),
                "units": workflow["input"]["units"],
            },
            "preprocessing": {
                "procrustes": {
                    "enabled": False,
                    "landmarks_file": None,
                    "scale_to_unit_centroid_size": True,
                    "allow_reflection": False,
                    "tolerance": 1e-10,
                    "max_iterations": 100,
                }
            },
            "quality_control": effective["quality_control"],
            "initialization": {
                "control_points": {
                    "method": "file",
                    "count": control_count,
                    "path": control_copy.relative_to(temporary).as_posix(),
                },
                "momenta": {
                    "method": "file",
                    "path": momenta_copy.relative_to(temporary).as_posix(),
                },
            },
            "model": effective["model"],
            "optimization": optimization,
            "analysis": effective["analysis"],
            "runtime": runtime,
            "output": {"directory": str(output)},
        }
        validate_modern_workflow_config(config)
        config_path = temporary / CONFIG_NAME
        with config_path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(CONFIG_MARKER + "\n")
            yaml.safe_dump(config, handle, sort_keys=False, allow_unicode=True)

        plan: dict[str, Any] = {
            "plan_version": PLAN_VERSION,
            "created_at": created_at or datetime.now(UTC).isoformat(),
            "status": "prospective_no_successor_result",
            "parent": {
                "run_directory": str(parent_root),
                "workflow_manifest_sha256": sha256_file(parent_root / WORKFLOW_MANIFEST_NAME),
                "bundle_manifest_sha256": sha256_file(bundle_root / BUNDLE_MANIFEST_NAME),
                "termination_reason": bundle["optimizer"]["termination_reason"],
                "converged": False,
                "cycles_completed": bundle["optimizer"]["cycles_completed"],
                "final_objective": bundle["optimizer"]["final_objective"],
            },
            "initial_state": {
                "template": _artifact(temporary, template_copy),
                "control_points": _artifact(temporary, control_copy),
                "momenta": _artifact(temporary, momenta_copy),
                "control_point_count": control_count,
                "dimensions": 3,
            },
            "optimizer_state": {
                "checkpoint_path": embedded_checkpoint.relative_to(temporary).as_posix(),
                "checkpoint_manifest_sha256": sha256_file(
                    embedded_checkpoint / CHECKPOINT_MANIFEST_NAME
                ),
                "source_effective_config": _artifact(temporary, source_effective_copy),
            },
            "subjects": subject_records,
            "continuation": {
                "max_cycles": max_cycles,
                "optimized_blocks": list(settings["block_order"]),
                "step_initialization": optimization.get("step_initialization", "fixed"),
                "initial_step_sizes": last_steps,
                "step_derivation": "exact values serialized in the final cycle checkpoint",
            },
            "config": {
                "path": CONFIG_NAME,
                "sha256": sha256_file(config_path),
                "expected_destination": str(output),
                "expected_engine_implementation": ENGINE_IMPLEMENTATION_VERSION,
            },
            "scientific_boundary": SCIENTIFIC_BOUNDARY,
        }
        html_path = temporary / PLAN_HTML_NAME
        html_path.write_text(_render_html(plan), encoding="utf-8", newline="\n")
        inventory = sorted(
            path
            for path in temporary.rglob("*")
            if path.is_file() and path not in {temporary / PLAN_NAME, temporary / PLAN_SIDECAR_NAME}
        )
        plan["artifacts"] = [_artifact(temporary, path) for path in inventory]
        plan_path = temporary / PLAN_NAME
        _write_json_exclusive(plan_path, plan)
        (temporary / PLAN_SIDECAR_NAME).write_text(
            f"{sha256_file(plan_path)}  {PLAN_NAME}\n",
            encoding="ascii",
            newline="\n",
        )
        verify_modern_continuation(temporary)
        temporary.rename(destination_path)
    except Exception:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise
    return destination_path


def verify_modern_continuation(directory: Path | str) -> dict[str, Any]:
    """Verify a frozen continuation plan without reading its live parent run."""

    root = Path(directory).expanduser().resolve()
    plan_path = root / PLAN_NAME
    sidecar_path = root / PLAN_SIDECAR_NAME
    if not root.is_dir() or root.is_symlink() or not plan_path.is_file():
        raise ModernContinuationError("Modern continuation plan is missing or symbolic")
    expected_sidecar = f"{sha256_file(plan_path)}  {PLAN_NAME}"
    if (
        not sidecar_path.is_file()
        or sidecar_path.read_text(encoding="ascii").strip() != expected_sidecar
    ):
        raise ModernContinuationError("Modern continuation sidecar differs")
    plan = _json_object(plan_path, "Modern continuation plan")
    plan_version = plan.get("plan_version")
    expected_fields = {
        "plan_version",
        "created_at",
        "status",
        "parent",
        "initial_state",
        "subjects",
        "continuation",
        "config",
        "scientific_boundary",
        "artifacts",
    }
    if plan_version == PLAN_VERSION:
        expected_fields.add("optimizer_state")
    if set(plan) != expected_fields:
        raise ModernContinuationError("Modern continuation top-level fields differ")
    if (
        plan_version not in SUPPORTED_PLAN_VERSIONS
        or plan["status"] != "prospective_no_successor_result"
        or plan["parent"].get("converged") is not False
    ):
        raise ModernContinuationError("Modern continuation identity differs")
    declared: set[str] = set()
    for record in plan["artifacts"]:
        path = _safe_path(root, record.get("path"), "Continuation artifact")
        relative = path.relative_to(root).as_posix()
        if relative in declared:
            raise ModernContinuationError(f"Duplicate continuation artifact: {relative}")
        declared.add(relative)
        if path.stat().st_size != record.get("bytes") or sha256_file(path) != record.get("sha256"):
            raise ModernContinuationError(f"Continuation artifact differs: {relative}")
    actual = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path not in {root / PLAN_NAME, root / PLAN_SIDECAR_NAME}
    }
    if actual != declared:
        raise ModernContinuationError("Modern continuation artifact inventory differs")
    config_path = _safe_path(root, plan["config"]["path"], "Continuation config")
    if sha256_file(config_path) != plan["config"]["sha256"]:
        raise ModernContinuationError("Modern continuation config hash differs")
    try:
        config = yaml.safe_load(config_path.read_text(encoding="utf-8", errors="strict"))
        validate_modern_workflow_config(config)
    except (OSError, UnicodeError, yaml.YAMLError, ConfigurationError) as error:
        raise ModernContinuationError(f"Modern continuation config is invalid: {error}") from error
    expected_schema_version = "0.5" if plan_version == PLAN_VERSION else "0.4"
    if (
        config["schema_version"] != expected_schema_version
        or config["preprocessing"]["procrustes"]["enabled"] is not False
        or config["optimization"]["step_initialization"] != "previous_accepted"
        or config["output"]["directory"] != plan["config"]["expected_destination"]
    ):
        raise ModernContinuationError("Modern continuation config semantics differ")
    expected_implementation = plan["config"].get("expected_engine_implementation")
    if (
        not isinstance(expected_implementation, str)
        or re.fullmatch(r"[0-9]+\.[0-9]+", expected_implementation) is None
    ):
        raise ModernContinuationError("Modern continuation engine implementation differs")
    if plan_version == PLAN_VERSION:
        optimizer_state = plan["optimizer_state"]
        if not isinstance(optimizer_state, dict) or set(optimizer_state) != {
            "checkpoint_path",
            "checkpoint_manifest_sha256",
            "source_effective_config",
        }:
            raise ModernContinuationError("Modern continuation optimizer state differs")
        checkpoint_root = _safe_path(
            root,
            optimizer_state["checkpoint_path"],
            "Continuation checkpoint",
            directory=True,
        )
        checkpoint = verify_modern_cycle_checkpoint(checkpoint_root)
        if (
            checkpoint["checkpoint_version"] != CHECKPOINT_VERSION
            or sha256_file(checkpoint_root / CHECKPOINT_MANIFEST_NAME)
            != optimizer_state["checkpoint_manifest_sha256"]
            or checkpoint["binding"]["engine_implementation"] != expected_implementation
        ):
            raise ModernContinuationError("Modern continuation checkpoint binding differs")
        source_effective_record = optimizer_state["source_effective_config"]
        source_effective = _safe_path(
            root,
            source_effective_record["path"],
            "Continuation source effective config",
        )
        if (
            _artifact(root, source_effective) != source_effective_record
            or sha256_file(source_effective) != checkpoint["binding"]["effective_config"]["sha256"]
        ):
            raise ModernContinuationError("Modern continuation source effective config differs")
        resume = config["optimization"].get("resume_state")
        if resume != {
            "checkpoint_directory": optimizer_state["checkpoint_path"],
            "checkpoint_manifest_sha256": optimizer_state["checkpoint_manifest_sha256"],
            "source_effective_config": source_effective_record["path"],
            "source_effective_config_sha256": source_effective_record["sha256"],
        }:
            raise ModernContinuationError("Modern continuation resume config differs")
    initial = plan["initial_state"]
    template = _safe_path(root, initial["template"]["path"], "Initial template")
    if _artifact(root, template) != initial["template"]:
        raise ModernContinuationError("Initial template evidence differs")
    controls = _safe_path(root, initial["control_points"]["path"], "Initial controls")
    if _artifact(root, controls) != initial["control_points"]:
        raise ModernContinuationError("Initial control-point evidence differs")
    try:
        _read_control_point_rows(controls, int(initial["control_point_count"]))
    except ConfigurationError as error:
        raise ModernContinuationError(f"Initial control points are invalid: {error}") from error
    labels = tuple(record["label"] for record in plan["subjects"])
    momenta = _safe_path(root, initial["momenta"]["path"], "Initial momenta")
    if _artifact(root, momenta) != initial["momenta"]:
        raise ModernContinuationError("Initial momenta evidence differs")
    try:
        _read_momenta_rows(momenta, labels, int(initial["control_point_count"]))
    except ConfigurationError as error:
        raise ModernContinuationError(f"Initial momenta are invalid: {error}") from error
    if config["initialization"]["momenta"]["path"] != initial["momenta"]["path"]:
        raise ModernContinuationError("Config and plan initial momenta differ")
    if config["initialization"]["control_points"]["path"] != initial["control_points"]["path"]:
        raise ModernContinuationError("Config and plan initial controls differ")
    if config["input"]["template"] != initial["template"]["path"]:
        raise ModernContinuationError("Config and plan initial template differ")
    if plan_version == PLAN_VERSION:
        checkpoint_state = checkpoint["state"]
        for name in ("template", "control_points", "momenta"):
            if (
                initial[name]["bytes"] != checkpoint_state[name]["bytes"]
                or initial[name]["sha256"] != checkpoint_state[name]["sha256"]
            ):
                raise ModernContinuationError(
                    f"Modern continuation initial {name} differs from checkpoint"
                )
    if tuple(sorted(labels)) != labels:
        raise ModernContinuationError("Continuation subject order is not deterministic")
    for record in plan["subjects"]:
        subject = _safe_path(
            root,
            record["effective_mesh"]["path"],
            f"Continuation subject {record['label']}",
        )
        if _artifact(root, subject) != record["effective_mesh"]:
            raise ModernContinuationError(
                f"Continuation subject evidence differs: {record['label']}"
            )
    observed_html = (root / PLAN_HTML_NAME).read_text(encoding="utf-8", errors="strict")
    expected_html = _render_html(plan)
    if observed_html != expected_html:
        mismatch = next(
            (
                index
                for index, (observed, expected) in enumerate(
                    zip(observed_html, expected_html, strict=False)
                )
                if observed != expected
            ),
            min(len(observed_html), len(expected_html)),
        )
        raise ModernContinuationError(
            "Modern continuation HTML differs at character "
            f"{mismatch} (observed length {len(observed_html)}, "
            f"expected length {len(expected_html)})"
        )
    return plan


def verify_modern_continuation_run(
    plan_directory: Path | str,
    successor_run: Path | str,
) -> dict[str, Any]:
    """Bind a verified successor run to its exact continuation plan and initial state."""

    plan_root = Path(plan_directory).expanduser().resolve()
    plan = verify_modern_continuation(plan_root)
    run_root = Path(successor_run).expanduser().resolve()
    workflow = verify_modern_workflow(run_root)
    if workflow["engine"].get("implementation_version") != plan["config"].get(
        "expected_engine_implementation"
    ):
        raise ModernContinuationError(
            "Successor engine implementation differs from the frozen continuation plan"
        )
    source_config = _safe_path(
        run_root,
        workflow["config"]["source_path"],
        "Successor source config",
    )
    if sha256_file(source_config) != plan["config"]["sha256"]:
        raise ModernContinuationError(
            "Successor run was not created from the frozen continuation config"
        )
    bundle_root = _safe_path(
        run_root,
        workflow["result_bundle"]["path"],
        "Successor bundle",
        directory=True,
    )
    bundle = verify_modern_atlas_bundle(bundle_root)
    labels = tuple(record["label"] for record in bundle["subjects"])
    if labels != tuple(record["label"] for record in plan["subjects"]):
        raise ModernContinuationError("Successor subject identity/order differs")
    history_path = _safe_path(
        bundle_root,
        bundle["optimizer"]["history_path"],
        "Successor optimizer history",
    )
    rows = _history(history_path)
    initial_objective = float(rows[0]["objective"])
    parent_final = float(plan["parent"]["final_objective"])
    tolerance = max(1e-12, abs(parent_final) * 1e-12)
    if not math.isclose(initial_objective, parent_final, rel_tol=1e-12, abs_tol=tolerance):
        raise ModernContinuationError(
            "Successor initial objective differs from the parent final objective"
        )
    return {
        "plan": plan,
        "workflow": workflow,
        "bundle": bundle,
        "initial_objective": initial_objective,
        "parent_final_objective": parent_final,
        "initial_objective_matches": True,
    }
