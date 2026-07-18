"""Fail-closed parent controller for approval-bound reference preparation."""

from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
import sys
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Literal

from diffeoforge.desktop.reference_preparation_request import (
    DesktopReferencePreparationRequest,
)
from diffeoforge.desktop.reference_preparation_worker_protocol import (
    DesktopReferencePreparationWorkerEvent,
    DesktopReferencePreparationWorkerProtocolError,
    ReferencePreparationWorkerEventLedger,
)
from diffeoforge.runs import verify_prepared_run
from diffeoforge.strict_json import load_strict_json_object

ReferencePreparationControllerState = Literal["idle", "running", "verified", "failed"]
ReferencePreparationEventCallback = Callable[
    [DesktopReferencePreparationWorkerEvent], None
]
DEFAULT_PREPARATION_SUPERVISION_TIMEOUT_SECONDS = 600.0
DEFAULT_PREPARATION_STDOUT_LINE_LIMIT = 262_144
DEFAULT_PREPARATION_STDERR_LIMIT = 65_536
MAX_PREPARATION_EVENTS = 5
FROZEN_REFERENCE_PREPARATION_WORKER_BASENAME = (
    "DiffeoForgeReferencePreparationWorker"
)


class ReferencePreparationControllerError(RuntimeError):
    """Base class for preparation-child launch and verification failures."""


class ReferencePreparationProtocolViolation(ReferencePreparationControllerError):
    """Raised when the child violates the bounded preparation protocol."""

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


class ReferencePreparationProcessError(ReferencePreparationControllerError):
    """Raised when the preparation child cannot be contained or exits incompletely."""

    def __init__(self, message: str, *, exit_code: int | None, stderr: str) -> None:
        super().__init__(message)
        self.exit_code = exit_code
        self.stderr = stderr


class ReferencePreparationExecutionError(ReferencePreparationControllerError):
    """Preserve one schema-valid failed terminal from the preparation child."""

    def __init__(
        self,
        event: DesktopReferencePreparationWorkerEvent,
        *,
        exit_code: int,
        stderr: str,
    ) -> None:
        super().__init__(str(event.payload["message"]))
        self.event = event
        self.exit_code = exit_code
        self.stderr = stderr


def default_reference_preparation_worker_command() -> tuple[str, ...]:
    """Resolve the source module or its dedicated sibling frozen executable."""

    if getattr(sys, "frozen", False):
        desktop_executable = Path(sys.executable).resolve()
        suffix = ".exe" if os.name == "nt" else ""
        worker = desktop_executable.with_name(
            f"{FROZEN_REFERENCE_PREPARATION_WORKER_BASENAME}{suffix}"
        )
        return (str(worker),)
    return (
        sys.executable,
        "-m",
        "diffeoforge.desktop.reference_preparation_worker_harness",
    )


def _create_windows_preparation_job():
    if os.name != "nt":
        return None
    from diffeoforge.desktop.windows_job import WindowsKillOnCloseJob

    return WindowsKillOnCloseJob()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class ReferencePreparationControllerResult:
    """One reconciled and independently reverified preparation-only outcome."""

    request_id: str
    exit_code: int
    terminal_event: DesktopReferencePreparationWorkerEvent
    events: tuple[DesktopReferencePreparationWorkerEvent, ...]
    stderr: str
    manifest_sha256: str

    @property
    def prepared_not_executed(self) -> bool:
        return self.terminal_event.payload["outcome"] == "prepared_not_executed"


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
            rendered = b"".join(self._parts).decode("utf-8", errors="replace")
            if self._truncated:
                rendered += "\n[stderr truncated by DiffeoForge]"
            return rendered


