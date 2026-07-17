"""Nonnumerical stdio harness for the future reference-worker boundary."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from typing import TextIO

from diffeoforge.desktop.reference_prelaunch import DesktopReferenceLaunchRequest
from diffeoforge.desktop.reference_worker_protocol import DesktopReferenceWorkerEvent
from diffeoforge.desktop.worker_protocol import DesktopWorkerProtocolError, parse_json_object


def _request_from_stream(stream: TextIO) -> DesktopReferenceLaunchRequest:
    line = stream.readline()
    if not line:
        raise DesktopWorkerProtocolError(
            "Reference worker harness requires one request JSON line"
        )
    request = DesktopReferenceLaunchRequest.from_dict(
        parse_json_object(line, "Reference worker harness request")
    )
    if stream.read():
        raise DesktopWorkerProtocolError(
            "Reference worker harness accepts exactly one request JSON line"
        )
    return request


def run_reference_worker_harness(
    *,
    stdin: TextIO,
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    """Verify one request over stdio and stop before any preparation or execution."""

    try:
        request = _request_from_stream(stdin)
    except (OSError, RuntimeError, TypeError, UnicodeError, ValueError) as error:
        print(f"REFERENCE_WORKER_PROTOCOL_ERROR: {error}", file=stderr, flush=True)
        return 2

    sequence = 0

    def emit(kind, payload) -> None:
        nonlocal sequence
        event = DesktopReferenceWorkerEvent(
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
            "engine": request.engine,
            "config_sha256": request.expected_config_sha256,
            "destination": str(request.destination),
            "cancellation": "phase_dependent",
        },
    )
    emit(
        "phase",
        {
            "phase": "verify_request",
            "message": "Verifying the exact prelaunch request inside the child process.",
        },
    )

    try:
        request.verify_launch_inputs()
        if request.destination.exists():
            raise FileExistsError(
                f"Reference launch destination appeared during harness verification: "
                f"{request.destination}"
            )
    except (OSError, RuntimeError, TypeError, ValueError) as error:
        emit(
            "terminal",
            {
                "outcome": "failed",
                "destination": str(request.destination),
                "destination_exists": request.destination.exists(),
                "result_sha256": None,
                "message": str(error) or type(error).__name__,
            },
        )
        return 1

    emit(
        "terminal",
        {
            "outcome": "stopped_before_prepare",
            "destination": str(request.destination),
            "destination_exists": False,
            "result_sha256": None,
            "message": (
                "Nonnumerical harness completed request verification and stopped before "
                "run preparation."
            ),
        },
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run the deliberately nonmutating harness; command-line arguments are unsupported."""

    arguments = tuple(sys.argv[1:] if argv is None else argv)
    if arguments:
        print(
            "REFERENCE_WORKER_PROTOCOL_ERROR: command-line arguments are not supported",
            file=sys.stderr,
        )
        return 2
    return run_reference_worker_harness(
        stdin=sys.stdin,
        stdout=sys.stdout,
        stderr=sys.stderr,
    )


if __name__ == "__main__":
    raise SystemExit(main())
