"""Qt-independent parent controller for one versioned desktop worker process."""

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

from diffeoforge.desktop.worker_protocol import (
    DesktopWorkerCommand,
    DesktopWorkerEvent,
    DesktopWorkerProtocolError,
    DesktopWorkerRequest,
    parse_json_object,
    sha256_file,
)

DesktopWorkerControllerState = Literal[
    "idle",
    "running",
    "cancelling",
    "completed",
    "cancelled",
    "failed",
]
DesktopWorkerEventCallback = Callable[[DesktopWorkerEvent], None]
TERMINAL_EXIT_TIMEOUT_SECONDS = 5
FROZEN_WORKER_BASENAME = "DiffeoForgeWorker"


class DesktopWorkerControllerError(RuntimeError):
    """Base class for parent-side launch, transport, and verification failures."""


class DesktopWorkerProtocolViolation(DesktopWorkerControllerError):
    """Raised when a child process violates the reviewed worker protocol."""

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


class DesktopWorkerProcessError(DesktopWorkerControllerError):
    """Raised when a worker exits without a valid terminal event."""

    def __init__(self, message: str, *, exit_code: int | None, stderr: str) -> None:
        super().__init__(message)
        self.exit_code = exit_code
        self.stderr = stderr


class DesktopWorkerExecutionError(DesktopWorkerControllerError):
    """Raised for a schema-valid terminal failure reported by the worker."""

    def __init__(
        self,
        event: DesktopWorkerEvent,
        *,
        exit_code: int,
        stderr: str,
    ) -> None:
        super().__init__(str(event.payload["message"]))
        self.event = event
        self.exit_code = exit_code
        self.stderr = stderr


def default_desktop_worker_command() -> tuple[str, ...]:
    """Resolve the source worker module or a sibling frozen worker executable."""

    if getattr(sys, "frozen", False):
        desktop_executable = Path(sys.executable).resolve()
        suffix = ".exe" if os.name == "nt" else ""
        worker = desktop_executable.with_name(f"{FROZEN_WORKER_BASENAME}{suffix}")
        return (str(worker),)
    return (sys.executable, "-m", "diffeoforge.desktop.worker")


@dataclass(frozen=True)
class DesktopWorkerControllerResult:
    """One reconciled completed or cancelled worker outcome."""

    request_id: str
    exit_code: int
    terminal_event: DesktopWorkerEvent
    events: tuple[DesktopWorkerEvent, ...]
    stderr: str

    @property
    def completed(self) -> bool:
        return self.terminal_event.kind == "completed"

    @property
    def cancelled(self) -> bool:
        return self.terminal_event.kind == "cancelled"


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


class _EventLedger:
    def __init__(self, request_id: str) -> None:
        self._request_id = request_id
        self._events: list[DesktopWorkerEvent] = []
        self._started = False
        self._terminal: DesktopWorkerEvent | None = None

    @property
    def events(self) -> tuple[DesktopWorkerEvent, ...]:
        return tuple(self._events)

    def accept(self, event: DesktopWorkerEvent) -> None:
        if event.request_id != self._request_id:
            raise DesktopWorkerProtocolViolation(
                "Worker event request_id does not match the reviewed launch request"
            )
        if event.sequence != len(self._events):
            raise DesktopWorkerProtocolViolation(
                "Worker event sequence is not contiguous from zero"
            )
        if self._terminal is not None:
            raise DesktopWorkerProtocolViolation("Worker emitted data after a terminal event")

        if not self._events:
            if event.kind == "started":
                self._started = True
            elif event.kind != "failed":
                raise DesktopWorkerProtocolViolation(
                    "First worker event must be started or a launch-time failure"
                )
        elif event.kind == "started":
            raise DesktopWorkerProtocolViolation("Worker emitted more than one started event")
        elif not self._started:
            raise DesktopWorkerProtocolViolation(
                "Worker emitted a nonterminal event without started"
            )

        if event.kind in {"completed", "cancelled"} and not self._started:
            raise DesktopWorkerProtocolViolation(
                "Worker completed or cancelled without a started event"
            )
        if event.kind in {"completed", "cancelled", "failed"}:
            self._terminal = event
        self._events.append(event)

    def reconcile(self, exit_code: int) -> DesktopWorkerEvent:
        if self._terminal is None:
            raise DesktopWorkerProcessError(
                "Worker exited without a terminal event",
                exit_code=exit_code,
                stderr="",
            )
        expected = {"completed": 0, "cancelled": 130, "failed": 1}[self._terminal.kind]
        if exit_code != expected:
            raise DesktopWorkerProtocolViolation(
                f"Worker terminal event {self._terminal.kind!r} requires exit code "
                f"{expected}, observed {exit_code}"
            )
        return self._terminal


