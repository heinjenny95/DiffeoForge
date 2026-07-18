"""Qt-independent desktop view of approval-bound preparation reconciliation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from diffeoforge.config import ConfigurationError
from diffeoforge.desktop.project_review import ProjectReviewResult
from diffeoforge.desktop.project_setup import DesktopEngine
from diffeoforge.reference_preparation_reconciliation import (
    reconcile_reference_preparation,
    serialize_reference_preparation_reconciliation,
    validate_reference_preparation_reconciliation,
    write_reference_preparation_reconciliation,
)


class DesktopReferencePreparationStatusError(RuntimeError):
    """Raised when a desktop status view cannot remain review-bound."""


class DesktopReferencePreparationStatusExportError(RuntimeError):
    """Raised when a reviewed status report cannot be exported safely."""


@dataclass(frozen=True)
class DesktopReferencePrivateStage:
    """One exact private-stage observation safe for bounded desktop display."""

    directory_name: str
    token: str
    path: Path
    status: str
    reason: str
    manifest_sha256: str | None
    engine_execution_started: bool | None


@dataclass(frozen=True)
class DesktopReferencePreparationStatus:
    """Bounded immutable desktop view of one versioned reconciliation report."""

    config_path: Path
    config_sha256: str
    approval_path: Path
    approval_sha256: str
    plan_fingerprint: str
    run_id: str
    status: str
    action_required: bool
    destination_path: Path
    destination_status: str
    destination_reason: str
    manifest_sha256: str | None
    engine_execution_started: bool | None
    private_stages: tuple[DesktopReferencePrivateStage, ...]
    state_stable_across_observations: bool
    mutation_performed: bool
    scientific_boundary: str
    report_schema_version: str
    report_bytes: bytes
    report_sha256: str

    def __post_init__(self) -> None:
        if self.mutation_performed:
            raise ValueError("Desktop preparation status must never report mutation")
        if not self.state_stable_across_observations:
            raise ValueError("Desktop preparation status requires a stable observation")
        if self.status not in {
            "clear_to_prepare",
            "published_prepared_not_executed_verified",
            "attention_required",
        }:
            raise ValueError(f"Unsupported preparation status: {self.status}")
        if self.action_required != (self.status == "attention_required"):
            raise ValueError("Preparation action_required does not match status")
        report = _validated_status_report(self.report_bytes, self.report_sha256)
        if self.report_schema_version != str(report["schema_version"]):
            raise ValueError("Desktop preparation status schema does not match report")
        approval = report["approval_request"]
        approved_plan = report["approved_plan"]
        current_plan = report["current_plan"]
        destination = report["destination"]
        bindings = (
            self.config_path,
            self.config_sha256,
            self.approval_path,
            self.approval_sha256,
            self.plan_fingerprint,
            self.run_id,
            self.status,
            self.action_required,
            self.destination_path,
            self.destination_status,
            self.destination_reason,
            self.manifest_sha256,
            self.engine_execution_started,
            self.private_stages,
            self.state_stable_across_observations,
            self.mutation_performed,
            self.scientific_boundary,
        )
        report_bindings = (
            Path(str(current_plan["config_path"])),
            str(current_plan["config_sha256"]),
            Path(str(approval["path"])),
            str(approval["sha256"]),
            str(approved_plan["canonical_fingerprint"]),
            str(approved_plan["run_id"]),
            str(report["status"]),
            bool(report["action_required"]),
            Path(str(destination["path"])),
            str(destination["status"]),
            str(destination["reason"]),
            (
                str(destination["manifest_sha256"])
                if destination["manifest_sha256"] is not None
                else None
            ),
            destination["engine_execution_started"],
            tuple(_private_stage(stage) for stage in report["private_stages"]),
            bool(report["state_stable_across_observations"]),
            bool(report["mutation_performed"]),
            str(report["scientific_boundary"]),
        )
        if bindings != report_bindings:
            raise ValueError("Desktop preparation status fields do not match report")
        if (
            str(approval["expected_sha256"]) != self.approval_sha256
            or Path(str(approved_plan["destination"])) != self.destination_path
            or str(current_plan["canonical_fingerprint"]) != self.plan_fingerprint
            or current_plan["exactly_matches_approved"] is not True
        ):
            raise ValueError("Desktop preparation status report bindings are inconsistent")

    @property
    def report_byte_count(self) -> int:
        """Return the exact number of bytes available for export."""

        return len(self.report_bytes)


@dataclass(frozen=True)
class DesktopReferencePreparationStatusExport:
    """Evidence for one non-overwriting deterministic JSON export."""

    path: Path
    byte_count: int
    sha256: str
    schema_version: str

    def __post_init__(self) -> None:
        if self.byte_count < 2:
            raise ValueError("Exported preparation status report is unexpectedly short")
        if len(self.sha256) != 64 or any(
            character not in "0123456789abcdef" for character in self.sha256
        ):
            raise ValueError("Exported preparation status report has an invalid SHA-256")


def _reject_nonfinite_json(value: str) -> None:
    raise ValueError(f"Non-finite JSON constant is not allowed: {value}")


def _validated_status_report(report_bytes: bytes, expected_sha256: str) -> dict[str, Any]:
    if not isinstance(report_bytes, bytes):
        raise ValueError("Desktop preparation status report must be immutable bytes")
    observed_sha256 = hashlib.sha256(report_bytes).hexdigest()
    if observed_sha256 != expected_sha256:
        raise ValueError("Desktop preparation status report SHA-256 does not match bytes")
    try:
        value = json.loads(report_bytes, parse_constant=_reject_nonfinite_json)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise ValueError(f"Desktop preparation status report is invalid JSON: {error}") from error
    if not isinstance(value, dict):
        raise ValueError("Desktop preparation status report must be a JSON object")
    try:
        validate_reference_preparation_reconciliation(value)
    except (ConfigurationError, TypeError, ValueError) as error:
        raise ValueError(f"Desktop preparation status report is invalid: {error}") from error
    if serialize_reference_preparation_reconciliation(value) != report_bytes:
        raise ValueError("Desktop preparation status report is not deterministic serialization")
    return value


def _reviewed_config_bytes(review: ProjectReviewResult) -> bytes:
    try:
        content = review.config_path.read_bytes()
    except OSError as error:
        raise DesktopReferencePreparationStatusError(
            f"Reviewed configuration is no longer readable: {error}"
        ) from error
    observed = hashlib.sha256(content).hexdigest()
    if observed != review.config_sha256:
        raise DesktopReferencePreparationStatusError(
            "Project configuration changed after parameter review; review it again "
            "before checking preparation status"
        )
    return content


def _private_stage(value: dict[str, Any]) -> DesktopReferencePrivateStage:
    return DesktopReferencePrivateStage(
        directory_name=str(value["directory_name"]),
        token=str(value["token"]),
        path=Path(str(value["path"])),
        status=str(value["status"]),
        reason=str(value["reason"]),
        manifest_sha256=(
            str(value["manifest_sha256"])
            if value["manifest_sha256"] is not None
            else None
        ),
        engine_execution_started=value["engine_execution_started"],
    )


def review_reference_preparation_status(
    review: ProjectReviewResult,
    approval_path: Path | str,
    expected_approval_sha256: str,
) -> DesktopReferencePreparationStatus:
    """Reconcile one approval for the exact reviewed config without mutation."""

    if not isinstance(review, ProjectReviewResult):
        raise TypeError("review must be a ProjectReviewResult")
    if review.engine is not DesktopEngine.DEFORMETRICA_REFERENCE:
        raise DesktopReferencePreparationStatusError(
            "Preparation status requires a Deformetrica reference review"
        )
    config_content = _reviewed_config_bytes(review)
    report = reconcile_reference_preparation(
        approval_path,
        current_config_path=review.config_path,
        expected_request_sha256=expected_approval_sha256,
    )
    if review.config_path.read_bytes() != config_content:
        raise DesktopReferencePreparationStatusError(
            "Project configuration changed while preparation status was checked; "
            "discarding the result"
        )
    if report.get("mutation_performed") is not False:
        raise DesktopReferencePreparationStatusError(
            "Preparation reconciliation did not preserve the read-only contract"
        )
    current_plan = report["current_plan"]
    if (
        Path(str(current_plan["config_path"])) != review.config_path.resolve()
        or str(current_plan["config_sha256"]) != review.config_sha256
    ):
        raise DesktopReferencePreparationStatusError(
            "Preparation reconciliation is not bound to the reviewed configuration"
        )
    approval = report["approval_request"]
    destination = report["destination"]
    report_bytes = serialize_reference_preparation_reconciliation(report)
    try:
        return DesktopReferencePreparationStatus(
            config_path=review.config_path.resolve(),
            config_sha256=review.config_sha256,
            approval_path=Path(str(approval["path"])),
            approval_sha256=str(approval["sha256"]),
            plan_fingerprint=str(report["approved_plan"]["canonical_fingerprint"]),
            run_id=str(report["approved_plan"]["run_id"]),
            status=str(report["status"]),
            action_required=bool(report["action_required"]),
            destination_path=Path(str(destination["path"])),
            destination_status=str(destination["status"]),
            destination_reason=str(destination["reason"]),
            manifest_sha256=(
                str(destination["manifest_sha256"])
                if destination["manifest_sha256"] is not None
                else None
            ),
            engine_execution_started=destination["engine_execution_started"],
            private_stages=tuple(
                _private_stage(stage) for stage in report["private_stages"]
            ),
            state_stable_across_observations=bool(
                report["state_stable_across_observations"]
            ),
            mutation_performed=bool(report["mutation_performed"]),
            scientific_boundary=str(report["scientific_boundary"]),
            report_schema_version=str(report["schema_version"]),
            report_bytes=report_bytes,
            report_sha256=hashlib.sha256(report_bytes).hexdigest(),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise DesktopReferencePreparationStatusError(
            f"Preparation reconciliation returned an invalid desktop view: {error}"
        ) from error


def export_reference_preparation_status_report(
    status: DesktopReferencePreparationStatus,
    destination: Path | str,
) -> DesktopReferencePreparationStatusExport:
    """Write one exact reviewed report to a new user-selected JSON file."""

    if not isinstance(status, DesktopReferencePreparationStatus):
        raise TypeError("status must be a DesktopReferencePreparationStatus")
    report = _validated_status_report(status.report_bytes, status.report_sha256)
    try:
        target = write_reference_preparation_reconciliation(report, destination)
        observed = target.read_bytes()
    except ConfigurationError as error:
        raise DesktopReferencePreparationStatusExportError(
            f"Could not export preparation status report: {error}"
        ) from error
    except OSError as error:
        raise DesktopReferencePreparationStatusExportError(
            f"Could not reread preparation status export: {error}"
        ) from error
    if observed != status.report_bytes:
        raise DesktopReferencePreparationStatusExportError(
            f"Preparation status export did not preserve exact bytes: {target}"
        )
    return DesktopReferencePreparationStatusExport(
        path=target,
        byte_count=len(observed),
        sha256=hashlib.sha256(observed).hexdigest(),
        schema_version=str(report["schema_version"]),
    )
