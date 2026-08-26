"""Authenticated persistent HTTP queue for portable Modern atlas requests."""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import os
import queue
import re
import shutil
import socket
import ssl
import threading
import uuid
import zipfile
from collections.abc import Callable
from copy import deepcopy
from datetime import UTC, datetime
from functools import cache
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import jsonschema

from diffeoforge.atomic_io import write_text_safely
from diffeoforge.mesh import sha256_file
from diffeoforge.modern_progress import ModernProgressEvent
from diffeoforge.modern_workflow import ModernWorkflowCancelled
from diffeoforge.remote_atlas_job import (
    MANIFEST_NAME,
    RemoteAtlasJobError,
    run_remote_atlas_job,
    verify_remote_atlas_job,
    verify_remote_atlas_result,
)
from diffeoforge.remote_atlas_transport import (
    ARCHIVE_CHUNK_BYTES,
    DEFAULT_MAX_ARCHIVE_FILES,
    DEFAULT_MAX_UNPACKED_BYTES,
    REMOTE_API_VERSION,
    REQUEST_MEDIA_TYPE,
    RESULT_MEDIA_TYPE,
    RemoteAtlasTransportError,
    create_remote_atlas_result_archive,
    extract_remote_atlas_job_archive,
    sha256_path,
)

SERVER_JOB_VERSION = "0.1"
SERVER_EVENT_VERSION = "0.1"
DEFAULT_MAX_UPLOAD_BYTES = 8 * 1024**3
DEFAULT_MAX_ACTIVE_JOBS = 100
TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled", "interrupted"})
ACTIVE_STATUSES = frozenset({"queued", "running", "cancel_requested"})
ALL_STATUSES = TERMINAL_STATUSES | ACTIVE_STATUSES
_JOB_ID = re.compile(r"^[0-9a-f]{32}$")
_ARCHIVE_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class RemoteAtlasServerError(RuntimeError):
    """Base error for server storage, state, or request failures."""


class RemoteAtlasServerNotFound(RemoteAtlasServerError):
    """Raised when a server job does not exist."""


class RemoteAtlasServerConflict(RemoteAtlasServerError):
    """Raised when a requested transition conflicts with job state."""


class RemoteAtlasServerCapacity(RemoteAtlasServerError):
    """Raised when bounded queue capacity is exhausted."""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        indent=2,
        sort_keys=True,
        ensure_ascii=False,
        allow_nan=False,
    ) + "\n"


def _linklike(path: Path) -> bool:
    is_junction = getattr(path, "is_junction", None)
    return path.is_symlink() or (callable(is_junction) and is_junction())


def _prepare_root(path: Path | str) -> Path:
    candidate = Path(path).expanduser().absolute()
    existing = candidate
    while not existing.exists():
        parent = existing.parent
        if parent == existing:
            raise RemoteAtlasServerError(f"Could not resolve server root parent: {candidate}")
        existing = parent
    for item in (existing, *existing.parents):
        if _linklike(item):
            raise RemoteAtlasServerError(f"Server root uses a symbolic path: {item}")
    candidate.mkdir(parents=True, exist_ok=True)
    if _linklike(candidate) or not candidate.is_dir():
        raise RemoteAtlasServerError(f"Server root is not a real directory: {candidate}")
    return candidate.resolve()


def _job_id(value: str) -> str:
    if _JOB_ID.fullmatch(value) is None:
        raise RemoteAtlasServerError("Server job ID is invalid")
    return value


