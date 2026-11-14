"""Persistent Qt-independent controller for one desktop remote-atlas session."""

from __future__ import annotations

import json
import shutil
import threading
import uuid
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import cache
from importlib.resources import files
from pathlib import Path
from typing import Any, Literal

import jsonschema

from diffeoforge.atomic_io import write_text_safely
from diffeoforge.desktop.worker_protocol import DesktopWorkerRequest, sha256_file
from diffeoforge.private_runs import discover_private_runs
from diffeoforge.remote_atlas_job import (
    MANIFEST_NAME,
    create_remote_atlas_job,
    verify_remote_atlas_job,
    verify_remote_atlas_result,
)
from diffeoforge.remote_atlas_transport import (
    RemoteAtlasClient,
    load_remote_token,
    validate_remote_server_url,
)
from diffeoforge.runs import publish_directory_exclusive
from diffeoforge.strict_json import load_strict_json_object

SESSION_VERSION = "0.1"
SESSION_STATE_NAME = "session.json"
REQUEST_DIRECTORY_NAME = "request"
TERMINAL_REMOTE_STATUSES = frozenset(
    {"downloaded", "failed", "cancelled", "interrupted", "cancelled_before_submit"}
)
SCIENTIFIC_BOUNDARY = (
    "Remote execution, transport integrity, and a verified download do not establish "
    "parameter suitability, optimizer convergence, reconstruction quality, sensitivity, "
    "PCA stability, biological validity, server confidentiality, or deletion."
)
DesktopRemoteStatus = Literal[
    "prepared",
    "queued",
    "running",
    "cancel_requested",
    "completed",
    "downloaded",
    "failed",
    "cancelled",
    "interrupted",
    "cancelled_before_submit",
]
RemoteEventCallback = Callable[[dict[str, Any]], None]


class DesktopRemoteAtlasError(RuntimeError):
    """Raised when a persistent remote desktop session cannot proceed safely."""


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


def _assert_no_link_chain(path: Path, *, label: str) -> None:
    for item in (path.absolute(), *path.absolute().parents):
        if _linklike(item):
            raise DesktopRemoteAtlasError(f"{label} uses a symbolic path: {item}")


def _real_file(path: Path | str, *, label: str) -> Path:
    candidate = Path(path).expanduser().absolute()
    _assert_no_link_chain(candidate, label=label)
    if not candidate.is_file():
        raise DesktopRemoteAtlasError(f"{label} is missing: {candidate}")
    return candidate.resolve()


@cache
def _schema() -> dict[str, Any]:
    resource = files("diffeoforge.schema").joinpath(
        "desktop-remote-atlas-session-v0.1.json"
    )
    return json.loads(resource.read_text(encoding="utf-8"))


def _validate_state(state: dict[str, Any]) -> None:
    try:
        jsonschema.Draft202012Validator(_schema()).validate(state)
    except jsonschema.ValidationError as error:
        location = ".".join(str(part) for part in error.absolute_path) or "document"
        raise DesktopRemoteAtlasError(
            f"Desktop remote session schema failed at {location}: {error.message}"
        ) from error
    if state["scientific_boundary"] != SCIENTIFIC_BOUNDARY:
        raise DesktopRemoteAtlasError("Desktop remote session scientific boundary differs")
    if state["submission_id"] != state["request_id"].removeprefix("remote-"):
        raise DesktopRemoteAtlasError("Desktop remote request and submission identities differ")
    validate_remote_server_url(state["server_url"])
    for field in ("created_at", "updated_at"):
        try:
            parsed = datetime.fromisoformat(state[field].replace("Z", "+00:00"))
        except ValueError as error:
            raise DesktopRemoteAtlasError(f"Desktop remote {field} is invalid") from error
        if parsed.tzinfo is None:
            raise DesktopRemoteAtlasError(f"Desktop remote {field} lacks a timezone")
    config = Path(state["request"]["original_config_path"])
    destination = Path(state["request"]["result_destination"])
    if not config.is_absolute() or not destination.is_absolute():
        raise DesktopRemoteAtlasError("Desktop remote session paths must be absolute")
    tls = state["tls"]
    if (tls["ca_file"] is None) != (tls["ca_sha256"] is None):
        raise DesktopRemoteAtlasError("Desktop remote TLS CA identity is incomplete")
    deleted_at = state["remote"].get("server_deleted_at")
    if deleted_at is not None:
        try:
            parsed = datetime.fromisoformat(deleted_at.replace("Z", "+00:00"))
        except ValueError as error:
            raise DesktopRemoteAtlasError(
                "Desktop remote server deletion time is invalid"
            ) from error
        if parsed.tzinfo is None:
            raise DesktopRemoteAtlasError(
                "Desktop remote server deletion time lacks a timezone"
            )