class ReferencePreparationWorkerController:
    """Launch, contain, and exactly reconcile one preparation-only child."""

    def __init__(
        self,
        request: DesktopReferencePreparationRequest,
        *,
        worker_command: Sequence[str] | None = None,
        cwd: Path | str | None = None,
        supervision_timeout: float = DEFAULT_PREPARATION_SUPERVISION_TIMEOUT_SECONDS,
        stdout_line_limit: int = DEFAULT_PREPARATION_STDOUT_LINE_LIMIT,
        stderr_limit: int = DEFAULT_PREPARATION_STDERR_LIMIT,
    ) -> None:
        if not isinstance(request, DesktopReferencePreparationRequest):
            raise TypeError("request must be a DesktopReferencePreparationRequest")
        command = (
            default_reference_preparation_worker_command()
            if worker_command is None
            else tuple(worker_command)
        )
        if not command or any(not isinstance(item, str) or not item for item in command):
            raise ValueError("worker_command must contain nonempty strings")
        if (
            isinstance(supervision_timeout, bool)
            or not isinstance(supervision_timeout, (int, float))
            or not math.isfinite(float(supervision_timeout))
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
        self._state: ReferencePreparationControllerState = "idle"
        self._process: subprocess.Popen[bytes] | None = None

    @property
    def state(self) -> ReferencePreparationControllerState:
        with self._lock:
            return self._state

    def run(
        self,
        *,
        event_callback: ReferencePreparationEventCallback | None = None,
    ) -> ReferencePreparationControllerResult:
        """Synchronously supervise one bounded preparation-only child."""

        if event_callback is not None and not callable(event_callback):
            raise TypeError("event_callback must be callable or None")
        with self._lock:
            if self._state != "idle":
                raise ReferencePreparationControllerError(
                    "Reference preparation controller is single-use"
                )
            self._state = "running"

        try:
            self.request.verify_inputs()
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            with self._lock:
                self._state = "failed"
            raise ReferencePreparationControllerError(
                f"Reference preparation request is no longer valid: {error}"
            ) from error

        process: subprocess.Popen[bytes] | None = None
        worker_job = None
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        try:
            worker_job = _create_windows_preparation_job()
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
            raise ReferencePreparationProcessError(
                f"Could not launch and contain reference preparation worker: {error}",
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
            name="diffeoforge-reference-preparation-stderr-reader",
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
        ledger = ReferencePreparationWorkerEventLedger(self.request)
        failed = True

        try:
            if process.stdin is None or process.stdout is None:
                raise ReferencePreparationProcessError(
                    "Reference preparation worker pipes were not created",
                    exit_code=process.poll(),
                    stderr="",
                )
            request_line = json.dumps(
                self.request.as_dict(),
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8") + b"\n"
            try:
                written = process.stdin.write(request_line)
                if written != len(request_line):
                    raise OSError(
                        "Reference preparation request pipe accepted only "
                        f"{written!r} of {len(request_line)} bytes"
                    )
                process.stdin.flush()
            except (OSError, ValueError) as error:
                raise ReferencePreparationProcessError(
                    "Could not deliver the reference preparation request",
                    exit_code=process.poll(),
                    stderr=stderr_buffer.render(),
                ) from error
            self._close_pipe(process.stdin)

            while True:
                raw_line = process.stdout.readline(self._stdout_line_limit + 1)
                if not raw_line:
                    break
                if len(raw_line) > self._stdout_line_limit:
                    raise ReferencePreparationProtocolViolation(
                        "Reference preparation worker stdout line exceeds the configured "
                        "limit"
                    )
                if not raw_line.endswith(b"\n"):
                    raise ReferencePreparationProtocolViolation(
                        "Reference preparation worker stdout line is not LF-terminated"
                    )
                if raw_line.strip() == b"":
                    raise ReferencePreparationProtocolViolation(
                        "Reference preparation worker emitted a blank stdout line"
                    )
                if len(ledger.events) >= MAX_PREPARATION_EVENTS:
                    raise ReferencePreparationProtocolViolation(
                        "Reference preparation worker emitted more than five events"
                    )
                try:
                    value = load_strict_json_object(
                        raw_line,
                        Path("<reference-preparation-worker-stdout>"),
                        label="Reference preparation worker event",
                    )
                    event = DesktopReferencePreparationWorkerEvent.from_dict(value)
                    ledger.accept(event)
                except (
                    DesktopReferencePreparationWorkerProtocolError,
                    OSError,
                    TypeError,
                    UnicodeError,
                    ValueError,
                ) as error:
                    raise ReferencePreparationProtocolViolation(str(error)) from error
                if event_callback is not None:
                    event_callback(event)

            exit_code = process.wait()
            timer.cancel()
            stderr_thread.join()
            stderr = stderr_buffer.render()
            if timed_out.is_set():
                raise ReferencePreparationProcessError(
                    "Reference preparation worker exceeded the supervision timeout",
                    exit_code=exit_code,
                    stderr=stderr,
                )
            try:
                terminal = ledger.reconcile()
            except DesktopReferencePreparationWorkerProtocolError as error:
                raise ReferencePreparationProcessError(
                    str(error), exit_code=exit_code, stderr=stderr
                ) from error
            self._verify_exact_lifecycle(ledger.events)
            outcome = str(terminal.payload["outcome"])
            expected_exit_code = {"prepared_not_executed": 0, "failed": 1}.get(outcome)
            if expected_exit_code is None:
                raise ReferencePreparationProtocolViolation(
                    f"Preparation worker reported unsupported outcome {outcome!r}"
                )
            if exit_code != expected_exit_code:
                raise ReferencePreparationProtocolViolation(
                    f"Reference preparation outcome {outcome!r} requires exit code "
                    f"{expected_exit_code}, observed {exit_code}"
                )
            if outcome == "failed":
                raise ReferencePreparationExecutionError(
                    terminal,
                    exit_code=exit_code,
                    stderr=stderr,
                )

            manifest_sha256 = self._verify_published_run(terminal)
            result = ReferencePreparationControllerResult(
                request_id=self.request.request_id,
                exit_code=exit_code,
                terminal_event=terminal,
                events=ledger.events,
                stderr=stderr,
                manifest_sha256=manifest_sha256,
            )
            with self._lock:
                self._state = "verified"
            failed = False
            return result
        except ReferencePreparationProtocolViolation as error:
            self._stop_process(process)
            error.exit_code = process.poll()
            error.stderr = stderr_buffer.render()
            raise
        except ReferencePreparationControllerError:
            raise
        except Exception as error:
            raise ReferencePreparationControllerError(
                f"Reference preparation supervision failed: {error}"
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
                        raise ReferencePreparationProcessError(
                            f"Could not close reference preparation Job Object: {error}",
                            exit_code=process.poll(),
                            stderr=stderr_buffer.render(),
                        ) from error

    def _verify_exact_lifecycle(
        self,
        events: tuple[DesktopReferencePreparationWorkerEvent, ...],
    ) -> None:
        kinds = tuple(event.kind for event in events)
        terminal = events[-1]
        if terminal.payload["outcome"] == "prepared_not_executed":
            if kinds != ("accepted", "phase", "phase", "phase", "terminal"):
                raise ReferencePreparationProtocolViolation(
                    "Successful reference preparation must emit exactly five events"
                )
            phases = tuple(str(event.payload["phase"]) for event in events[1:4])
            expected = ("verify_request", "prepare_approved", "verify_prepared_run")
            if phases != expected:
                raise ReferencePreparationProtocolViolation(
                    "Successful reference preparation emitted a different phase sequence"
                )
            return
        if len(events) < 3 or kinds[0] != "accepted" or kinds[-1] != "terminal":
            raise ReferencePreparationProtocolViolation(
                "Failed reference preparation requires acceptance and a phase prefix"
            )
        if any(kind != "phase" for kind in kinds[1:-1]):
            raise ReferencePreparationProtocolViolation(
                "Failed reference preparation contains a non-phase intermediate event"
            )
        if events[1].payload["phase"] != "verify_request":
            raise ReferencePreparationProtocolViolation(
                "Failed reference preparation must enter verify_request"
            )

    def _verify_published_run(
        self,
        terminal: DesktopReferencePreparationWorkerEvent,
    ) -> str:
        try:
            manifest = verify_prepared_run(self.request.destination)
            manifest_path = self.request.destination / "manifest.json"
            manifest_sha256 = _sha256_file(manifest_path)
            bindings = {
                "manifest SHA-256": (
                    manifest_sha256 == terminal.payload["manifest_sha256"]
                ),
                "run ID": manifest["run_id"] == self.request.run_id,
                "configuration SHA-256": (
                    manifest["source_config"]["sha256"]
                    == self.request.expected_config_sha256
                ),
                "backend": manifest["backend"]["id"] == self.request.engine,
            }
        except (KeyError, OSError, RuntimeError, TypeError, ValueError) as error:
            raise ReferencePreparationProtocolViolation(
                f"Prepared-run parent verification failed: {error}"
            ) from error
        for label, matches in bindings.items():
            if not matches:
                raise ReferencePreparationProtocolViolation(
                    f"Prepared-run parent verification found a different {label}"
                )
        return manifest_sha256

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
