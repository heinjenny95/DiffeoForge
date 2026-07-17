"""Child-process entry point for the versioned DiffeoForge desktop worker."""

from __future__ import annotations

import sys
import threading
from collections.abc import Sequence
from typing import TextIO

from diffeoforge.desktop.worker_protocol import (
    DesktopWorkerCommand,
    DesktopWorkerEvent,
    DesktopWorkerProtocolError,
    DesktopWorkerRequest,
    parse_json_object,
    sha256_file,
)


def _request_from_stream(stream: TextIO) -> DesktopWorkerRequest:
    line = stream.readline()
    if not line:
        raise DesktopWorkerProtocolError("Desktop worker requires one request JSON line")
    return DesktopWorkerRequest.from_dict(parse_json_object(line, "Desktop worker request"))


def run_worker(
    *,
    stdin: TextIO,
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    """Run one request and exchange strict JSON lines with the parent process."""

    try:
        request = _request_from_stream(stdin)
    except (DesktopWorkerProtocolError, TypeError, ValueError) as error:
        print(f"WORKER_PROTOCOL_ERROR: {error}", file=stderr, flush=True)
        return 2

    sequence = 0

    def emit(kind, payload) -> None:
        nonlocal sequence
        event = DesktopWorkerEvent(
            request_id=request.request_id,
            sequence=sequence,
            kind=kind,
            payload=payload,
        )
        stdout.write(event.to_json_line() + "\n")
        stdout.flush()
        sequence += 1

    def fail(error: Exception) -> int:
        emit(
            "failed",
            {
                "error_type": type(error).__name__,
                "message": str(error) or type(error).__name__,
                "destination": str(request.destination),
                "destination_exists": request.destination.exists(),
            },
        )
        return 1

    try:
        request.verify_launch_inputs()
    except (OSError, RuntimeError, TypeError, ValueError) as error:
        return fail(error)

    cancel_event = threading.Event()
    command_errors: list[DesktopWorkerProtocolError] = []

    def read_commands() -> None:
        for line in stdin:
            if not line.strip():
                continue
            try:
                command = DesktopWorkerCommand.from_dict(
                    parse_json_object(line, "Desktop worker command")
                )
                if command.request_id != request.request_id:
                    raise DesktopWorkerProtocolError(
                        "Desktop worker command request_id does not match the active request"
                    )
            except (DesktopWorkerProtocolError, TypeError, ValueError) as error:
                command_errors.append(DesktopWorkerProtocolError(str(error)))
                cancel_event.set()
                return
            cancel_event.set()
            return

    emit(
        "started",
        {
            "engine": request.engine,
            "config_sha256": request.expected_config_sha256,
            "destination": str(request.destination),
            "cancellation": "cooperative_safe_points",
        },
    )
    command_thread = threading.Thread(
        target=read_commands,
        name="diffeoforge-worker-command-reader",
        daemon=True,
    )
    command_thread.start()

    try:
        from diffeoforge.modern_workflow import (
            MANIFEST_NAME,
            ModernWorkflowCancelled,
            run_modern_workflow,
            verify_modern_workflow,
        )
    except ImportError as error:
        return fail(
            DesktopWorkerProtocolError(
                "Modern engine dependencies are missing; install "
                f"diffeoforge[modern-engine]. ({error})"
            )
        )

    try:
        request.verify_launch_inputs()
        run_directory = run_modern_workflow(
            request.config_path,
            destination=request.destination,
            progress_callback=lambda event: emit("progress", {"modern_progress": event.as_dict()}),
            cancel_requested=cancel_event.is_set,
        )
        if command_errors:
            return fail(command_errors[0])
        manifest = verify_modern_workflow(run_directory)
        emit(
            "completed",
            {
                "destination": str(run_directory),
                "manifest_sha256": sha256_file(run_directory / MANIFEST_NAME),
                "subject_count": len(manifest["input"]["subjects"]),
                "bundle_path": manifest["result_bundle"]["path"],
            },
        )
        return 0
    except ModernWorkflowCancelled:
        if command_errors:
            return fail(command_errors[0])
        if request.destination.exists():
            return fail(RuntimeError("Cancelled worker unexpectedly found a published destination"))
        emit(
            "cancelled",
            {
                "destination": str(request.destination),
                "published": False,
                "resumable": False,
                "message": (
                    "Cancellation completed at a safe point; private temporary work was "
                    "removed. This Modern run has no checkpoint and is not resumable."
                ),
            },
        )
        return 130
    except (OSError, RuntimeError, TypeError, ValueError) as error:
        return fail(error)


def main(argv: Sequence[str] | None = None) -> int:
    """Execute the stdio worker; command-line arguments are intentionally unsupported."""

    arguments = tuple(sys.argv[1:] if argv is None else argv)
    if arguments:
        print("WORKER_PROTOCOL_ERROR: command-line arguments are not supported", file=sys.stderr)
        return 2
    return run_worker(stdin=sys.stdin, stdout=sys.stdout, stderr=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
