"""Qt-independent desktop view of one verified saved preparation status report."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from diffeoforge.config import ConfigurationError
from diffeoforge.reference_preparation_reconciliation_verification import (
    CHECKS,
    STATUS,
    serialize_reference_preparation_reconciliation_verification,
    verify_saved_reference_preparation_reconciliation,
    write_reference_preparation_reconciliation_verification,
)
from diffeoforge.strict_json import load_strict_json_object

_REPORT_STATUSES = {
    "clear_to_prepare",
    "published_prepared_not_executed_verified",
    "attention_required",
}
_DESTINATION_STATUSES = {
    "absent",
    "verified_prepared_not_executed",
    "unsafe_link",
    "unsafe_content_link",
    "not_directory",
    "incomplete_or_mismatched",
}


class DesktopSavedReferencePreparationStatusVerificationError(RuntimeError):
    """Raised when saved status evidence cannot be presented safely."""


class DesktopSavedReferencePreparationStatusVerificationExportError(RuntimeError):
    """Raised when verified evidence cannot be exported safely."""


def _valid_sha256(value: str) -> bool:
    return len(value) == 64 and all(
        character in "0123456789abcdef" for character in value
    )


@dataclass(frozen=True)
class DesktopSavedReferencePreparationStatusVerification:
    """Bounded immutable desktop view of saved-report verification evidence."""

    report_path: Path
    report_byte_count: int
    report_sha256: str
    expected_report_sha256: str
    report_schema_version: str
    report_status: str
    action_required: bool
    mutation_performed: bool
    state_stable_across_observations: bool
    matches_deterministic_serialization: bool
    run_id: str
    approval_sha256: str
    plan_fingerprint: str
    destination_status: str
    manifest_sha256: str | None
    engine_execution_started: bool | None
    private_stage_count: int
    verification_schema_version: str
    verification_status: str
    verifier_version: str
    checks: tuple[str, ...]
    scientific_boundary: str
    evidence_bytes: bytes
    evidence_sha256: str

    def __post_init__(self) -> None:
        if not self.report_path.is_absolute():
            raise ValueError("Saved status report path must be absolute")
        if self.report_byte_count < 2:
            raise ValueError("Saved status report is unexpectedly short")
        if not _valid_sha256(self.report_sha256):
            raise ValueError("Saved status report SHA-256 is invalid")
        if self.expected_report_sha256 != self.report_sha256:
            raise ValueError("Expected and observed saved status hashes do not match")
        if self.report_schema_version != "0.1":
            raise ValueError("Unsupported saved preparation status schema")
        if self.report_status not in _REPORT_STATUSES:
            raise ValueError("Unsupported saved preparation status")
        if self.action_required != (self.report_status == "attention_required"):
            raise ValueError("Saved status action flag does not match its status")
        if self.mutation_performed:
            raise ValueError("Saved status verification must never report mutation")
        if not self.state_stable_across_observations:
            raise ValueError("Saved status report must record a stable observation")
        if not self.matches_deterministic_serialization:
            raise ValueError("Saved status report must match deterministic serialization")
        if not self.run_id:
            raise ValueError("Saved status verification requires a run ID")
        if not _valid_sha256(self.approval_sha256):
            raise ValueError("Recorded approval SHA-256 is invalid")
        if not _valid_sha256(self.plan_fingerprint):
            raise ValueError("Recorded plan fingerprint is invalid")
        if self.destination_status not in _DESTINATION_STATUSES:
            raise ValueError("Unsupported recorded destination status")
        if self.manifest_sha256 is not None and not _valid_sha256(
            self.manifest_sha256
        ):
            raise ValueError("Recorded manifest SHA-256 is invalid")
        if self.engine_execution_started not in {None, False}:
            raise ValueError("Saved status verifier cannot present an engine start")
        if self.private_stage_count < 0:
            raise ValueError("Recorded private-stage count cannot be negative")
        if self.verification_schema_version != "0.1":
            raise ValueError("Unsupported saved status verification schema")
        if self.verification_status != STATUS:
            raise ValueError("Unsupported saved status verification result")
        if not self.verifier_version:
            raise ValueError("Saved status verification requires a verifier version")
        if self.checks != CHECKS:
            raise ValueError("Saved status verification checks are incomplete")
        if not self.scientific_boundary:
            raise ValueError("Saved status verification requires an explicit boundary")
        evidence = _validated_evidence(self.evidence_bytes, self.evidence_sha256)
        report = evidence["report"]
        recorded = evidence["recorded_observation"]
        bindings = (
            self.report_path,
            self.report_byte_count,
            self.report_sha256,
            self.expected_report_sha256,
            self.report_schema_version,
            self.report_status,
            self.action_required,
            self.mutation_performed,
            self.state_stable_across_observations,
            self.matches_deterministic_serialization,
            self.run_id,
            self.approval_sha256,
            self.plan_fingerprint,
            self.destination_status,
            self.manifest_sha256,
            self.engine_execution_started,
            self.private_stage_count,
            self.verification_schema_version,
            self.verification_status,
            self.verifier_version,
            self.checks,
            self.scientific_boundary,
        )
        evidence_bindings = (
            Path(str(report["path"])),
            int(report["bytes"]),
            str(report["sha256"]),
            str(report["expected_sha256"]),
            str(report["schema_version"]),
            str(report["status"]),
            bool(report["action_required"]),
            bool(report["mutation_performed"]),
            bool(report["state_stable_across_observations"]),
            bool(report["matches_deterministic_serialization"]),
            str(recorded["run_id"]),
            str(recorded["approval_sha256"]),
            str(recorded["plan_fingerprint"]),
            str(recorded["destination_status"]),
            (
                str(recorded["manifest_sha256"])
                if recorded["manifest_sha256"] is not None
                else None
            ),
            recorded["engine_execution_started"],
            int(recorded["private_stage_count"]),
            str(evidence["schema_version"]),
            str(evidence["status"]),
            str(evidence["verifier"]["diffeoforge"]),
            tuple(str(check) for check in evidence["checks"]),
            str(evidence["scientific_boundary"]),
        )
        if bindings != evidence_bindings:
            raise ValueError("Desktop saved status fields do not match evidence bytes")

    @property
    def evidence_byte_count(self) -> int:
        """Return the exact number of verified evidence bytes available for export."""

        return len(self.evidence_bytes)


@dataclass(frozen=True)
class DesktopSavedReferencePreparationStatusVerificationExport:
    """Evidence for one non-overwriting deterministic verification export."""

    path: Path
    byte_count: int
    sha256: str
    schema_version: str

    def __post_init__(self) -> None:
        if self.byte_count < 2:
            raise ValueError("Exported saved status verification is unexpectedly short")
        if not _valid_sha256(self.sha256):
            raise ValueError("Exported saved status verification SHA-256 is invalid")


def _validated_evidence(
    evidence_bytes: bytes,
    expected_sha256: str,
) -> dict[str, Any]:
    if not isinstance(evidence_bytes, bytes):
        raise ValueError("Desktop saved status evidence must be immutable bytes")
    observed_sha256 = hashlib.sha256(evidence_bytes).hexdigest()
    if observed_sha256 != expected_sha256:
        raise ValueError("Desktop saved status evidence SHA-256 does not match bytes")
    try:
        evidence = load_strict_json_object(
            evidence_bytes,
            Path("<desktop-saved-status-verification>"),
            label="Desktop saved status verification evidence",
        )
        deterministic = serialize_reference_preparation_reconciliation_verification(
            evidence
        )
    except (ConfigurationError, TypeError, ValueError) as error:
        raise ValueError(f"Desktop saved status evidence is invalid: {error}") from error
    if deterministic != evidence_bytes:
        raise ValueError(
            "Desktop saved status evidence is not deterministic serialization"
        )
    return evidence


def review_saved_reference_preparation_status(
    report_path: Path | str,
    expected_report_sha256: str,
) -> DesktopSavedReferencePreparationStatusVerification:
    """Verify one saved report and map only bounded evidence for desktop display."""

    try:
        evidence = verify_saved_reference_preparation_reconciliation(
            report_path,
            expected_report_sha256=expected_report_sha256,
        )
        report = evidence["report"]
        recorded = evidence["recorded_observation"]
        evidence_bytes = serialize_reference_preparation_reconciliation_verification(
            evidence
        )
        return DesktopSavedReferencePreparationStatusVerification(
            report_path=Path(str(report["path"])),
            report_byte_count=int(report["bytes"]),
            report_sha256=str(report["sha256"]),
            expected_report_sha256=str(report["expected_sha256"]),
            report_schema_version=str(report["schema_version"]),
            report_status=str(report["status"]),
            action_required=bool(report["action_required"]),
            mutation_performed=bool(report["mutation_performed"]),
            state_stable_across_observations=bool(
                report["state_stable_across_observations"]
            ),
            matches_deterministic_serialization=bool(
                report["matches_deterministic_serialization"]
            ),
            run_id=str(recorded["run_id"]),
            approval_sha256=str(recorded["approval_sha256"]),
            plan_fingerprint=str(recorded["plan_fingerprint"]),
            destination_status=str(recorded["destination_status"]),
            manifest_sha256=(
                str(recorded["manifest_sha256"])
                if recorded["manifest_sha256"] is not None
                else None
            ),
            engine_execution_started=recorded["engine_execution_started"],
            private_stage_count=int(recorded["private_stage_count"]),
            verification_schema_version=str(evidence["schema_version"]),
            verification_status=str(evidence["status"]),
            verifier_version=str(evidence["verifier"]["diffeoforge"]),
            checks=tuple(str(check) for check in evidence["checks"]),
            scientific_boundary=str(evidence["scientific_boundary"]),
            evidence_bytes=evidence_bytes,
            evidence_sha256=hashlib.sha256(evidence_bytes).hexdigest(),
        )
    except (
        ConfigurationError,
        KeyError,
        OSError,
        TypeError,
        ValueError,
    ) as error:
        raise DesktopSavedReferencePreparationStatusVerificationError(
            f"Saved preparation status report is not safely verifiable: {error}"
        ) from error


def export_saved_reference_preparation_status_verification(
    result: DesktopSavedReferencePreparationStatusVerification,
    destination: Path | str,
) -> DesktopSavedReferencePreparationStatusVerificationExport:
    """Write exact already-validated evidence to one new user-selected file."""

    if not isinstance(result, DesktopSavedReferencePreparationStatusVerification):
        raise TypeError(
            "result must be a DesktopSavedReferencePreparationStatusVerification"
        )
    evidence = _validated_evidence(result.evidence_bytes, result.evidence_sha256)
    try:
        target = write_reference_preparation_reconciliation_verification(
            evidence,
            destination,
        )
        observed = target.read_bytes()
    except ConfigurationError as error:
        raise DesktopSavedReferencePreparationStatusVerificationExportError(
            f"Could not export saved status verification evidence: {error}"
        ) from error
    except OSError as error:
        raise DesktopSavedReferencePreparationStatusVerificationExportError(
            f"Could not reread saved status verification export: {error}"
        ) from error
    if observed != result.evidence_bytes:
        raise DesktopSavedReferencePreparationStatusVerificationExportError(
            f"Saved status verification export did not preserve exact bytes: {target}"
        )
    return DesktopSavedReferencePreparationStatusVerificationExport(
        path=target,
        byte_count=len(observed),
        sha256=hashlib.sha256(observed).hexdigest(),
        schema_version=result.verification_schema_version,
    )
