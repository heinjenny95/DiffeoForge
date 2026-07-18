"""Strict read-only verification of one saved preparation reconciliation report."""

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
from diffeoforge.reference_preparation_reconciliation import (
    serialize_reference_preparation_reconciliation,
    validate_reference_preparation_reconciliation,
)
from diffeoforge.strict_json import load_strict_json_object

SCHEMA_VERSION = "0.1"
STATUS = "verified_saved_reference_preparation_reconciliation"
CHECKS = (
    "report_strict_utf8_single_json_document",
    "report_unique_object_keys_and_finite_constants",
    "report_matches_external_sha256",
    "report_schema_valid",
    "report_matches_deterministic_serialization",
    "report_records_read_only_stable_observation",
    "report_unchanged_during_verification",
)
SCIENTIFIC_BOUNDARY = (
    "This read-only verification proves only that one saved report is a strict UTF-8 JSON "
    "document matching an independently supplied complete-file SHA-256, the supported "
    "reconciliation schema, and the exact deterministic DiffeoForge serialization, and "
    "that it remained unchanged during verification. It reads no current config, mesh, "
    "destination, private stage, process, container, or engine state. Recorded paths and "
    "file names remain private provenance. Verification does not prove that recorded state "
    "is still current, that preparation, publication, recovery, or execution is safe, or "
    "that parameters, numerical results, registration, atlas quality, or biological "
    "interpretation are valid."
)
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def _schema() -> Mapping[str, Any]:
    resource = files("diffeoforge.schema").joinpath(
        "reference-preparation-reconciliation-verification-v0.1.json"
    )
    return json.loads(resource.read_text(encoding="utf-8"))


def _validate_evidence(evidence: Mapping[str, Any]) -> None:
    errors = sorted(
        Draft202012Validator(_schema()).iter_errors(evidence),
        key=lambda error: list(error.path),
    )
    if not errors:
        return
    first = errors[0]
    location = ".".join(str(part) for part in first.path) or "<root>"
    raise ConfigurationError(
        "Reference preparation reconciliation verification schema violation at "
        f"{location}: {first.message}"
    )


def _normalize_expected_sha256(value: str) -> str:
    if not isinstance(value, str):
        raise ConfigurationError("Expected report SHA-256 must be a string")
    normalized = value.strip().lower()
    if not _SHA256_PATTERN.fullmatch(normalized):
        raise ConfigurationError(
            "Expected report SHA-256 must be exactly 64 hexadecimal digits"
        )
    return normalized


def _read_required_file(path: Path) -> bytes:
    if not path.is_file():
        raise ConfigurationError(f"Saved reconciliation report is not a readable file: {path}")
    try:
        return path.read_bytes()
    except OSError as error:
        raise ConfigurationError(
            f"Could not read saved reconciliation report {path}: {error}"
        ) from error


def verify_saved_reference_preparation_reconciliation(
    report_path: Path | str,
    *,
    expected_report_sha256: str,
) -> dict[str, Any]:
    """Verify one saved deterministic reconciliation report without external-state reads."""

    source = Path(report_path).expanduser().resolve()
    expected_sha256 = _normalize_expected_sha256(expected_report_sha256)
    report_bytes = _read_required_file(source)
    observed_sha256 = hashlib.sha256(report_bytes).hexdigest()
    if observed_sha256 != expected_sha256:
        raise ConfigurationError(
            "Saved reconciliation report does not match the independently recorded "
            f"SHA-256; expected {expected_sha256}, observed {observed_sha256}"
        )

    report = load_strict_json_object(
        report_bytes,
        source,
        label="Saved reconciliation report",
    )
    validate_reference_preparation_reconciliation(report)
    deterministic = serialize_reference_preparation_reconciliation(report)
    if deterministic != report_bytes:
        raise ConfigurationError(
            "Saved reconciliation report does not exactly match the deterministic "
            f"DiffeoForge serialization: {source}"
        )
    if (
        report["mutation_performed"] is not False
        or report["state_stable_across_observations"] is not True
    ):
        raise ConfigurationError(
            "Saved reconciliation report does not record a stable read-only observation"
        )

    destination = report["destination"]
    evidence = {
        "schema_version": SCHEMA_VERSION,
        "status": STATUS,
        "verifier": {"diffeoforge": __version__},
        "report": {
            "path": str(source),
            "bytes": len(report_bytes),
            "sha256": observed_sha256,
            "expected_sha256": expected_sha256,
            "schema_version": str(report["schema_version"]),
            "status": str(report["status"]),
            "action_required": bool(report["action_required"]),
            "mutation_performed": False,
            "state_stable_across_observations": True,
            "matches_deterministic_serialization": True,
        },
        "recorded_observation": {
            "run_id": str(report["approved_plan"]["run_id"]),
            "approval_sha256": str(report["approval_request"]["sha256"]),
            "plan_fingerprint": str(
                report["approved_plan"]["canonical_fingerprint"]
            ),
            "destination_status": str(destination["status"]),
            "manifest_sha256": (
                str(destination["manifest_sha256"])
                if destination["manifest_sha256"] is not None
                else None
            ),
            "engine_execution_started": destination["engine_execution_started"],
            "private_stage_count": len(report["private_stages"]),
        },
        "checks": list(CHECKS),
        "scientific_boundary": SCIENTIFIC_BOUNDARY,
    }
    _validate_evidence(evidence)
    if _read_required_file(source) != report_bytes:
        raise ConfigurationError(
            f"Saved reconciliation report changed during verification: {source}"
        )
    return evidence
