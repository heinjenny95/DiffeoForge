from __future__ import annotations

import json
from pathlib import Path

import pytest

from diffeoforge.desktop.reference_prelaunch import DesktopReferenceLaunchRequest
from diffeoforge.desktop.reference_worker_protocol import (
    DesktopReferenceWorkerCommand,
    DesktopReferenceWorkerEvent,
    DesktopReferenceWorkerProtocolError,
    ReferenceWorkerEventLedger,
)

REQUEST_ID = "reference-worker-test"
REQUEST = DesktopReferenceLaunchRequest(
    request_id=REQUEST_ID,
    config_path=(Path.cwd() / "reference-worker-test" / "atlas.yaml").resolve(),
    destination=(Path.cwd() / "reference-worker-test" / "runs" / "pilot-001").resolve(),
    run_id="pilot-001",
    expected_config_sha256="a" * 64,
    launcher_engine="docker",
    launcher_image="reference:image",
)
DESTINATION = str(REQUEST.destination)


def _accepted(
    sequence: int = 0,
    *,
    request_id: str = REQUEST_ID,
    config_sha256: str = "a" * 64,
    destination: str = DESTINATION,
):
    return DesktopReferenceWorkerEvent(
        request_id=request_id,
        sequence=sequence,
        kind="accepted",
        payload={
            "engine": "deformetrica_reference",
            "config_sha256": config_sha256,
            "destination": destination,
            "cancellation": "phase_dependent",
        },
    )


def _phase(sequence: int, phase: str):
    return DesktopReferenceWorkerEvent(
        request_id=REQUEST_ID,
        sequence=sequence,
        kind="phase",
        payload={"phase": phase, "message": f"entered {phase}"},
    )


def _terminal(
    sequence: int,
    outcome: str,
    *,
    destination_exists: bool,
    result_sha256: str | None,
):
    return DesktopReferenceWorkerEvent(
        request_id=REQUEST_ID,
        sequence=sequence,
        kind="terminal",
        payload={
            "outcome": outcome,
            "destination": DESTINATION,
            "destination_exists": destination_exists,
            "result_sha256": result_sha256,
            "message": outcome,
        },
    )


def _progress(sequence: int, iteration: int):
    return DesktopReferenceWorkerEvent(
        request_id=REQUEST_ID,
        sequence=sequence,
        kind="progress",
        payload={
            "iteration": iteration,
            "maximum_iterations": 100,
            "log_likelihood": -10.0 + iteration,
            "attachment": -8.0,
            "regularity": -2.0,
            "elapsed_seconds": 10.0 + iteration,
            "seconds_per_iteration": None,
            "eta_to_iteration_cap_seconds": None,
            "estimate_status": "warming_up",
        },
    )


def _ledger_with_phases(*phases: str) -> ReferenceWorkerEventLedger:
    ledger = ReferenceWorkerEventLedger(REQUEST)
    ledger.accept(_accepted())
    for sequence, phase in enumerate(phases, start=1):
        ledger.accept(_phase(sequence, phase))
    return ledger


def test_reference_worker_command_and_event_round_trip() -> None:
    command = DesktopReferenceWorkerCommand(REQUEST_ID)
    assert DesktopReferenceWorkerCommand.from_dict(command.as_dict()) == command

    event = _accepted()
    parsed = DesktopReferenceWorkerEvent.from_dict(json.loads(event.to_json_line()))
    assert parsed.as_dict() == event.as_dict()
    with pytest.raises(TypeError):
        parsed.payload["engine"] = "changed"


def test_reference_worker_completed_lifecycle() -> None:
    phases = (
        "verify_request",
        "preflight",
        "prepare",
        "execute",
        "finalize",
        "verify_result",
    )
    ledger = _ledger_with_phases(*phases)
    terminal = _terminal(
        len(phases) + 1,
        "completed",
        destination_exists=True,
        result_sha256="b" * 64,
    )
    ledger.accept(terminal)

    assert ledger.reconcile() == terminal
    assert len(ledger.events) == 8


def test_reference_worker_accepts_strictly_increasing_progress_only_during_execute() -> None:
    ledger = _ledger_with_phases("verify_request", "preflight", "prepare", "execute")
    ledger.accept(_progress(5, 0))
    ledger.accept(_progress(6, 1))
    with pytest.raises(DesktopReferenceWorkerProtocolError, match="increase strictly"):
        ledger.accept(_progress(7, 1))

    before_execute = _ledger_with_phases("verify_request", "preflight", "prepare")
    with pytest.raises(DesktopReferenceWorkerProtocolError, match="execute phase"):
        before_execute.accept(_progress(4, 0))


def test_reference_worker_progress_rejects_nonfinite_json_numbers() -> None:
    payload = _progress(0, 1).as_dict()
    payload["payload"]["log_likelihood"] = float("nan")
    with pytest.raises(DesktopReferenceWorkerProtocolError, match="strict JSON"):
        DesktopReferenceWorkerEvent.from_dict(payload)