def _read_state(root: Path) -> dict[str, Any]:
    path = root / SESSION_STATE_NAME
    if _linklike(path) or not path.is_file():
        raise DesktopRemoteAtlasError(f"Desktop remote session state is missing: {path}")
    try:
        state = load_strict_json_object(
            path.read_bytes(),
            path,
            label="Desktop remote atlas session",
        )
    except (OSError, RuntimeError, ValueError) as error:
        raise DesktopRemoteAtlasError(str(error)) from error
    _validate_state(state)
    return state


def _write_state(root: Path, state: dict[str, Any]) -> None:
    state["updated_at"] = _now()
    _validate_state(state)
    write_text_safely(
        root / SESSION_STATE_NAME,
        _canonical_json(state),
        overwrite=True,
    )


def verify_desktop_remote_atlas_session(directory: Path | str) -> dict[str, Any]:
    """Reverify one persistent request/session and any downloaded result."""

    root = Path(directory).expanduser().absolute()
    _assert_no_link_chain(root, label="Desktop remote session")
    if not root.is_dir():
        raise DesktopRemoteAtlasError(f"Desktop remote session is missing: {root}")
    root = root.resolve()
    entries = {path.name for path in root.iterdir()}
    if entries != {SESSION_STATE_NAME, REQUEST_DIRECTORY_NAME}:
        raise DesktopRemoteAtlasError(
            f"Desktop remote session inventory differs: {sorted(entries)}"
        )
    state = _read_state(root)
    request = root / REQUEST_DIRECTORY_NAME
    if _linklike(request):
        raise DesktopRemoteAtlasError("Desktop remote request directory is symbolic")
    for path in request.rglob("*"):
        if _linklike(path):
            raise DesktopRemoteAtlasError(
                f"Desktop remote request contains a symbolic path: {path}"
            )
    manifest = verify_remote_atlas_job(request)
    request_state = state["request"]
    if sha256_file(request / MANIFEST_NAME) != request_state["manifest_sha256"]:
        raise DesktopRemoteAtlasError("Desktop remote request manifest identity differs")
    if manifest["source"]["config_sha256"] != request_state["original_config_sha256"]:
        raise DesktopRemoteAtlasError("Desktop remote source configuration identity differs")
    if len(manifest["input"]["subjects"]) != request_state["subjects"]:
        raise DesktopRemoteAtlasError("Desktop remote request subject count differs")
    if manifest["execution"]["device"] != request_state["device"]:
        raise DesktopRemoteAtlasError("Desktop remote request device differs")
    if state["remote"]["status"] == "downloaded":
        destination = Path(request_state["result_destination"])
        result = verify_remote_atlas_result(request, destination)
        if (
            sha256_file(destination / "workflow-manifest.json")
            != state["result"]["workflow_manifest_sha256"]
        ):
            raise DesktopRemoteAtlasError("Desktop remote result manifest identity differs")
        if result["engine"]["device"] != request_state["device"]:
            raise DesktopRemoteAtlasError("Desktop remote result device differs")
    return deepcopy(state)


