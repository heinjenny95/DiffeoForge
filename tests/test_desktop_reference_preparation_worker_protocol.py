from __future__ import annotations

import json
from pathlib import Path

import pytest

from diffeoforge.desktop.reference_preparation_request import (
    DesktopReferencePreparationRequest,
)
from diffeoforge.desktop.reference_preparation_worker_protocol import (
    DesktopReferencePreparationWorkerEvent,
    DesktopReferencePreparationWorkerProtocolError,
    ReferencePreparationWorkerEventLedger,
)

REQUEST_ID = "approved-preparation-worker"
DESTINATION = (Path.cwd() / "approved-worker" / "runs" / "pilot-001").resolve()
REQUEST = DesktopReferencePreparationRequest(
    request_id=REQUEST_ID,
    approval_path=(Path.cwd() / "approved-worker" / "approval.json").resolve(),
    expected_approval_sha256="a" * 64,
    config_path=(Path.cwd() / "approved-worker" / "atlas.yaml").resolve(),
    expected_config_sha256="c" * 64,
    approved_plan_fingerprint="b" * 64,
    run_id="pilot-001",
    destination=DESTINATION,
)
CHECKS = [
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
]


def _evidence() -> dict:
    return {
        "schema_version": "0.1",
        "status": "prepared_approved_reference_run_not_executed",
        "preparer": {"diffeoforge": "test"},
        "approval_request": {
            "path": str(REQUEST.approval_path),
            "bytes": 2,
            "sha256": "a" * 64,
            "expected_sha256": "a" * 64,
        },
        "approved_plan": {
            "canonical_fingerprint": "b" * 64,
            "run_id": "pilot-001",
            "destination": str(DESTINATION),
            "subjects": 2,
            "protected_files": 8,
            "total_protected_bytes": 1,
        },
        "prepared_run": {
            "path": str(DESTINATION),
            "manifest_path": str(DESTINATION / "manifest.json"),
            "manifest_bytes": 2,
            "manifest_sha256": "d" * 64,
            "protected_files": 8,
            "lifecycle_last_event": "prepared",
            "output_empty": True,
            "engine_execution_started": False,
        },
        "checks": CHECKS,
        "scientific_boundary": "Preparation-only test evidence; no scientific claim.",
    }


def _accepted(sequence: int = 0, **changes) -> DesktopReferencePreparationWorkerEvent:
    payload = {
        "operation": "prepare_approved_only",
        "approval_request_sha256": "a" * 64,
        "config_sha256": "c" * 64,
        "approved_plan_fingerprint": "b" * 64,
        "run_id": "pilot-001",
        "destination": str(DESTINATION),
        "engine_execution_authorized": False,
        **changes,
    }
    return DesktopReferencePreparationWorkerEvent(
        request_id=REQUEST_ID,
        sequence=sequence,
        kind="accepted",
        payload=payload,
    )


def _phase(sequence: int, phase: str) -> DesktopReferencePreparationWorkerEvent:
    return DesktopReferencePreparationWorkerEvent(
        request_id=REQUEST_ID,
        sequence=sequence,
        kind="phase",
        payload={"phase": phase, "message": phase},
    )


def _success(sequence: int, evidence: dict | None = None):
    nested = _evidence() if evidence is None else evidence
    return DesktopReferencePreparationWorkerEvent(
        request_id=REQUEST_ID,
        sequence=sequence,
        kind="terminal",
        payload={
            "outcome": "prepared_not_executed",
            "destination": str(DESTINATION),
            "destination_exists": True,
            "approval_request_sha256": "a" * 64,
            "approved_plan_fingerprint": "b" * 64,
            "manifest_sha256": "d" * 64,
            "preparation_evidence": nested,
            "engine_execution_started": False,
            "message": "prepared only",
        },
    )


def _ledger_with_phases(*phases: str) -> ReferencePreparationWorkerEventLedger:
    ledger = ReferencePreparationWorkerEventLedger(REQUEST)
    ledger.accept(_accepted())
    for sequence, phase in enumerate(phases, start=1):
        ledger.accept(_phase(sequence, phase))
    return ledger


