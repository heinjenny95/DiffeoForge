"""Remember which project folders the researcher opened most recently.

This module stores interface convenience state and nothing else. It records the
paths and the coordinate unit a researcher already chose so the first desktop
screen can offer them again instead of presenting empty fields after every
restart.

Deliberate boundaries:

* The store never holds scientific evidence. It is not part of any run, it is
  never hashed into a manifest, and deleting it loses no result.
* Recording an entry never reads, opens, verifies, or changes a project.
* Offering an entry never loads it. The researcher still chooses explicitly on
  the first screen, and the existing project-resume path performs every
  verification it performed before.
* A missing, unreadable, or invalid store is treated as "no history". It is
  never repaired in place and never aborts the application.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib.resources import files
from pathlib import Path
from typing import Any

import jsonschema

from diffeoforge.atomic_io import write_text_safely

STORE_VERSION = "0.1"
STORE_KIND = "diffeoforge_desktop_recent_projects"
SCIENTIFIC_BOUNDARY = "interface_convenience_state_not_run_evidence"
SCHEMA_NAME = "desktop-recent-projects-v0.1.json"
STORE_FILENAME = "recent-projects.json"
MAXIMUM_ENTRIES = 8

REFERENCE_ENGINE = "deformetrica_reference"
MODERN_ENGINE = "modern_cpu"

_CONFIG_FILENAMES = {
    REFERENCE_ENGINE: "atlas.yaml",
    MODERN_ENGINE: "modern-atlas.yaml",
}


@dataclass(frozen=True)
class RecentProject:
    """One previously opened project folder and the inputs it was opened with."""

    engine: str
    project_directory: Path
    mesh_directory: Path
    subject_pattern: str
    coordinate_unit: str
    recorded_at: str
    project_name: str | None = None
    template: Path | None = None
    landmarks: Path | None = None

    @property
    def configuration_path(self) -> Path:
        """Path of the generated configuration this entry would resume."""

        return self.project_directory / _CONFIG_FILENAMES[self.engine]

    @property
    def is_available(self) -> bool:
        """True when the recorded project still has a generated configuration.

        This is a read-only existence check. It does not open, parse, verify, or
        in any way vouch for the configuration it finds.
        """

        try:
            return self.configuration_path.is_file() and self.mesh_directory.is_dir()
        except OSError:
            return False

    @property
    def label(self) -> str:
        """Short one-line description for a chooser."""

        name = self.project_name or self.project_directory.name
        return f"{name} — {self.project_directory}"

    def as_entry(self) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "engine": self.engine,
            "project_directory": str(self.project_directory),
            "mesh_directory": str(self.mesh_directory),
            "subject_pattern": self.subject_pattern,
            "coordinate_unit": self.coordinate_unit,
            "recorded_at": self.recorded_at,
        }
        if self.project_name:
            entry["project_name"] = self.project_name
        if self.template is not None:
            entry["template"] = str(self.template)
        if self.landmarks is not None:
            entry["landmarks"] = str(self.landmarks)
        return entry


def _schema() -> dict[str, Any]:
    resource = files("diffeoforge.schema").joinpath(SCHEMA_NAME)
    return json.loads(resource.read_text(encoding="utf-8"))


def _validate(document: dict[str, Any]) -> None:
    jsonschema.Draft202012Validator(_schema()).validate(document)


def default_store_path() -> Path:
    """Per-user location of the convenience store.

    The store lives beside other per-user application state, never inside a
    project folder, so that no project directory gains a file a researcher did
    not ask for.
    """

    override = os.environ.get("DIFFEOFORGE_STATE_HOME")
    if override:
        return Path(override).expanduser() / STORE_FILENAME
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA")
        root = Path(base).expanduser() if base else Path.home() / "AppData" / "Local"
        return root / "DiffeoForge" / STORE_FILENAME
    base = os.environ.get("XDG_STATE_HOME")
    root = Path(base).expanduser() if base else Path.home() / ".local" / "state"
    return root / "diffeoforge" / STORE_FILENAME


def _entry_to_recent_project(entry: dict[str, Any]) -> RecentProject:
    template = entry.get("template")
    landmarks = entry.get("landmarks")
    return RecentProject(
        engine=str(entry["engine"]),
        project_directory=Path(str(entry["project_directory"])),
        mesh_directory=Path(str(entry["mesh_directory"])),
        subject_pattern=str(entry["subject_pattern"]),
        coordinate_unit=str(entry["coordinate_unit"]),
        recorded_at=str(entry["recorded_at"]),
        project_name=str(entry["project_name"]) if entry.get("project_name") else None,
        template=Path(str(template)) if template else None,
        landmarks=Path(str(landmarks)) if landmarks else None,
    )


def load_recent_projects(store_path: Path | str | None = None) -> tuple[RecentProject, ...]:
    """Read the convenience store, tolerating every failure as "no history".

    A corrupt or foreign file is ignored rather than repaired, so a broken store
    can never block the application or silently become a different document.
    """

    path = Path(store_path) if store_path is not None else default_store_path()
    try:
        payload = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ()
    try:
        document = json.loads(payload)
    except json.JSONDecodeError:
        return ()
    if not isinstance(document, dict):
        return ()
    try:
        _validate(document)
    except jsonschema.ValidationError:
        return ()
    try:
        return tuple(_entry_to_recent_project(entry) for entry in document["entries"])
    except (KeyError, TypeError, ValueError):
        return ()


def available_recent_projects(
    store_path: Path | str | None = None,
) -> tuple[RecentProject, ...]:
    """Recent entries whose configuration and mesh folder still exist."""

    return tuple(entry for entry in load_recent_projects(store_path) if entry.is_available)


def _same_project(left: RecentProject, right: RecentProject) -> bool:
    return os.path.normcase(str(left.project_directory)) == os.path.normcase(
        str(right.project_directory)
    ) and left.engine == right.engine


def record_recent_project(
    project: RecentProject,
    store_path: Path | str | None = None,
    *,
    existing: Iterable[RecentProject] | None = None,
) -> tuple[RecentProject, ...]:
    """Move one project to the front of the store and return the new order.

    Writing is best-effort: if the store cannot be written the researcher simply
    gets no history next time. Nothing else in the application depends on it.
    """

    path = Path(store_path) if store_path is not None else default_store_path()
    history = tuple(existing) if existing is not None else load_recent_projects(path)
    remaining = tuple(entry for entry in history if not _same_project(entry, project))
    ordered = (project, *remaining)[:MAXIMUM_ENTRIES]
    document = {
        "store_version": STORE_VERSION,
        "kind": STORE_KIND,
        "scientific_boundary": SCIENTIFIC_BOUNDARY,
        "entries": [entry.as_entry() for entry in ordered],
    }
    _validate(document)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        write_text_safely(
            path,
            json.dumps(document, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            overwrite=True,
        )
    except OSError:
        return ordered
    return ordered


def recent_project_from_inputs(
    *,
    engine: str,
    project_directory: Path | str,
    mesh_directory: Path | str,
    subject_pattern: str,
    coordinate_unit: str,
    project_name: str | None = None,
    template: Path | str | None = None,
    landmarks: Path | str | None = None,
    recorded_at: str | None = None,
) -> RecentProject:
    """Build an entry from the first-screen inputs without touching the disk."""

    if engine not in _CONFIG_FILENAMES:
        raise ValueError(f"Unsupported desktop engine identifier: {engine}")
    stamp = recorded_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )
    return RecentProject(
        engine=engine,
        project_directory=Path(project_directory),
        mesh_directory=Path(mesh_directory),
        subject_pattern=subject_pattern,
        coordinate_unit=coordinate_unit,
        recorded_at=stamp,
        project_name=project_name or None,
        template=Path(template) if template else None,
        landmarks=Path(landmarks) if landmarks else None,
    )