def _read_json_object(path: Path, *, label: str) -> dict[str, Any]:
    if _linklike(path) or not path.is_file():
        raise RemoteAtlasServerError(f"{label} is missing or symbolic: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8", errors="strict"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RemoteAtlasServerError(f"{label} is unreadable JSON: {path}") from error
    if not isinstance(value, dict):
        raise RemoteAtlasServerError(f"{label} must be a JSON object: {path}")
    return value


@cache
def _state_schema() -> dict[str, Any]:
    resource = files("diffeoforge.schema").joinpath(
        "remote-atlas-server-job-v0.1.json"
    )
    return json.loads(resource.read_text(encoding="utf-8"))


def _validate_state(state: dict[str, Any], *, expected_job_id: str) -> None:
    try:
        jsonschema.Draft202012Validator(_state_schema()).validate(state)
    except jsonschema.ValidationError as error:
        location = ".".join(str(part) for part in error.absolute_path) or "document"
        raise RemoteAtlasServerError(
            f"Server job state schema failed at {location}: {error.message}"
        ) from error
    if state["job_id"] != expected_job_id:
        raise RemoteAtlasServerError("Server job state ID differs from its directory")
    for field in ("created_at", "updated_at"):
        try:
            timestamp = datetime.fromisoformat(state[field].replace("Z", "+00:00"))
        except ValueError as error:
            raise RemoteAtlasServerError(f"Server job {field} is invalid") from error
        if timestamp.tzinfo is None:
            raise RemoteAtlasServerError(f"Server job {field} lacks a timezone")


Runner = Callable[..., Path]


class RemoteAtlasJobManager:
    """Persist requests and execute them through the existing Modern workflow."""

    def __init__(
        self,
        root: Path | str,
        *,
        worker_count: int = 1,
        max_active_jobs: int = DEFAULT_MAX_ACTIVE_JOBS,
        max_archive_files: int = DEFAULT_MAX_ARCHIVE_FILES,
        max_unpacked_bytes: int = DEFAULT_MAX_UNPACKED_BYTES,
        runner: Runner = run_remote_atlas_job,
        autostart: bool = True,
    ) -> None:
        if not 1 <= worker_count <= 64:
            raise ValueError("worker_count must be between 1 and 64")
        if not 1 <= max_active_jobs <= 1_000_000:
            raise ValueError("max_active_jobs must be between 1 and 1000000")
        self.root = _prepare_root(root)
        self.jobs_root = self.root / "jobs"
        self.incoming_root = self.root / "incoming"
        self.jobs_root.mkdir(exist_ok=True)
        self.incoming_root.mkdir(exist_ok=True)
        if _linklike(self.jobs_root) or _linklike(self.incoming_root):
            raise RemoteAtlasServerError("Server storage subdirectories must not be symbolic")
        self.worker_count = worker_count
        self.max_active_jobs = max_active_jobs
        self.max_archive_files = max_archive_files
        self.max_unpacked_bytes = max_unpacked_bytes
        self._runner = runner
        self._lock = threading.RLock()
        self._queue: queue.Queue[str | None] = queue.Queue()
        self._cancel_events: dict[str, threading.Event] = {}
        self._workers: list[threading.Thread] = []
        self._submissions_in_progress = 0
        self._started = False
        self._closed = False
        self._recover_states()
        if autostart:
            self.start()

    def _job_directory(self, job_id: str) -> Path:
        return self.jobs_root / _job_id(job_id)

    def _state_path(self, job_id: str) -> Path:
        return self._job_directory(job_id) / "state.json"

    def _events_path(self, job_id: str) -> Path:
        return self._job_directory(job_id) / "events.jsonl"

    def _load_state_locked(self, job_id: str) -> dict[str, Any]:
        directory = self._job_directory(job_id)
        if _linklike(directory) or not directory.is_dir():
            raise RemoteAtlasServerNotFound(f"Remote job does not exist: {job_id}")
        state = _read_json_object(self._state_path(job_id), label="Server job state")
        _validate_state(state, expected_job_id=job_id)
        return state

    def _write_state_locked(self, job_id: str, state: dict[str, Any]) -> None:
        state["updated_at"] = _now()
        _validate_state(state, expected_job_id=job_id)
        write_text_safely(
            self._state_path(job_id),
            _canonical_json(state),
            overwrite=True,
        )

    def _append_event_locked(
        self,
        job_id: str,
        state: dict[str, Any],
        *,
        kind: str,
        status: str,
        message: str,
        progress: dict[str, Any] | None = None,
    ) -> None:
        index = int(state["progress"]["event_count"])
        event = {
            "server_event_version": SERVER_EVENT_VERSION,
            "index": index,
            "timestamp": _now(),
            "kind": kind,
            "status": status,
            "message": message,
            "progress": progress,
        }
        payload = json.dumps(
            event,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        )
        with self._events_path(job_id).open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(payload + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        state["progress"]["event_count"] = index + 1
        if progress is not None:
            state["progress"]["latest"] = progress

    def _reconcile_event_tail_locked(
        self,
        job_id: str,
        state: dict[str, Any],
    ) -> None:
        """Discard only event bytes written before their state commit completed."""

        path = self._events_path(job_id)
        if _linklike(path) or not path.is_file():
            raise RemoteAtlasServerError("Remote job event log is missing or symbolic")
        expected_count = int(state["progress"]["event_count"])
        with path.open("r+b") as handle:
            committed_end = 0
            for expected_index in range(expected_count):
                line = handle.readline()
                if not line:
                    raise RemoteAtlasServerError(
                        "Remote job event log is shorter than committed state"
                    )
                try:
                    event = json.loads(line.decode("utf-8", errors="strict"))
                except (UnicodeError, json.JSONDecodeError) as error:
                    raise RemoteAtlasServerError(
                        f"Committed remote job event {expected_index} is invalid"
                    ) from error
                if not isinstance(event, dict) or event.get("index") != expected_index:
                    raise RemoteAtlasServerError("Remote job event ordering differs")
                committed_end = handle.tell()
            if handle.read(1):
                handle.truncate(committed_end)
                handle.flush()
                os.fsync(handle.fileno())

    def _recover_states(self) -> None:
        queued: list[tuple[str, str]] = []
        for directory in sorted(self.jobs_root.iterdir()):
            if directory.name.startswith("."):
                continue
            if _JOB_ID.fullmatch(directory.name) is None or _linklike(directory):
                raise RemoteAtlasServerError(
                    f"Server jobs directory contains an unsafe entry: {directory}"
                )
            with self._lock:
                state = self._load_state_locked(directory.name)
                self._reconcile_event_tail_locked(directory.name, state)
                if state["status"] in {"running", "cancel_requested"}:
                    state["status"] = "interrupted"
                    state["cancel_requested"] = False
                    state["error"] = {
                        "type": "ServerRestart",
                        "message": (
                            "Server stopped before a terminal result. Private checkpoint "
                            "state, if present, was preserved for explicit recovery."
                        ),
                    }
                    self._append_event_locked(
                        directory.name,
                        state,
                        kind="server",
                        status="interrupted",
                        message="Server restart detected an interrupted job",
                    )
                    self._write_state_locked(directory.name, state)
                elif state["status"] == "queued":
                    queued.append((state["created_at"], directory.name))
                elif state["status"] == "completed":
                    verify_remote_atlas_result(
                        directory / "request",
                        directory / "result",
                    )
                    result_archive = directory / "result.zip"
                    if (
                        not result_archive.is_file()
                        or _linklike(result_archive)
                        or sha256_path(result_archive) != state["result"]["archive_sha256"]
                    ):
                        raise RemoteAtlasServerError(
                            f"Completed remote job archive differs: {directory.name}"
                        )
        for _, job_id in sorted(queued):
            self._queue.put(job_id)

    def start(self) -> None:
        with self._lock:
            if self._closed:
                raise RemoteAtlasServerError("Remote job manager is closed")
            if self._started:
                return
            self._started = True
            for index in range(self.worker_count):
                worker = threading.Thread(
                    target=self._worker_loop,
                    name=f"diffeoforge-remote-worker-{index + 1}",
                    daemon=True,
                )
                worker.start()
                self._workers.append(worker)

    def close(self, *, wait: bool = False) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            for _ in self._workers:
                self._queue.put(None)
        if wait:
            for worker in self._workers:
                worker.join()

    def _active_count_locked(self) -> int:
        count = 0
        for directory in self.jobs_root.iterdir():
            if _JOB_ID.fullmatch(directory.name) is None or not directory.is_dir():
                continue
            state = self._load_state_locked(directory.name)
            if state["status"] in ACTIVE_STATUSES:
                count += 1
        return count

    def submit_archive(
        self,
        archive_path: Path | str,
        *,
        archive_bytes: int,
        archive_sha256: str,
    ) -> dict[str, Any]:
        archive = Path(archive_path).expanduser().resolve()
        if (
            not archive.is_file()
            or _linklike(archive)
            or archive.stat().st_size != archive_bytes
            or _ARCHIVE_SHA256.fullmatch(archive_sha256) is None
            or sha256_path(archive) != archive_sha256
        ):
            raise RemoteAtlasServerError("Uploaded request archive identity differs")
        with self._lock:
            if self._closed:
                raise RemoteAtlasServerError("Remote job manager is closed")
            if (
                self._active_count_locked() + self._submissions_in_progress
                >= self.max_active_jobs
            ):
                raise RemoteAtlasServerCapacity("Remote atlas queue capacity is exhausted")
            self._submissions_in_progress += 1
        job_id = uuid.uuid4().hex
        final = self._job_directory(job_id)
        staging = self.jobs_root / f".{job_id}.tmp-{uuid.uuid4().hex}"
        try:
            staging.mkdir()
            request = extract_remote_atlas_job_archive(
                archive,
                staging / "request",
                max_files=self.max_archive_files,
                max_unpacked_bytes=self.max_unpacked_bytes,
            )
            manifest = verify_remote_atlas_job(request)
            timestamp = _now()
            state: dict[str, Any] = {
                "server_job_version": SERVER_JOB_VERSION,
                "job_id": job_id,
                "status": "queued",
                "created_at": timestamp,
                "updated_at": timestamp,
                "request": {
                    "archive_bytes": archive_bytes,
                    "archive_sha256": archive_sha256,
                    "manifest_sha256": sha256_file(request / MANIFEST_NAME),
                    "subjects": len(manifest["input"]["subjects"]),
                    "device": manifest["execution"]["device"],
                    "precision": manifest["execution"]["precision"],
                    "engine_implementation": manifest["execution"][
                        "expected_engine_implementation"
                    ],
                },
                "progress": {"event_count": 1, "latest": None},
                "result": None,
                "error": None,
                "cancel_requested": False,
                "retention": {
                    "automatic_deletion_enabled": False,
                    "delete_after": None,
                },
            }
            event = {
                "server_event_version": SERVER_EVENT_VERSION,
                "index": 0,
                "timestamp": timestamp,
                "kind": "server",
                "status": "queued",
                "message": "Verified request accepted into the execution queue",
                "progress": None,
            }
            write_text_safely(
                staging / "events.jsonl",
                json.dumps(event, sort_keys=True, ensure_ascii=False) + "\n",
                overwrite=False,
            )
            write_text_safely(
                staging / "state.json",
                _canonical_json(state),
                overwrite=False,
            )
            with self._lock:
                if self._closed:
                    raise RemoteAtlasServerError("Remote job manager closed during submission")
                if final.exists() or final.is_symlink():
                    raise FileExistsError(
                        f"Remote server job destination already exists: {final}"
                    )
                staging.rename(final)
                self._queue.put(job_id)
        except BaseException:
            if staging.exists() and staging.parent == self.jobs_root:
                shutil.rmtree(staging)
            raise
        finally:
            with self._lock:
                self._submissions_in_progress -= 1
        return self.get_state(job_id)

    def get_state(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            return deepcopy(self._load_state_locked(_job_id(job_id)))

    def get_events(
        self,
        job_id: str,
        *,
        after: int = -1,
        limit: int = 100,
    ) -> dict[str, Any]:
        if after < -1:
            raise RemoteAtlasServerError("Event cursor must be -1 or nonnegative")
        if not 1 <= limit <= 1000:
            raise RemoteAtlasServerError("Event page limit must be between 1 and 1000")
        with self._lock:
            state = self._load_state_locked(_job_id(job_id))
            path = self._events_path(job_id)
            if _linklike(path) or not path.is_file():
                raise RemoteAtlasServerError("Remote job event log is missing or symbolic")
            events: list[dict[str, Any]] = []
            observed_count = 0
            with path.open("r", encoding="utf-8", errors="strict") as handle:
                for line_number, line in enumerate(handle):
                    observed_count = line_number + 1
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError as error:
                        raise RemoteAtlasServerError(
                            f"Remote job event line {line_number + 1} is invalid"
                        ) from error
                    if not isinstance(event, dict) or event.get("index") != line_number:
                        raise RemoteAtlasServerError("Remote job event ordering differs")
                    if line_number > after and len(events) < limit:
                        events.append(event)
            if int(state["progress"]["event_count"]) != observed_count:
                raise RemoteAtlasServerError("Remote job event count differs from state")
            next_after = after if not events else int(events[-1]["index"])
            return {
                "job_id": job_id,
                "events": events,
                "next_after": next_after,
                "has_more": next_after + 1 < observed_count,
            }

    def cancel(self, job_id: str) -> dict[str, Any]:
        validated = _job_id(job_id)
        with self._lock:
            state = self._load_state_locked(validated)
            status = state["status"]
            if status == "queued":
                state["status"] = "cancelled"
                state["cancel_requested"] = True
                self._append_event_locked(
                    validated,
                    state,
                    kind="server",
                    status="cancelled",
                    message="Queued job cancelled before execution",
                )
                self._write_state_locked(validated, state)
            elif status == "running":
                state["status"] = "cancel_requested"
                state["cancel_requested"] = True
                cancel = self._cancel_events.get(validated)
                if cancel is None:
                    raise RemoteAtlasServerError("Running job cancellation signal is missing")
                cancel.set()
                self._append_event_locked(
                    validated,
                    state,
                    kind="server",
                    status="cancel_requested",
                    message="Cooperative cancellation requested",
                )
                self._write_state_locked(validated, state)
            elif status == "cancel_requested":
                pass
            else:
                raise RemoteAtlasServerConflict(
                    f"Remote job is already terminal and cannot be cancelled: {status}"
                )
            return deepcopy(state)

    def result_archive(self, job_id: str) -> tuple[Path, dict[str, Any]]:
        validated = _job_id(job_id)
        with self._lock:
            state = self._load_state_locked(validated)
            if state["status"] != "completed":
                raise RemoteAtlasServerConflict(
                    f"Remote result is unavailable while job status is {state['status']}"
                )
            archive = self._job_directory(validated) / "result.zip"
            result = state["result"]
            if (
                not archive.is_file()
                or _linklike(archive)
                or archive.stat().st_size != result["archive_bytes"]
                or sha256_path(archive) != result["archive_sha256"]
            ):
                raise RemoteAtlasServerError("Remote result archive identity differs")
            return archive, deepcopy(state)

    def delete(self, job_id: str) -> dict[str, Any]:
        validated = _job_id(job_id)
        with self._lock:
            state = self._load_state_locked(validated)
            if state["status"] not in TERMINAL_STATUSES:
                raise RemoteAtlasServerConflict(
                    "Only a terminal remote job can be deleted"
                )
            directory = self._job_directory(validated)
            resolved = directory.resolve()
            if (
                _linklike(directory)
                or resolved.parent != self.jobs_root.resolve()
                or resolved.name != validated
            ):
                raise RemoteAtlasServerError("Refusing to delete an unsafe server job path")
            retired = self.jobs_root / f".deleted-{validated}-{uuid.uuid4().hex}"
            directory.rename(retired)
        shutil.rmtree(retired)
        return {"job_id": validated, "status": "deleted"}

    def _worker_loop(self) -> None:
        while True:
            job_id = self._queue.get()
            try:
                if job_id is None:
                    return
                self._execute_job(job_id)
            finally:
                self._queue.task_done()

    def _execute_job(self, job_id: str) -> None:
        cancel = threading.Event()
        with self._lock:
            state = self._load_state_locked(job_id)
            if self._closed or state["status"] != "queued":
                return
            state["status"] = "running"
            self._cancel_events[job_id] = cancel
            self._append_event_locked(
                job_id,
                state,
                kind="server",
                status="running",
                message="Verified request execution started",
            )
            self._write_state_locked(job_id, state)

        def progress(event: ModernProgressEvent) -> None:
            serialized = event.as_dict()
            with self._lock:
                current = self._load_state_locked(job_id)
                self._append_event_locked(
                    job_id,
                    current,
                    kind="modern_progress",
                    status="progress",
                    message=event.message,
                    progress=serialized,
                )
                self._write_state_locked(job_id, current)

        directory = self._job_directory(job_id)
        request = directory / "request"
        result = directory / "result"
        archive = directory / "result.zip"
        try:
            completed = self._runner(
                request,
                result,
                progress_callback=progress,
                cancel_requested=cancel.is_set,
            )
            verify_remote_atlas_result(request, completed)
            created_archive = create_remote_atlas_result_archive(
                request,
                completed,
                archive,
            )
            with self._lock:
                state = self._load_state_locked(job_id)
                state["status"] = "completed"
                state["cancel_requested"] = False
                state["result"] = {
                    "archive_bytes": created_archive.stat().st_size,
                    "archive_sha256": sha256_path(created_archive),
                    "workflow_manifest_sha256": sha256_file(
                        completed / "workflow-manifest.json"
                    ),
                }
                state["error"] = None
                self._append_event_locked(
                    job_id,
                    state,
                    kind="server",
                    status="completed",
                    message="Result verified and ready for download",
                )
                self._write_state_locked(job_id, state)
        except ModernWorkflowCancelled:
            archive.unlink(missing_ok=True)
            with self._lock:
                state = self._load_state_locked(job_id)
                state["status"] = "cancelled"
                state["cancel_requested"] = True
                state["error"] = None
                self._append_event_locked(
                    job_id,
                    state,
                    kind="server",
                    status="cancelled",
                    message="Cooperative cancellation completed",
                )
                self._write_state_locked(job_id, state)
        except Exception as error:
            archive.unlink(missing_ok=True)
            with self._lock:
                state = self._load_state_locked(job_id)
                state["status"] = "failed"
                state["cancel_requested"] = False
                state["error"] = {
                    "type": type(error).__name__[:128],
                    "message": str(error)[:2048],
                }
                self._append_event_locked(
                    job_id,
                    state,
                    kind="server",
                    status="failed",
                    message="Remote execution failed without publishing a result",
                )
                self._write_state_locked(job_id, state)
        finally:
            with self._lock:
                self._cancel_events.pop(job_id, None)


class _RemoteAtlasHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        server_address: tuple[str, int],
        manager: RemoteAtlasJobManager,
        token: str,
        *,
        max_upload_bytes: int,
    ) -> None:
        self.manager = manager
        self.expected_authorization = f"Bearer {token}".encode()
        self.max_upload_bytes = max_upload_bytes
        super().__init__(server_address, _RemoteAtlasRequestHandler)


class _RemoteAtlasRequestHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "DiffeoForgeRemote/0.1"
    sys_version = ""
    timeout = 60

    @property
    def remote_server(self) -> _RemoteAtlasHTTPServer:
        server = self.server
        if not isinstance(server, _RemoteAtlasHTTPServer):
            raise TypeError("Unexpected HTTP server type")
        return server

    def log_message(self, format: str, *args: object) -> None:
        del format, args

    def _authorized(self) -> bool:
        values = self.headers.get_all("Authorization", failobj=[])
        if len(values) != 1:
            return False
        try:
            observed = values[0].encode("utf-8", errors="strict")
        except UnicodeError:
            return False
        return hmac.compare_digest(observed, self.remote_server.expected_authorization)

    def handle_expect_100(self) -> bool:
        if not self._authorized():
            self.close_connection = True
            self._send_json(
                HTTPStatus.UNAUTHORIZED,
                {"error": "Bearer authentication required"},
                authenticate=True,
            )
            return False
        return super().handle_expect_100()

    def _send_json(
        self,
        status: HTTPStatus,
        value: object,
        *,
        authenticate: bool = False,
    ) -> None:
        payload = _canonical_json(value).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        if authenticate:
            self.send_header("WWW-Authenticate", 'Bearer realm="DiffeoForge"')
        self.end_headers()
        self.wfile.write(payload)

    def _require_authentication(self) -> bool:
        if self._authorized():
            return True
        self.close_connection = True
        self._send_json(
            HTTPStatus.UNAUTHORIZED,
            {"error": "Bearer authentication required"},
            authenticate=True,
        )
        return False

    def _route(self) -> tuple[list[str], dict[str, list[str]]]:
        parsed = urlsplit(self.path)
        prefix = f"/{REMOTE_API_VERSION}"
        if not parsed.path.startswith(prefix):
            return [], parse_qs(parsed.query, strict_parsing=False)
        suffix = parsed.path[len(prefix) :]
        parts = [part for part in suffix.split("/") if part]
        return parts, parse_qs(parsed.query, strict_parsing=False)

    def _send_server_error(self, error: Exception) -> None:
        if isinstance(error, RemoteAtlasServerNotFound):
            status = HTTPStatus.NOT_FOUND
        elif isinstance(error, RemoteAtlasServerConflict):
            status = HTTPStatus.CONFLICT
        elif isinstance(error, RemoteAtlasServerCapacity):
            status = HTTPStatus.SERVICE_UNAVAILABLE
        else:
            status = HTTPStatus.BAD_REQUEST
        self._send_json(status, {"error": str(error)})

    def do_GET(self) -> None:
        parts, query = self._route()
        if parts == ["health"]:
            self._send_json(
                HTTPStatus.OK,
                {
                    "api_version": REMOTE_API_VERSION,
                    "status": "ready",
                    "authentication_required_for_jobs": True,
                },
            )
            return
        if not self._require_authentication():
            return
        try:
            if len(parts) == 2 and parts[0] == "jobs":
                self._send_json(
                    HTTPStatus.OK,
                    self.remote_server.manager.get_state(parts[1]),
                )
                return
            if len(parts) == 3 and parts[0] == "jobs" and parts[2] == "events":
                after_values = query.get("after", ["-1"])
                if len(after_values) != 1:
                    raise RemoteAtlasServerError("Event cursor must appear exactly once")
                try:
                    after = int(after_values[0])
                except ValueError as error:
                    raise RemoteAtlasServerError("Event cursor must be an integer") from error
                limit_values = query.get("limit", ["100"])
                if len(limit_values) != 1:
                    raise RemoteAtlasServerError("Event page limit must appear exactly once")
                try:
                    limit = int(limit_values[0])
                except ValueError as error:
                    raise RemoteAtlasServerError("Event page limit must be an integer") from error
                self._send_json(
                    HTTPStatus.OK,
                    self.remote_server.manager.get_events(
                        parts[1],
                        after=after,
                        limit=limit,
                    ),
                )
                return
            if len(parts) == 3 and parts[0] == "jobs" and parts[2] == "result":
                archive, state = self.remote_server.manager.result_archive(parts[1])
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", RESULT_MEDIA_TYPE)
                self.send_header("Content-Length", str(archive.stat().st_size))
                self.send_header(
                    "X-DiffeoForge-Archive-SHA256",
                    state["result"]["archive_sha256"],
                )
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                with archive.open("rb") as handle:
                    for chunk in iter(lambda: handle.read(ARCHIVE_CHUNK_BYTES), b""):
                        self.wfile.write(chunk)
                return
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "Unknown remote API route"})
        except (RemoteAtlasServerError, OSError, ValueError) as error:
            self._send_server_error(error)

    def do_POST(self) -> None:
        if not self._require_authentication():
            return
        parts, _ = self._route()
        try:
            if parts == ["jobs"]:
                self._receive_job()
                return
            if len(parts) == 3 and parts[0] == "jobs" and parts[2] == "cancel":
                state = self.remote_server.manager.cancel(parts[1])
                self._send_json(HTTPStatus.ACCEPTED, state)
                return
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "Unknown remote API route"})
        except (
            RemoteAtlasJobError,
            RemoteAtlasServerError,
            RemoteAtlasTransportError,
            OSError,
            ValueError,
            zipfile.BadZipFile,
        ) as error:
            self._send_server_error(error)

    def _receive_job(self) -> None:
        if self.headers.get("Transfer-Encoding") is not None:
            raise RemoteAtlasServerError("Chunked uploads are not accepted")
        if self.headers.get_content_type() != REQUEST_MEDIA_TYPE:
            raise RemoteAtlasServerError("Remote request media type differs")
        lengths = self.headers.get_all("Content-Length", failobj=[])
        hashes = self.headers.get_all("X-DiffeoForge-Archive-SHA256", failobj=[])
        if len(lengths) != 1 or len(hashes) != 1:
            raise RemoteAtlasServerError("Upload length and SHA-256 headers are required once")
        try:
            length = int(lengths[0])
        except ValueError as error:
            raise RemoteAtlasServerError("Upload Content-Length is invalid") from error
        expected_hash = hashes[0]
        if (
            not 1 <= length <= self.remote_server.max_upload_bytes
            or _ARCHIVE_SHA256.fullmatch(expected_hash) is None
        ):
            raise RemoteAtlasServerError("Upload size or SHA-256 header is outside policy")
        incoming = self.remote_server.manager.incoming_root / (
            f".upload-{uuid.uuid4().hex}.zip"
        )
        digest = hashlib.sha256()
        remaining = length
        try:
            with incoming.open("xb") as handle:
                while remaining:
                    chunk = self.rfile.read(min(ARCHIVE_CHUNK_BYTES, remaining))
                    if not chunk:
                        raise RemoteAtlasServerError("Upload ended before Content-Length")
                    remaining -= len(chunk)
                    digest.update(chunk)
                    handle.write(chunk)
                handle.flush()
                os.fsync(handle.fileno())
            if digest.hexdigest() != expected_hash:
                raise RemoteAtlasServerError("Uploaded archive SHA-256 differs")
            state = self.remote_server.manager.submit_archive(
                incoming,
                archive_bytes=length,
                archive_sha256=expected_hash,
            )
            self._send_json(HTTPStatus.CREATED, state)
        finally:
            incoming.unlink(missing_ok=True)

    def do_DELETE(self) -> None:
        if not self._require_authentication():
            return
        parts, _ = self._route()
        try:
            if len(parts) == 2 and parts[0] == "jobs":
                result = self.remote_server.manager.delete(parts[1])
                self._send_json(HTTPStatus.OK, result)
                return
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "Unknown remote API route"})
        except (RemoteAtlasServerError, OSError, ValueError) as error:
            self._send_server_error(error)


