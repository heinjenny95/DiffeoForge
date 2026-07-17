"""Read-only discovery and process leases for private unpublished runs."""

from __future__ import annotations

import errno
import json
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path
from typing import Any, BinaryIO, Literal

import jsonschema

from diffeoforge import __version__

MARKER_NAME = ".diffeoforge-private-run.json"
LEASE_NAME = ".diffeoforge-private-run.lock"
MARKER_VERSION = "0.1"
DISCOVERY_VERSION = "0.1"
MAX_MARKER_BYTES = 64 * 1024

PrivateRunStatus = Literal[
    "active",
    "abandoned",
    "unattributed",
    "invalid_metadata",
    "indeterminate",
    "unsafe_link",
]


class PrivateRunError(RuntimeError):
    """Raised when private-run state cannot be created or inspected safely."""


class _LeaseHeld(Exception):
    """Internal signal that another process currently holds a lease."""


def _schema(name: str) -> dict[str, Any]:
    resource = files("diffeoforge.schema").joinpath(name)
    return json.loads(resource.read_text(encoding="utf-8"))


def _validate(value: dict[str, Any], schema_name: str, label: str) -> None:
    validator = jsonschema.Draft202012Validator(_schema(schema_name))
    errors = sorted(validator.iter_errors(value), key=lambda error: list(error.absolute_path))
    if errors:
        error = errors[0]
        location = ".".join(str(part) for part in error.absolute_path) or "document"
        raise PrivateRunError(
            f"{label} schema validation failed at {location}: {error.message}"
        )


def _canonical(path: Path | str) -> str:
    return os.path.normcase(str(Path(path).expanduser().resolve()))


def _candidate_pattern(destination: Path) -> re.Pattern[str]:
    if not destination.name:
        raise ValueError("Private-run destination must have a directory name")
    return re.compile(rf"^\.{re.escape(destination.name)}\.tmp-([0-9a-f]{{32}})$")


def _acquire_nonblocking_lock(handle: BinaryIO) -> None:
    if os.name == "nt":
        import msvcrt

        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as error:
            if error.errno in {errno.EACCES, errno.EAGAIN}:
                raise _LeaseHeld from error
            raise
        return

    import fcntl

    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as error:
        if error.errno in {errno.EACCES, errno.EAGAIN}:
            raise _LeaseHeld from error
        raise


def _release_lock(handle: BinaryIO) -> None:
    if os.name == "nt":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return

    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@dataclass(frozen=True)
class PrivateRunCandidate:
    """One exact-name private directory observed without changing its content."""

    path: Path
    status: PrivateRunStatus
    reason: str
    marker: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "directory_name": self.path.name,
            "status": self.status,
            "reason": self.reason,
            "marker": self.marker,
        }


@dataclass(frozen=True)
class PrivateRunDiscovery:
    """Strict read-only status for one exact prospective destination."""

    destination: Path
    destination_exists: bool
    candidates: tuple[PrivateRunCandidate, ...]

    @property
    def status(self) -> str:
        if self.candidates:
            return "attention_required"
        if self.destination_exists:
            return "destination_exists"
        return "clear"

    @property
    def ready_for_new_run(self) -> bool:
        return self.status == "clear"

    def as_dict(self) -> dict[str, Any]:
        value = {
            "discovery_version": DISCOVERY_VERSION,
            "kind": "diffeoforge_private_run_discovery",
            "destination": str(self.destination),
            "destination_exists": self.destination_exists,
            "status": self.status,
            "ready_for_new_run": self.ready_for_new_run,
            "mutation_performed": False,
            "candidates": [candidate.as_dict() for candidate in self.candidates],
            "limitations": [
                "A held lease proves that a process owns the private directory; it does not "
                "prove scientific progress or health.",
                "Unattributed, invalid, indeterminate, and abandoned candidates require "
                "explicit user review; discovery never deletes, renames, resumes, or publishes.",
            ],
        }
        _validate(value, "private-run-discovery-v0.1.json", "Private-run discovery")
        return value


