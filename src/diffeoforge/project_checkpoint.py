"""Project-local, disposable, content-bound setup and inspection checkpoints.

These JSON files preserve engineering work and explicit GPA review decisions.
They never replace scientific run evidence or confer a new review approval.
Only an explicit desktop check writes them; ordinary core reads stay read-only.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import fields, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from diffeoforge.atomic_io import write_text_safely

CHECKPOINT_VERSION = "1"
CHECKPOINT_KIND = "diffeoforge_project_checkpoint"
MAX_CHECKPOINT_BYTES = 32 * 1024 * 1024


class CheckpointUnavailable(ValueError):
    """Saved work is absent, incompatible, corrupt or bound to other inputs."""


def checkpoint_directory(project: Path | str) -> Path:
    return Path(project).expanduser().resolve() / ".diffeoforge" / "checks"


def _types() -> dict[str, type]:
    # Fixed allow-list; no module/class name from a file is imported or executed.
    from diffeoforge.analysis.mesh_scaling import MeshScaleMetrics
    from diffeoforge.analysis.procrustes import (
        GeneralizedProcrustesResult,
        ProcrustesIteration,
        SimilarityTransform,
    )
    from diffeoforge.input_preflight import (
        InputMeshQualityObservation,
        InputPreflightIssue,
        MeshInputPreflight,
    )
    from diffeoforge.mesh import MeshMetadata
    from diffeoforge.mesh_quality import MeshQualityResult, MetricSummary
    from diffeoforge.preprocessing import LandmarkAlignmentPreview
    from diffeoforge.surface_io import SurfaceMeshMetadata

    return {cls.__name__: cls for cls in (
        MeshScaleMetrics, GeneralizedProcrustesResult, ProcrustesIteration,
        SimilarityTransform, InputMeshQualityObservation, InputPreflightIssue,
        MeshInputPreflight, MeshMetadata, MeshQualityResult, MetricSummary,
        LandmarkAlignmentPreview, SurfaceMeshMetadata,
    )}


def _encode(value: Any) -> Any:
    import numpy as np

    if isinstance(value, Enum):
        return {"$enum": type(value).__name__, "value": value.value}
    if isinstance(value, Path):
        return {"$path": str(value)}
    if isinstance(value, np.ndarray):
        if value.dtype != np.float64 or not np.isfinite(value).all():
            raise ValueError("Only finite float64 checkpoint arrays are supported")
        return {"$array": value.tolist()}
    if is_dataclass(value) and not isinstance(value, type):
        if type(value).__name__ not in _types():
            raise TypeError("Unsupported checkpoint record")
        return {"$record": type(value).__name__, "fields": {
            field.name: _encode(getattr(value, field.name)) for field in fields(value)
        }}
    if isinstance(value, tuple):
        return {"$tuple": [_encode(item) for item in value]}
    if isinstance(value, list):
        return [_encode(item) for item in value]
    if isinstance(value, dict):
        if any(not isinstance(key, str) or key.startswith("$") for key in value):
            raise ValueError("Invalid checkpoint mapping key")
        return {key: _encode(item) for key, item in value.items()}
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    raise ValueError("Unsupported or non-finite checkpoint value")


def _decode(value: Any) -> Any:
    if isinstance(value, list):
        return [_decode(item) for item in value]
    if not isinstance(value, dict):
        return value
    if "$record" in value:
        cls = _types().get(value["$record"])
        if cls is None or set(value) != {"$record", "fields"}:
            raise ValueError("Unknown checkpoint record")
        if set(value["fields"]) != {field.name for field in fields(cls)}:
            raise ValueError("Checkpoint record fields changed")
        return cls(**{key: _decode(item) for key, item in value["fields"].items()})
    if "$array" in value and set(value) == {"$array"}:
        import numpy as np

        result = np.asarray(value["$array"], dtype=np.float64)
        if result.ndim > 3 or not np.isfinite(result).all():
            raise ValueError("Invalid checkpoint array")
        result.setflags(write=False)
        return result
    if "$tuple" in value and set(value) == {"$tuple"}:
        return tuple(_decode(item) for item in value["$tuple"])
    if "$path" in value and set(value) == {"$path"}:
        return Path(value["$path"])
    if "$enum" in value and set(value) == {"$enum", "value"}:
        from diffeoforge.mesh_scaling_contract import MeshScalingMode

        if value["$enum"] != "MeshScalingMode":
            raise ValueError("Unknown checkpoint enum")
        return MeshScalingMode(value["value"])
    if any(key.startswith("$") for key in value):
        raise ValueError("Unknown checkpoint tag")
    return {key: _decode(item) for key, item in value.items()}


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")).hexdigest()


def _path(project: Path | str, name: str) -> Path:
    if not name or any(char not in "abcdefghijklmnopqrstuvwxyz0123456789-" for char in name):
        raise ValueError("Invalid checkpoint name")
    root = Path(project).expanduser().resolve()
    folder = checkpoint_directory(root)
    destination = folder / f"{name}.json"
    if any(item.is_symlink() or (hasattr(item, "is_junction") and item.is_junction())
           for item in (root / ".diffeoforge", folder, destination)):
        raise CheckpointUnavailable("Checkpoint paths must not be symbolic links")
    return destination


def load_checkpoint(project: Path | str, name: str) -> Any:
    try:
        path = _path(project, name)
        if path.stat().st_size > MAX_CHECKPOINT_BYTES:
            raise ValueError("Checkpoint exceeds size limit")
        document = json.loads(path.read_text(encoding="utf-8"))
        if (not isinstance(document, dict) or document.get("kind") != CHECKPOINT_KIND
                or document.get("version") != CHECKPOINT_VERSION
                or _digest(document["payload"]) != document.get("sha256")):
            raise ValueError("Checkpoint identity or integrity differs")
        return _decode(document["payload"])
    except (OSError, UnicodeError, KeyError, TypeError, ValueError, OverflowError,
            RecursionError) as error:
        raise CheckpointUnavailable(str(error)) from error


def save_checkpoint(project: Path | str, name: str, payload: Any) -> None:
    destination = _path(project, name)
    if destination.exists():
        try:
            previous = json.loads(destination.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError) as error:
            raise CheckpointUnavailable("Unrecognized existing checkpoint is preserved") from error
        if not isinstance(previous, dict) or previous.get("kind") != CHECKPOINT_KIND:
            raise CheckpointUnavailable("Unrecognized existing file is preserved")
    encoded = _encode(payload)
    document = {"kind": CHECKPOINT_KIND, "version": CHECKPOINT_VERSION,
                "payload": encoded, "sha256": _digest(encoded)}
    text = json.dumps(document, sort_keys=True, allow_nan=False) + "\n"
    if len(text.encode("utf-8")) > MAX_CHECKPOINT_BYTES:
        raise CheckpointUnavailable("Checkpoint exceeds size limit")
    write_text_safely(destination, text, overwrite=destination.exists())