def _loopback_bind(host: str) -> bool:
    try:
        addresses = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
        return bool(addresses) and all(
            ipaddress.ip_address(address[4][0]).is_loopback for address in addresses
        )
    except (OSError, ValueError):
        return False


def create_remote_atlas_http_server(
    manager: RemoteAtlasJobManager,
    token: str,
    *,
    host: str = "127.0.0.1",
    port: int = 8787,
    tls_certificate: Path | str | None = None,
    tls_private_key: Path | str | None = None,
    max_upload_bytes: int = DEFAULT_MAX_UPLOAD_BYTES,
) -> _RemoteAtlasHTTPServer:
    """Create a configured server; caller controls its serving lifecycle."""

    if not 0 <= port <= 65535:
        raise ValueError("port must be between 0 and 65535")
    if not 1 <= max_upload_bytes <= 1024**5:
        raise ValueError("max_upload_bytes must be between 1 byte and 1 PiB")
    if not 32 <= len(token) <= 512 or any(character.isspace() for character in token):
        raise RemoteAtlasServerError("Remote bearer token has an invalid format")
    if (tls_certificate is None) != (tls_private_key is None):
        raise RemoteAtlasServerError(
            "TLS certificate and private key must be supplied together"
        )
    tls_enabled = tls_certificate is not None
    if not _loopback_bind(host) and not tls_enabled:
        raise RemoteAtlasServerError(
            "Non-loopback server binding requires an explicit TLS certificate and key"
        )
    server = _RemoteAtlasHTTPServer(
        (host, port),
        manager,
        token,
        max_upload_bytes=max_upload_bytes,
    )
    if tls_enabled:
        certificate = Path(tls_certificate).expanduser().absolute()
        private_key = Path(tls_private_key).expanduser().absolute()
        if (
            _linklike(certificate)
            or not certificate.is_file()
            or _linklike(private_key)
            or not private_key.is_file()
        ):
            server.server_close()
            raise RemoteAtlasServerError("TLS certificate or private key is missing or symbolic")
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        try:
            context.load_cert_chain(certificate.resolve(), private_key.resolve())
            server.socket = context.wrap_socket(server.socket, server_side=True)
        except BaseException:
            server.server_close()
            raise
    return server
