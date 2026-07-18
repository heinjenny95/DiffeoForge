"""Qt-independent desktop view of approval-bound preparation reconciliation."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from diffeoforge.desktop.project_review import ProjectReviewResult
from diffeoforge.desktop.project_setup import DesktopEngine
from diffeoforge.reference_preparation_reconciliation import (
    reconcile_reference_preparation,
)


class DesktopReferencePreparationStatusError(RuntimeError):
    """Raised when a desktop status view cannot remain review-bound."""


@dataclass(frozen=True)
class DesktopReferencePrivateStage:
    """One exact private-stage observation safe for bounded desktop display."""

    directory_name: str
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
        )
    except (KeyError, TypeError, ValueError) as error:
        raise DesktopReferencePreparationStatusError(
            f"Preparation reconciliation returned an invalid desktop view: {error}"
        ) from error
