"""Safe archive transport and HTTP client for portable Modern atlas jobs."""

from __future__ import annotations

import hashlib
import http.client
import ipaddress
import json
import os
import re
import secrets
import shutil
import socket
import ssl
import stat
import tempfile
import unicodedata
import uuid
import zipfile
from collections.abc import Callable, Mapping
from functools import cache
from importlib.resources import files
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlencode, urlsplit

import jsonschema

from diffeoforge.remote_atlas_job import (
    verify_remote_atlas_job,
    verify_remote_atlas_result,
)

REMOTE_API_VERSION = "v1"
REQUEST_MEDIA_TYPE = "application/vnd.diffeoforge.remote-atlas-job+zip"
RESULT_MEDIA_TYPE = "application/vnd.diffeoforge.remote-atlas-result+zip"
ARCHIVE_CHUNK_BYTES = 1024 * 1024
DEFAULT_MAX_ARCHIVE_FILES = 100_000
DEFAULT_MAX_UNPACKED_BYTES = 64 * 1024**3
DEFAULT_MAX_RESPONSE_BYTES = 1024 * 1024
DEFAULT_MAX_DOWNLOAD_BYTES = 64 * 1024**3
_JOB_ID = re.compile(r"^[0-9a-f]{32}$")
_WINDOWS_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{index}" for index in range(1, 10)}
    | {f"LPT{index}" for index in range(1, 10)}
)
_SERVER_STATUSES = frozenset(
    {"queued", "running", "cancel_requested", "completed", "failed", "cancelled", "interrupted"}
)


class RemoteAtlasTransportError(RuntimeError):
    """Raised when remote transport, authentication, or archive checks fail."""


@cache
def _server_state_schema() -> dict[str, Any]:
    resource = files("diffeoforge.schema").joinpath(
        "remote-atlas-server-job-v0.1.json"
    )
    return json.loads(resource.read_text(encoding="utf-8"))


def validate_remote_atlas_server_state(
    value: object,
    *,
    expected_job_id: str | None = None,
) -> dict[str, Any]:
    """Validate untrusted server state before a client acts on it."""

    if not isinstance(value, dict):
        raise RemoteAtlasTransportError("Remote server state must be a JSON object")
    try:
        jsonschema.Draft202012Validator(_server_state_schema()).validate(value)
    except jsonschema.ValidationError as error:
        location = ".".join(str(part) for part in error.absolute_path) or "document"
        raise RemoteAtlasTransportError(
            f"Remote server state schema failed at {location}: {error.message}"
        ) from error
    job_id = str(value["job_id"])
    if expected_job_id is not None and job_id != expected_job_id:
        raise RemoteAtlasTransportError("Remote server state job ID differs")
    return value


def _validate_event_page(
    value: dict[str, Any],
    *,
    expected_job_id: str,
    after: int,
) -> dict[str, Any]:
    if set(value) != {"job_id", "events", "next_after", "has_more"}:
        raise RemoteAtlasTransportError("Remote event page fields differ")
    if value["job_id"] != expected_job_id or not isinstance(value["events"], list):
        raise RemoteAtlasTransportError("Remote event page identity or events differ")
    if type(value["next_after"]) is not int or not isinstance(value["has_more"], bool):
        raise RemoteAtlasTransportError("Remote event cursor fields differ")
    expected_index = after + 1
    for event in value["events"]:
        if not isinstance(event, dict) or set(event) != {
            "server_event_version",
            "index",
            "timestamp",
            "kind",
            "status",
            "message",
            "progress",
        }:
            raise RemoteAtlasTransportError("Remote event fields differ")
        if (
            event["server_event_version"] != "0.1"
            or type(event["index"]) is not int
            or event["index"] != expected_index
            or not isinstance(event["kind"], str)
            or event["kind"] not in {"server", "modern_progress"}
            or not isinstance(event["status"], str)
            or event["status"] not in _SERVER_STATUSES | {"progress"}
            or not isinstance(event["timestamp"], str)
            or not isinstance(event["message"], str)
            or not isinstance(event["progress"], (dict, type(None)))
        ):
            raise RemoteAtlasTransportError("Remote event content differs")
        expected_index += 1
    expected_cursor = after if not value["events"] else expected_index - 1
    if value["next_after"] != expected_cursor:
        raise RemoteAtlasTransportError("Remote event next cursor differs")
    if value["has_more"] and not value["events"]:
        raise RemoteAtlasTransportError("Remote event page cannot advance")
    return value


