"""Parent-side supervision for one desktop Deformetrica execution worker."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TextIO

from diffeoforge.config import load_config
from diffeoforge.desktop.reference_prelaunch import DesktopReferenceLaunchRequest
from diffeoforge.desktop.reference_worker_protocol import (
    DesktopReferenceWorkerCommand,
    DesktopReferenceWorkerEvent,
    DesktopReferenceWorkerProtocolError,
    ReferenceWorkerEventLedger,
)
from diffeoforge.desktop.worker_protocol import parse_json_object, sha256_file
from diffeoforge.result_report import collect_run_report
from diffeoforge.runs import verify_prepared_run
from diffeoforge.subprocess_policy import hidden_windows_process_kwargs

ReferenceExecutionControllerState = Literal[
    "idle",
    "running",
    "cancelling",
    "completed",
    "interrupted",
    "prepared_not_executed",
    "stopped_before_prepare",
    "failed",
]
ReferenceExecutionEventCallback = Callable[[DesktopReferenceWorkerEvent], None]
TERMINAL_EXIT_TIMEOUT_SECONDS = 5
FROZEN_REFERENCE_EXECUTION_WORKER_BASENAME = "DiffeoForgeReferenceExecutionWorker"


class ReferenceExecutionControllerError(RuntimeError):
    """Base class for reference-execution supervision failures."""


class ReferenceExecutionProtocolViolation(ReferenceExecutionControllerError):
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


class ReferenceExecutionProcessError(ReferenceExecutionControllerError):
    def __init__(self, message: str, *, exit_code: int | None, stderr: str) -> None:
        super().__init__(message)
        self.exit_code = exit_code
        self.stderr = stderr


class ReferenceExecutionWorkerError(ReferenceExecutionControllerError):
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


def default_reference_execution_worker_command() -> tuple[str, ...]:
    if getattr(sys, "frozen", False):
        executable = Path(sys.executable).resolve()
        suffix = ".exe" if os.name == "nt" else ""
        return (
            str(
                executable.with_name(
                    f"{FROZEN_REFERENCE_EXECUTION_WORKER_BASENAME}{suffix}"
                )
            ),
        )
    return (sys.executable, "-m", "diffeoforge.desktop.reference_execution_worker")


def _create_windows_worker_job():
    if os.name != "nt":
        return None
    from diffeoforge.desktop.windows_job import WindowsKillOnCloseJob

    return WindowsKillOnCloseJob()


@dataclass(frozen=True)
class ReferenceExecutionControllerResult:
    request_id: str
    exit_code: int
    terminal_event: DesktopReferenceWorkerEvent
    events: tuple[DesktopReferenceWorkerEvent, ...]
    stderr: str

    @property
    def outcome(self) -> str:
        return str(self.terminal_event.payload["outcome"])

    @property
    def completed(self) -> bool:
        return self.outcome == "completed"

    @property
    def interrupted(self) -> bool:
        return self.outcome == "interrupted"


class _BoundedText:
    def __init__(self, limit: int) -> None:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise ValueError("stderr_limit must be a positive integer")
        self._limit = limit
        self._parts: list[str] = []
        self._stored = 0
        self._truncated = False
        self._lock = threading.Lock()

    def append(self, value: str) -> None:
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
            text = "".join(self._parts)
            if self._truncated:
                text += "\n[stderr truncated by DiffeoForge]"
            return text


class ReferenceExecutionController:
    """Contain, control, and independently verify one Deformetrica worker."""

    def __init__(
        self,
        request: DesktopReferenceLaunchRequest,
        *,
        worker_command: Sequence[str] | None = None,
        cwd: Path | str | None = None,
        stderr_limit: int = 262_144,
        stdout_line_limit: int = 262_144,
    ) -> None:
        if not isinstance(request, DesktopReferenceLaunchRequest):
            raise TypeError("request must be a DesktopReferenceLaunchRequest")
        command = (
            default_reference_execution_worker_command()
            if worker_command is None
            else tuple(worker_command)
        )
        if not command or any(not isinstance(item, str) or not item for item in command):
            raise ValueError("worker_command must contain nonempty strings")
        if isinstance(stdout_line_limit, bool) or stdout_line_limit < 1:
            raise ValueError("stdout_line_limit must be a positive integer")
        _BoundedText(stderr_limit)
        self.request = request
        self.worker_command = tuple(command)
        self.cwd = None if cwd is None else Path(cwd).expanduser().resolve()
        self._stderr_limit = stderr_limit
        self._stdout_line_limit = int(stdout_line_limit)
        self._lock = threading.RLock()
        self._process: subprocess.Popen[str] | None = None
        self._state: ReferenceExecutionControllerState = "idle"
        self._request_written = False
        self._cancel_pending = False
        self._cancel_sent = False

    @property
    def state(self) -> ReferenceExecutionControllerState:
        with self._lock:
            return self._state

    def request_cancel(self) -> bool:
        with self._lock:
            if self._state == "idle":
                if self._cancel_pending:
                    return False
                self._cancel_pending = True
                return True
            if self._state not in {"running", "cancelling"}:
                return False
            if self._cancel_pending or self._cancel_sent:
                return False
            process = self._process
            if process is None or not self._request_written:
                self._cancel_pending = True
                self._state = "cancelling"
                return True
            if process.poll() is not None:
                return False
            return self._send_cancel_locked(process)

    def run(
        self,
        *,
        event_callback: ReferenceExecutionEventCallback | None = None,
    ) -> ReferenceExecutionControllerResult:
        if event_callback is not None and not callable(event_callback):
            raise TypeError("event_callback must be callable or None")
        with self._lock:
            if self._state != "idle":
                raise ReferenceExecutionControllerError(
                    "Reference execution controller is single-use"
                )
            self._state = "running"
        try:
            self.request.verify_launch_inputs()
            config = load_config(self.request.config_path)
            maximum_iterations = int(config["optimization"]["max_iterations"])
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            with self._lock:
                self._state = "failed"
            raise ReferenceExecutionControllerError(
                f"Reference execution request is no longer valid: {error}"
            ) from error

        process: subprocess.Popen[str] | None = None
        worker_job = None
        try:
            worker_job = _create_windows_worker_job()
            process = subprocess.Popen(
                self.worker_command,
                cwd=self.cwd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                **hidden_windows_process_kwargs(),
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
            raise ReferenceExecutionProcessError(
                f"Could not launch and contain reference execution worker: {error}",
                exit_code=None,
                stderr="",
            ) from error

        assert process is not None
        with self._lock:
            self._process = process
        stderr_buffer = _BoundedText(self._stderr_limit)
        stderr_thread = threading.Thread(
            target=self._drain_stderr,
            args=(process.stderr, stderr_buffer),
            name="diffeoforge-reference-execution-stderr-reader",
            daemon=True,
        )
        stderr_thread.start()
        ledger = ReferenceWorkerEventLedger(self.request)
        failed = True
        try:
            if process.stdin is None or process.stdout is None:
                raise ReferenceExecutionProcessError(
                    "Reference execution worker pipes were not created",
                    exit_code=process.poll(),
                    stderr="",
                )
            process.stdin.write(json.dumps(self.request.as_dict(), sort_keys=True) + "\n")
            process.stdin.flush()
            with self._lock:
                self._request_written = True
                if self._cancel_pending:
                    self._cancel_pending = False
                    self._send_cancel_locked(process)

            while True:
                line = process.stdout.readline(self._stdout_line_limit + 1)
                if not line:
                    break
                if len(line) > self._stdout_line_limit:
                    raise ReferenceExecutionProtocolViolation(
                        "Reference execution worker stdout line exceeds the configured limit"
                    )
                if not line.endswith("\n"):
                    raise ReferenceExecutionProtocolViolation(
                        "Reference execution worker stdout line is not LF-terminated"
                    )
                if not line.strip():
                    raise ReferenceExecutionProtocolViolation(
                        "Reference execution worker emitted a blank stdout line"
                    )
                try:
                    event = DesktopReferenceWorkerEvent.from_dict(
                        parse_json_object(line, "Reference execution worker event")
                    )
                    ledger.accept(event)
                except (
                    DesktopReferenceWorkerProtocolError,
                    TypeError,
                    UnicodeError,
                    ValueError,
                ) as error:
                    raise ReferenceExecutionProtocolViolation(str(error)) from error
                self._verify_event_binding(event, maximum_iterations)
                if event_callback is not None:
                    event_callback(event)
                if event.kind == "terminal":
                    self._close_pipe(process.stdin)
                    try:
                        process.wait(timeout=TERMINAL_EXIT_TIMEOUT_SECONDS)
                    except subprocess.TimeoutExpired as error:
                        raise ReferenceExecutionProcessError(
                            "Reference execution worker did not exit after terminal event",
                            exit_code=None,
                            stderr=stderr_buffer.render(),
                        ) from error

            exit_code = process.wait()
            stderr_thread.join()
            stderr = stderr_buffer.render()
            try:
                terminal = ledger.reconcile()
            except DesktopReferenceWorkerProtocolError as error:
                raise ReferenceExecutionProcessError(
                    str(error), exit_code=exit_code, stderr=stderr
                ) from error
            outcome = str(terminal.payload["outcome"])
            expected_exit = {
                "completed": 0,
                "stopped_before_prepare": 130,
                "prepared_not_executed": 130,
                "interrupted": 130,
                "failed": 1,
            }[outcome]
            if exit_code != expected_exit:
                raise ReferenceExecutionProtocolViolation(
                    f"Reference outcome {outcome!r} requires exit code {expected_exit}, "
                    f"observed {exit_code}",
                    exit_code=exit_code,
                    stderr=stderr,
                )
            if outcome == "failed":
                raise ReferenceExecutionWorkerError(
                    terminal,
                    exit_code=exit_code,
                    stderr=stderr,
                )
            self._verify_terminal(terminal)
            terminal_states: dict[str, ReferenceExecutionControllerState] = {
                "completed": "completed",
                "interrupted": "interrupted",
                "prepared_not_executed": "prepared_not_executed",
                "stopped_before_prepare": "stopped_before_prepare",
            }
            state = terminal_states[outcome]
            result = ReferenceExecutionControllerResult(
                request_id=self.request.request_id,
                exit_code=exit_code,
                terminal_event=terminal,
                events=ledger.events,
                stderr=stderr,
            )
            with self._lock:
                self._state = state
            failed = False
            return result
        except ReferenceExecutionProtocolViolation as error:
            self._stop_process(process)
            stderr_thread.join(timeout=TERMINAL_EXIT_TIMEOUT_SECONDS)
            error.exit_code = process.poll()
            error.stderr = stderr_buffer.render()
            raise
        except ReferenceExecutionControllerError:
            raise
        except Exception as error:
            raise ReferenceExecutionControllerError(
                f"Reference execution supervision failed: {error}"
            ) from error
        finally:
            if failed:
                self._stop_process(process)
                stderr_thread.join(timeout=TERMINAL_EXIT_TIMEOUT_SECONDS)
                with self._lock:
                    self._state = "failed"
            self._close_pipe(process.stdin)
            self._close_pipe(process.stdout)
            self._close_pipe(process.stderr)
            with self._lock:
                self._process = None
            if worker_job is not None:
                try:
                    worker_job.close()
                except OSError as error:
                    if not failed:
                        with self._lock:
                            self._state = "failed"
                        raise ReferenceExecutionProcessError(
                            f"Could not close reference execution Job Object: {error}",
                            exit_code=process.poll(),
                            stderr=stderr_buffer.render(),
                        ) from error

    def _verify_event_binding(
        self,
        event: DesktopReferenceWorkerEvent,
        maximum_iterations: int,
    ) -> None:
        if event.kind == "progress" and (
            event.payload["maximum_iterations"] != maximum_iterations
            or event.payload["iteration"] > maximum_iterations
        ):
            raise ReferenceExecutionProtocolViolation(
                "Reference progress differs from the reviewed iteration limit"
            )

    def _verify_terminal(self, terminal: DesktopReferenceWorkerEvent) -> None:
        outcome = str(terminal.payload["outcome"])
        destination = self.request.destination
        if outcome == "stopped_before_prepare":
            if destination.exists():
                raise ReferenceExecutionProtocolViolation(
                    "Stopped-before-prepare outcome left a destination"
                )
            return
        if not destination.is_dir():
            raise ReferenceExecutionProtocolViolation(
                "Reference terminal outcome did not leave the declared run directory"
            )
        if outcome == "prepared_not_executed":
            verify_prepared_run(destination)
            return
        report = collect_run_report(destination)
        failed_checks = tuple(check.label for check in report.checks if check.status != "pass")
        if failed_checks:
            raise ReferenceExecutionProtocolViolation(
                "Parent verification failed: " + ", ".join(failed_checks)
            )
        expected_status = "completed" if outcome == "completed" else "interrupted"
        if report.result["status"] != expected_status:
            raise ReferenceExecutionProtocolViolation(
                "Reference terminal outcome differs from independently reviewed result"
            )
        result_path = destination / "result.json"
        if terminal.payload["result_sha256"] != sha256_file(result_path):
            raise ReferenceExecutionProtocolViolation(
                "Reference result hash differs after parent verification"
            )

    def _send_cancel_locked(self, process: subprocess.Popen[str]) -> bool:
        if process.stdin is None or process.stdin.closed:
            return False
        command = DesktopReferenceWorkerCommand(self.request.request_id)
        try:
            process.stdin.write(json.dumps(command.as_dict(), sort_keys=True) + "\n")
            process.stdin.flush()
        except (OSError, ValueError) as error:
            raise ReferenceExecutionControllerError(
                "Could not deliver reference cancellation command"
            ) from error
        self._cancel_sent = True
        self._state = "cancelling"
        return True

    @staticmethod
    def _drain_stderr(stream: TextIO | None, buffer: _BoundedText) -> None:
        if stream is None:
            return
        for chunk in iter(lambda: stream.read(8192), ""):
            buffer.append(chunk)

    @staticmethod
    def _stop_process(process: subprocess.Popen[str]) -> None:
        if process.poll() is not None:
            return
        try:
            process.terminate()
            process.wait(timeout=TERMINAL_EXIT_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            try:
                process.kill()
                process.wait(timeout=TERMINAL_EXIT_TIMEOUT_SECONDS)
            except (OSError, subprocess.TimeoutExpired):
                pass
        except OSError:
            pass

    @staticmethod
    def _close_pipe(stream: TextIO | None) -> None:
        if stream is None or stream.closed:
            return
        try:
            stream.close()
        except OSError:
            pass
