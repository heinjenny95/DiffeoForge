"""Read-only result discovery and disposable, per-user navigation preferences.

Listing reads small records only. Opening still uses the existing full result
verifier; a catalog entry is neither scientific approval nor verified evidence.
"""

from __future__ import annotations

import json
import os
import stat
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Event

from diffeoforge.atomic_io import write_text_safely
from diffeoforge.desktop.completed_results import CompletedResultRun
from diffeoforge.desktop.recent_projects import default_store_path

MAX_DIRECTORIES = 6000
MAX_DEPTH = 14
MAX_RECORD_BYTES = 8 * 1024 * 1024
_SKIP = frozenset(
    {
        "output",
        "engine",
        "analysis",
        "visualizations",
        "preprocessing",
        "inputs",
        "working-targets",
        "meshes",
        "recordings",
        "videos",
        ".git",
        ".venv",
        "__pycache__",
    }
)


def _key(path: Path) -> str:
    return os.path.normcase(os.path.abspath(path))


def _linked(path: Path) -> bool:
    try:
        return path.is_symlink() or bool(
            getattr(path.lstat(), "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        )
    except OSError:
        return True


def _record(path: Path) -> dict:
    try:
        if _linked(path) or path.stat().st_size > MAX_RECORD_BYTES:
            return {}
        with path.open("rb") as stream:
            raw = stream.read(MAX_RECORD_BYTES + 1)
        if len(raw) > MAX_RECORD_BYTES:
            return {}
        value = json.loads(raw.decode("utf-8-sig"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, UnicodeError, RecursionError):
        return {}


def _object(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def _text(value: object) -> str:
    return " ".join(value.split())[:200] if isinstance(value, str) else ""


@dataclass(frozen=True)
class ResultLibraryEntry:
    result: CompletedResultRun
    project_name: str
    subjects: int | None
    completed_at: str
    timestamp: float
    pilot: bool

    @property
    def date_label(self) -> str:
        if not self.completed_at:
            return "Unknown"
        return datetime.fromtimestamp(self.timestamp, UTC).astimezone().strftime("%Y-%m-%d %H:%M")


@dataclass(frozen=True)
class ResultLibraryScan:
    entries: tuple[ResultLibraryEntry, ...]
    visited: int
    incomplete: bool
    unavailable: tuple[str, ...]


def _entry(directory: Path) -> ResultLibraryEntry | None:
    manifest = _record(directory / "manifest.json")
    result = _record(directory / "result.json")
    reference = (
        _object(manifest.get("backend")).get("id") == "deformetrica_reference"
        and result.get("status") == "completed"
        and type(result.get("return_code")) is int
        and result["return_code"] == 0
    )
    if not reference:
        manifest = _record(directory / "workflow-manifest.json")
        if not manifest:
            return None
    config = _object(manifest.get("effective_config"))
    name = _text(_object(manifest.get("project")).get("name")) or _text(
        _object(config.get("project")).get("name")
    )
    count = _object(manifest.get("input_count")).get("subjects")
    if type(count) is not int or count < 1:
        subjects = manifest.get("subjects")
        count = len(subjects) if isinstance(subjects, list) and subjects else None
    stamp = _text(result.get("ended_at")) or _text(manifest.get("created_at"))
    try:
        date = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        if date.tzinfo is None:
            raise ValueError("Unzoned record date")
        timestamp = date.timestamp()
        datetime.fromtimestamp(timestamp, UTC)
    except (ValueError, OSError, OverflowError):
        try:
            timestamp = directory.stat().st_mtime
        except OSError:
            return None
        stamp = ""
    return ResultLibraryEntry(
        result=CompletedResultRun(directory, reference=bool(reference)),
        project_name=name or directory.name,
        subjects=count,
        completed_at=stamp,
        timestamp=timestamp,
        pilot=(
            any(
                word in f" {name.lower()} " for word in (" calibration ", " diagnostic ", " pilot ")
            )
            or directory.name.lower().startswith("pilot-")
        ),
    )


def scan_result_library(
    roots: tuple[Path, ...],
    cancelled: Event | None = None,
    *,
    maximum_directories: int = MAX_DIRECTORIES,
    maximum_depth: int = MAX_DEPTH,
) -> ResultLibraryScan:
    """Search only chosen/known roots, bounded and cancellable between folders.

    Never follow symbolic links or Windows junctions. Do not traverse output,
    cache, or geometry folders or descend into a discovered run. No hashing,
    mesh loading, SSH connection, recovery or scientific write occurs here.
    """
    queue = deque((Path(root).expanduser().absolute(), 0) for root in roots)
    seen: set[str] = set()
    entries: list[ResultLibraryEntry] = []
    unavailable: list[str] = []
    incomplete = False
    while queue and len(seen) < maximum_directories:
        if cancelled is not None and cancelled.is_set():
            incomplete = True
            break
        directory, depth = queue.popleft()
        key = _key(directory)
        if key in seen:
            continue
        seen.add(key)
        if _linked(directory) or not directory.is_dir():
            unavailable.append(str(directory))
            continue
        entry = _entry(directory)
        if entry is not None:
            entries.append(entry)
            continue
        try:
            with os.scandir(directory) as children:
                for child in children:
                    if cancelled is not None and cancelled.is_set():
                        incomplete = True
                        break
                    if child.name.lower() in _SKIP or not child.is_dir(follow_symlinks=False):
                        continue
                    if _linked(Path(child.path)):
                        continue
                    if depth >= maximum_depth:
                        incomplete = True
                    elif len(queue) < maximum_directories:
                        queue.append((Path(child.path), depth + 1))
                    else:
                        incomplete = True
        except OSError:
            unavailable.append(str(directory))
    return ResultLibraryScan(
        entries=tuple(sorted(entries, key=lambda e: (-e.timestamp, _key(e.result.run_directory)))),
        visited=len(seen),
        incomplete=incomplete or bool(queue),
        unavailable=tuple(unavailable),
    )


def library_store_path() -> Path:
    return default_store_path().with_name("result-library.json")


def load_library_preferences(path: Path | None = None) -> dict:
    value = _record(path if path is not None else library_store_path())
    if value.get("kind") != "diffeoforge_result_library" or value.get("version") != 1:
        return {"roots": [], "opened": [], "names": {}}
    return {
        "roots": [
            p
            for p in value.get("roots", [])
            if isinstance(p, str) and p.strip() and Path(p).is_absolute()
        ][:64]
        if isinstance(value.get("roots"), list)
        else [],
        "opened": [
            p
            for p in value.get("opened", [])
            if isinstance(p, str) and p.strip() and Path(p).is_absolute()
        ][:200]
        if isinstance(value.get("opened"), list)
        else [],
        "names": {
            k: _text(v)
            for k, v in value.get("names", {}).items()
            if isinstance(k, str) and _text(v)
        }
        if isinstance(value.get("names"), dict)
        else {},
    }


def save_library_preference(
    *,
    root: Path | None = None,
    opened: Path | None = None,
    rename: tuple[Path, str] | None = None,
    path: Path | None = None,
) -> bool:
    """Store navigation state outside every project; failure never blocks opening."""
    target = path if path is not None else library_store_path()
    value = load_library_preferences(target)
    for key, item, limit in (("roots", root, 64), ("opened", opened, 200)):
        if item is not None:
            item = item.expanduser().absolute()
            value[key] = [str(item), *[p for p in value[key] if _key(Path(p)) != _key(item)]][
                :limit
            ]
    if rename is not None:
        key, name = _key(rename[0]), _text(rename[1])
        if name:
            value["names"][key] = name
        else:
            value["names"].pop(key, None)
    value.update(kind="diffeoforge_result_library", version=1)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        write_text_safely(
            target, json.dumps(value, ensure_ascii=False, indent=2) + "\n", overwrite=True
        )
    except OSError:
        return False
    return True


def entry_name(entry: ResultLibraryEntry, preferences: dict) -> str:
    return preferences["names"].get(_key(entry.result.run_directory), entry.project_name)
