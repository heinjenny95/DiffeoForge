"""Atomic, hash-bound complete-cycle checkpoints for the Modern optimizer."""

from __future__ import annotations

import csv
import json
import math
import re
import shutil
import uuid
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

import torch

from diffeoforge.engine import AtlasCycleCheckpoint
from diffeoforge.mesh import read_vtk_polydata, sha256_file, write_vtk_polydata

CHECKPOINT_VERSION = "0.1"
MANIFEST_NAME = "checkpoint.json"
SIDECAR_NAME = "checkpoint.sha256"
SCIENTIFIC_BOUNDARY = (
    "A complete-cycle checkpoint is private recovery state, not a completed atlas result, "
    "an independent replicate, convergence evidence, biological validation, or permission "
    "to overwrite its source run. Recovery must create a separately bound successor."
)


class ModernCheckpointError(RuntimeError):
    """Raised when a Modern cycle checkpoint is invalid or inconsistent."""


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
        handle.write("\n")


def _artifact(root: Path, path: Path) -> dict[str, object]:
    return {
        "path": path.relative_to(root).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def _safe(root: Path, value: object, label: str) -> Path:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ModernCheckpointError(f"{label} must be a POSIX-style path")
    relative = PurePosixPath(value)
    if relative.is_absolute() or "." in relative.parts or ".." in relative.parts:
        raise ModernCheckpointError(f"{label} is unsafe")
    path = root.joinpath(*relative.parts)
    try:
        resolved = path.resolve(strict=True)
    except OSError as error:
        raise ModernCheckpointError(f"{label} cannot be resolved") from error
    if not resolved.is_relative_to(root) or not path.is_file() or path.is_symlink():
        raise ModernCheckpointError(f"{label} is missing, symbolic, or escapes its root")
    return path


def _float(value: float) -> str:
    return format(float(value), ".17g")


def _binding(value: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {
        "engine_implementation",
        "source_config",
        "effective_config",
        "template_input",
        "subjects",
        "block_order",
        "max_cycles",
    }:
        raise ValueError("binding fields differ from the Modern checkpoint contract")
    implementation = value["engine_implementation"]
    if (
        not isinstance(implementation, str)
        or re.fullmatch(r"[0-9]+\.[0-9]+", implementation) is None
    ):
        raise ValueError("binding engine_implementation is invalid")
    blocks = value["block_order"]
    if (
        not isinstance(blocks, list)
        or not blocks
        or len(blocks) != len(set(blocks))
        or not set(blocks) <= {"momenta", "template", "control_points"}
    ):
        raise ValueError("binding block_order is invalid")
    maximum = value["max_cycles"]
    if isinstance(maximum, bool) or not isinstance(maximum, int) or maximum < 1:
        raise ValueError("binding max_cycles is invalid")
    for name in ("source_config", "effective_config", "template_input"):
        record = value[name]
        if (
            not isinstance(record, dict)
            or set(record) != {"path", "sha256"}
            or not isinstance(record["path"], str)
            or re.fullmatch(r"[0-9a-f]{64}", str(record["sha256"])) is None
        ):
            raise ValueError(f"binding {name} is invalid")
    subjects = value["subjects"]
    if not isinstance(subjects, list) or not subjects:
        raise ValueError("binding subjects must be a non-empty list")
    labels: list[str] = []
    for record in subjects:
        if (
            not isinstance(record, dict)
            or set(record) != {"label", "path", "sha256"}
            or not isinstance(record["label"], str)
            or not record["label"]
            or not isinstance(record["path"], str)
            or re.fullmatch(r"[0-9a-f]{64}", str(record["sha256"])) is None
        ):
            raise ValueError("binding subject record is invalid")
        labels.append(record["label"])
    if labels != sorted(labels) or len(labels) != len(set(labels)):
        raise ValueError("binding subject labels must be unique deterministic order")
    return json.loads(json.dumps(value, allow_nan=False))


def write_modern_cycle_checkpoint(
    destination: Path | str,
    checkpoint: AtlasCycleCheckpoint,
    template_triangles: torch.Tensor,
    subject_labels: list[str] | tuple[str, ...],
    binding: dict[str, Any],
    *,
    created_at: str | None = None,
) -> Path:
    """Atomically publish one immutable complete-cycle private checkpoint."""

    if not isinstance(checkpoint, AtlasCycleCheckpoint):
        raise TypeError("checkpoint must be an AtlasCycleCheckpoint")
    if not isinstance(template_triangles, torch.Tensor) or template_triangles.dtype != torch.int64:
        raise TypeError("template_triangles must be an int64 torch.Tensor")
    if template_triangles.ndim != 2 or template_triangles.shape[1] != 3:
        raise ValueError("template_triangles must have shape (triangles, 3)")
    normalized_binding = _binding(binding)
    labels = tuple(subject_labels)
    if labels != tuple(record["label"] for record in normalized_binding["subjects"]):
        raise ValueError("subject_labels differ from checkpoint binding")
    if (
        checkpoint.record.cycle < 1
        or checkpoint.record.block != normalized_binding["block_order"][-1]
    ):
        raise ValueError("checkpoint is not at a complete-cycle boundary")
    if checkpoint.record.cycle > normalized_binding["max_cycles"]:
        raise ValueError("checkpoint cycle exceeds the bound optimizer cap")
    if set(checkpoint.next_step_sizes) != set(normalized_binding["block_order"]):
        raise ValueError("checkpoint next-step blocks differ from the binding")
    if any(
        not math.isfinite(float(value)) or float(value) <= 0
        for value in checkpoint.next_step_sizes.values()
    ):
        raise ValueError("checkpoint next step sizes must be finite and positive")
    if checkpoint.momenta.ndim != 3 or tuple(checkpoint.momenta.shape[2:]) != (3,):
        raise ValueError("checkpoint momenta must have shape (subjects, controls, 3)")
    if checkpoint.momenta.shape[0] != len(labels):
        raise ValueError("checkpoint momenta subject count differs")
    control_count = int(checkpoint.momenta.shape[1])
    if tuple(checkpoint.control_points.shape) != (control_count, 3):
        raise ValueError("checkpoint control-point shape differs")
    if checkpoint.template_vertices.ndim != 2 or checkpoint.template_vertices.shape[1] != 3:
        raise ValueError("checkpoint template vertices must have shape (points, 3)")
    for name, tensor in (
        ("template", checkpoint.template_vertices),
        ("control points", checkpoint.control_points),
        ("momenta", checkpoint.momenta),
    ):
        if tensor.device.type != "cpu" or tensor.dtype != torch.float64:
            raise ValueError(f"checkpoint {name} must be CPU float64")
        if tensor.requires_grad or not bool(torch.isfinite(tensor).all()):
            raise ValueError(f"checkpoint {name} must be detached and finite")

    timestamp = created_at or datetime.now(UTC).isoformat(timespec="seconds")
    if not isinstance(timestamp, str) or not timestamp:
        raise ValueError("created_at must be a non-empty string")
    output = Path(destination).expanduser().resolve()
    if output.exists():
        raise FileExistsError(f"Modern checkpoint destination exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.parent / f".{output.name}.tmp-{uuid.uuid4().hex}"
    temporary.mkdir()
    try:
        template_path = write_vtk_polydata(
            temporary / "state" / "estimated-template.vtk",
            checkpoint.template_vertices.tolist(),
            template_triangles.tolist(),
            title=f"DiffeoForge private checkpoint cycle {checkpoint.record.cycle}",
        )
        controls_path = temporary / "state" / "control-points.txt"
        controls_path.parent.mkdir(parents=True, exist_ok=True)
        with controls_path.open("x", encoding="utf-8", newline="\n") as handle:
            for point in checkpoint.control_points.tolist():
                handle.write(" ".join(_float(value) for value in point) + "\n")
        momenta_path = temporary / "state" / "momenta.csv"
        with momenta_path.open("x", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerow(["subject_label", "control_point", "x", "y", "z"])
            for label, values in zip(labels, checkpoint.momenta.tolist(), strict=True):
                for index, point in enumerate(values):
                    writer.writerow([label, index, *(_float(value) for value in point)])
        artifacts = [
            _artifact(temporary, path) for path in sorted(temporary.rglob("*")) if path.is_file()
        ]
        manifest = {
            "checkpoint_version": CHECKPOINT_VERSION,
            "created_at": timestamp,
            "status": "private_complete_cycle_not_a_result",
            "cycle": checkpoint.record.cycle,
            "record": asdict(checkpoint.record),
            "optimizer_state": {
                "next_step_sizes": {
                    block: float(checkpoint.next_step_sizes[block])
                    for block in normalized_binding["block_order"]
                }
            },
            "state": {
                "template": {
                    **_artifact(temporary, template_path),
                    "points": int(checkpoint.template_vertices.shape[0]),
                    "triangles": int(template_triangles.shape[0]),
                },
                "control_points": {
                    **_artifact(temporary, controls_path),
                    "count": control_count,
                },
                "momenta": {
                    **_artifact(temporary, momenta_path),
                    "subjects": len(labels),
                    "control_points": control_count,
                    "dimensions": 3,
                },
            },
            "binding": normalized_binding,
            "artifacts": artifacts,
            "scientific_boundary": SCIENTIFIC_BOUNDARY,
        }
        manifest_path = temporary / MANIFEST_NAME
        _write_json(manifest_path, manifest)
        (temporary / SIDECAR_NAME).write_text(
            f"{sha256_file(manifest_path)}  {MANIFEST_NAME}\n",
            encoding="ascii",
            newline="\n",
        )
        verify_modern_cycle_checkpoint(temporary)
        temporary.rename(output)
    except Exception:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise
    return output


def verify_modern_cycle_checkpoint(
    directory: Path | str,
    *,
    workflow_root: Path | str | None = None,
) -> dict[str, Any]:
    """Verify one checkpoint internally and optionally against its workflow inputs."""

    root = Path(directory).expanduser().resolve()
    manifest_path = root / MANIFEST_NAME
    sidecar = root / SIDECAR_NAME
    if not root.is_dir() or not manifest_path.is_file() or not sidecar.is_file():
        raise ModernCheckpointError("Modern checkpoint files are missing")
    if (
        sidecar.read_text(encoding="ascii").strip()
        != f"{sha256_file(manifest_path)}  {MANIFEST_NAME}"
    ):
        raise ModernCheckpointError("Modern checkpoint sidecar differs")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8", errors="strict"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ModernCheckpointError(f"Modern checkpoint manifest is unreadable: {error}") from error
    if not isinstance(manifest, dict) or set(manifest) != {
        "checkpoint_version",
        "created_at",
        "status",
        "cycle",
        "record",
        "optimizer_state",
        "state",
        "binding",
        "artifacts",
        "scientific_boundary",
    }:
        raise ModernCheckpointError("Modern checkpoint manifest fields differ")
    if (
        manifest["checkpoint_version"] != CHECKPOINT_VERSION
        or manifest["status"] != "private_complete_cycle_not_a_result"
        or manifest["scientific_boundary"] != SCIENTIFIC_BOUNDARY
    ):
        raise ModernCheckpointError("Modern checkpoint identity differs")
    try:
        binding = _binding(manifest["binding"])
    except (TypeError, ValueError) as error:
        raise ModernCheckpointError(f"Modern checkpoint binding is invalid: {error}") from error
    record = manifest["record"]
    if not isinstance(record, dict) or set(record) != {
        "cycle",
        "block",
        "status",
        "objective",
        "attachment",
        "regularity",
        "residuals",
        "gradient_norm",
        "accepted_step_size",
        "line_search_evaluations",
    }:
        raise ModernCheckpointError("Modern checkpoint optimizer record fields differ")
    if manifest["cycle"] != record.get("cycle"):
        raise ModernCheckpointError("Modern checkpoint record cycle differs")
    if (
        isinstance(manifest["cycle"], bool)
        or not isinstance(manifest["cycle"], int)
        or not 1 <= manifest["cycle"] <= binding["max_cycles"]
        or record.get("block") != binding["block_order"][-1]
        or record.get("status") not in {"accepted", "stationary"}
    ):
        raise ModernCheckpointError("Modern checkpoint is not a complete-cycle record")
    finite_record_values = [record.get(name) for name in ("objective", "attachment", "regularity")]
    if (
        any(
            not isinstance(value, (int, float)) or not math.isfinite(value)
            for value in finite_record_values
        )
        or not isinstance(record.get("residuals"), list)
        or any(
            not isinstance(value, (int, float)) or not math.isfinite(value)
            for value in record["residuals"]
        )
    ):
        raise ModernCheckpointError("Modern checkpoint optimizer values are invalid")
    for name in ("gradient_norm", "accepted_step_size"):
        value = record.get(name)
        if value is not None and (not isinstance(value, (int, float)) or not math.isfinite(value)):
            raise ModernCheckpointError("Modern checkpoint optimizer values are invalid")
    evaluations = record.get("line_search_evaluations")
    if isinstance(evaluations, bool) or not isinstance(evaluations, int) or evaluations < 0:
        raise ModernCheckpointError("Modern checkpoint line-search count is invalid")
    optimizer_state = manifest["optimizer_state"]
    if not isinstance(optimizer_state, dict) or set(optimizer_state) != {"next_step_sizes"}:
        raise ModernCheckpointError("Modern checkpoint optimizer state fields differ")
    steps = optimizer_state["next_step_sizes"]
    if not isinstance(steps, dict) or set(steps) != set(binding["block_order"]):
        raise ModernCheckpointError("Modern checkpoint next-step order differs")
    if any(
        not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0
        for value in steps.values()
    ):
        raise ModernCheckpointError("Modern checkpoint next steps are invalid")
    declared: set[str] = set()
    for record in manifest["artifacts"]:
        if not isinstance(record, dict):
            raise ModernCheckpointError("Modern checkpoint artifact record is invalid")
        path = _safe(root, record.get("path"), "Checkpoint artifact")
        relative = path.relative_to(root).as_posix()
        if relative in declared:
            raise ModernCheckpointError("Modern checkpoint artifact is duplicated")
        declared.add(relative)
        if path.stat().st_size != record.get("bytes") or sha256_file(path) != record.get("sha256"):
            raise ModernCheckpointError(f"Modern checkpoint artifact differs: {relative}")
    actual = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path not in {manifest_path, sidecar}
    }
    if actual != declared:
        raise ModernCheckpointError("Modern checkpoint artifact inventory differs")
    state = manifest["state"]
    if not isinstance(state, dict) or set(state) != {"template", "control_points", "momenta"}:
        raise ModernCheckpointError("Modern checkpoint state fields differ")
    if any(not isinstance(state[name], dict) for name in state):
        raise ModernCheckpointError("Modern checkpoint state records are invalid")
    template = _safe(root, state["template"]["path"], "Checkpoint template")
    if _artifact(root, template) != {
        key: state["template"][key] for key in ("path", "bytes", "sha256")
    }:
        raise ModernCheckpointError("Modern checkpoint template evidence differs")
    geometry = read_vtk_polydata(template)
    if (
        len(geometry.vertices) != state["template"]["points"]
        or len(geometry.triangles) != state["template"]["triangles"]
    ):
        raise ModernCheckpointError("Modern checkpoint template geometry differs")
    controls = _safe(root, state["control_points"]["path"], "Checkpoint controls")
    if _artifact(root, controls) != {
        key: state["control_points"][key] for key in ("path", "bytes", "sha256")
    }:
        raise ModernCheckpointError("Modern checkpoint control-point evidence differs")
    try:
        control_rows = [line.split() for line in controls.read_text(encoding="utf-8").splitlines()]
        if len(control_rows) != state["control_points"]["count"] or any(
            len(row) != 3 or not all(math.isfinite(float(value)) for value in row)
            for row in control_rows
        ):
            raise ValueError
    except (OSError, UnicodeError, ValueError) as error:
        raise ModernCheckpointError("Modern checkpoint control points are invalid") from error
    momenta = _safe(root, state["momenta"]["path"], "Checkpoint momenta")
    if _artifact(root, momenta) != {
        key: state["momenta"][key] for key in ("path", "bytes", "sha256")
    }:
        raise ModernCheckpointError("Modern checkpoint momenta evidence differs")
    if state["momenta"]["control_points"] != state["control_points"]["count"]:
        raise ModernCheckpointError("Modern checkpoint state control-point counts differ")
    try:
        with momenta.open(encoding="utf-8", errors="strict", newline="") as handle:
            rows = list(csv.reader(handle))
        expected_rows = state["momenta"]["subjects"] * state["momenta"]["control_points"]
        if (
            rows[:1] != [["subject_label", "control_point", "x", "y", "z"]]
            or len(rows) - 1 != expected_rows
        ):
            raise ValueError
        expected = [
            (record["label"], str(index))
            for record in binding["subjects"]
            for index in range(state["momenta"]["control_points"])
        ]
        if [(row[0], row[1]) for row in rows[1:]] != expected or any(
            len(row) != 5 or not all(math.isfinite(float(value)) for value in row[2:])
            for row in rows[1:]
        ):
            raise ValueError
    except (OSError, UnicodeError, csv.Error, ValueError, IndexError) as error:
        raise ModernCheckpointError("Modern checkpoint momenta are invalid") from error
    if workflow_root is not None:
        workflow = Path(workflow_root).expanduser().resolve()
        for name in ("source_config", "effective_config", "template_input"):
            record = binding[name]
            path = _safe(workflow, record["path"], f"Bound {name}")
            if sha256_file(path) != record["sha256"]:
                raise ModernCheckpointError(f"Bound {name} differs")
        for record in binding["subjects"]:
            path = _safe(workflow, record["path"], f"Bound subject {record['label']}")
            if sha256_file(path) != record["sha256"]:
                raise ModernCheckpointError(f"Bound subject differs: {record['label']}")
    return manifest