class PrivateRunLease:
    """Exclusive process lease held until cleanup or pre-publication removal."""

    def __init__(
        self,
        private_directory: Path,
        marker_path: Path,
        lease_path: Path,
        handle: BinaryIO,
    ) -> None:
        self.private_directory = private_directory
        self.marker_path = marker_path
        self.lease_path = lease_path
        self._handle: BinaryIO | None = handle

    @property
    def open(self) -> bool:
        return self._handle is not None

    def close(self) -> None:
        """Release ownership while retaining evidence for crash-style inspection."""

        handle = self._handle
        if handle is None:
            return
        self._handle = None
        try:
            _release_lock(handle)
        finally:
            handle.close()

    def remove_for_publication(self) -> None:
        """Remove private-only lease evidence before immutable artifact inventory."""

        if self._handle is None:
            raise PrivateRunError("Private-run lease is no longer held")
        self.marker_path.unlink()
        self.close()
        self.lease_path.unlink()


def acquire_private_run_lease(
    private_directory: Path | str,
    destination: Path | str,
    *,
    operation: str,
) -> PrivateRunLease:
    """Create and hold one versioned lease in an already private directory."""

    private = Path(private_directory).expanduser().resolve()
    output = Path(destination).expanduser().resolve()
    if not private.is_dir() or private.is_symlink():
        raise PrivateRunError(f"Private-run directory is not a real directory: {private}")
    if private.parent != output.parent:
        raise PrivateRunError("Private-run directory and destination must share one parent")
    match = _candidate_pattern(output).fullmatch(private.name)
    if match is None:
        raise PrivateRunError(
            f"Private-run directory does not match the exact destination contract: {private.name}"
        )
    token = match.group(1)
    lease_path = private / LEASE_NAME
    marker_path = private / MARKER_NAME
    handle: BinaryIO | None = None
    try:
        handle = lease_path.open("x+b", buffering=0)
        handle.write(f"{token}\n".encode("ascii"))
        handle.flush()
        os.fsync(handle.fileno())
        _acquire_nonblocking_lock(handle)
        marker = {
            "marker_version": MARKER_VERSION,
            "kind": "diffeoforge_private_run",
            "safety_status": "private_unpublished_not_a_result",
            "operation": operation,
            "destination": str(output),
            "private_directory": str(private),
            "run_token": token,
            "pid": os.getpid(),
            "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "diffeoforge_version": __version__,
            "lease_file": LEASE_NAME,
        }
        _validate(marker, "private-run-marker-v0.1.json", "Private-run marker")
        with marker_path.open("x", encoding="utf-8", newline="\n") as marker_handle:
            json.dump(marker, marker_handle, indent=2, ensure_ascii=False, sort_keys=True)
            marker_handle.write("\n")
            marker_handle.flush()
            os.fsync(marker_handle.fileno())
        return PrivateRunLease(private, marker_path, lease_path, handle)
    except Exception:
        if handle is not None:
            try:
                _release_lock(handle)
            except OSError:
                pass
            handle.close()
        for path in (marker_path, lease_path):
            try:
                path.unlink()
            except FileNotFoundError:
                pass
        raise


