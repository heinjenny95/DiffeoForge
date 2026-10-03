"""Strict transport and lifecycle ledger for a future reference worker."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from importlib.resources import files
from types import MappingProxyType
from typing import Any, Literal

import jsonschema

from diffeoforge.desktop.reference_prelaunch import DesktopReferenceLaunchRequest

REFERENCE_WORKER_COMMAND_VERSION = "0.1"
REFERENCE_WORKER_EVENT_VERSION = "0.1"
REFERENCE_WORKER_PHASES = (
    "verify_request",
    "preflight",
    "prepare",
    "execute",
    "finalize",
    "verify_result",
)
ReferenceWorkerEventKind = Literal[
    "accepted",
    "phase",
    "activity",
    "progress",
    "terminal",
]
ReferenceWorkerOutcome = Literal[
    "completed",
    "stopped_before_prepare",
    "prepared_not_executed",
    "interrupted",
    "failed",
]


class DesktopReferenceWorkerProtocolError(ValueError):
    """Raised when reference-worker transport or lifecycle evidence is invalid."""


def _schema(name: str) -> dict[str, Any]:
    resource = files("diffeoforge.schema").joinpath(name)
    return json.loads(resource.read_text(encoding="utf-8"))


def _validate(value: Mapping[str, Any], schema_name: str, label: str) -> None:
    try:
        jsonschema.Draft202012Validator(_schema(schema_name)).validate(dict(value))
    except jsonschema.ValidationError as error:
        location = ".".join(str(part) for part in error.absolute_path) or "document"
        raise DesktopReferenceWorkerProtocolError(
            f"{label} schema validation failed at {location}: {error.message}"
        ) from error


def _freeze_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise DesktopReferenceWorkerProtocolError(
                "Reference worker payload keys must be strings"
            )
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
class DesktopReferenceWorkerCommand:
    """One request-bound control command for the future reference worker."""

    request_id: str
    command: Literal["cancel"] = "cancel"

    def as_dict(self) -> dict[str, Any]:
        return {
            "reference_worker_command_version": REFERENCE_WORKER_COMMAND_VERSION,
            "request_id": self.request_id,
            "command": self.command,
        }

    def __post_init__(self) -> None:
        _validate(
            self.as_dict(),
            "desktop-reference-worker-command-v0.1.json",
            "Reference worker command",
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> DesktopReferenceWorkerCommand:
        _validate(
            value,
            "desktop-reference-worker-command-v0.1.json",
            "Reference worker command",
        )
        return cls(request_id=str(value["request_id"]), command=value["command"])


@dataclass(frozen=True)
class DesktopReferenceWorkerEvent:
    """One schema-valid reference-worker event envelope."""

    request_id: str
    sequence: int
    kind: ReferenceWorkerEventKind
    payload: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", _freeze_json(self.payload))
        validate_reference_worker_event(self.as_dict())

    def as_dict(self) -> dict[str, Any]:
        return {
            "reference_worker_event_version": REFERENCE_WORKER_EVENT_VERSION,
            "request_id": self.request_id,
            "sequence": self.sequence,
            "kind": self.kind,
            "payload": _thaw_json(self.payload),
        }

    def to_json_line(self) -> str:
        return json.dumps(
            self.as_dict(),
            allow_nan=False,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> DesktopReferenceWorkerEvent:
        validate_reference_worker_event(value)
        return cls(
            request_id=str(value["request_id"]),
            sequence=int(value["sequence"]),
            kind=value["kind"],
            payload=dict(value["payload"]),
        )


def validate_reference_worker_event(value: Mapping[str, Any]) -> None:
    """Validate one event envelope and its kind-specific payload."""

    try:
        json.dumps(dict(value), allow_nan=False)
    except (TypeError, ValueError) as error:
        raise DesktopReferenceWorkerProtocolError(
            f"Reference worker event is not strict JSON: {error}"
        ) from error
    _validate(
        value,
        "desktop-reference-worker-event-v0.1.json",
        "Reference worker event",
    )


class ReferenceWorkerEventLedger:
    """Fail-closed parent-side ordering and terminal-state reconciler."""

    def __init__(self, request: DesktopReferenceLaunchRequest) -> None:
        if not isinstance(request, DesktopReferenceLaunchRequest):
            raise TypeError("request must be a DesktopReferenceLaunchRequest")
        self._request = request
        self._request_id = request.request_id
        self._events: list[DesktopReferenceWorkerEvent] = []
        self._accepted = False
        self._last_phase_index: int | None = None
        self._last_activity_elapsed: float | None = None
        self._last_progress_iteration: int | None = None
        self._terminal: DesktopReferenceWorkerEvent | None = None

    @property
    def events(self) -> tuple[DesktopReferenceWorkerEvent, ...]:
        return tuple(self._events)

    @property
    def terminal(self) -> DesktopReferenceWorkerEvent | None:
        return self._terminal

    def accept(self, event: DesktopReferenceWorkerEvent) -> None:
        if not isinstance(event, DesktopReferenceWorkerEvent):
            raise TypeError("event must be a DesktopReferenceWorkerEvent")
        if event.request_id != self._request_id:
            raise DesktopReferenceWorkerProtocolError(
                "Reference worker event request_id does not match the launch request"
            )
        if event.sequence != len(self._events):
            raise DesktopReferenceWorkerProtocolError(
                "Reference worker event sequence is not contiguous from zero"
            )
        if self._terminal is not None:
            raise DesktopReferenceWorkerProtocolError(
                "Reference worker emitted data after a terminal event"
            )

        if event.kind == "accepted":
            if self._events:
                raise DesktopReferenceWorkerProtocolError(
                    "Reference worker accepted event must be first"
                )
            if event.payload["config_sha256"] != self._request.expected_config_sha256:
                raise DesktopReferenceWorkerProtocolError(
                    "Reference worker accepted a different configuration hash"
                )
            if event.payload["destination"] != str(self._request.destination):
                raise DesktopReferenceWorkerProtocolError(
                    "Reference worker accepted a different launch destination"
                )
            self._accepted = True
        elif event.kind == "phase":
            if not self._accepted:
                raise DesktopReferenceWorkerProtocolError(
                    "Reference worker phase requires an accepted event"
                )
            phase_index = REFERENCE_WORKER_PHASES.index(str(event.payload["phase"]))
            if self._last_phase_index is not None and phase_index <= self._last_phase_index:
                raise DesktopReferenceWorkerProtocolError(
                    "Reference worker phases must advance without repetition or regression"
                )
            self._last_phase_index = phase_index
        elif event.kind == "activity":
            execute_index = REFERENCE_WORKER_PHASES.index("execute")
            if self._last_phase_index != execute_index:
                raise DesktopReferenceWorkerProtocolError(
                    "Reference worker activity is allowed only during the execute phase"
                )
            elapsed = float(event.payload["elapsed_seconds"])
            if (
                self._last_activity_elapsed is not None
                and elapsed <= self._last_activity_elapsed
            ):
                raise DesktopReferenceWorkerProtocolError(
                    "Reference worker activity elapsed time must increase strictly"
                )
            self._last_activity_elapsed = elapsed
        elif event.kind == "progress":
            execute_index = REFERENCE_WORKER_PHASES.index("execute")
            if self._last_phase_index != execute_index:
                raise DesktopReferenceWorkerProtocolError(
                    "Reference worker progress is allowed only during the execute phase"
                )
            iteration = int(event.payload["iteration"])
            if (
                self._last_progress_iteration is not None
                and iteration <= self._last_progress_iteration
            ):
                raise DesktopReferenceWorkerProtocolError(
                    "Reference worker progress iterations must increase strictly"
                )
            self._last_progress_iteration = iteration
        else:
            outcome = str(event.payload["outcome"])
            if event.payload["destination"] != str(self._request.destination):
                raise DesktopReferenceWorkerProtocolError(
                    "Reference worker terminal event targets a different destination"
                )
            if not self._accepted and outcome != "failed":
                raise DesktopReferenceWorkerProtocolError(
                    "Reference worker terminal outcome requires an accepted event"
                )
            self._validate_terminal_phase(outcome)
            self._terminal = event
        self._events.append(event)

    def reconcile(self) -> DesktopReferenceWorkerEvent:
        """Return the sole terminal event or reject an incomplete stream."""

        if self._terminal is None:
            raise DesktopReferenceWorkerProtocolError(
                "Reference worker event stream ended without a terminal event"
            )
        return self._terminal

    def _validate_terminal_phase(self, outcome: str) -> None:
        prepare_index = REFERENCE_WORKER_PHASES.index("prepare")
        execute_index = REFERENCE_WORKER_PHASES.index("execute")
        verify_result_index = REFERENCE_WORKER_PHASES.index("verify_result")
        last = self._last_phase_index
        if outcome == "completed" and last != verify_result_index:
            raise DesktopReferenceWorkerProtocolError(
                "Completed reference worker requires the verify_result phase"
            )
        if outcome == "stopped_before_prepare" and last is not None and last >= prepare_index:
            raise DesktopReferenceWorkerProtocolError(
                "stopped_before_prepare conflicts with an observed prepare phase"
            )
        if outcome == "prepared_not_executed" and (
            last is None or last < prepare_index or last >= execute_index
        ):
            raise DesktopReferenceWorkerProtocolError(
                "prepared_not_executed requires prepare and forbids execute"
            )
        if outcome == "interrupted" and (last is None or last < execute_index):
            raise DesktopReferenceWorkerProtocolError(
                "Interrupted reference worker requires an execute phase"
            )
