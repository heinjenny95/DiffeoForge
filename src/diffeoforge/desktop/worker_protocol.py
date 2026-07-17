"""Strict Qt-independent JSON-lines protocol for desktop compute workers."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal

import jsonschema

from diffeoforge.config import resolve_output_directory

WORKER_REQUEST_VERSION = "0.1"
WORKER_COMMAND_VERSION = "0.1"
WORKER_EVENT_VERSION = "0.1"
WorkerEventKind = Literal["started", "progress", "completed", "cancelled", "failed"]


class DesktopWorkerProtocolError(ValueError):
    """Raised when worker transport data is malformed or no longer matches its inputs."""


def _schema(name: str) -> dict[str, Any]:
    resource = files("diffeoforge.schema").joinpath(name)
    return json.loads(resource.read_text(encoding="utf-8"))


def _validate(value: Mapping[str, Any], schema_name: str, label: str) -> None:
    try:
        jsonschema.Draft202012Validator(_schema(schema_name)).validate(dict(value))
    except jsonschema.ValidationError as error:
        location = ".".join(str(part) for part in error.absolute_path) or "document"
        raise DesktopWorkerProtocolError(
            f"{label} schema validation failed at {location}: {error.message}"
        ) from error


def sha256_file(path: Path | str) -> str:
    """Hash one file without importing the optional numerical engine."""

    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _freeze_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise DesktopWorkerProtocolError("Worker protocol object keys must be strings")
        return MappingProxyType({key: _freeze_json(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in value)
    return value


def _thaw_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


@dataclass(frozen=True)
class DesktopWorkerRequest:
    """One immutable Modern CPU worker launch request."""

    request_id: str
    config_path: Path
    destination: Path
    expected_config_sha256: str

    @property
    def engine(self) -> str:
        return "modern_cpu"

    def as_dict(self) -> dict[str, Any]:
        return {
            "worker_request_version": WORKER_REQUEST_VERSION,
            "request_id": self.request_id,
            "engine": self.engine,
            "config_path": str(self.config_path),
            "destination": str(self.destination),
            "expected_config_sha256": self.expected_config_sha256,
        }

    def __post_init__(self) -> None:
        if not self.config_path.is_absolute() or not self.destination.is_absolute():
            raise DesktopWorkerProtocolError("Worker paths must be absolute")
        _validate(
            self.as_dict(),
            "desktop-worker-request-v0.1.json",
            "Desktop worker request",
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> DesktopWorkerRequest:
        _validate(value, "desktop-worker-request-v0.1.json", "Desktop worker request")
        config_path = Path(value["config_path"]).expanduser()
        destination = Path(value["destination"]).expanduser()
        if not config_path.is_absolute() or not destination.is_absolute():
            raise DesktopWorkerProtocolError("Worker request paths must be absolute")
        return cls(
            request_id=str(value["request_id"]),
            config_path=config_path.resolve(),
            destination=destination.resolve(),
            expected_config_sha256=str(value["expected_config_sha256"]),
        )

    def verify_launch_inputs(self) -> None:
        if not self.config_path.is_file():
            raise DesktopWorkerProtocolError(
                f"Worker configuration does not exist: {self.config_path}"
            )
        observed = sha256_file(self.config_path)
        if observed != self.expected_config_sha256:
            raise DesktopWorkerProtocolError(
                "Worker configuration changed after the reviewed launch request was created"
            )
        if self.destination.exists():
            raise FileExistsError(f"Worker destination already exists: {self.destination}")


def build_worker_request(
    config_path: Path | str,
    *,
    request_id: str,
    destination: Path | str | None = None,
) -> DesktopWorkerRequest:
    """Validate a Modern config and bind a launch request to its current bytes."""

    try:
        from diffeoforge.modern_workflow import load_modern_workflow_config
    except ImportError as error:
        raise DesktopWorkerProtocolError(
            "Modern engine dependencies are missing; install diffeoforge[modern-engine]."
        ) from error

    source = Path(config_path).expanduser().resolve()
    if not source.is_file():
        raise DesktopWorkerProtocolError(f"Worker configuration does not exist: {source}")
    hash_before_validation = sha256_file(source)
    config = load_modern_workflow_config(source)
    hash_after_validation = sha256_file(source)
    if hash_before_validation != hash_after_validation:
        raise DesktopWorkerProtocolError(
            "Worker configuration changed while the reviewed launch request was created"
        )
    output = (
        resolve_output_directory(config, source)
        if destination is None
        else Path(destination).expanduser().resolve()
    )
    request = DesktopWorkerRequest(
        request_id=request_id,
        config_path=source,
        destination=output,
        expected_config_sha256=hash_after_validation,
    )
    request.verify_launch_inputs()
    return request


@dataclass(frozen=True)
class DesktopWorkerCommand:
    """One parent-to-worker control command."""

    request_id: str
    command: Literal["cancel"] = "cancel"

    def as_dict(self) -> dict[str, Any]:
        return {
            "worker_command_version": WORKER_COMMAND_VERSION,
            "request_id": self.request_id,
            "command": self.command,
        }

    def __post_init__(self) -> None:
        _validate(
            self.as_dict(),
            "desktop-worker-command-v0.1.json",
            "Desktop worker command",
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> DesktopWorkerCommand:
        _validate(value, "desktop-worker-command-v0.1.json", "Desktop worker command")
        return cls(request_id=str(value["request_id"]), command=value["command"])


@dataclass(frozen=True)
class DesktopWorkerEvent:
    """One validated worker-to-parent event envelope."""

    request_id: str
    sequence: int
    kind: WorkerEventKind
    payload: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", _freeze_json(self.payload))
        validate_worker_event(self.as_dict())

    def as_dict(self) -> dict[str, Any]:
        return {
            "worker_event_version": WORKER_EVENT_VERSION,
            "request_id": self.request_id,
            "sequence": self.sequence,
            "kind": self.kind,
            "payload": _thaw_json(self.payload),
        }

    def to_json_line(self) -> str:
        return json.dumps(
            self.as_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> DesktopWorkerEvent:
        validate_worker_event(value)
        return cls(
            request_id=str(value["request_id"]),
            sequence=int(value["sequence"]),
            kind=value["kind"],
            payload=dict(value["payload"]),
        )


def validate_worker_event(value: Mapping[str, Any]) -> None:
    """Validate an envelope and the nested strict Modern progress contract."""

    _validate(value, "desktop-worker-event-v0.1.json", "Desktop worker event")
    if value["kind"] == "progress":
        from diffeoforge.modern_progress import validate_modern_progress_event

        try:
            validate_modern_progress_event(dict(value["payload"]["modern_progress"]))
        except jsonschema.ValidationError as error:
            location = ".".join(str(part) for part in error.absolute_path) or "document"
            raise DesktopWorkerProtocolError(
                "Desktop worker nested Modern progress validation failed at "
                f"{location}: {error.message}"
            ) from error


def parse_json_object(line: str, label: str) -> dict[str, Any]:
    """Parse exactly one JSON object from one transport line."""

    try:
        value = json.loads(line)
    except json.JSONDecodeError as error:
        raise DesktopWorkerProtocolError(f"{label} is not valid JSON: {error.msg}") from error
    if not isinstance(value, dict):
        raise DesktopWorkerProtocolError(f"{label} must be a JSON object")
    return value