def create_desktop_remote_atlas_session(
    request: DesktopWorkerRequest,
    directory: Path | str,
    *,
    server_url: str,
    ca_file: Path | str | None = None,
    submission_id: str | None = None,
    created_at: str | None = None,
) -> Path:
    """Create an immutable packaged request plus mutable reconnect state, without upload."""

    if not isinstance(request, DesktopWorkerRequest):
        raise TypeError("request must be DesktopWorkerRequest")
    request.verify_launch_inputs()
    discovery = discover_private_runs(request.destination)
    if not discovery.ready_for_new_run:
        raise DesktopRemoteAtlasError(
            "Remote result destination has a published or private candidate"
        )
    validate_remote_server_url(server_url)
    ca_path: Path | None = None
    ca_sha256: str | None = None
    if ca_file is not None:
        ca_path = _real_file(ca_file, label="Desktop remote TLS CA file")
        ca_sha256 = sha256_file(ca_path)
    identity = submission_id or uuid.uuid4().hex
    if len(identity) != 32 or any(character not in "0123456789abcdef" for character in identity):
        raise DesktopRemoteAtlasError(
            "Desktop remote submission ID must contain 32 lowercase hex characters"
        )
    target = Path(directory).expanduser().absolute()
    if target.exists() or target.is_symlink():
        raise FileExistsError(f"Desktop remote session already exists: {target}")
    _assert_no_link_chain(target.parent, label="Desktop remote session parent")
    target.parent.mkdir(parents=True, exist_ok=True)
    _assert_no_link_chain(target.parent, label="Desktop remote session parent")
    temporary = target.parent / f".{target.name}.tmp-{uuid.uuid4().hex}"
    temporary.mkdir()
    try:
        portable = create_remote_atlas_job(
            request.config_path,
            temporary / REQUEST_DIRECTORY_NAME,
            created_at=created_at,
        )
        manifest = verify_remote_atlas_job(portable)
        if manifest["source"]["config_sha256"] != request.expected_config_sha256:
            raise DesktopRemoteAtlasError(
                "Reviewed configuration changed while the remote request was packaged"
            )
        timestamp = created_at or _now()
        state: dict[str, Any] = {
            "session_version": SESSION_VERSION,
            "request_id": f"remote-{identity}",
            "submission_id": identity,
            "created_at": timestamp,
            "updated_at": timestamp,
            "server_url": server_url,
            "request": {
                "directory": REQUEST_DIRECTORY_NAME,
                "manifest_sha256": sha256_file(portable / MANIFEST_NAME),
                "original_config_path": str(request.config_path),
                "original_config_sha256": request.expected_config_sha256,
                "result_destination": str(request.destination),
                "subjects": len(manifest["input"]["subjects"]),
                "device": manifest["execution"]["device"],
            },
            "tls": {
                "ca_file": None if ca_path is None else str(ca_path),
                "ca_sha256": ca_sha256,
            },
            "remote": {
                "status": "prepared",
                "event_cursor": -1,
                "last_server_update": None,
                "server_deleted_at": None,
                "error": None,
            },
            "result": None,
            "scientific_boundary": SCIENTIFIC_BOUNDARY,
        }
        write_text_safely(
            temporary / SESSION_STATE_NAME,
            _canonical_json(state),
            overwrite=False,
        )
        verify_desktop_remote_atlas_session(temporary)
        publish_directory_exclusive(temporary, target)
        verify_desktop_remote_atlas_session(target)
        return target.resolve()
    except BaseException:
        if temporary.exists() and temporary.parent == target.parent:
            shutil.rmtree(temporary)
        raise


def _verified_ca_file(state: dict[str, Any]) -> Path | None:
    tls = state["tls"]
    if tls["ca_file"] is None:
        return None
    path = _real_file(tls["ca_file"], label="Desktop remote TLS CA file")
    if sha256_file(path) != tls["ca_sha256"]:
        raise DesktopRemoteAtlasError("Desktop remote TLS CA file changed")
    return path


@dataclass(frozen=True)
class DesktopRemoteAtlasResult:
    """One terminal persistent remote outcome."""

    request_id: str
    submission_id: str
    status: DesktopRemoteStatus
    session_directory: Path
    destination: Path
    remote_state: dict[str, Any] | None
    detached: bool = False

    @property
    def completed(self) -> bool:
        return self.status == "downloaded"

    @property
    def cancelled(self) -> bool:
        return self.status in {"cancelled", "cancelled_before_submit"}


