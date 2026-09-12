"""Bounded discovery of completed atlas runs for the desktop results view."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

_REFERENCE_MANIFEST = "manifest.json"
_REFERENCE_RESULT = "result.json"
_REFERENCE_BACKEND = "deformetrica_reference"
_MODERN_WORKFLOW_MANIFEST = "workflow-manifest.json"


class CompletedResultDiscoveryError(RuntimeError):
    """Raised when a selected result location cannot be inspected safely."""


@dataclass(frozen=True)
class CompletedResultRun:
    """One completed result candidate awaiting full fail-closed verification."""

    run_directory: Path
    reference: bool


def _json_object(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _reference_candidate(directory: Path) -> bool:
    manifest_path = directory / _REFERENCE_MANIFEST
    result_path = directory / _REFERENCE_RESULT
    if (
        manifest_path.is_symlink()
        or result_path.is_symlink()
        or not manifest_path.is_file()
        or not result_path.is_file()
    ):
        return False
    manifest = _json_object(manifest_path)
    result = _json_object(result_path)
    backend = manifest.get("backend")
    return bool(
        isinstance(backend, dict)
        and backend.get("id") == _REFERENCE_BACKEND
        and result.get("status") == "completed"
        and result.get("return_code") == 0
    )


def _modern_candidate(directory: Path) -> bool:
    manifest_path = directory / _MODERN_WORKFLOW_MANIFEST
    return not manifest_path.is_symlink() and manifest_path.is_file()


def _candidate_directories(selected: Path) -> tuple[Path, ...]:
    candidates = [selected]
    run_roots = (selected / "runs", selected / "diffeoforge-project" / "runs")
    for root in run_roots:
        if root.is_symlink() or not root.is_dir():
            continue
        try:
            candidates.extend(
                child for child in root.iterdir() if child.is_dir() and not child.is_symlink()
            )
        except OSError as error:
            raise CompletedResultDiscoveryError(
                f"The run directory could not be inspected: {root}"
            ) from error
    return tuple(dict.fromkeys(candidates))


def discover_completed_results(directory: Path | str) -> tuple[CompletedResultRun, ...]:
    """Find completed runs at one selected location without recursive traversal."""

    selected = Path(directory).expanduser()
    if selected.is_symlink() or not selected.is_dir():
        raise CompletedResultDiscoveryError(
            f"The selected folder is missing, is not a folder, or is symbolic: {selected}"
        )
    try:
        selected = selected.resolve(strict=True)
    except OSError as error:
        raise CompletedResultDiscoveryError(
            f"The selected folder could not be resolved: {selected}"
        ) from error

    discovered: list[CompletedResultRun] = []
    for candidate in _candidate_directories(selected):
        if _reference_candidate(candidate):
            discovered.append(CompletedResultRun(candidate.resolve(), reference=True))
        elif _modern_candidate(candidate):
            discovered.append(CompletedResultRun(candidate.resolve(), reference=False))

    try:
        return tuple(
            sorted(
                discovered,
                key=lambda result: result.run_directory.stat().st_mtime_ns,
                reverse=True,
            )
        )
    except OSError as error:
        raise CompletedResultDiscoveryError(
            "A completed result folder changed while it was being inspected."
        ) from error
