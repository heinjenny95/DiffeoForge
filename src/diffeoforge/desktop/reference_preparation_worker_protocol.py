"""Strict event transport for approval-bound reference preparation."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from importlib.resources import files
from types import MappingProxyType
from typing import Any, Literal

import jsonschema

from diffeoforge.config import ConfigurationError
from diffeoforge.desktop.reference_preparation_request import (
    DesktopReferencePreparationRequest,
)
from diffeoforge.reference_approved_preparation import (
    validate_approved_reference_preparation_evidence,
)

REFERENCE_PREPARATION_WORKER_EVENT_VERSION = "0.1"
REFERENCE_PREPARATION_WORKER_PHASES = (
    "verify_request",
    "prepare_approved",
    "verify_prepared_run",
)
ReferencePreparationWorkerEventKind = Literal["accepted", "phase", "terminal"]
ReferencePreparationWorkerOutcome = Literal["prepared_not_executed", "failed"]


class DesktopReferencePreparationWorkerProtocolError(ValueError):
    """Raised when preparation-worker transport evidence is inconsistent."""


def _schema() -> dict[str, Any]:
    resource = files("diffeoforge.schema").joinpath(
        "desktop-reference-preparation-worker-event-v0.1.json"
    )
    return json.loads(resource.read_text(encoding="utf-8"))


def _freeze_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise DesktopReferencePreparationWorkerProtocolError(
                "Reference preparation worker payload keys must be strings"
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


def validate_reference_preparation_worker_event(value: Mapping[str, Any]) -> None:
    """Validate one event envelope and any nested preparation evidence."""

    try:
        jsonschema.Draft202012Validator(_schema()).validate(dict(value))
    except jsonschema.ValidationError as error:
        location = ".".join(str(part) for part in error.absolute_path) or "document"
        raise DesktopReferencePreparationWorkerProtocolError(
            "Reference preparation worker event schema validation failed at "
            f"{location}: {error.message}"
        ) from error
    if value["kind"] != "terminal":
        return
    evidence = value["payload"].get("preparation_evidence")
    if evidence is None:
        return
    try:
        validate_approved_reference_preparation_evidence(evidence)
    except (ConfigurationError, TypeError, ValueError) as error:
        raise DesktopReferencePreparationWorkerProtocolError(
            f"Nested approved preparation evidence is invalid: {error}"
        ) from error


@dataclass(frozen=True)
class DesktopReferencePreparationWorkerEvent:
    """One immutable schema-valid preparation-worker event."""

    request_id: str
    sequence: int
    kind: ReferencePreparationWorkerEventKind
    payload: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", _freeze_json(self.payload))
        validate_reference_preparation_worker_event(self.as_dict())

    def as_dict(self) -> dict[str, Any]:
        return {
            "reference_preparation_worker_event_version": (
                REFERENCE_PREPARATION_WORKER_EVENT_VERSION
            ),
            "request_id": self.request_id,
            "sequence": self.sequence,
            "kind": self.kind,
            "payload": _thaw_json(self.payload),
        }

    def to_json_line(self) -> str:
        return json.dumps(
            self.as_dict(),
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, Any],
    ) -> DesktopReferencePreparationWorkerEvent:
        validate_reference_preparation_worker_event(value)
        return cls(
            request_id=str(value["request_id"]),
            sequence=int(value["sequence"]),
            kind=value["kind"],
            payload=dict(value["payload"]),
        )


class ReferencePreparationWorkerEventLedger:
    """Parent-side exact ordering and terminal-evidence reconciler."""

    def __init__(self, request: DesktopReferencePreparationRequest) -> None:
        if not isinstance(request, DesktopReferencePreparationRequest):
            raise TypeError("request must be a DesktopReferencePreparationRequest")
        self._request = request
        self._events: list[DesktopReferencePreparationWorkerEvent] = []
        self._accepted = False
        self._last_phase_index: int | None = None
        self._terminal: DesktopReferencePreparationWorkerEvent | None = None

    @property
    def events(self) -> tuple[DesktopReferencePreparationWorkerEvent, ...]:
        return tuple(self._events)

    @property
    def terminal(self) -> DesktopReferencePreparationWorkerEvent | None:
        return self._terminal

    def accept(self, event: DesktopReferencePreparationWorkerEvent) -> None:
        if not isinstance(event, DesktopReferencePreparationWorkerEvent):
            raise TypeError("event must be a DesktopReferencePreparationWorkerEvent")
        if event.request_id != self._request.request_id:
            raise DesktopReferencePreparationWorkerProtocolError(
                "Reference preparation worker event request_id mismatch"
            )
        if event.sequence != len(self._events):
            raise DesktopReferencePreparationWorkerProtocolError(
                "Reference preparation worker event sequence is not contiguous from zero"
            )
        if self._terminal is not None:
            raise DesktopReferencePreparationWorkerProtocolError(
                "Reference preparation worker emitted data after terminal"
            )

        if event.kind == "accepted":
            self._accept_initial(event)
        elif event.kind == "phase":
            self._accept_phase(event)
        else:
            self._accept_terminal(event)
        self._events.append(event)

    def _accept_initial(self, event: DesktopReferencePreparationWorkerEvent) -> None:
        if self._events:
            raise DesktopReferencePreparationWorkerProtocolError(
                "Reference preparation worker accepted event must be first"
            )
        expected = {
            "operation": "prepare_approved_only",
            "approval_request_sha256": self._request.expected_approval_sha256,
            "config_sha256": self._request.expected_config_sha256,
            "approved_plan_fingerprint": self._request.approved_plan_fingerprint,
            "run_id": self._request.run_id,
            "destination": str(self._request.destination),
            "engine_execution_authorized": False,
        }
        if dict(event.payload) != expected:
            raise DesktopReferencePreparationWorkerProtocolError(
                "Reference preparation worker accepted different bound request values"
            )
        self._accepted = True

    def _accept_phase(self, event: DesktopReferencePreparationWorkerEvent) -> None:
        if not self._accepted:
            raise DesktopReferencePreparationWorkerProtocolError(
                "Reference preparation worker phase requires acceptance"
            )
        phase_index = REFERENCE_PREPARATION_WORKER_PHASES.index(
            str(event.payload["phase"])
        )
        expected_index = (
            0 if self._last_phase_index is None else self._last_phase_index + 1
        )
        if phase_index != expected_index:
            raise DesktopReferencePreparationWorkerProtocolError(
                "Reference preparation worker phases must be complete and in order"
            )
        self._last_phase_index = phase_index

    def _accept_terminal(self, event: DesktopReferencePreparationWorkerEvent) -> None:
        if not self._accepted:
            raise DesktopReferencePreparationWorkerProtocolError(
                "Reference preparation worker terminal requires acceptance"
            )
        payload = event.payload
        bindings = {
            "destination": payload["destination"] == str(self._request.destination),
            "approval SHA-256": (
                payload["approval_request_sha256"]
                == self._request.expected_approval_sha256
            ),
            "plan fingerprint": (
                payload["approved_plan_fingerprint"]
                == self._request.approved_plan_fingerprint
            ),
            "execution boundary": payload["engine_execution_started"] is False,
        }
        for label, matches in bindings.items():
            if not matches:
                raise DesktopReferencePreparationWorkerProtocolError(
                    f"Reference preparation worker terminal {label} mismatch"
                )
        outcome = str(payload["outcome"])
        if outcome == "prepared_not_executed":
            final_index = len(REFERENCE_PREPARATION_WORKER_PHASES) - 1
            if self._last_phase_index != final_index:
                raise DesktopReferencePreparationWorkerProtocolError(
                    "prepared_not_executed requires verify_prepared_run phase"
                )
            evidence = payload["preparation_evidence"]
            if payload["manifest_sha256"] != evidence["prepared_run"][
                "manifest_sha256"
            ]:
                raise DesktopReferencePreparationWorkerProtocolError(
                    "Terminal manifest SHA-256 differs from nested preparation evidence"
                )
            if evidence["prepared_run"]["path"] != str(self._request.destination):
                raise DesktopReferencePreparationWorkerProtocolError(
                    "Nested preparation evidence targets a different destination"
                )
            if (
                evidence["approval_request"]["sha256"]
                != self._request.expected_approval_sha256
            ):
                raise DesktopReferencePreparationWorkerProtocolError(
                    "Nested preparation evidence contains a different approval SHA-256"
                )
            if evidence["approval_request"]["path"] != str(
                self._request.approval_path
            ):
                raise DesktopReferencePreparationWorkerProtocolError(
                    "Nested preparation evidence contains a different approval path"
                )
            if (
                evidence["approval_request"]["expected_sha256"]
                != self._request.expected_approval_sha256
            ):
                raise DesktopReferencePreparationWorkerProtocolError(
                    "Nested preparation evidence contains a different expected approval "
                    "SHA-256"
                )
            if (
                evidence["approved_plan"]["canonical_fingerprint"]
                != self._request.approved_plan_fingerprint
            ):
                raise DesktopReferencePreparationWorkerProtocolError(
                    "Nested preparation evidence contains a different plan fingerprint"
                )
            if evidence["approved_plan"]["run_id"] != self._request.run_id:
                raise DesktopReferencePreparationWorkerProtocolError(
                    "Nested preparation evidence contains a different run ID"
                )
        self._terminal = event

    def reconcile(self) -> DesktopReferencePreparationWorkerEvent:
        if self._terminal is None:
            raise DesktopReferencePreparationWorkerProtocolError(
                "Reference preparation worker stream ended without terminal"
            )
        return self._terminal
