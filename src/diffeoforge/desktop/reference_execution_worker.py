"""Contained Deformetrica preparation/execution worker for the desktop app."""

from __future__ import annotations

import contextlib
import os
import sys
import threading
import time
from collections.abc import Iterator, Sequence
from typing import Protocol, TextIO

from diffeoforge.config import load_config
from diffeoforge.desktop.reference_prelaunch import DesktopReferenceLaunchRequest
from diffeoforge.desktop.reference_progress import ReferenceProgressTracker
from diffeoforge.desktop.reference_worker_protocol import (
    DesktopReferenceWorkerCommand,
    DesktopReferenceWorkerEvent,
)
from diffeoforge.desktop.worker_protocol import parse_json_object, sha256_file
from diffeoforge.report import collect_preflight
from diffeoforge.result_report import collect_run_report
from diffeoforge.runs import execute_run, prepare_run


class _LineInput(Protocol):
    def readline(self) -> str: ...

    def __iter__(self) -> Iterator[str]: ...


class _UnbufferedUtf8LineInput:
    """Read commands without holding the GIL while the numerical worker runs."""

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


def _request_from_stream(stream: _LineInput) -> DesktopReferenceLaunchRequest:
    line = stream.readline()
    if not line:
        raise ValueError("Reference execution worker requires one request JSON line")
    return DesktopReferenceLaunchRequest.from_dict(
        parse_json_object(line, "Reference execution worker request")
    )


def run_reference_execution_worker(
    *,
    stdin: _LineInput,
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    """Prepare, execute, and verify one hash-bound Deformetrica run."""

    try:
        request = _request_from_stream(stdin)
    except (OSError, RuntimeError, TypeError, UnicodeError, ValueError) as error:
        print(f"REFERENCE_EXECUTION_PROTOCOL_ERROR: {error}", file=stderr, flush=True)
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

    def terminal(outcome: str, message: str) -> int:
        result_path = request.destination / "result.json"
        result_sha256 = sha256_file(result_path) if result_path.is_file() else None
        emit(
            "terminal",
            {
                "outcome": outcome,
                "destination": str(request.destination),
                "destination_exists": request.destination.exists(),
                "result_sha256": result_sha256,
                "message": message,
            },
        )
        return {
            "completed": 0,
            "stopped_before_prepare": 130,
            "prepared_not_executed": 130,
            "interrupted": 130,
            "failed": 1,
        }[outcome]

    cancel_event = threading.Event()
    parent_disconnected = threading.Event()
    command_errors: list[Exception] = []

    def read_commands() -> None:
        for line in stdin:
            if not line.strip():
                continue
            try:
                command = DesktopReferenceWorkerCommand.from_dict(
                    parse_json_object(line, "Reference execution worker command")
                )
                if command.request_id != request.request_id:
                    raise ValueError(
                        "Reference execution command request_id does not match the active run"
                    )
            except (OSError, RuntimeError, TypeError, UnicodeError, ValueError) as error:
                command_errors.append(error)
            cancel_event.set()
            return
        parent_disconnected.set()
        cancel_event.set()

    emit(
        "accepted",
        {
            "engine": request.engine,
            "config_sha256": request.expected_config_sha256,
            "destination": str(request.destination),
            "cancellation": "phase_dependent",
        },
    )
    command_thread = threading.Thread(
        target=read_commands,
        name="diffeoforge-reference-execution-command-reader",
        daemon=True,
    )
    command_thread.start()

    try:
        emit(
            "phase",
            {
                "phase": "verify_request",
                "message": "Reverifying reviewed configuration and destination binding.",
            },
        )
        request.verify_launch_inputs()
        if cancel_event.is_set():
            if parent_disconnected.is_set():
                return 130
            return terminal("stopped_before_prepare", "Cancelled before run preparation.")

        emit(
            "phase",
            {
                "phase": "preflight",
                "message": "Revalidating meshes and effective Deformetrica parameters.",
            },
        )
        collect_preflight(request.config_path)
        config = load_config(request.config_path)
        maximum_iterations = int(config["optimization"]["max_iterations"])
        if cancel_event.is_set():
            if parent_disconnected.is_set():
                return 130
            return terminal("stopped_before_prepare", "Cancelled after preflight.")

        emit(
            "phase",
            {
                "phase": "prepare",
                "message": "Creating the immutable reviewed Deformetrica run.",
            },
        )
        run_directory = prepare_run(request.config_path, run_id=request.run_id)
        if run_directory.resolve() != request.destination:
            raise RuntimeError("Prepared reference destination differs from the reviewed request")
        if cancel_event.is_set():
            if parent_disconnected.is_set():
                return 130
            return terminal(
                "prepared_not_executed",
                "Cancelled after immutable preparation; Deformetrica was not started.",
            )

        emit(
            "phase",
            {
                "phase": "execute",
                "message": "Deformetrica is running in the configured external environment.",
            },
        )
        tracker = ReferenceProgressTracker(maximum_iterations)
        started = time.monotonic()

        def observe_line(line: str) -> None:
            if cancel_event.is_set():
                raise KeyboardInterrupt
            progress = tracker.observe(
                line,
                elapsed_seconds=time.monotonic() - started,
            )
            if progress is not None:
                emit("progress", progress.as_dict())

        with contextlib.redirect_stdout(stderr):
            return_code = execute_run(
                run_directory,
                line_callback=observe_line,
            )

        emit(
            "phase",
            {
                "phase": "finalize",
                "message": "Inventorying outputs and terminal execution evidence.",
            },
        )
        emit(
            "phase",
            {
                "phase": "verify_result",
                "message": "Verifying lifecycle, inventory, convergence, and result hashes.",
            },
        )
        report = collect_run_report(run_directory)
        failed_checks = tuple(check.label for check in report.checks if check.status != "pass")
        if failed_checks:
            raise RuntimeError(
                "Terminal reference evidence failed: " + ", ".join(failed_checks)
            )
        if command_errors:
            raise command_errors[0]
        if parent_disconnected.is_set():
            return return_code
        if return_code == 130 or report.result["status"] == "interrupted":
            return terminal(
                "interrupted",
                "Deformetrica stopped after cancellation; terminal evidence was preserved.",
            )
        if return_code != 0 or report.result["status"] != "completed":
            raise RuntimeError(
                f"Deformetrica finished with return code {return_code} and "
                f"status {report.result['status']!r}"
            )
        return terminal("completed", "Deformetrica completed and its result evidence verified.")
    except (OSError, RuntimeError, TypeError, UnicodeError, ValueError) as error:
        if parent_disconnected.is_set():
            return 1
        return terminal("failed", str(error) or type(error).__name__)


def main(
    argv: Sequence[str] | None = None,
    *,
    stdin: _LineInput | None = None,
) -> int:
    arguments = tuple(sys.argv[1:] if argv is None else argv)
    if arguments:
        print(
            "REFERENCE_EXECUTION_PROTOCOL_ERROR: command-line arguments are not supported",
            file=sys.stderr,
        )
        return 2
    return run_reference_execution_worker(
        stdin=sys.stdin if stdin is None else stdin,
        stdout=sys.stdout,
        stderr=sys.stderr,
    )


def _process_main() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="strict", write_through=True)
    exit_code = main(stdin=_UnbufferedUtf8LineInput(sys.stdin.fileno()))
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    finally:
        os._exit(exit_code)


if __name__ == "__main__":
    _process_main()
