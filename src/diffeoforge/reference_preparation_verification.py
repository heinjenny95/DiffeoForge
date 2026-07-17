"""Strict read-only verification of saved reference preparation review artifacts."""

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
    reference_preparation_plan_fingerprint,
    render_reference_preparation_plan_html,
)
from diffeoforge.strict_json import load_strict_json_object

SCHEMA_VERSION = "0.1"
STATUS = "verified_saved_reference_preparation_plan"
SCIENTIFIC_BOUNDARY = (
    "This read-only verification proves that the saved plan is one strict UTF-8 JSON "
    "document satisfying the supported schema and that any supplied HTML is its exact "
    "deterministic DiffeoForge rendering. An optional expected fingerprint binds the plan "
    "to an external record. Verification does not prove that source config or mesh files "
    "still match, that the recorded destination is currently absent, that preparation or "
    "execution occurred, or that parameters, convergence, registration, or biological "
    "interpretation are valid."
)
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def _schema() -> Mapping[str, Any]:
    resource = files("diffeoforge.schema").joinpath(
        "reference-preparation-plan-verification-v0.1.json"
    )
    return json.loads(resource.read_text(encoding="utf-8"))


def _validate_verification(evidence: Mapping[str, Any]) -> None:
    validator = Draft202012Validator(_schema())
    errors = sorted(validator.iter_errors(evidence), key=lambda error: list(error.path))
    if not errors:
        return
    first = errors[0]
    location = ".".join(str(part) for part in first.path) or "<root>"
    raise ConfigurationError(
        f"Reference preparation verification schema violation at {location}: {first.message}"
    )


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _read_required_file(path: Path, label: str) -> bytes:
    if not path.is_file():
        raise ConfigurationError(f"{label} is not a readable file: {path}")
    try:
        return path.read_bytes()
    except OSError as error:
        raise ConfigurationError(f"Could not read {label.lower()} {path}: {error}") from error


def _normalize_expected_fingerprint(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if not _SHA256_PATTERN.fullmatch(normalized):
        raise ConfigurationError("Expected plan fingerprint must be exactly 64 hexadecimal digits")
    return normalized


def verify_saved_reference_preparation_plan(
    plan_path: Path | str,
    *,
    report_path: Path | str | None = None,
    expected_fingerprint: str | None = None,
) -> dict[str, Any]:
    """Verify saved plan JSON and optional HTML without modifying either artifact."""

    source = Path(plan_path).expanduser().resolve()
    report = Path(report_path).expanduser().resolve() if report_path is not None else None
    normalized_expected = _normalize_expected_fingerprint(expected_fingerprint)

    plan_bytes = _read_required_file(source, "Saved plan")
    plan = load_strict_json_object(plan_bytes, source, label="Saved plan")
    fingerprint = reference_preparation_plan_fingerprint(plan)
    if normalized_expected is not None and fingerprint != normalized_expected:
        raise ConfigurationError(
            "Saved plan canonical fingerprint mismatch; "
            f"expected {normalized_expected}, observed {fingerprint}"
        )

    report_bytes: bytes | None = None
    report_record: dict[str, Any] | None = None
    if report is not None:
        report_bytes = _read_required_file(report, "Saved HTML report")
        expected_report = render_reference_preparation_plan_html(plan).encode("utf-8")
        if report_bytes != expected_report:
            raise ConfigurationError(
                "Saved HTML report does not exactly match deterministic regeneration "
                f"from the saved plan: {report}"
            )
        report_record = {
            "path": str(report),
            "bytes": len(report_bytes),
            "sha256": _sha256_bytes(report_bytes),
            "matches_deterministic_regeneration": True,
        }

    checks = [
        "plan_strict_utf8_single_json_document",
        "plan_unique_object_keys_and_finite_constants",
        "plan_schema_valid",
        "plan_canonical_fingerprint_computed",
    ]
    if normalized_expected is not None:
        checks.append("plan_fingerprint_matches_expected")
    if report is not None:
        checks.append("report_exact_deterministic_regeneration")
    checks.append("supplied_artifacts_unchanged_during_verification")

    evidence = {
        "schema_version": SCHEMA_VERSION,
        "status": STATUS,
        "verifier": {"diffeoforge": __version__},
        "plan": {
            "path": str(source),
            "bytes": len(plan_bytes),
            "sha256": _sha256_bytes(plan_bytes),
            "canonical_fingerprint": fingerprint,
            "expected_fingerprint": normalized_expected,
        },
        "report": report_record,
        "recorded_plan": {
            "schema_version": str(plan["schema_version"]),
            "run_id": str(plan["run"]["run_id"]),
            "destination": str(plan["run"]["destination"]),
            "templates": int(plan["input_count"]["templates"]),
            "subjects": int(plan["input_count"]["subjects"]),
            "protected_files": int(plan["protected_file_count"]),
            "total_protected_bytes": int(plan["total_protected_bytes"]),
        },
        "checks": checks,
        "scientific_boundary": SCIENTIFIC_BOUNDARY,
    }
    _validate_verification(evidence)

    if _read_required_file(source, "Saved plan") != plan_bytes:
        raise ConfigurationError(f"Saved plan changed during verification: {source}")
    if report is not None and _read_required_file(report, "Saved HTML report") != report_bytes:
        raise ConfigurationError(f"Saved HTML report changed during verification: {report}")
    return evidence