@dataclass(frozen=True)
class DesktopRemoteAtlasDeletionResult:
    """Recorded deletion of one terminal server copy."""

    submission_id: str
    session_directory: Path
    deleted_at: str
    already_recorded: bool


class DesktopRemoteAtlasDeletionController:
    """Delete terminal server state while retaining local request/result evidence."""

    def __init__(
        self,
        session_directory: Path | str,
        *,
        token_file: Path | str,
    ) -> None:
        self.session_directory = Path(session_directory).expanduser().resolve()
        self.token_file = Path(token_file).expanduser().absolute()

    def run(self) -> DesktopRemoteAtlasDeletionResult:
        state = verify_desktop_remote_atlas_session(self.session_directory)
        recorded = state["remote"].get("server_deleted_at")
        if recorded is not None:
            return DesktopRemoteAtlasDeletionResult(
                submission_id=state["submission_id"],
                session_directory=self.session_directory,
                deleted_at=recorded,
                already_recorded=True,
            )
        if state["remote"]["status"] not in {
            "completed",
            "downloaded",
            "failed",
            "cancelled",
            "interrupted",
        }:
            raise DesktopRemoteAtlasError(
                "Only a terminal submitted remote job can be deleted from the server"
            )
        try:
            client = RemoteAtlasClient(
                state["server_url"],
                load_remote_token(self.token_file),
                ca_file=_verified_ca_file(state),
            )
            client.delete(state["submission_id"])
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            if isinstance(error, DesktopRemoteAtlasError):
                raise
            raise DesktopRemoteAtlasError(
                f"Remote atlas server copy could not be deleted: {error}"
            ) from error
        deleted_at = _now()
        state["remote"]["server_deleted_at"] = deleted_at
        try:
            _write_state(self.session_directory, state)
            verify_desktop_remote_atlas_session(self.session_directory)
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            if isinstance(error, DesktopRemoteAtlasError):
                raise
            raise DesktopRemoteAtlasError(
                "Server deletion succeeded, but its local session record could not be "
                f"verified: {error}"
            ) from error
        return DesktopRemoteAtlasDeletionResult(
            submission_id=state["submission_id"],
            session_directory=self.session_directory,
            deleted_at=deleted_at,
            already_recorded=False,
        )


