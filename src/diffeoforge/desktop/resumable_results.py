"""Bounded read-only discovery of resumable Deformetrica reference runs."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from diffeoforge.runs import (
    RESUMABLE_STATES,
    ResumeSourceEvidence,
    inspect_abandoned_run,
    inspect_resume_source,
    recover_run,
)


class ResumableResultDiscoveryError(RuntimeError):
    """Raised when a selected recovery location cannot be inspected safely."""


@dataclass(frozen=True)
class ResumableReferenceRun:
    """One fully verified interrupted/failed source with an inventoried checkpoint."""

    run_directory: Path
    project_name: str
    subject_count: int
    terminal_status: str
    checkpoint_bytes: int
    source_config_path: Path
    source_config_sha256: str


@dataclass(frozen=True)
class AbandonedReferenceRun:
    """One verified nonterminal run awaiting explicit stopped-process confirmation."""

    run_directory: Path
    project_name: str
    subject_count: int
    started_at: str
    checkpoint_bytes: int | None
    retained_terminal_status: str | None = None


@dataclass(frozen=True)
class RecoveredReferenceRun:
    """Terminal recovery result with an optional fully verified resume source."""

    run_directory: Path
    terminal_status: str
    resumable: ResumableReferenceRun | None


def _json_object(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _candidate_directories(selected: Path) -> tuple[Path, ...]:
    candidates = [selected]
    for root in (selected / "runs", selected / "diffeoforge-project" / "runs"):
        if root.is_symlink() or not root.is_dir():
            continue
        try:
            candidates.extend(
                child for child in root.iterdir() if child.is_dir() and not child.is_symlink()
            )
        except OSError as error:
            raise ResumableResultDiscoveryError(
                f"The run directory could not be inspected: {root}"
            ) from error
    return tuple(dict.fromkeys(candidates))


def _looks_resumable(candidate: Path) -> bool:
    if candidate.is_symlink() or not candidate.is_dir():
        return False
    manifest = _json_object(candidate / "manifest.json")
    result = _json_object(candidate / "result.json")
    backend = manifest.get("backend")
    return bool(
        isinstance(backend, dict)
        and backend.get("id") == "deformetrica_reference"
        and result.get("status") in RESUMABLE_STATES
    )


def _latest_event_name(path: Path) -> str | None:
    if path.is_symlink() or not path.is_file():
        return None
    try:
        size = path.stat().st_size
        if size < 1 or size > 4 * 1024 * 1024:
            return None
        with path.open("rb") as handle:
            handle.seek(max(0, size - 262_144))
            tail = handle.read()
        lines = [line for line in tail.splitlines() if line.strip()]
        if not lines:
            return None
        latest = json.loads(lines[-1].decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return str(latest.get("event")) if isinstance(latest, dict) else None


def _looks_abandoned(candidate: Path) -> bool:
    if candidate.is_symlink() or not candidate.is_dir():
        return False
    manifest = _json_object(candidate / "manifest.json")
    backend = manifest.get("backend")
    return bool(
        isinstance(backend, dict)
        and backend.get("id") == "deformetrica_reference"
        and _latest_event_name(candidate / "events.jsonl") == "started"
    )


def _resumable_from_evidence(evidence: ResumeSourceEvidence) -> ResumableReferenceRun:
    manifest = evidence.manifest
    source_config = manifest["source_config"]
    return ResumableReferenceRun(
        run_directory=evidence.source_run,
        project_name=str(manifest["project"]["name"]),
        subject_count=int(manifest["input_count"]["subjects"]),
        terminal_status=evidence.terminal_status,
        checkpoint_bytes=evidence.checkpoint_bytes,
        source_config_path=evidence.source_run / "config" / "source-config.yaml",
        source_config_sha256=str(source_config["sha256"]),
    )


def discover_resumable_reference_runs(
    directory: Path | str,
) -> tuple[ResumableReferenceRun, ...]:
    """Find and fully verify resumable runs without recursive traversal or mutation."""

    selected = Path(directory).expanduser()
    if selected.is_symlink() or not selected.is_dir():
        raise ResumableResultDiscoveryError(
            f"The selected folder is missing, is not a folder, or is symbolic: {selected}"
        )
    try:
        selected = selected.resolve(strict=True)
    except OSError as error:
        raise ResumableResultDiscoveryError(
            f"The selected folder could not be resolved: {selected}"
        ) from error

    discovered: list[ResumableReferenceRun] = []
    for candidate in _candidate_directories(selected):
        if not _looks_resumable(candidate):
            continue
        try:
            evidence = inspect_resume_source(candidate)
            result = _resumable_from_evidence(evidence)
        except (KeyError, OSError, RuntimeError, TypeError, ValueError):
            continue
        discovered.append(result)
    try:
        return tuple(
            sorted(
                discovered,
                key=lambda result: result.run_directory.stat().st_mtime_ns,
                reverse=True,
            )
        )
    except OSError as error:
        raise ResumableResultDiscoveryError(
            "A resumable run folder changed while it was being inspected."
        ) from error


def discover_abandoned_reference_runs(
    directory: Path | str,
) -> tuple[AbandonedReferenceRun, ...]:
    """Find fully verified nonterminal reference runs without changing them."""

    selected = Path(directory).expanduser()
    if selected.is_symlink() or not selected.is_dir():
        raise ResumableResultDiscoveryError(
            f"The selected folder is missing, is not a folder, or is symbolic: {selected}"
        )
    try:
        selected = selected.resolve(strict=True)
    except OSError as error:
        raise ResumableResultDiscoveryError(
            f"The selected folder could not be resolved: {selected}"
        ) from error

    discovered: list[AbandonedReferenceRun] = []
    for candidate in _candidate_directories(selected):
        if not _looks_abandoned(candidate):
            continue
        try:
            evidence = inspect_abandoned_run(candidate)
            manifest = evidence.manifest
            discovered.append(
                AbandonedReferenceRun(
                    run_directory=evidence.run_directory,
                    project_name=str(manifest["project"]["name"]),
                    subject_count=int(manifest["input_count"]["subjects"]),
                    started_at=str(evidence.started_event["timestamp"]),
                    checkpoint_bytes=evidence.checkpoint_bytes,
                    retained_terminal_status=(
                        None
                        if evidence.terminal_result is None
                        else str(evidence.terminal_result["status"])
                    ),
                )
            )
        except (KeyError, OSError, RuntimeError, TypeError, ValueError):
            continue
    try:
        return tuple(
            sorted(
                discovered,
                key=lambda result: result.run_directory.stat().st_mtime_ns,
                reverse=True,
            )
        )
    except OSError as error:
        raise ResumableResultDiscoveryError(
            "An abandoned run folder changed while it was being inspected."
        ) from error


def recover_abandoned_reference_run(
    abandoned: AbandonedReferenceRun,
    *,
    reason: str,
) -> RecoveredReferenceRun:
    """Finalize one user-confirmed stopped run, then verify any resume checkpoint."""

    if not isinstance(abandoned, AbandonedReferenceRun):
        raise TypeError("abandoned must be an AbandonedReferenceRun")
    result = recover_run(
        abandoned.run_directory,
        reason=reason,
        confirm_process_stopped=True,
    )
    terminal_status = str(result["status"])
    if (
        terminal_status not in RESUMABLE_STATES
        or not result["checkpoint"]["available"]
    ):
        return RecoveredReferenceRun(
            abandoned.run_directory,
            terminal_status=terminal_status,
            resumable=None,
        )
    evidence = inspect_resume_source(abandoned.run_directory)
    return RecoveredReferenceRun(
        abandoned.run_directory,
        terminal_status=terminal_status,
        resumable=_resumable_from_evidence(evidence),
    )
