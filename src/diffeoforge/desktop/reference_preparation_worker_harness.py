"""Approval-bound reference preparation over one strict stdio request."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from diffeoforge.desktop.reference_preparation_request import (
    DesktopReferencePreparationRequest,
)
from diffeoforge.desktop.reference_preparation_worker_protocol import (
    DesktopReferencePreparationWorkerEvent,
)
from diffeoforge.reference_approved_preparation import (
    prepare_approved_reference_run,
)
from diffeoforge.runs import verify_prepared_run
from diffeoforge.strict_json import load_strict_json_object


def _request_from_stream(stream: TextIO) -> DesktopReferencePreparationRequest:
    line = stream.readline()
    if not line:
        raise ValueError("Reference preparation worker requires one request JSON line")
    if not line.endswith("\n"):
        raise ValueError("Reference preparation worker request must be LF-terminated")
    value = load_strict_json_object(
        line.encode("utf-8"),
        Path("<reference-preparation-worker-stdin>"),
        label="Reference preparation worker request",
    )
    if stream.read():
        raise ValueError(
            "Reference preparation worker accepts exactly one request JSON line"
        )
    return DesktopReferencePreparationRequest.from_dict(value)


def run_reference_preparation_worker_harness(
    *,
    stdin: TextIO,
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    """Prepare one exact approved run and stop before every engine action."""

    try:
        request = _request_from_stream(stdin)
    except (OSError, RuntimeError, TypeError, UnicodeError, ValueError) as error:
        print(
            f"REFERENCE_PREPARATION_WORKER_PROTOCOL_ERROR: {error}",
            file=stderr,
            flush=True,
        )
        return 2

    sequence = 0

    def emit(kind, payload) -> None:
        nonlocal sequence
        event = DesktopReferencePreparationWorkerEvent(
            request_id=request.request_id,
            sequence=sequence,
            kind=kind,
            payload=payload,
        )
        stdout.write(event.to_json_line() + "\n")
        stdout.flush()
        sequence += 1

    emit(
        "accepted",
        {
            "operation": "prepare_approved_only",
            "approval_request_sha256": request.expected_approval_sha256,
            "config_sha256": request.expected_config_sha256,
            "approved_plan_fingerprint": request.approved_plan_fingerprint,
            "run_id": request.run_id,
            "destination": str(request.destination),
            "engine_execution_authorized": False,
        },
    )
    emit(
        "phase",
        {
            "phase": "verify_request",
            "message": "Reverifying approval, config, exact plan, and absent destination.",
        },
    )

    try:
        request.verify_inputs()
        emit(
            "phase",
            {
                "phase": "prepare_approved",
                "message": "Privately staging and atomically publishing the approved plan.",
            },
        )
        evidence = prepare_approved_reference_run(
            request.approval_path,
            current_config_path=request.config_path,
            expected_request_sha256=request.expected_approval_sha256,
        )
        emit(
            "phase",
            {
                "phase": "verify_prepared_run",
                "message": "Reverifying immutable artifacts and pristine unexecuted output.",
            },
        )
        verify_prepared_run(request.destination)
        if evidence["prepared_run"]["path"] != str(request.destination):
            raise RuntimeError("Preparation evidence targets a different destination")
        if evidence["approval_request"]["sha256"] != request.expected_approval_sha256:
            raise RuntimeError("Preparation evidence contains a different approval SHA-256")
        if (
            evidence["approved_plan"]["canonical_fingerprint"]
            != request.approved_plan_fingerprint
        ):
            raise RuntimeError("Preparation evidence contains a different plan fingerprint")
    except (OSError, RuntimeError, TypeError, UnicodeError, ValueError) as error:
        emit(
            "terminal",
            {
                "outcome": "failed",
                "destination": str(request.destination),
                "destination_exists": request.destination.exists(),
                "approval_request_sha256": request.expected_approval_sha256,
                "approved_plan_fingerprint": request.approved_plan_fingerprint,
                "manifest_sha256": None,
                "preparation_evidence": None,
                "engine_execution_started": False,
                "message": str(error) or type(error).__name__,
            },
        )
        return 1

    emit(
        "terminal",
        {
            "outcome": "prepared_not_executed",
            "destination": str(request.destination),
            "destination_exists": True,
            "approval_request_sha256": request.expected_approval_sha256,
            "approved_plan_fingerprint": request.approved_plan_fingerprint,
            "manifest_sha256": evidence["prepared_run"]["manifest_sha256"],
            "preparation_evidence": evidence,
            "engine_execution_started": False,
            "message": (
                "Approved immutable reference run prepared and verified; engine execution "
                "was not started."
            ),
        },
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run the preparation-only harness; command-line arguments are unsupported."""

    arguments = tuple(sys.argv[1:] if argv is None else argv)
    if arguments:
        print(
            "REFERENCE_PREPARATION_WORKER_PROTOCOL_ERROR: command-line arguments are not "
            "supported",
            file=sys.stderr,
        )
        return 2
    return run_reference_preparation_worker_harness(
        stdin=sys.stdin,
        stdout=sys.stdout,
        stderr=sys.stderr,
    )


if __name__ == "__main__":
    raise SystemExit(main())