def _read_marker(candidate: Path, destination: Path, token: str) -> dict[str, Any]:
    marker_path = candidate / MARKER_NAME
    if marker_path.is_symlink():
        raise PrivateRunError("Private-run marker must not be a symbolic link")
    try:
        size = marker_path.stat().st_size
    except FileNotFoundError as error:
        raise PrivateRunError("Private-run marker is missing") from error
    except OSError as error:
        raise PrivateRunError(f"Private-run marker cannot be inspected: {error}") from error
    if not 1 <= size <= MAX_MARKER_BYTES:
        raise PrivateRunError(
            f"Private-run marker size must be between 1 and {MAX_MARKER_BYTES} bytes"
        )
    try:
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise PrivateRunError(f"Private-run marker is not readable JSON: {error}") from error
    if not isinstance(marker, dict):
        raise PrivateRunError("Private-run marker must be a JSON object")
    _validate(marker, "private-run-marker-v0.1.json", "Private-run marker")
    if _canonical(marker["destination"]) != _canonical(destination):
        raise PrivateRunError("Private-run marker destination does not match the requested target")
    if _canonical(marker["private_directory"]) != _canonical(candidate):
        raise PrivateRunError("Private-run marker directory does not match its container")
    if marker["run_token"] != token:
        raise PrivateRunError("Private-run marker token does not match its directory name")
    return marker


def _inspect_candidate(candidate: Path, destination: Path, token: str) -> PrivateRunCandidate:
    if candidate.is_symlink():
        return PrivateRunCandidate(
            candidate,
            "unsafe_link",
            "Matching private-run path is a symbolic link and was not followed.",
        )
    if not candidate.is_dir():
        return PrivateRunCandidate(
            candidate,
            "invalid_metadata",
            "Matching private-run path is not a directory.",
        )
    marker_path = candidate / MARKER_NAME
    if not marker_path.exists() and not marker_path.is_symlink():
        return PrivateRunCandidate(
            candidate,
            "unattributed",
            "Matching private directory has no DiffeoForge ownership marker.",
        )
    try:
        marker = _read_marker(candidate, destination, token)
    except PrivateRunError as error:
        return PrivateRunCandidate(candidate, "invalid_metadata", str(error))

    lease_path = candidate / LEASE_NAME
    if lease_path.is_symlink() or not lease_path.is_file():
        return PrivateRunCandidate(
            candidate,
            "invalid_metadata",
            "Private-run lease is missing, not a regular file, or a symbolic link.",
            marker,
        )
    try:
        handle = lease_path.open("r+b", buffering=0)
    except OSError as error:
        return PrivateRunCandidate(
            candidate,
            "indeterminate",
            f"Private-run lease cannot be opened for a non-mutating lock probe: {error}",
            marker,
        )
    try:
        try:
            _acquire_nonblocking_lock(handle)
        except _LeaseHeld:
            return PrivateRunCandidate(
                candidate,
                "active",
                "Another process currently holds the private-run lease.",
                marker,
            )
        except OSError as error:
            return PrivateRunCandidate(
                candidate,
                "indeterminate",
                f"Private-run lease state cannot be determined: {error}",
                marker,
            )
        try:
            _release_lock(handle)
        except OSError as error:
            return PrivateRunCandidate(
                candidate,
                "indeterminate",
                f"Private-run probe lock could not be released cleanly: {error}",
                marker,
            )
        return PrivateRunCandidate(
            candidate,
            "abandoned",
            "No process holds the valid private-run lease; explicit review is required.",
            marker,
        )
    finally:
        handle.close()


def discover_private_runs(destination: Path | str) -> PrivateRunDiscovery:
    """Inspect exact-name private candidates without deleting or rewriting anything."""

    output = Path(destination).expanduser().resolve()
    pattern = _candidate_pattern(output)
    parent = output.parent
    candidates: list[PrivateRunCandidate] = []
    if parent.exists():
        if not parent.is_dir():
            raise PrivateRunError(f"Private-run destination parent is not a directory: {parent}")
        try:
            with os.scandir(parent) as iterator:
                entries = sorted(iterator, key=lambda entry: entry.name)
        except OSError as error:
            raise PrivateRunError(
                f"Could not inspect destination parent {parent}: {error}"
            ) from error
        for entry in entries:
            match = pattern.fullmatch(entry.name)
            if match is None:
                continue
            candidates.append(_inspect_candidate(Path(entry.path), output, match.group(1)))
    discovery = PrivateRunDiscovery(output, output.exists(), tuple(candidates))
    discovery.as_dict()
    return discovery
