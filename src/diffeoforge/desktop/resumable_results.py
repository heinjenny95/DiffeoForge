"""Bounded read-only discovery of resumable Deformetrica reference runs."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from diffeoforge.runs import RESUMABLE_STATES, inspect_resume_source


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
            manifest = evidence.manifest
            source_config = manifest["source_config"]
            source_config_path = evidence.source_run / "config" / "source-config.yaml"
            subject_count = int(manifest["input_count"]["subjects"])
            project_name = str(manifest["project"]["name"])
        except (KeyError, OSError, RuntimeError, TypeError, ValueError):
            continue
        discovered.append(
            ResumableReferenceRun(
                run_directory=evidence.source_run,
                project_name=project_name,
                subject_count=subject_count,
                terminal_status=evidence.terminal_status,
                checkpoint_bytes=evidence.checkpoint_bytes,
                source_config_path=source_config_path,
                source_config_sha256=str(source_config["sha256"]),
            )
        )
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
