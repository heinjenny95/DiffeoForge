"""Atomic preparation of one externally bound reference approval request."""

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
from diffeoforge.reference_preparation_approval import (
    load_saved_reference_preparation_approval,
)
from diffeoforge.reference_preparation_plan import (
    plan_reference_preparation,
    reference_preparation_plan_fingerprint,
)
from diffeoforge.runs import prepare_run_against_plan, verify_prepared_run

SCHEMA_VERSION = "0.1"
STATUS = "prepared_approved_reference_run_not_executed"
SCIENTIFIC_BOUNDARY = (
    "This evidence proves that one immutable reference run was atomically prepared from "
    "private staging that exactly matched an externally hash-bound approval request and "
    "that its prepared lifecycle and pristine output were verified before returning. It "
    "does not identify the approver, authorize or prove engine execution, validate scientific "
    "parameters, establish convergence or registration quality, or support biological "
    "interpretation."
)
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def _schema() -> Mapping[str, Any]:
    resource = files("diffeoforge.schema").joinpath(
        "reference-approved-preparation-v0.1.json"
    )
    return json.loads(resource.read_text(encoding="utf-8"))


def _validate_evidence(value: Mapping[str, Any]) -> None:
    validator = Draft202012Validator(_schema())
    errors = sorted(validator.iter_errors(value), key=lambda error: list(error.path))
    if not errors:
        return
    first = errors[0]
    location = ".".join(str(part) for part in first.path) or "<root>"
    raise ConfigurationError(
        f"Approved reference preparation evidence schema violation at {location}: "
        f"{first.message}"
    )


def _normalize_sha256(value: str) -> str:
    if not isinstance(value, str):
        raise ConfigurationError("Expected approval request SHA-256 must be a string")
    normalized = value.strip().lower()
    if not _SHA256_PATTERN.fullmatch(normalized):
        raise ConfigurationError(
            "Expected approval request SHA-256 must be exactly 64 hexadecimal digits"
        )
    return normalized


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _read_request_bytes(path: Path) -> bytes:
    if not path.is_file():
        raise ConfigurationError(f"Saved approval request is not a readable file: {path}")
    try:
        return path.read_bytes()
    except OSError as error:
        raise ConfigurationError(
            f"Could not reread saved approval request {path}: {error}"
        ) from error


def prepare_approved_reference_run(
    request_path: Path | str,
    *,
    current_config_path: Path | str,
    expected_request_sha256: str,
) -> dict[str, Any]:
    """Prepare exactly one approved plan and stop with pristine unexecuted output."""

    source = Path(request_path).expanduser().resolve()
    current_config = Path(current_config_path).expanduser().resolve()
    expected_request_hash = _normalize_sha256(expected_request_sha256)
    request, request_bytes = load_saved_reference_preparation_approval(source)
    observed_request_hash = _sha256_bytes(request_bytes)
    if observed_request_hash != expected_request_hash:
        raise ConfigurationError(
            "Saved approval request does not match the independently recorded SHA-256; "
            f"expected {expected_request_hash}, observed {observed_request_hash}"
        )

    approved_plan = request["plan"]
    approved_plan_fingerprint = reference_preparation_plan_fingerprint(approved_plan)
    fresh_plan = plan_reference_preparation(
        current_config,
        run_id=str(approved_plan["run"]["run_id"]),
    )
    fresh_fingerprint = reference_preparation_plan_fingerprint(fresh_plan)
    if fresh_fingerprint != approved_plan_fingerprint or fresh_plan != approved_plan:
        raise ConfigurationError(
            "Fresh current reference preparation plan does not exactly match the approved "
            f"plan; approved {approved_plan_fingerprint}, current {fresh_fingerprint}"
        )
    if _read_request_bytes(source) != request_bytes:
        raise ConfigurationError(
            f"Saved approval request changed before private staging began: {source}"
        )

    evidence_holder: dict[str, dict[str, Any]] = {}

    def before_publish(temp_directory: Path, manifest: Mapping[str, Any]) -> None:
        if _read_request_bytes(source) != request_bytes:
            raise ConfigurationError(
                f"Saved approval request changed before atomic publication: {source}"
            )
        manifest_path = temp_directory / "manifest.json"
        manifest_bytes = manifest_path.read_bytes()
        evidence = {
            "schema_version": SCHEMA_VERSION,
            "status": STATUS,
            "preparer": {"diffeoforge": __version__},
            "approval_request": {
                "path": str(source),
                "bytes": len(request_bytes),
                "sha256": observed_request_hash,
                "expected_sha256": expected_request_hash,
            },
            "approved_plan": {
                "canonical_fingerprint": approved_plan_fingerprint,
                "run_id": str(approved_plan["run"]["run_id"]),
                "destination": str(approved_plan["run"]["destination"]),
                "subjects": int(approved_plan["input_count"]["subjects"]),
                "protected_files": int(approved_plan["protected_file_count"]),
                "total_protected_bytes": int(approved_plan["total_protected_bytes"]),
            },
            "prepared_run": {
                "path": str(approved_plan["run"]["destination"]),
                "manifest_path": str(
                    Path(str(approved_plan["run"]["destination"])) / "manifest.json"
                ),
                "manifest_bytes": len(manifest_bytes),
                "manifest_sha256": _sha256_bytes(manifest_bytes),
                "protected_files": len(manifest["protected_artifacts"]),
                "lifecycle_last_event": "prepared",
                "output_empty": True,
                "engine_execution_started": False,
            },
            "checks": [
                "approval_request_strict_and_schema_valid",
                "approval_request_matches_external_sha256",
                "embedded_plan_matches_approval_fingerprint",
                "fresh_current_plan_exactly_matches_approved_plan",
                "private_stage_exactly_matches_approved_protected_bytes",
                "approval_request_unchanged_before_atomic_publication",
                "destination_published_atomically_without_replace",
                "prepared_manifest_and_protected_files_verified",
                "prepared_lifecycle_has_no_execution_event",
                "prepared_output_is_pristine",
            ],
            "scientific_boundary": SCIENTIFIC_BOUNDARY,
        }
        _validate_evidence(evidence)
        evidence_holder["evidence"] = evidence

    run_directory = prepare_run_against_plan(
        current_config,
        approved_plan,
        before_publish=before_publish,
    )
    verified_manifest = verify_prepared_run(run_directory)
    evidence = evidence_holder.get("evidence")
    if evidence is None:
        raise ConfigurationError("Approved preparation produced no prepublication evidence")
    manifest_path = run_directory / "manifest.json"
    if _sha256_bytes(manifest_path.read_bytes()) != evidence["prepared_run"][
        "manifest_sha256"
    ]:
        raise ConfigurationError(
            f"Prepared manifest changed after atomic publication: {manifest_path}"
        )
    if len(verified_manifest["protected_artifacts"]) != evidence["prepared_run"][
        "protected_files"
    ]:
        raise ConfigurationError(
            "Prepared protected-file inventory changed after atomic publication"
        )
    return evidence
