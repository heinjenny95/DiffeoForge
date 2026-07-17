"""Fail-closed parent controller for the nonnumerical reference-worker harness."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Literal

from diffeoforge.desktop.reference_prelaunch import DesktopReferenceLaunchRequest
from diffeoforge.desktop.reference_worker_protocol import (
    DesktopReferenceWorkerEvent,
    DesktopReferenceWorkerProtocolError,
    ReferenceWorkerEventLedger,
)
from diffeoforge.desktop.worker_protocol import parse_json_object

ReferenceHarnessControllerState = Literal["idle", "running", "verified", "failed"]
ReferenceHarnessEventCallback = Callable[[DesktopReferenceWorkerEvent], None]
DEFAULT_SUPERVISION_TIMEOUT_SECONDS = 30.0
DEFAULT_STDOUT_LINE_LIMIT = 65_536
DEFAULT_STDERR_LIMIT = 65_536
MAX_HARNESS_EVENTS = 3
FROZEN_REFERENCE_HARNESS_BASENAME = "DiffeoForgeReferenceWorker"


class ReferenceHarnessControllerError(RuntimeError):
    """Base class for parent-side harness launch and verification failures."""


class ReferenceHarnessProtocolViolation(ReferenceHarnessControllerError):
    """Raised when the child violates the bounded harness protocol."""

    def __init__(
        self,
        message: str,
        *,
        exit_code: int | None = None,
        stderr: str = "",
    ) -> None:
        super().__init__(message)
        self.exit_code = exit_code
        self.stderr = stderr


class ReferenceHarnessProcessError(ReferenceHarnessControllerError):
    """Raised when the harness cannot be contained or exits incompletely."""

    def __init__(self, message: str, *, exit_code: int | None, stderr: str) -> None:
        super().__init__(message)
        self.exit_code = exit_code
        self.stderr = stderr


class ReferenceHarnessExecutionError(ReferenceHarnessControllerError):
    """Preserve a schema-valid failed terminal outcome from the harness."""

    def __init__(
        self,
        event: DesktopReferenceWorkerEvent,
        *,
        exit_code: int,
        stderr: str,
    ) -> None:
        super().__init__(str(event.payload["message"]))
        self.event = event
        self.exit_code = exit_code
        self.stderr = stderr


def default_reference_harness_command() -> tuple[str, ...]:
    """Resolve the source module or a future sibling frozen harness executable."""

    if getattr(sys, "frozen", False):
        desktop_executable = Path(sys.executable).resolve()
        suffix = ".exe" if os.name == "nt" else ""
        worker = desktop_executable.with_name(
            f"{FROZEN_REFERENCE_HARNESS_BASENAME}{suffix}"
        )
        return (str(worker),)
    return (sys.executable, "-m", "diffeoforge.desktop.reference_worker_harness")


def _create_windows_harness_job():
    if os.name != "nt":
        return None
    from diffeoforge.desktop.windows_job import WindowsKillOnCloseJob

    return WindowsKillOnCloseJob()


@dataclass(frozen=True)
class ReferenceHarnessControllerResult:
    """One reconciled, independently reverified nonnumerical harness outcome."""

    request_id: str
    exit_code: int
    terminal_event: DesktopReferenceWorkerEvent
    events: tuple[DesktopReferenceWorkerEvent, ...]
    stderr: str

    @property
    def stopped_before_prepare(self) -> bool:
        return self.terminal_event.payload["outcome"] == "stopped_before_prepare"


class _BoundedBytes:
    def __init__(self, limit: int) -> None:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise ValueError("stderr_limit must be a positive integer")
        self._limit = limit
        self._parts: list[bytes] = []
        self._stored = 0
        self._truncated = False
        self._lock = threading.Lock()

    def append(self, value: bytes) -> None:
        with self._lock:
            remaining = self._limit - self._stored
            if remaining > 0:
                retained = value[:remaining]
                self._parts.append(retained)
                self._stored += len(retained)
            if len(value) > remaining:
                self._truncated = True

    def render(self) -> str:
        with self._lock:
            text = b"".join(self._parts).decode("utf-8", errors="replace")
            if self._truncated:
                text += "\n[stderr truncated by DiffeoForge]"
            return text


class ReferenceHarnessController:
    """Launch only the nonmutating harness and reconcile its exact evidence."""

    def __init__(
        self,
        request: DesktopReferenceLaunchRequest,
        *,
        worker_command: Sequence[str] | None = None,
        cwd: Path | str | None = None,
        supervision_timeout: float = DEFAULT_SUPERVISION_TIMEOUT_SECONDS,
        stdout_line_limit: int = DEFAULT_STDOUT_LINE_LIMIT,
        stderr_limit: int = DEFAULT_STDERR_LIMIT,
    ) -> None:
        if not isinstance(request, DesktopReferenceLaunchRequest):
            raise TypeError("request must be a DesktopReferenceLaunchRequest")
        command = (
            default_reference_harness_command()
            if worker_command is None
            else tuple(worker_command)
        )
        if not command or any(not isinstance(item, str) or not item for item in command):
            raise ValueError("worker_command must contain nonempty strings")
        if (
            isinstance(supervision_timeout, bool)
            or not isinstance(supervision_timeout, (int, float))
            or supervision_timeout <= 0
        ):
            raise ValueError("supervision_timeout must be a positive number")
        if (
            isinstance(stdout_line_limit, bool)
            or not isinstance(stdout_line_limit, int)
            or stdout_line_limit < 1
        ):
            raise ValueError("stdout_line_limit must be a positive integer")
        _BoundedBytes(stderr_limit)
        self.request = request
        self.worker_command = tuple(command)
        self.cwd = None if cwd is None else Path(cwd).expanduser().resolve()
        self._supervision_timeout = float(supervision_timeout)
        self._stdout_line_limit = stdout_line_limit
        self._stderr_limit = stderr_limit
        self._lock = threading.RLock()
        self._state: ReferenceHarnessControllerState = "idle"
        self._process: subprocess.Popen[bytes] | None = None

    @property
    def state(self) -> ReferenceHarnessControllerState:
        with self._lock:
            return self._state

    def run(
        self,
        *,
        event_callback: ReferenceHarnessEventCallback | None = None,
    ) -> ReferenceHarnessControllerResult:
        """Synchronously supervise one bounded, deliberately nonnumerical child."""

        if event_callback is not None and not callable(event_callback):
            raise TypeError("event_callback must be callable or None")
        with self._lock:
            if self._state != "idle":
                raise ReferenceHarnessControllerError(
                    "Reference harness controller is single-use"
                )
            self._state = "running"

        try:
            self.request.verify_launch_inputs()
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            with self._lock:
                self._state = "failed"
            raise ReferenceHarnessControllerError(
                f"Reference harness request is no longer valid: {error}"
            ) from error

        process: subprocess.Popen[bytes] | None = None
        worker_job = None
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        try:
            worker_job = _create_windows_harness_job()
            process = subprocess.Popen(
                self.worker_command,
                cwd=self.cwd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
                creationflags=creationflags,
            )
            if worker_job is not None:
                worker_job.assign(process)
        except OSError as error:
            if process is not None:
                self._stop_process(process)
            if worker_job is not None:
                try:
                    worker_job.close()
                except OSError:
                    pass
            with self._lock:
                self._state = "failed"
            raise ReferenceHarnessProcessError(
                f"Could not launch and contain reference harness: {error}",
                exit_code=None,
                stderr="",
            ) from error

        assert process is not None
        with self._lock:
            self._process = process

        stderr_buffer = _BoundedBytes(self._stderr_limit)
        stderr_thread = threading.Thread(
            target=self._drain_stderr,
            args=(process.stderr, stderr_buffer),
            name="diffeoforge-reference-harness-stderr-reader",
            daemon=True,
        )
        stderr_thread.start()
        timed_out = threading.Event()

        def expire() -> None:
            if process.poll() is not None:
                return
            timed_out.set()
            if worker_job is not None:
                try:
                    worker_job.close()
                    return
                except OSError:
                    pass
            self._stop_process(process)

        timer = threading.Timer(self._supervision_timeout, expire)
        timer.daemon = True
        timer.start()
        ledger = ReferenceWorkerEventLedger(self.request)
        failed = True

        try:
            if process.stdin is None or process.stdout is None:
                raise ReferenceHarnessProcessError(
                    "Reference harness pipes were not created",
                    exit_code=process.poll(),
                    stderr="",
                )
            request_line = json.dumps(
                self.request.as_dict(),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8") + b"\n"
            try:
                process.stdin.write(request_line)
                process.stdin.flush()
            except (OSError, ValueError) as error:
                raise ReferenceHarnessProcessError(
                    "Could not deliver the reference harness request",
                    exit_code=process.poll(),
                    stderr=stderr_buffer.render(),
                ) from error
            self._close_pipe(process.stdin)

            while True:
                raw_line = process.stdout.readline(self._stdout_line_limit + 1)
                if not raw_line:
                    break
                if len(raw_line) > self._stdout_line_limit:
                    raise ReferenceHarnessProtocolViolation(
                        "Reference harness stdout line exceeds the configured limit"
                    )
                if not raw_line.endswith(b"\n"):
                    raise ReferenceHarnessProtocolViolation(
                        "Reference harness stdout line is not LF-terminated"
                    )
                if raw_line.strip() == b"":
                    raise ReferenceHarnessProtocolViolation(
                        "Reference harness emitted a blank stdout line"
                    )
                if len(ledger.events) >= MAX_HARNESS_EVENTS:
                    raise ReferenceHarnessProtocolViolation(
                        "Reference harness emitted more than three events"
                    )
                try:
                    line = raw_line.decode("utf-8", errors="strict")
                    event = DesktopReferenceWorkerEvent.from_dict(
                        parse_json_object(line, "Reference harness event")
                    )
                    ledger.accept(event)
                except (
                    DesktopReferenceWorkerProtocolError,
                    TypeError,
                    UnicodeError,
                    ValueError,
                ) as error:
                    raise ReferenceHarnessProtocolViolation(str(error)) from error
                if event_callback is not None:
                    event_callback(event)

            exit_code = process.wait()
            timer.cancel()
            stderr_thread.join()
            stderr = stderr_buffer.render()
            if timed_out.is_set():
                raise ReferenceHarnessProcessError(
                    "Reference harness exceeded the supervision timeout",
                    exit_code=exit_code,
                    stderr=stderr,
                )
            try:
                terminal = ledger.reconcile()
            except DesktopReferenceWorkerProtocolError as error:
                raise ReferenceHarnessProcessError(
                    str(error), exit_code=exit_code, stderr=stderr
                ) from error
            self._verify_exact_harness_lifecycle(ledger.events)
            outcome = str(terminal.payload["outcome"])
            expected_exit_code = {"stopped_before_prepare": 0, "failed": 1}.get(outcome)
            if expected_exit_code is None:
                raise ReferenceHarnessProtocolViolation(
                    f"Nonnumerical harness reported unsupported outcome {outcome!r}"
                )
            if exit_code != expected_exit_code:
                raise ReferenceHarnessProtocolViolation(
                    f"Reference harness outcome {outcome!r} requires exit code "
                    f"{expected_exit_code}, observed {exit_code}"
                )
            if outcome == "failed":
                raise ReferenceHarnessExecutionError(
                    terminal, exit_code=exit_code, stderr=stderr
                )
            try:
                self.request.verify_launch_inputs()
            except (OSError, RuntimeError, TypeError, ValueError) as error:
                raise ReferenceHarnessProtocolViolation(
                    f"Reference harness success failed parent reverification: {error}"
                ) from error
            if terminal.payload["destination_exists"] or self.request.destination.exists():
                raise ReferenceHarnessProtocolViolation(
                    "Reference harness success conflicts with an existing destination"
                )
            result = ReferenceHarnessControllerResult(
                request_id=self.request.request_id,
                exit_code=exit_code,
                terminal_event=terminal,
                events=ledger.events,
                stderr=stderr,
            )
            with self._lock:
                self._state = "verified"
            failed = False
            return result
        except ReferenceHarnessProtocolViolation as error:
            self._stop_process(process)
            error.exit_code = process.poll()
            error.stderr = stderr_buffer.render()
            raise
        except ReferenceHarnessControllerError:
            raise
        except Exception as error:
            raise ReferenceHarnessControllerError(
                f"Reference harness supervision failed: {error}"
            ) from error
        finally:
            timer.cancel()
            if failed:
                self._stop_process(process)
                with self._lock:
                    self._state = "failed"
            self._close_pipe(process.stdin)
            self._close_pipe(process.stdout)
            self._close_pipe(process.stderr)
            stderr_thread.join(timeout=5)
            with self._lock:
                self._process = None
            if worker_job is not None:
                try:
                    worker_job.close()
                except OSError as error:
                    if not failed:
                        with self._lock:
                            self._state = "failed"
                        raise ReferenceHarnessProcessError(
                            f"Could not close reference harness Job Object: {error}",
                            exit_code=process.poll(),
                            stderr=stderr_buffer.render(),
                        ) from error

    def _verify_exact_harness_lifecycle(
        self,
        events: tuple[DesktopReferenceWorkerEvent, ...],
    ) -> None:
        kinds = tuple(event.kind for event in events)
        if kinds == ("terminal",) and events[0].payload["outcome"] == "failed":
            return
        if kinds != ("accepted", "phase", "terminal"):
            raise ReferenceHarnessProtocolViolation(
                "Reference harness must emit accepted, verify_request, then terminal"
            )
        if events[1].payload["phase"] != "verify_request":
            raise ReferenceHarnessProtocolViolation(
                "Reference harness phase must be verify_request"
            )

    @staticmethod
    def _drain_stderr(stream: BinaryIO | None, buffer: _BoundedBytes) -> None:
        if stream is None:
            return
        for chunk in iter(lambda: stream.read(8192), b""):
            buffer.append(chunk)

    @staticmethod
    def _stop_process(process: subprocess.Popen[bytes]) -> None:
        if process.poll() is not None:
            return
        try:
            process.terminate()
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                process.kill()
                process.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                pass
        except OSError:
            pass

    @staticmethod
    def _close_pipe(stream: BinaryIO | None) -> None:
        if stream is None or stream.closed:
            return
        try:
            stream.close()
        except OSError:
            pass
