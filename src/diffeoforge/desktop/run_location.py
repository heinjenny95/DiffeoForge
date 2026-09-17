"""Bounded read-only description of what a selected run location actually contains.

The three desktop entry points for existing runs each accept only one lifecycle
state. When none is found, the user must learn what *was* found and which action
fits it. This module classifies folders from their small JSON records only: it
never hashes output, never traverses recursively, and never changes a file.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from diffeoforge.runs import RESUMABLE_STATES

_REFERENCE_BACKEND = "deformetrica_reference"
_MODERN_WORKFLOW_MANIFEST = "workflow-manifest.json"
_MAX_JSON_BYTES = 16 * 1024 * 1024
_MAX_NEARBY_CHILDREN = 200
_MAX_LISTED = 6


class RunLookupPurpose(Enum):
    """Which desktop action the user chose."""

    OPEN_COMPLETED = "open_completed"
    RESUME_INTERRUPTED = "resume_interrupted"
    RECOVER_CRASHED = "recover_crashed"


class RunFolderState(Enum):
    """Lifecycle state read from a run folder's own records."""

    COMPLETED = "completed"
    STOPPED_WITH_CHECKPOINT = "stopped_with_checkpoint"
    STOPPED_WITHOUT_CHECKPOINT = "stopped_without_checkpoint"
    STARTED = "started"
    PREPARED = "prepared"
    UNRECOGNIZED = "unrecognized"


_ACTION_LABELS = {
    RunLookupPurpose.OPEN_COMPLETED: "Open completed run…",
    RunLookupPurpose.RESUME_INTERRUPTED: "Resume interrupted run…",
    RunLookupPurpose.RECOVER_CRASHED: "Recover after crash…",
}

_EXPECTED = {
    RunLookupPurpose.OPEN_COMPLETED: (
        "a completed run: a folder containing manifest.json and a result.json with "
        "status 'completed' (Deformetrica), or a workflow-manifest.json (Modern)"
    ),
    RunLookupPurpose.RESUME_INTERRUPTED: (
        "an interrupted or failed Deformetrica run whose result.json records an "
        "available checkpoint (output/deformetrica-state.p)"
    ),
    RunLookupPurpose.RECOVER_CRASHED: (
        "a Deformetrica run whose events.jsonl still ends with 'started', i.e. a run "
        "that never recorded how it ended"
    ),
}

_FITTING_PURPOSE = {
    RunFolderState.COMPLETED: RunLookupPurpose.OPEN_COMPLETED,
    RunFolderState.STOPPED_WITH_CHECKPOINT: RunLookupPurpose.RESUME_INTERRUPTED,
    RunFolderState.STARTED: RunLookupPurpose.RECOVER_CRASHED,
}


@dataclass(frozen=True)
class RunFolderFinding:
    """One run folder and the lifecycle state its records describe."""

    run_directory: Path
    state: RunFolderState
    summary: str


@dataclass(frozen=True)
class RunLocationDescription:
    """Everything cheaply learnable about one selected folder."""

    selected: Path
    findings: tuple[RunFolderFinding, ...]
    nearby_run_roots: tuple[Path, ...]
    enclosing_run: Path | None


def _json_object(path: Path) -> dict:
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > _MAX_JSON_BYTES:
            return {}
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _latest_event_name(path: Path) -> str | None:
    try:
        if path.is_symlink() or not path.is_file():
            return None
        size = path.stat().st_size
        if size < 1:
            return None
        with path.open("rb") as handle:
            handle.seek(max(0, size - 262_144))
            tail = handle.read()
        lines = [line for line in tail.splitlines() if line.strip()]
        latest = json.loads(lines[-1].decode("utf-8")) if lines else None
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return str(latest.get("event")) if isinstance(latest, dict) else None


def _is_run_folder(directory: Path) -> bool:
    return bool(
        not directory.is_symlink()
        and directory.is_dir()
        and (
            (directory / "manifest.json").is_file()
            or (directory / _MODERN_WORKFLOW_MANIFEST).is_file()
        )
    )


def _progress_detail(result: dict) -> str:
    rows = result.get("convergence_rows")
    if isinstance(rows, int) and not isinstance(rows, bool) and rows > 0:
        return f" The convergence log holds {rows} recorded iteration row(s)."
    return ""