def test_event_round_trip_and_complete_prepared_not_executed_lifecycle() -> None:
    event = _accepted()
    parsed = DesktopReferencePreparationWorkerEvent.from_dict(
        json.loads(event.to_json_line())
    )
    assert parsed.as_dict() == event.as_dict()
    with pytest.raises(TypeError):
        parsed.payload["operation"] = "changed"

    phases = ("verify_request", "prepare_approved", "verify_prepared_run")
    ledger = _ledger_with_phases(*phases)
    terminal = _success(4)
    ledger.accept(terminal)

    assert ledger.reconcile() == terminal
    assert len(ledger.events) == 5


def test_ledger_rejects_sequence_request_binding_and_phase_errors() -> None:
    ledger = ReferencePreparationWorkerEventLedger(REQUEST)
    changed = _accepted(sequence=1)
    with pytest.raises(DesktopReferencePreparationWorkerProtocolError, match="contiguous"):
        ledger.accept(changed)

    ledger = ReferencePreparationWorkerEventLedger(REQUEST)
    with pytest.raises(DesktopReferencePreparationWorkerProtocolError, match="bound"):
        ledger.accept(_accepted(approval_request_sha256="e" * 64))

    ledger = _ledger_with_phases("verify_request", "prepare_approved")
    with pytest.raises(DesktopReferencePreparationWorkerProtocolError, match="in order"):
        ledger.accept(_phase(3, "verify_request"))

    ledger = _ledger_with_phases("verify_request")
    with pytest.raises(DesktopReferencePreparationWorkerProtocolError, match="complete"):
        ledger.accept(_phase(2, "verify_prepared_run"))

    ledger = _ledger_with_phases("verify_request", "prepare_approved")
    with pytest.raises(
        DesktopReferencePreparationWorkerProtocolError,
        match="verify_prepared_run",
    ):
        ledger.accept(_success(3))


def test_ledger_rejects_terminal_or_nested_evidence_mismatch() -> None:
    ledger = _ledger_with_phases(
        "verify_request", "prepare_approved", "verify_prepared_run"
    )
    terminal = _success(4).as_dict()
    terminal["payload"]["manifest_sha256"] = "e" * 64
    with pytest.raises(DesktopReferencePreparationWorkerProtocolError, match="differs"):
        ledger.accept(DesktopReferencePreparationWorkerEvent.from_dict(terminal))

    evidence = _evidence()
    evidence["prepared_run"]["path"] = str(DESTINATION.parent / "other")
    ledger = _ledger_with_phases(
        "verify_request", "prepare_approved", "verify_prepared_run"
    )
    with pytest.raises(DesktopReferencePreparationWorkerProtocolError, match="destination"):
        ledger.accept(_success(4, evidence))

    evidence = _evidence()
    evidence["approval_request"]["sha256"] = "e" * 64
    ledger = _ledger_with_phases(
        "verify_request", "prepare_approved", "verify_prepared_run"
    )
    with pytest.raises(DesktopReferencePreparationWorkerProtocolError, match="approval"):
        ledger.accept(_success(4, evidence))

    evidence = _evidence()
    evidence["approved_plan"]["run_id"] = "different-run"
    ledger = _ledger_with_phases(
        "verify_request", "prepare_approved", "verify_prepared_run"
    )
    with pytest.raises(DesktopReferencePreparationWorkerProtocolError, match="run ID"):
        ledger.accept(_success(4, evidence))

    invalid = _evidence()
    invalid["prepared_run"]["engine_execution_started"] = True
    with pytest.raises(
        DesktopReferencePreparationWorkerProtocolError,
        match="Nested approved preparation evidence",
    ):
        _success(4, invalid)


def test_failed_terminal_is_bounded_and_post_terminal_data_is_rejected() -> None:
    ledger = _ledger_with_phases("verify_request")
    failed = DesktopReferencePreparationWorkerEvent(
        request_id=REQUEST_ID,
        sequence=2,
        kind="terminal",
        payload={
            "outcome": "failed",
            "destination": str(DESTINATION),
            "destination_exists": False,
            "approval_request_sha256": "a" * 64,
            "approved_plan_fingerprint": "b" * 64,
            "manifest_sha256": None,
            "preparation_evidence": None,
            "engine_execution_started": False,
            "message": "failed closed",
        },
    )
    ledger.accept(failed)
    assert ledger.reconcile() == failed
    with pytest.raises(DesktopReferencePreparationWorkerProtocolError, match="after terminal"):
        ledger.accept(_phase(3, "prepare_approved"))

    incomplete = _ledger_with_phases("verify_request")
    with pytest.raises(DesktopReferencePreparationWorkerProtocolError, match="without terminal"):
        incomplete.reconcile()