class DesktopWorkerController:
    """Launch and fail-closed supervise one Modern CPU desktop worker."""

    def __init__(
        self,
        request: DesktopWorkerRequest,
        *,
        worker_command: Sequence[str] | None = None,
        cwd: Path | str | None = None,
        stderr_limit: int = 65_536,
    ) -> None:
        if not isinstance(request, DesktopWorkerRequest):
            raise TypeError("request must be a DesktopWorkerRequest")
        command = (
            default_desktop_worker_command()
            if worker_command is None
            else tuple(worker_command)
        )
        if not command or any(not isinstance(item, str) or not item for item in command):
            raise ValueError("worker_command must contain nonempty strings")
        self.request = request
        self.worker_command = tuple(command)
        self.cwd = None if cwd is None else Path(cwd).expanduser().resolve()
        self._stderr_limit = stderr_limit
        _BoundedText(stderr_limit)
        self._lock = threading.RLock()
        self._process: subprocess.Popen[str] | None = None
        self._state: DesktopWorkerControllerState = "idle"
        self._request_written = False
        self._cancel_pending = False
        self._cancel_sent = False

    @property
    def state(self) -> DesktopWorkerControllerState:
        with self._lock:
            return self._state

    def request_cancel(self) -> bool:
        """Send the single matching v0.1 cancel command if the worker is active."""

        with self._lock:
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
        event_callback: DesktopWorkerEventCallback | None = None,
    ) -> DesktopWorkerControllerResult:
        """Synchronously supervise one process; callers may place this in a GUI worker thread."""

        if event_callback is not None and not callable(event_callback):
            raise TypeError("event_callback must be callable or None")
        with self._lock:
            if self._state != "idle":
                raise DesktopWorkerControllerError("Desktop worker controller is single-use")
            self._state = "running"

        try:
            self.request.verify_launch_inputs()
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            with self._lock:
                self._state = "failed"
            raise DesktopWorkerControllerError(
                f"Worker launch request is no longer valid: {error}"
            ) from error

        creationflags = 0
        if os.name == "nt":
            creationflags = subprocess.CREATE_NO_WINDOW
        try:
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
                creationflags=creationflags,
            )
        except OSError as error:
            with self._lock:
                self._state = "failed"
            raise DesktopWorkerProcessError(
                f"Could not launch desktop worker: {error}",
                exit_code=None,
                stderr="",
            ) from error

        with self._lock:
            self._process = process
        stderr_buffer = _BoundedText(self._stderr_limit)
        stderr_thread = threading.Thread(
            target=self._drain_stderr,
            args=(process.stderr, stderr_buffer),
            name="diffeoforge-worker-stderr-reader",
            daemon=True,
        )
        stderr_thread.start()
        ledger = _EventLedger(self.request.request_id)
        exit_code: int | None = None
        failed = True

        try:
            if process.stdin is None or process.stdout is None:
                raise DesktopWorkerProcessError(
                    "Worker pipes were not created",
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
            for line in process.stdout:
                if not line.strip():
                    raise DesktopWorkerProtocolViolation("Worker emitted a blank stdout line")
                try:
                    event = DesktopWorkerEvent.from_dict(
                        parse_json_object(line, "Desktop worker event")
                    )
                except (DesktopWorkerProtocolError, TypeError, ValueError) as error:
                    raise DesktopWorkerProtocolViolation(str(error)) from error
                self._verify_event_binding(event)
                ledger.accept(event)
                if event_callback is not None:
                    event_callback(event)
                if event.kind in {"completed", "cancelled", "failed"}:
                    self._close_pipe(process.stdin)
                    try:
                        process.wait(timeout=TERMINAL_EXIT_TIMEOUT_SECONDS)
                    except subprocess.TimeoutExpired as error:
                        raise DesktopWorkerProcessError(
                            "Worker did not exit after its terminal event",
                            exit_code=None,
                            stderr=stderr_buffer.render(),
                        ) from error
            exit_code = process.wait()
            stderr_thread.join()
            stderr = stderr_buffer.render()
            try:
                terminal = ledger.reconcile(exit_code)
            except DesktopWorkerProcessError as error:
                raise DesktopWorkerProcessError(
                    str(error), exit_code=exit_code, stderr=stderr
                ) from error

            if terminal.kind == "failed":
                raise DesktopWorkerExecutionError(
                    terminal,
                    exit_code=exit_code,
                    stderr=stderr,
                )
            if terminal.kind == "completed":
                self._verify_completion(terminal)
                state: DesktopWorkerControllerState = "completed"
            else:
                if self.request.destination.exists():
                    raise DesktopWorkerProtocolViolation(
                        "Cancelled worker left a published destination"
                    )
                state = "cancelled"
            result = DesktopWorkerControllerResult(
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
        except DesktopWorkerProtocolViolation as error:
            self._stop_process(process)
            stderr_thread.join(timeout=TERMINAL_EXIT_TIMEOUT_SECONDS)
            error.exit_code = process.poll()
            error.stderr = stderr_buffer.render()
            raise
        except DesktopWorkerControllerError:
            raise
        except Exception as error:
            raise DesktopWorkerControllerError(
                f"Desktop worker supervision failed: {error}"
            ) from error
        finally:
            if failed:
                self._stop_process(process)
                stderr_thread.join(timeout=5)
                with self._lock:
                    self._state = "failed"
            self._close_pipe(process.stdin)
            self._close_pipe(process.stdout)
            self._close_pipe(process.stderr)
            with self._lock:
                self._process = None

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

    def _verify_completion(self, terminal: DesktopWorkerEvent) -> None:
        destination = Path(terminal.payload["destination"]).expanduser().resolve()
        if destination != self.request.destination:
            raise DesktopWorkerProtocolViolation(
                "Completed worker destination differs from the reviewed request"
            )
        try:
            from diffeoforge.modern_workflow import MANIFEST_NAME, verify_modern_workflow

            manifest = verify_modern_workflow(destination)
        except (ImportError, OSError, RuntimeError, TypeError, ValueError) as error:
            raise DesktopWorkerProtocolViolation(
                f"Completed worker result did not independently verify: {error}"
            ) from error
        observed_hash = sha256_file(destination / MANIFEST_NAME)
        if terminal.payload["manifest_sha256"] != observed_hash:
            raise DesktopWorkerProtocolViolation(
                "Completed worker manifest hash differs after parent verification"
            )
        if terminal.payload["subject_count"] != len(manifest["input"]["subjects"]):
            raise DesktopWorkerProtocolViolation(
                "Completed worker subject count differs after parent verification"
            )
        if terminal.payload["bundle_path"] != manifest["result_bundle"]["path"]:
            raise DesktopWorkerProtocolViolation(
                "Completed worker bundle path differs after parent verification"
            )

    def _verify_event_binding(self, event: DesktopWorkerEvent) -> None:
        if event.kind == "started":
            if event.payload["engine"] != self.request.engine:
                raise DesktopWorkerProtocolViolation(
                    "Started worker engine differs from the reviewed request"
                )
            if event.payload["config_sha256"] != self.request.expected_config_sha256:
                raise DesktopWorkerProtocolViolation(
                    "Started worker configuration hash differs from the reviewed request"
                )
        if event.kind in {"started", "completed", "cancelled", "failed"}:
            destination = Path(event.payload["destination"]).expanduser().resolve()
            if destination != self.request.destination:
                raise DesktopWorkerProtocolViolation(
                    f"Worker {event.kind} destination differs from the reviewed request"
                )

    def _send_cancel_locked(self, process: subprocess.Popen[str]) -> bool:
        if process.stdin is None:
            raise DesktopWorkerControllerError("Worker stdin is unavailable for cancellation")
        if process.stdin.closed:
            return False
        command = DesktopWorkerCommand(request_id=self.request.request_id)
        line = json.dumps(
            command.as_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        try:
            process.stdin.write(line + "\n")
            process.stdin.flush()
        except (OSError, ValueError) as error:
            raise DesktopWorkerControllerError(
                "Could not deliver the worker cancellation command"
            ) from error
        self._cancel_sent = True
        self._state = "cancelling"
        return True