@pytest.mark.parametrize(
    ("phases", "outcome", "destination_exists", "result_sha256"),
    [
        (("verify_request", "preflight"), "stopped_before_prepare", False, None),
        (
            ("verify_request", "preflight", "prepare"),
            "prepared_not_executed",
            True,
            None,
        ),
        (
            ("verify_request", "preflight", "prepare", "execute"),
            "interrupted",
            True,
            "c" * 64,
        ),
    ],
)
def test_reference_worker_phase_dependent_stop_lifecycles(
    phases: tuple[str, ...],
    outcome: str,
    destination_exists: bool,
    result_sha256: str | None,
) -> None:
    ledger = _ledger_with_phases(*phases)
    terminal = _terminal(
        len(phases) + 1,
        outcome,
        destination_exists=destination_exists,
        result_sha256=result_sha256,
    )
    ledger.accept(terminal)
    assert ledger.reconcile() == terminal


def test_reference_worker_allows_launch_time_failure() -> None:
    ledger = ReferenceWorkerEventLedger(REQUEST)
    terminal = _terminal(
        0,
        "failed",
        destination_exists=False,
        result_sha256=None,
    )
    ledger.accept(terminal)
    assert ledger.reconcile() == terminal


def test_reference_worker_rejects_request_and_sequence_mismatch() -> None:
    ledger = ReferenceWorkerEventLedger(REQUEST)
    with pytest.raises(DesktopReferenceWorkerProtocolError, match="request_id"):
        ledger.accept(_accepted(request_id="different-request"))
    with pytest.raises(DesktopReferenceWorkerProtocolError, match="contiguous"):
        ledger.accept(_accepted(sequence=1))


def test_reference_worker_rejects_accepted_hash_or_destination_mismatch() -> None:
    ledger = ReferenceWorkerEventLedger(REQUEST)
    with pytest.raises(DesktopReferenceWorkerProtocolError, match="configuration hash"):
        ledger.accept(_accepted(config_sha256="b" * 64))

    ledger = ReferenceWorkerEventLedger(REQUEST)
    with pytest.raises(DesktopReferenceWorkerProtocolError, match="launch destination"):
        ledger.accept(_accepted(destination=str(REQUEST.destination.parent / "other")))


def test_reference_worker_rejects_terminal_destination_mismatch() -> None:
    ledger = _ledger_with_phases("verify_request")
    terminal = _terminal(
        2,
        "stopped_before_prepare",
        destination_exists=False,
        result_sha256=None,
    )
    payload = terminal.as_dict()
    payload["payload"]["destination"] = str(REQUEST.destination.parent / "other")
    mismatched = DesktopReferenceWorkerEvent.from_dict(payload)
    with pytest.raises(DesktopReferenceWorkerProtocolError, match="different destination"):
        ledger.accept(mismatched)


def test_reference_worker_rejects_phase_repetition_or_regression() -> None:
    ledger = _ledger_with_phases("verify_request", "prepare")
    with pytest.raises(DesktopReferenceWorkerProtocolError, match="advance"):
        ledger.accept(_phase(3, "prepare"))

    ledger = _ledger_with_phases("verify_request", "prepare")
    with pytest.raises(DesktopReferenceWorkerProtocolError, match="advance"):
        ledger.accept(_phase(3, "preflight"))


@pytest.mark.parametrize(
    ("phases", "outcome", "message"),
    [
        (("verify_request", "preflight"), "completed", "verify_result"),
        (("verify_request", "prepare"), "stopped_before_prepare", "conflicts"),
        (("verify_request", "preflight"), "prepared_not_executed", "requires prepare"),
        (("verify_request", "prepare", "execute"), "prepared_not_executed", "forbids"),
        (("verify_request", "prepare"), "interrupted", "requires an execute"),
    ],
)
def test_reference_worker_rejects_outcome_phase_conflicts(
    phases: tuple[str, ...],
    outcome: str,
    message: str,
) -> None:
    ledger = _ledger_with_phases(*phases)
    destination_exists = outcome != "stopped_before_prepare"
    result = "d" * 64 if outcome in {"completed", "interrupted"} else None
    terminal = _terminal(
        len(phases) + 1,
        outcome,
        destination_exists=destination_exists,
        result_sha256=result,
    )
    with pytest.raises(DesktopReferenceWorkerProtocolError, match=message):
        ledger.accept(terminal)


def test_reference_worker_schema_rejects_inconsistent_terminal_evidence() -> None:
    with pytest.raises(DesktopReferenceWorkerProtocolError, match="schema validation"):
        _terminal(
            0,
            "completed",
            destination_exists=False,
            result_sha256=None,
        )


def test_reference_worker_rejects_post_terminal_data_and_incomplete_stream() -> None:
    ledger = _ledger_with_phases("verify_request")
    with pytest.raises(DesktopReferenceWorkerProtocolError, match="without a terminal"):
        ledger.reconcile()

    terminal = _terminal(
        2,
        "stopped_before_prepare",
        destination_exists=False,
        result_sha256=None,
    )
    ledger.accept(terminal)
    with pytest.raises(DesktopReferenceWorkerProtocolError, match="after a terminal"):
        ledger.accept(_phase(3, "preflight"))
