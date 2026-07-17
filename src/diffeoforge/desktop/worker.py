"""Child-process entry point for the versioned DiffeoForge desktop worker."""

from __future__ import annotations

import os
import sys
import threading
from collections.abc import Iterator, Sequence
from typing import Protocol, TextIO

from diffeoforge.desktop.worker_protocol import (
    DesktopWorkerCommand,
    DesktopWorkerEvent,
    DesktopWorkerProtocolError,
    DesktopWorkerRequest,
    parse_json_object,
    sha256_file,
)


class _LineInput(Protocol):
    def readline(self) -> str: ...

    def __iter__(self) -> Iterator[str]: ...


class _UnbufferedUtf8LineInput:
    """Read process stdin with ``os.read`` so a blocking command wait releases the GIL."""

    def __init__(self, file_descriptor: int) -> None:
        self._file_descriptor = file_descriptor
        self._buffer = bytearray()
        self._eof = False

    def readline(self) -> str:
        while True:
            newline = self._buffer.find(b"\n")
            if newline >= 0:
                line = bytes(self._buffer[: newline + 1])
                del self._buffer[: newline + 1]
                return line.decode("utf-8")
            if self._eof:
                if not self._buffer:
                    return ""
                line = bytes(self._buffer)
                self._buffer.clear()
                return line.decode("utf-8")
            chunk = os.read(self._file_descriptor, 4096)
            if chunk:
                self._buffer.extend(chunk)
            else:
                self._eof = True

    def __iter__(self) -> Iterator[str]:
        return self

    def __next__(self) -> str:
        line = self.readline()
        if not line:
            raise StopIteration
        return line


def _request_from_stream(stream: _LineInput) -> DesktopWorkerRequest:
    line = stream.readline()
    if not line:
        raise DesktopWorkerProtocolError("Desktop worker requires one request JSON line")
    return DesktopWorkerRequest.from_dict(parse_json_object(line, "Desktop worker request"))


def run_worker(
    *,
    stdin: _LineInput,
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    """Run one request and exchange strict JSON lines with the parent process."""

    try:
        request = _request_from_stream(stdin)
    except (DesktopWorkerProtocolError, OSError, TypeError, UnicodeError, ValueError) as error:
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
            except (
                DesktopWorkerProtocolError,
                OSError,
                TypeError,
                UnicodeError,
                ValueError,
            ) as error:
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


def main(
    argv: Sequence[str] | None = None,
    *,
    stdin: _LineInput | None = None,
) -> int:
    """Execute the stdio worker; command-line arguments are intentionally unsupported."""

    arguments = tuple(sys.argv[1:] if argv is None else argv)
    if arguments:
        print("WORKER_PROTOCOL_ERROR: command-line arguments are not supported", file=sys.stderr)
        return 2
    return run_worker(
        stdin=sys.stdin if stdin is None else stdin,
        stdout=sys.stdout,
        stderr=sys.stderr,
    )


def _process_main() -> None:
    """Flush the dedicated transport process and bypass a blocked daemon stdin reader."""

    exit_code = main(stdin=_UnbufferedUtf8LineInput(sys.stdin.fileno()))
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    finally:
        os._exit(exit_code)


if __name__ == "__main__":
    _process_main()