def _linklike(path: Path) -> bool:
    is_junction = getattr(path, "is_junction", None)
    return path.is_symlink() or (callable(is_junction) and is_junction())


def _assert_no_link_chain(path: Path, *, label: str) -> None:
    current = path.absolute()
    while True:
        if _linklike(current):
            raise RemoteAtlasTransportError(f"{label} uses a symbolic path: {current}")
        parent = current.parent
        if parent == current:
            return
        current = parent


def _canonical_json(value: object) -> bytes:
    return (
        json.dumps(
            value,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def sha256_path(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(ARCHIVE_CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_relative_archive_path(value: str) -> PurePosixPath:
    if not value or "\\" in value or value.startswith("/") or "//" in value:
        raise RemoteAtlasTransportError(f"Unsafe archive entry path: {value!r}")
    relative = PurePosixPath(value)
    if (
        relative.as_posix() != value
        or relative.is_absolute()
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise RemoteAtlasTransportError(f"Unsafe archive entry path: {value!r}")
    for part in relative.parts:
        if (
            ":" in part
            or part.endswith((" ", "."))
            or any(ord(character) < 32 for character in part)
            or part.split(".", 1)[0].upper() in _WINDOWS_RESERVED_NAMES
        ):
            raise RemoteAtlasTransportError(f"Non-portable archive entry path: {value!r}")
    return relative


def _portable_collision_key(value: str) -> str:
    return unicodedata.normalize("NFC", value).casefold()


def _real_directory(path: Path | str, *, label: str) -> Path:
    candidate = Path(path).expanduser().absolute()
    _assert_no_link_chain(candidate, label=label)
    if not candidate.is_dir():
        raise RemoteAtlasTransportError(f"{label} is missing or symbolic: {candidate}")
    return candidate.resolve()


def _real_file(path: Path | str, *, label: str) -> Path:
    candidate = Path(path).expanduser().absolute()
    _assert_no_link_chain(candidate, label=label)
    if not candidate.is_file():
        raise RemoteAtlasTransportError(f"{label} is missing or symbolic: {candidate}")
    return candidate.resolve()


def _archive_tree(
    source_directory: Path | str,
    destination: Path | str,
    *,
    verifier: Callable[[Path], object],
) -> Path:
    source = _real_directory(source_directory, label="Archive source")
    verifier(source)
    target = Path(destination).expanduser().absolute()
    if target == source or source in target.parents:
        raise RemoteAtlasTransportError(
            "Archive destination must be outside its immutable source directory"
        )
    if target.exists() or target.is_symlink():
        raise FileExistsError(f"Archive destination already exists: {target}")
    _assert_no_link_chain(target.parent, label="Archive destination parent")
    target.parent.mkdir(parents=True, exist_ok=True)
    _assert_no_link_chain(target.parent, label="Archive destination parent")
    temporary = target.parent / f".{target.name}.tmp-{uuid.uuid4().hex}"
    try:
        files = sorted(path for path in source.rglob("*") if path.is_file())
        for path in source.rglob("*"):
            if _linklike(path):
                raise RemoteAtlasTransportError(
                    f"Archive source contains a symbolic path: {path}"
                )
        archive_entries = [(path, path.relative_to(source).as_posix()) for path in files]
        keys = [_portable_collision_key(relative) for _, relative in archive_entries]
        if len(keys) != len(set(keys)):
            raise RemoteAtlasTransportError(
                "Archive source contains paths that collide across supported hosts"
            )
        with zipfile.ZipFile(
            temporary,
            mode="x",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=6,
            allowZip64=True,
        ) as archive:
            for path, relative in archive_entries:
                _safe_relative_archive_path(relative)
                info = zipfile.ZipInfo(relative, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.create_system = 3
                info.external_attr = (stat.S_IFREG | 0o600) << 16
                with path.open("rb") as reader, archive.open(info, mode="w") as writer:
                    shutil.copyfileobj(reader, writer, length=ARCHIVE_CHUNK_BYTES)
        with temporary.open("r+b") as handle:
            os.fsync(handle.fileno())
        verifier(source)
        if target.exists() or target.is_symlink():
            raise FileExistsError(f"Archive destination appeared during creation: {target}")
        temporary.rename(target)
        return target
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def create_remote_atlas_job_archive(
    job_directory: Path | str,
    destination: Path | str,
) -> Path:
    """Create a deterministic ZIP from one exact portable request."""

    return _archive_tree(
        job_directory,
        destination,
        verifier=verify_remote_atlas_job,
    )


def create_remote_atlas_result_archive(
    job_directory: Path | str,
    result_directory: Path | str,
    destination: Path | str,
) -> Path:
    """Create a deterministic ZIP from one result bound to its request."""

    job = _real_directory(job_directory, label="Remote atlas request")

    def verify(result: Path) -> object:
        return verify_remote_atlas_result(job, result)

    return _archive_tree(result_directory, destination, verifier=verify)


def _extract_archive(
    archive_path: Path | str,
    destination: Path | str,
    *,
    verifier: Callable[[Path], object],
    max_files: int,
    max_unpacked_bytes: int,
) -> Path:
    archive_file = _real_file(archive_path, label="Remote atlas archive")
    if not 1 <= max_files <= 10_000_000:
        raise ValueError("max_files must be between 1 and 10000000")
    if max_unpacked_bytes < 1:
        raise ValueError("max_unpacked_bytes must be positive")
    target = Path(destination).expanduser().absolute()
    if target.exists() or target.is_symlink():
        raise FileExistsError(f"Archive extraction destination already exists: {target}")
    _assert_no_link_chain(target.parent, label="Archive extraction destination parent")
    target.parent.mkdir(parents=True, exist_ok=True)
    _assert_no_link_chain(target.parent, label="Archive extraction destination parent")
    temporary = target.parent / f".{target.name}.tmp-{uuid.uuid4().hex}"
    temporary.mkdir()
    try:
        with zipfile.ZipFile(archive_file, mode="r") as archive:
            infos = archive.infolist()
            if not infos or len(infos) > max_files:
                raise RemoteAtlasTransportError(
                    f"Archive file count must be between 1 and {max_files}"
                )
            names = [info.filename for info in infos]
            collision_keys = [_portable_collision_key(name) for name in names]
            if len(names) != len(set(names)) or len(names) != len(set(collision_keys)):
                raise RemoteAtlasTransportError(
                    "Archive contains duplicate or cross-host-colliding entry names"
                )
            total = 0
            for info in infos:
                relative = _safe_relative_archive_path(info.filename)
                if info.is_dir() or info.flag_bits & 0x1:
                    raise RemoteAtlasTransportError(
                        f"Archive entry is a directory or encrypted: {info.filename}"
                    )
                mode = (info.external_attr >> 16) & 0xFFFF
                kind = stat.S_IFMT(mode)
                if kind not in {0, stat.S_IFREG}:
                    raise RemoteAtlasTransportError(
                        f"Archive entry is not a regular file: {info.filename}"
                    )
                if info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
                    raise RemoteAtlasTransportError(
                        f"Archive entry uses an unsupported compression method: {info.filename}"
                    )
                total += info.file_size
                if total > max_unpacked_bytes:
                    raise RemoteAtlasTransportError(
                        "Archive exceeds the configured uncompressed byte limit"
                    )
                output = temporary.joinpath(*relative.parts)
                output.parent.mkdir(parents=True, exist_ok=True)
                written = 0
                with archive.open(info, mode="r") as reader, output.open("xb") as writer:
                    while True:
                        chunk = reader.read(ARCHIVE_CHUNK_BYTES)
                        if not chunk:
                            break
                        written += len(chunk)
                        if written > info.file_size:
                            raise RemoteAtlasTransportError(
                                f"Archive entry expanded beyond its recorded size: {info.filename}"
                            )
                        writer.write(chunk)
                    writer.flush()
                    os.fsync(writer.fileno())
                if written != info.file_size:
                    raise RemoteAtlasTransportError(
                        f"Archive entry size differs after extraction: {info.filename}"
                    )
        verifier(temporary)
        if target.exists() or target.is_symlink():
            raise FileExistsError(
                f"Archive extraction destination appeared during verification: {target}"
            )
        temporary.rename(target)
        return target
    except BaseException:
        if temporary.exists() and temporary.parent == target.parent:
            shutil.rmtree(temporary)
        raise


def extract_remote_atlas_job_archive(
    archive_path: Path | str,
    destination: Path | str,
    *,
    max_files: int = DEFAULT_MAX_ARCHIVE_FILES,
    max_unpacked_bytes: int = DEFAULT_MAX_UNPACKED_BYTES,
) -> Path:
    """Safely extract and verify one portable request archive."""

    return _extract_archive(
        archive_path,
        destination,
        verifier=verify_remote_atlas_job,
        max_files=max_files,
        max_unpacked_bytes=max_unpacked_bytes,
    )


def extract_remote_atlas_result_archive(
    archive_path: Path | str,
    job_directory: Path | str,
    destination: Path | str,
    *,
    max_files: int = DEFAULT_MAX_ARCHIVE_FILES,
    max_unpacked_bytes: int = DEFAULT_MAX_UNPACKED_BYTES,
) -> Path:
    """Safely extract a result and bind it to the original request."""

    job = _real_directory(job_directory, label="Remote atlas request")

    def verify(result: Path) -> object:
        return verify_remote_atlas_result(job, result)

    return _extract_archive(
        archive_path,
        destination,
        verifier=verify,
        max_files=max_files,
        max_unpacked_bytes=max_unpacked_bytes,
    )


def create_remote_token_file(destination: Path | str) -> Path:
    """Create one high-entropy bearer token file without printing its secret."""

    target = Path(destination).expanduser().absolute()
    if target.exists() or target.is_symlink():
        raise FileExistsError(f"Remote token file already exists: {target}")
    _assert_no_link_chain(target.parent, label="Remote token parent")
    target.parent.mkdir(parents=True, exist_ok=True)
    _assert_no_link_chain(target.parent, label="Remote token parent")
    token = secrets.token_urlsafe(32)
    with target.open("x", encoding="ascii", newline="\n") as handle:
        handle.write(token + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    try:
        target.chmod(0o600)
    except OSError:
        pass
    return target.resolve()


def load_remote_token(path: Path | str) -> str:
    """Read one bearer token from a bounded real file."""

    source = _real_file(path, label="Remote token file")
    if source.stat().st_size > 1024:
        raise RemoteAtlasTransportError("Remote token file is unexpectedly large")
    try:
        text = source.read_text(encoding="ascii", errors="strict")
    except (OSError, UnicodeError) as error:
        raise RemoteAtlasTransportError("Remote token file is unreadable") from error
    lines = text.splitlines()
    if len(lines) != 1 or lines[0] != lines[0].strip():
        raise RemoteAtlasTransportError("Remote token file must contain exactly one token")
    token = lines[0]
    if not 32 <= len(token) <= 512 or any(character.isspace() for character in token):
        raise RemoteAtlasTransportError(
            "Remote token must contain 32 to 512 non-whitespace characters"
        )
    return token


def _loopback_host(host: str) -> bool:
    try:
        addresses = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
        return bool(addresses) and all(
            ipaddress.ip_address(address[4][0]).is_loopback for address in addresses
        )
    except (OSError, ValueError):
        return False


def validate_remote_server_url(value: str) -> tuple[str, str, int, str]:
    """Return a normalized scheme, host, port, and base path."""

    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise RemoteAtlasTransportError("Remote server URL must use http:// or https://")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise RemoteAtlasTransportError(
            "Remote server URL must not contain credentials, query, or fragment"
        )
    if parsed.scheme == "http" and not _loopback_host(parsed.hostname):
        raise RemoteAtlasTransportError(
            "Plain HTTP is permitted only for a loopback server; use HTTPS remotely"
        )
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError as error:
        raise RemoteAtlasTransportError("Remote server URL port is invalid") from error
    base_path = parsed.path.rstrip("/")
    return parsed.scheme, parsed.hostname, port, base_path


def _validate_job_id(job_id: str) -> str:
    if _JOB_ID.fullmatch(job_id) is None:
        raise RemoteAtlasTransportError("Remote job ID must contain 32 lowercase hex characters")
    return job_id


class RemoteAtlasClient:
    """Memory-bounded authenticated client for one DiffeoForge server."""

    def __init__(
        self,
        server_url: str,
        token: str,
        *,
        ca_file: Path | str | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        self.scheme, self.host, self.port, self.base_path = validate_remote_server_url(
            server_url
        )
        if not 32 <= len(token) <= 512 or any(character.isspace() for character in token):
            raise RemoteAtlasTransportError("Remote bearer token has an invalid format")
        if not 1 <= timeout_seconds <= 3600:
            raise ValueError("timeout_seconds must be between 1 and 3600")
        self.token = token
        self.timeout_seconds = timeout_seconds
        self.ssl_context: ssl.SSLContext | None = None
        if self.scheme == "https":
            cafile = None
            if ca_file is not None:
                cafile = str(_real_file(ca_file, label="Remote TLS CA file"))
            self.ssl_context = ssl.create_default_context(cafile=cafile)

    def _connection(self) -> http.client.HTTPConnection:
        if self.scheme == "https":
            return http.client.HTTPSConnection(
                self.host,
                self.port,
                timeout=self.timeout_seconds,
                context=self.ssl_context,
            )
        return http.client.HTTPConnection(
            self.host,
            self.port,
            timeout=self.timeout_seconds,
        )

    def _path(self, suffix: str) -> str:
        return f"{self.base_path}/{REMOTE_API_VERSION}{suffix}"

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
            "User-Agent": "DiffeoForge-remote-client/0.1",
        }

    @staticmethod
    def _read_json_response(
        response: http.client.HTTPResponse,
        *,
        maximum_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
    ) -> dict[str, Any]:
        content_length = response.getheader("Content-Length")
        if content_length is not None:
            try:
                observed_length = int(content_length)
                if not 0 <= observed_length <= maximum_bytes:
                    raise RemoteAtlasTransportError("Remote JSON response is too large")
            except ValueError as error:
                raise RemoteAtlasTransportError(
                    "Remote response Content-Length is invalid"
                ) from error
        payload = response.read(maximum_bytes + 1)
        if len(payload) > maximum_bytes:
            raise RemoteAtlasTransportError("Remote JSON response is too large")
        try:
            value = json.loads(payload.decode("utf-8", errors="strict"))
        except (UnicodeError, json.JSONDecodeError) as error:
            raise RemoteAtlasTransportError("Remote response is not valid JSON") from error
        if not isinstance(value, dict):
            raise RemoteAtlasTransportError("Remote response must be a JSON object")
        if not 200 <= response.status < 300:
            message = value.get("error", "Remote server rejected the request")
            raise RemoteAtlasTransportError(f"Remote server HTTP {response.status}: {message}")
        return value

    def _json_request(
        self,
        method: str,
        suffix: str,
        *,
        body: Mapping[str, object] | None = None,
    ) -> dict[str, Any]:
        payload = None if body is None else _canonical_json(body)
        headers = self._headers()
        if payload is not None:
            headers["Content-Type"] = "application/json"
        connection = self._connection()
        try:
            connection.request(method, self._path(suffix), body=payload, headers=headers)
            response = connection.getresponse()
            return self._read_json_response(response)
        except (OSError, http.client.HTTPException) as error:
            raise RemoteAtlasTransportError(f"Remote request failed: {error}") from error
        finally:
            connection.close()

    def health(self) -> dict[str, Any]:
        connection = self._connection()
        try:
            connection.request(
                "GET",
                f"{self.base_path}/{REMOTE_API_VERSION}/health",
                headers={"Accept": "application/json"},
            )
            result = self._read_json_response(connection.getresponse())
            if result != {
                "api_version": REMOTE_API_VERSION,
                "status": "ready",
                "authentication_required_for_jobs": True,
            }:
                raise RemoteAtlasTransportError("Remote health contract differs")
            return result
        except (OSError, http.client.HTTPException) as error:
            raise RemoteAtlasTransportError(f"Remote health request failed: {error}") from error
        finally:
            connection.close()

    def submit(
        self,
        job_directory: Path | str,
        *,
        submission_id: str | None = None,
    ) -> dict[str, Any]:
        job = _real_directory(job_directory, label="Remote atlas request")
        verify_remote_atlas_job(job)
        identity = _validate_job_id(submission_id or uuid.uuid4().hex)
        with tempfile.TemporaryDirectory(
            prefix="diffeoforge-remote-submit-",
            dir=job.parent,
        ) as temporary_name:
            archive = create_remote_atlas_job_archive(
                job,
                Path(temporary_name) / "request.zip",
            )
            archive_bytes = archive.stat().st_size
            archive_sha256 = sha256_path(archive)
            headers = self._headers()
            headers.update(
                {
                    "Content-Type": REQUEST_MEDIA_TYPE,
                    "Content-Length": str(archive_bytes),
                    "X-DiffeoForge-Archive-SHA256": archive_sha256,
                    "X-DiffeoForge-Submission-ID": identity,
                }
            )
            connection = self._connection()
            try:
                connection.putrequest("POST", self._path("/jobs"))
                for name, value in headers.items():
                    connection.putheader(name, value)
                connection.endheaders()
                with archive.open("rb") as handle:
                    for chunk in iter(lambda: handle.read(ARCHIVE_CHUNK_BYTES), b""):
                        connection.send(chunk)
                state = self._read_json_response(connection.getresponse())
                return validate_remote_atlas_server_state(
                    state,
                    expected_job_id=identity,
                )
            except (OSError, http.client.HTTPException) as error:
                raise RemoteAtlasTransportError(f"Remote upload failed: {error}") from error
            finally:
                connection.close()

    def status(self, job_id: str) -> dict[str, Any]:
        validated = _validate_job_id(job_id)
        return validate_remote_atlas_server_state(
            self._json_request("GET", f"/jobs/{validated}"),
            expected_job_id=validated,
        )

    def events(
        self,
        job_id: str,
        *,
        after: int = -1,
        limit: int = 100,
    ) -> dict[str, Any]:
        if after < -1:
            raise ValueError("after must be -1 or a nonnegative event index")
        if not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        validated = _validate_job_id(job_id)
        query = urlencode({"after": after, "limit": limit})
        return _validate_event_page(
            self._json_request("GET", f"/jobs/{validated}/events?{query}"),
            expected_job_id=validated,
            after=after,
        )

    def cancel(self, job_id: str) -> dict[str, Any]:
        validated = _validate_job_id(job_id)
        return validate_remote_atlas_server_state(
            self._json_request("POST", f"/jobs/{validated}/cancel"),
            expected_job_id=validated,
        )

    def delete(self, job_id: str) -> dict[str, Any]:
        validated = _validate_job_id(job_id)
        result = self._json_request("DELETE", f"/jobs/{validated}")
        if result != {"job_id": validated, "status": "deleted"}:
            raise RemoteAtlasTransportError("Remote delete response differs")
        return result

    def download(
        self,
        job_id: str,
        job_directory: Path | str,
        destination: Path | str,
    ) -> Path:
        request = _real_directory(job_directory, label="Remote atlas request")
        verify_remote_atlas_job(request)
        target = Path(destination).expanduser().absolute()
        if target == request or request in target.parents:
            raise RemoteAtlasTransportError(
                "Remote result destination must be outside the immutable request"
            )
        if target.exists() or target.is_symlink():
            raise FileExistsError(f"Remote result destination already exists: {target}")
        _assert_no_link_chain(target.parent, label="Remote result destination parent")
        target.parent.mkdir(parents=True, exist_ok=True)
        _assert_no_link_chain(target.parent, label="Remote result destination parent")
        descriptor, archive_name = tempfile.mkstemp(
            prefix=f".{target.name}.download-",
            suffix=".zip",
            dir=target.parent,
        )
        os.close(descriptor)
        archive = Path(archive_name)
        connection = self._connection()
        try:
            headers = self._headers()
            headers["Accept"] = RESULT_MEDIA_TYPE
            connection.request(
                "GET",
                self._path(f"/jobs/{_validate_job_id(job_id)}/result"),
                headers=headers,
            )
            response = connection.getresponse()
            if not 200 <= response.status < 300:
                self._read_json_response(response)
                raise AssertionError("Unreachable non-success response")
            if response.getheader("Content-Type") != RESULT_MEDIA_TYPE:
                raise RemoteAtlasTransportError("Remote result media type differs")
            expected_sha256 = response.getheader("X-DiffeoForge-Archive-SHA256")
            if expected_sha256 is None or re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is None:
                raise RemoteAtlasTransportError("Remote result archive hash header is invalid")
            recorded_length = response.getheader("Content-Length")
            expected_length: int | None = None
            if recorded_length is not None:
                try:
                    expected_length = int(recorded_length)
                except ValueError as error:
                    raise RemoteAtlasTransportError(
                        "Remote result Content-Length is invalid"
                    ) from error
                if not 0 <= expected_length <= DEFAULT_MAX_DOWNLOAD_BYTES:
                    raise RemoteAtlasTransportError("Remote result download is too large")
            digest = hashlib.sha256()
            received = 0
            with archive.open("wb") as handle:
                while True:
                    chunk = response.read(ARCHIVE_CHUNK_BYTES)
                    if not chunk:
                        break
                    received += len(chunk)
                    if received > DEFAULT_MAX_DOWNLOAD_BYTES:
                        raise RemoteAtlasTransportError("Remote result download is too large")
                    digest.update(chunk)
                    handle.write(chunk)
                handle.flush()
                os.fsync(handle.fileno())
            if expected_length is not None and received != expected_length:
                raise RemoteAtlasTransportError("Remote result download length differs")
            if digest.hexdigest() != expected_sha256:
                raise RemoteAtlasTransportError("Remote result archive SHA-256 differs")
            return extract_remote_atlas_result_archive(archive, request, target)
        except (OSError, http.client.HTTPException) as error:
            raise RemoteAtlasTransportError(f"Remote download failed: {error}") from error
        finally:
            connection.close()
            archive.unlink(missing_ok=True)
