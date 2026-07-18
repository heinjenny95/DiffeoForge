"""Approval-bound, preparation-only request for a reference child process."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Any

import jsonschema

from diffeoforge.config import ConfigurationError
from diffeoforge.reference_preparation_approval import (
    load_saved_reference_preparation_approval,
    verify_saved_reference_preparation_approval,
)
from diffeoforge.reference_preparation_plan import (
    reference_preparation_plan_fingerprint,
)

REFERENCE_PREPARATION_REQUEST_VERSION = "0.1"
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class DesktopReferencePreparationRequestError(RuntimeError):
    """Raised when an approval-bound child request cannot remain exact."""


def _schema() -> dict[str, Any]:
    resource = files("diffeoforge.schema").joinpath(
        "desktop-reference-preparation-request-v0.1.json"
    )
    return json.loads(resource.read_text(encoding="utf-8"))


def validate_reference_preparation_request(value: Mapping[str, Any]) -> None:
    """Validate one serialized preparation-only child request."""

    try:
        jsonschema.Draft202012Validator(_schema()).validate(dict(value))
    except jsonschema.ValidationError as error:
        location = ".".join(str(part) for part in error.absolute_path) or "document"
        raise DesktopReferencePreparationRequestError(
            "Reference preparation request schema validation failed at "
            f"{location}: {error.message}"
        ) from error


def _normalize_sha256(value: str, label: str) -> str:
    if not isinstance(value, str):
        raise DesktopReferencePreparationRequestError(f"{label} must be a string")
    normalized = value.strip().lower()
    if not _SHA256_PATTERN.fullmatch(normalized):
        raise DesktopReferencePreparationRequestError(
            f"{label} must be exactly 64 hexadecimal digits"
        )
    return normalized


def _read_bytes(path: Path, label: str) -> bytes:
    if not path.is_file():
        raise DesktopReferencePreparationRequestError(
            f"{label} is not a readable file: {path}"
        )
    try:
        return path.read_bytes()
    except OSError as error:
        raise DesktopReferencePreparationRequestError(
            f"Could not read {label.lower()} {path}: {error}"
        ) from error


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


@dataclass(frozen=True)
class DesktopReferencePreparationRequest:
    """One exact authorization input for preparation without engine execution."""

    request_id: str
    approval_path: Path
    expected_approval_sha256: str
    config_path: Path
    expected_config_sha256: str
    approved_plan_fingerprint: str
    run_id: str
    destination: Path

    @property
    def engine(self) -> str:
        return "deformetrica_reference"

    def as_dict(self) -> dict[str, Any]:
        return {
            "reference_preparation_request_version": (
                REFERENCE_PREPARATION_REQUEST_VERSION
            ),
            "request_id": self.request_id,
            "operation": "prepare_approved_only",
            "engine": self.engine,
            "approval_path": str(self.approval_path),
            "expected_approval_sha256": self.expected_approval_sha256,
            "config_path": str(self.config_path),
            "expected_config_sha256": self.expected_config_sha256,
            "approved_plan_fingerprint": self.approved_plan_fingerprint,
            "run_id": self.run_id,
            "destination": str(self.destination),
            "engine_execution_authorized": False,
        }

    def __post_init__(self) -> None:
        if not self.approval_path.is_absolute() or not self.config_path.is_absolute():
            raise DesktopReferencePreparationRequestError(
                "Reference preparation input paths must be absolute"
            )
        if not self.destination.is_absolute():
            raise DesktopReferencePreparationRequestError(
                "Reference preparation destination must be absolute"
            )
        validate_reference_preparation_request(self.as_dict())
        if self.destination.name != self.run_id:
            raise DesktopReferencePreparationRequestError(
                "Reference preparation destination name must equal run_id"
            )

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, Any],
    ) -> DesktopReferencePreparationRequest:
        validate_reference_preparation_request(value)
        approval_path = Path(str(value["approval_path"])).expanduser()
        config_path = Path(str(value["config_path"])).expanduser()
        destination = Path(str(value["destination"])).expanduser()
        if not approval_path.is_absolute() or not config_path.is_absolute():
            raise DesktopReferencePreparationRequestError(
                "Reference preparation input paths must be absolute"
            )
        if not destination.is_absolute():
            raise DesktopReferencePreparationRequestError(
                "Reference preparation destination must be absolute"
            )
        return cls(
            request_id=str(value["request_id"]),
            approval_path=approval_path.resolve(),
            expected_approval_sha256=str(value["expected_approval_sha256"]),
            config_path=config_path.resolve(),
            expected_config_sha256=str(value["expected_config_sha256"]),
            approved_plan_fingerprint=str(value["approved_plan_fingerprint"]),
            run_id=str(value["run_id"]),
            destination=destination.resolve(),
        )

    def verify_inputs(self) -> None:
        """Recheck approval/config bytes, embedded plan identity, and current state."""

        approval_bytes = _read_bytes(self.approval_path, "Approval request")
        approval_hash = _sha256_bytes(approval_bytes)
        if approval_hash != self.expected_approval_sha256:
            raise DesktopReferencePreparationRequestError(
                "Approval request changed after the preparation request was bound"
            )
        try:
            approval, loaded_bytes = load_saved_reference_preparation_approval(
                self.approval_path
            )
        except (ConfigurationError, OSError, TypeError, ValueError) as error:
            raise DesktopReferencePreparationRequestError(
                f"Bound approval request is invalid: {error}"
            ) from error
        if loaded_bytes != approval_bytes:
            raise DesktopReferencePreparationRequestError(
                "Approval request changed while the preparation request was verified"
            )
        plan = approval["plan"]
        fingerprint = reference_preparation_plan_fingerprint(plan)
        bindings = {
            "approved plan fingerprint": (
                fingerprint == self.approved_plan_fingerprint
            ),
            "configuration path": (
                Path(str(plan["source_config"]["path"])).resolve() == self.config_path
            ),
            "configuration SHA-256": (
                str(plan["source_config"]["sha256"]) == self.expected_config_sha256
            ),
            "run ID": str(plan["run"]["run_id"]) == self.run_id,
            "destination": (
                Path(str(plan["run"]["destination"])).resolve() == self.destination
            ),
            "preparation-only scope": (
                approval["approval"]["scope"] == "preparation_only"
                and approval["approval"]["engine_execution_authorized"] is False
            ),
        }
        for label, matches in bindings.items():
            if not matches:
                raise DesktopReferencePreparationRequestError(
                    f"Approval request has a different bound {label}"
                )

        config_bytes = _read_bytes(self.config_path, "Reference configuration")
        if _sha256_bytes(config_bytes) != self.expected_config_sha256:
            raise DesktopReferencePreparationRequestError(
                "Reference configuration changed after the preparation request was bound"
            )
        try:
            verify_saved_reference_preparation_approval(
                self.approval_path,
                current_config_path=self.config_path,
            )
        except (ConfigurationError, OSError, TypeError, ValueError) as error:
            raise DesktopReferencePreparationRequestError(
                f"Current reference plan no longer matches the bound approval: {error}"
            ) from error
        if _read_bytes(self.approval_path, "Approval request") != approval_bytes:
            raise DesktopReferencePreparationRequestError(
                "Approval request changed during current-state verification"
            )
        if _read_bytes(self.config_path, "Reference configuration") != config_bytes:
            raise DesktopReferencePreparationRequestError(
                "Reference configuration changed during current-state verification"
            )
        if self.destination.exists():
            raise DesktopReferencePreparationRequestError(
                f"Reference preparation destination already exists: {self.destination}"
            )


def build_reference_preparation_request(
    approval_path: Path | str,
    current_config_path: Path | str,
    *,
    expected_approval_sha256: str,
    request_id: str,
) -> DesktopReferencePreparationRequest:
    """Bind one exact saved approval to a preparation-only child request."""

    approval_source = Path(approval_path).expanduser().resolve()
    config_source = Path(current_config_path).expanduser().resolve()
    normalized_approval_hash = _normalize_sha256(
        expected_approval_sha256,
        "Expected approval request SHA-256",
    )
    try:
        approval, approval_bytes = load_saved_reference_preparation_approval(
            approval_source
        )
    except (ConfigurationError, OSError, TypeError, ValueError) as error:
        raise DesktopReferencePreparationRequestError(
            f"Approval request cannot be bound: {error}"
        ) from error
    if _sha256_bytes(approval_bytes) != normalized_approval_hash:
        raise DesktopReferencePreparationRequestError(
            "Approval request does not match the independently recorded SHA-256"
        )
    plan = approval["plan"]
    request = DesktopReferencePreparationRequest(
        request_id=request_id,
        approval_path=approval_source,
        expected_approval_sha256=normalized_approval_hash,
        config_path=config_source,
        expected_config_sha256=str(plan["source_config"]["sha256"]),
        approved_plan_fingerprint=reference_preparation_plan_fingerprint(plan),
        run_id=str(plan["run"]["run_id"]),
        destination=Path(str(plan["run"]["destination"])).resolve(),
    )
    request.verify_inputs()
    return request