class DesktopRemoteAtlasController:
    """Submit or reconnect one persistent session without tying it to Qt."""

    def __init__(
        self,
        session_directory: Path | str,
        *,
        token_file: Path | str,
        poll_seconds: float = 2.0,
    ) -> None:
        if not 0.1 <= poll_seconds <= 3600:
            raise ValueError("poll_seconds must be between 0.1 and 3600")
        self.session_directory = Path(session_directory).expanduser().resolve()
        self.token_file = Path(token_file).expanduser().absolute()
        self.poll_seconds = poll_seconds
        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._cancel_requested = False
        self._detach_requested = False
        self._running = False
        self._finished = False

    @property
    def state(self) -> str:
        with self._lock:
            if self._finished:
                return "completed"
            if self._running:
                return "cancelling" if self._cancel_requested else "running"
            return "idle"

    def request_cancel(self) -> bool:
        with self._lock:
            if self._finished or self._cancel_requested:
                return False
            self._cancel_requested = True
            self._wake.set()
            return True

    def request_detach(self) -> bool:
        """Stop local monitoring without cancelling or mutating the remote job."""

        with self._lock:
            if self._finished or self._detach_requested:
                return False
            self._detach_requested = True
            self._wake.set()
            return True

    def _result(
        self,
        state: dict[str, Any],
        remote_state: dict[str, Any] | None,
        *,
        detached: bool = False,
    ) -> DesktopRemoteAtlasResult:
        return DesktopRemoteAtlasResult(
            request_id=state["request_id"],
            submission_id=state["submission_id"],
            status=state["remote"]["status"],
            session_directory=self.session_directory,
            destination=Path(state["request"]["result_destination"]),
            remote_state=remote_state,
            detached=detached,
        )

    def run(
        self,
        *,
        event_callback: RemoteEventCallback | None = None,
    ) -> DesktopRemoteAtlasResult:
        if event_callback is not None and not callable(event_callback):
            raise TypeError("event_callback must be callable or None")
        with self._lock:
            if self._running or self._finished:
                raise DesktopRemoteAtlasError("Desktop remote controller is single-use")
            self._running = True
        remote_state: dict[str, Any] | None = None
        try:
            state = verify_desktop_remote_atlas_session(self.session_directory)
            status = state["remote"]["status"]
            if status in TERMINAL_REMOTE_STATUSES:
                return self._result(state, None)
            if self._detach_requested:
                return self._result(state, None, detached=True)
            if self._cancel_requested and status == "prepared":
                state["remote"]["status"] = "cancelled_before_submit"
                _write_state(self.session_directory, state)
                return self._result(state, None)
            ca_file = _verified_ca_file(state)
            client = RemoteAtlasClient(
                state["server_url"],
                load_remote_token(self.token_file),
                ca_file=ca_file,
            )
            client.health()
            request_directory = self.session_directory / REQUEST_DIRECTORY_NAME
            if status == "prepared":
                original = _real_file(
                    state["request"]["original_config_path"],
                    label="Reviewed Modern configuration",
                )
                if sha256_file(original) != state["request"]["original_config_sha256"]:
                    raise DesktopRemoteAtlasError(
                        "Reviewed configuration changed before remote submission"
                    )
                remote_state = client.submit(
                    request_directory,
                    submission_id=state["submission_id"],
                )
                state["remote"]["status"] = remote_state["status"]
                state["remote"]["last_server_update"] = remote_state["updated_at"]
                state["remote"]["error"] = remote_state["error"]
                _write_state(self.session_directory, state)
                if self._detach_requested:
                    return self._result(state, remote_state, detached=True)
            while True:
                cursor = int(state["remote"]["event_cursor"])
                while True:
                    page = client.events(
                        state["submission_id"],
                        after=cursor,
                    )
                    for event in page["events"]:
                        if event_callback is not None:
                            event_callback(deepcopy(event))
                    cursor = page["next_after"]
                    state["remote"]["event_cursor"] = cursor
                    _write_state(self.session_directory, state)
                    if not page["has_more"]:
                        break
                if self._cancel_requested and state["remote"]["status"] in {
                    "queued",
                    "running",
                    "cancel_requested",
                }:
                    remote_state = client.cancel(state["submission_id"])
                else:
                    remote_state = client.status(state["submission_id"])
                state["remote"]["status"] = remote_state["status"]
                state["remote"]["last_server_update"] = remote_state["updated_at"]
                state["remote"]["error"] = remote_state["error"]
                _write_state(self.session_directory, state)
                status = state["remote"]["status"]
                if status in {"failed", "cancelled", "interrupted"}:
                    return self._result(state, remote_state)
                if status == "completed":
                    destination = Path(state["request"]["result_destination"])
                    if destination.exists():
                        verify_remote_atlas_result(request_directory, destination)
                    else:
                        client.download(
                            state["submission_id"],
                            request_directory,
                            destination,
                        )
                    state["result"] = {
                        "workflow_manifest_sha256": sha256_file(
                            destination / "workflow-manifest.json"
                        )
                    }
                    state["remote"]["status"] = "downloaded"
                    _write_state(self.session_directory, state)
                    verify_desktop_remote_atlas_session(self.session_directory)
                    return self._result(state, remote_state)
                if self._detach_requested:
                    return self._result(state, remote_state, detached=True)
                self._wake.wait(self.poll_seconds)
                self._wake.clear()
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            if isinstance(error, DesktopRemoteAtlasError):
                raise
            raise DesktopRemoteAtlasError(
                f"Desktop remote atlas session failed: {error}"
            ) from error
        finally:
            with self._lock:
                self._running = False
                self._finished = True