def _classify(directory: Path) -> RunFolderFinding | None:
    if not _is_run_folder(directory):
        return None
    if (directory / _MODERN_WORKFLOW_MANIFEST).is_file() and not (
        directory / "manifest.json"
    ).is_file():
        return RunFolderFinding(directory, RunFolderState.COMPLETED, "a Modern workflow result")
    manifest = _json_object(directory / "manifest.json")
    backend = manifest.get("backend")
    if not isinstance(backend, dict) or backend.get("id") != _REFERENCE_BACKEND:
        return RunFolderFinding(
            directory,
            RunFolderState.UNRECOGNIZED,
            "a manifest.json that does not describe a Deformetrica reference run",
        )
    result = _json_object(directory / "result.json")
    status = result.get("status")
    latest_event = _latest_event_name(directory / "events.jsonl")
    if status == "completed" and result.get("return_code") == 0:
        return RunFolderFinding(
            directory, RunFolderState.COMPLETED, "a completed Deformetrica run"
        )
    if status in RESUMABLE_STATES:
        checkpoint = result.get("checkpoint")
        available = isinstance(checkpoint, dict) and checkpoint.get("available") is True
        recovered = isinstance(result.get("recovery"), dict)
        origin = " It was recorded by crash recovery." if recovered else ""
        if available:
            return RunFolderFinding(
                directory,
                RunFolderState.STOPPED_WITH_CHECKPOINT,
                f"a Deformetrica run recorded as {status} with a checkpoint.{origin}"
                + _progress_detail(result),
            )
        return RunFolderFinding(
            directory,
            RunFolderState.STOPPED_WITHOUT_CHECKPOINT,
            f"a Deformetrica run recorded as {status}, but no checkpoint was ever "
            f"written, so it cannot be continued.{origin}" + _progress_detail(result)
            + " Its retained files are unchanged; only a new run can replace it.",
        )
    if latest_event == "started":
        return RunFolderFinding(
            directory,
            RunFolderState.STARTED,
            "a Deformetrica run that started but never recorded how it ended",
        )
    if latest_event == "prepared":
        return RunFolderFinding(
            directory,
            RunFolderState.PREPARED,
            "a Deformetrica run that was prepared but never started",
        )
    return RunFolderFinding(
        directory,
        RunFolderState.UNRECOGNIZED,
        "a Deformetrica run folder whose records describe no known lifecycle state "
        f"(result status {status!r}, latest event {latest_event!r})",
    )


def _run_children(root: Path) -> tuple[Path, ...]:
    if root.is_symlink() or not root.is_dir():
        return ()
    try:
        return tuple(
            sorted(child for child in root.iterdir() if _is_run_folder(child))
        )
    except OSError:
        return ()


def describe_run_location(directory: Path | str) -> RunLocationDescription:
    """Classify the selected folder, its direct run roots, and its close surroundings."""

    selected = Path(directory).expanduser()
    try:
        selected = selected.resolve(strict=True)
    except OSError:
        return RunLocationDescription(selected, (), (), None)
    if not selected.is_dir():
        return RunLocationDescription(selected, (), (), None)

    candidates = [selected]
    for root in (selected / "runs", selected / "diffeoforge-project" / "runs"):
        candidates.extend(_run_children(root))
    findings = tuple(
        finding
        for finding in (_classify(candidate) for candidate in dict.fromkeys(candidates))
        if finding is not None
    )

    enclosing_run = None
    if not findings:
        for parent in list(selected.parents)[:3]:
            if _is_run_folder(parent):
                enclosing_run = parent
                break

    nearby: list[Path] = []
    if not findings and enclosing_run is None:
        try:
            children = sorted(
                child
                for child in selected.iterdir()
                if child.is_dir() and not child.is_symlink()
            )[:_MAX_NEARBY_CHILDREN]
        except OSError:
            children = []
        for child in children:
            for root in (child / "runs", child / "diffeoforge-project" / "runs"):
                if _run_children(root):
                    nearby.append(child)
                    break
        if selected.name == "runs" and _run_children(selected):
            nearby.insert(0, selected.parent)
    return RunLocationDescription(selected, findings, tuple(nearby), enclosing_run)


def explain_missing_run(
    purpose: RunLookupPurpose,
    description: RunLocationDescription,
    rejected: tuple[tuple[Path, str], ...] = (),
) -> str:
    """Say what was expected, what was found instead, and what to do next."""

    lines = [
        f"“{_ACTION_LABELS[purpose]}” found nothing it can use in:",
        str(description.selected),
        "",
        f"It looks for {_EXPECTED[purpose]}. You may select either the run folder "
        "itself or the project folder that directly contains its “runs” folder.",
    ]
    rejected_paths = {path for path, _reason in rejected}
    if rejected:
        lines += ["", "A matching run was found but failed full verification:"]
        summaries = {finding.run_directory: finding.summary for finding in description.findings}
        for path, reason in rejected[:_MAX_LISTED]:
            lines.append(f"• {path.name}: {reason}")
            if path in summaries:
                lines.append(f"  Its own records describe {summaries[path].rstrip('.')}.")
    others = [
        finding for finding in description.findings if finding.run_directory not in rejected_paths
    ]
    if others:
        lines += ["", "What this location contains instead:"]
        for finding in others[:_MAX_LISTED]:
            fitting = _FITTING_PURPOSE.get(finding.state)
            advice = (
                f" Use “{_ACTION_LABELS[fitting]}” for it."
                if fitting is not None and fitting is not purpose
                else ""
            )
            summary = finding.summary.rstrip(".") + "."
            lines.append(f"• {finding.run_directory.name}: {summary}{advice}")
        if len(others) > _MAX_LISTED:
            lines.append(f"• … and {len(others) - _MAX_LISTED} more run folder(s).")
    elif not rejected:
        lines += ["", "No DiffeoForge run folder was found at this location."]
        if description.enclosing_run is not None:
            lines.append(
                "The selection lies inside a run folder. Select this folder instead: "
                f"{description.enclosing_run}"
            )
        elif description.nearby_run_roots:
            lines.append("Run folders exist one level away. Select one of these instead:")
            lines += [f"• {path}" for path in description.nearby_run_roots[:_MAX_LISTED]]
    lines += ["", "Nothing was loaded and nothing was changed."]
    return "\n".join(lines)
