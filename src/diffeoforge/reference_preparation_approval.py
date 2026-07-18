"""Preparation-only approval requests for the Deformetrica reference path."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from importlib.resources import files
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from diffeoforge import __version__
from diffeoforge.config import ConfigurationError
from diffeoforge.reference_preparation_plan import (
    plan_reference_preparation,
    reference_preparation_plan_fingerprint,
)
from diffeoforge.strict_json import load_strict_json_object

REQUEST_SCHEMA_VERSION = "0.1"
REQUEST_STATUS = "approved_reference_preparation_not_prepared"
APPROVAL_SCOPE = "preparation_only"
APPROVAL_STATEMENT = (
    "I reviewed the embedded exact preparation plan and approve creation of its immutable "
    "staged run directory only; no engine execution is authorized."
)
REQUEST_BOUNDARY = (
    "This deterministic request records preparation-only approval for the embedded exact "
    "reference plan. It creates no run directory and launches no process. A future consumer "
    "must freshly recompute and match the complete plan immediately before atomic preparation. "
    "The request never authorizes Docker, Deformetrica, or other engine execution and does not "
    "validate parameters, convergence, registration, or biological interpretation."
)
VERIFICATION_SCHEMA_VERSION = "0.1"
VERIFICATION_STATUS = "verified_reference_preparation_approval"
VERIFICATION_BOUNDARY = (
    "This read-only verification proves the saved approval request is internally valid and "
    "unchanged during verification. When a current config is supplied, it also proves that a "
    "fresh read-only plan currently matches the approved embedded plan and has an absent "
    "destination. Verification creates no run, grants no preparation or execution permission, "
    "and makes no scientific claim."
)
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def _resource_schema(name: str) -> Mapping[str, Any]:
    resource = files("diffeoforge.schema").joinpath(name)
    return json.loads(resource.read_text(encoding="utf-8"))


def _validate_schema(value: Mapping[str, Any], name: str, label: str) -> None:
    validator = Draft202012Validator(_resource_schema(name))
    errors = sorted(validator.iter_errors(value), key=lambda error: list(error.path))
    if not errors:
        return
    first = errors[0]
    location = ".".join(str(part) for part in first.path) or "<root>"
    raise ConfigurationError(f"{label} schema violation at {location}: {first.message}")


def _normalize_fingerprint(value: str) -> str:
    if not isinstance(value, str):
        raise ConfigurationError("Approved plan fingerprint must be a string")
    normalized = value.strip().lower()
    if not _SHA256_PATTERN.fullmatch(normalized):
        raise ConfigurationError("Approved plan fingerprint must be exactly 64 hexadecimal digits")
    return normalized


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _read_required_file(path: Path, label: str) -> bytes:
    if not path.is_file():
        raise ConfigurationError(f"{label} is not a readable file: {path}")
    try:
        return path.read_bytes()
    except OSError as error:
        raise ConfigurationError(f"Could not read {label.lower()} {path}: {error}") from error


def _validate_request(request: Mapping[str, Any]) -> str:
    _validate_schema(
        request,
        "reference-preparation-approval-v0.1.json",
        "Reference preparation approval",
    )
    fingerprint = reference_preparation_plan_fingerprint(request["plan"])
    approved = str(request["approval"]["approved_plan_fingerprint"])
    if fingerprint != approved:
        raise ConfigurationError(
            "Embedded reference plan fingerprint does not match the approval; "
            f"approved {approved}, observed {fingerprint}"
        )
    return fingerprint


def create_reference_preparation_approval(
    config_path: Path | str,
    *,
    run_id: str,
    approved_fingerprint: str,
) -> dict[str, Any]:
    """Recompute one exact plan and bind explicit preparation-only approval to it."""

    normalized_approved = _normalize_fingerprint(approved_fingerprint)
    plan = plan_reference_preparation(config_path, run_id=run_id)
    observed = reference_preparation_plan_fingerprint(plan)
    if observed != normalized_approved:
        raise ConfigurationError(
            "Fresh reference preparation plan fingerprint differs from the explicitly approved "
            f"fingerprint; approved {normalized_approved}, observed {observed}"
        )
    request = {
        "schema_version": REQUEST_SCHEMA_VERSION,
        "status": REQUEST_STATUS,
        "approval": {
            "scope": APPROVAL_SCOPE,
            "statement": APPROVAL_STATEMENT,
            "approved_plan_fingerprint": normalized_approved,
            "engine_execution_authorized": False,
        },
        "plan": plan,
        "scientific_boundary": REQUEST_BOUNDARY,
    }
    _validate_request(request)
    return request


def serialize_reference_preparation_approval(request: Mapping[str, Any]) -> bytes:
    """Serialize one validated request as deterministic ASCII-safe JSON."""

    _validate_request(request)
    return (
        json.dumps(request, indent=2, ensure_ascii=True, sort_keys=True) + "\n"
    ).encode("ascii")


def write_reference_preparation_approval(
    request: Mapping[str, Any],
    output_path: Path | str,
) -> Path:
    """Write one request exclusively and never replace an existing path."""

    destination = Path(output_path).expanduser().resolve()
    payload = serialize_reference_preparation_approval(request)
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("xb") as handle:
            handle.write(payload)
    except FileExistsError as error:
        raise ConfigurationError(
            "Reference preparation approval already exists and will not be overwritten: "
            f"{destination}"
        ) from error
    except OSError as error:
        raise ConfigurationError(
            f"Could not write reference preparation approval {destination}: {error}"
        ) from error
    return destination


def load_saved_reference_preparation_approval(
    request_path: Path | str,
) -> tuple[dict[str, Any], bytes]:
    """Strictly load and validate one saved approval request without mutation."""

    source = Path(request_path).expanduser().resolve()
    request_bytes = _read_required_file(source, "Saved approval request")
    request = load_strict_json_object(
        request_bytes,
        source,
        label="Saved approval request",
    )
    _validate_request(request)
    return request, request_bytes


def verify_saved_reference_preparation_approval(
    request_path: Path | str,
    *,
    current_config_path: Path | str | None = None,
) -> dict[str, Any]:
    """Verify internal approval and optionally a freshly recomputed current plan."""

    source = Path(request_path).expanduser().resolve()
    request, request_bytes = load_saved_reference_preparation_approval(source)
    fingerprint = _validate_request(request)
    embedded_plan = request["plan"]

    current_state: dict[str, Any] | None = None
    if current_config_path is not None:
        current_config = Path(current_config_path).expanduser().resolve()
        current_plan = plan_reference_preparation(
            current_config,
            run_id=str(embedded_plan["run"]["run_id"]),
        )
        current_fingerprint = reference_preparation_plan_fingerprint(current_plan)
        if current_fingerprint != fingerprint:
            raise ConfigurationError(
                "Fresh current reference preparation plan does not match the approved plan; "
                f"approved {fingerprint}, current {current_fingerprint}"
            )
        current_state = {
            "config_path": str(current_config),
            "plan_fingerprint": current_fingerprint,
            "matches_approved_plan": True,
            "destination_absent": True,
        }

    checks = [
        "request_strict_utf8_single_json_document",
        "request_unique_object_keys_and_finite_constants",
        "request_schema_valid",
        "embedded_plan_schema_valid",
        "embedded_plan_matches_approved_fingerprint",
        "preparation_only_scope_and_no_engine_authorization",
    ]
    if current_state is not None:
        checks.append("fresh_current_plan_matches_approved_plan")
    checks.append("request_unchanged_during_verification")

    evidence = {
        "schema_version": VERIFICATION_SCHEMA_VERSION,
        "status": VERIFICATION_STATUS,
        "verifier": {"diffeoforge": __version__},
        "request": {
            "path": str(source),
            "bytes": len(request_bytes),
            "sha256": _sha256_bytes(request_bytes),
        },
        "approval": {
            "scope": str(request["approval"]["scope"]),
            "approved_plan_fingerprint": fingerprint,
            "engine_execution_authorized": False,
        },
        "recorded_plan": {
            "run_id": str(embedded_plan["run"]["run_id"]),
            "destination": str(embedded_plan["run"]["destination"]),
            "subjects": int(embedded_plan["input_count"]["subjects"]),
            "protected_files": int(embedded_plan["protected_file_count"]),
            "total_protected_bytes": int(embedded_plan["total_protected_bytes"]),
        },
        "current_state": current_state,
        "checks": checks,
        "scientific_boundary": VERIFICATION_BOUNDARY,
    }
    _validate_schema(
        evidence,
        "reference-preparation-approval-verification-v0.1.json",
        "Reference preparation approval verification",
    )
    if _read_required_file(source, "Saved approval request") != request_bytes:
        raise ConfigurationError(f"Saved approval request changed during verification: {source}")
    return evidence
