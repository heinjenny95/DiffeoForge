"""Tests for the first-screen recent-project convenience store."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from diffeoforge.desktop.recent_projects import (
    MAXIMUM_ENTRIES,
    MODERN_ENGINE,
    REFERENCE_ENGINE,
    available_recent_projects,
    default_store_path,
    load_recent_projects,
    recent_project_from_inputs,
    record_recent_project,
)


def _project(tmp_path: Path, name: str, *, engine: str = REFERENCE_ENGINE) -> Path:
    project = tmp_path / name
    project.mkdir()
    filename = "atlas.yaml" if engine == REFERENCE_ENGINE else "modern-atlas.yaml"
    (project / filename).write_text("schema_version: '0.1'\n", encoding="utf-8")
    meshes = tmp_path / f"{name}-meshes"
    meshes.mkdir(exist_ok=True)
    return project


def _entry(tmp_path: Path, name: str, *, engine: str = REFERENCE_ENGINE):
    project = _project(tmp_path, name, engine=engine)
    return recent_project_from_inputs(
        engine=engine,
        project_directory=project,
        mesh_directory=tmp_path / f"{name}-meshes",
        subject_pattern="*.ply",
        coordinate_unit="micrometer",
        project_name=name,
    )


def test_store_round_trips_one_entry(tmp_path: Path) -> None:
    store = tmp_path / "recent.json"
    entry = _entry(tmp_path, "medaka")

    record_recent_project(entry, store)
    loaded = load_recent_projects(store)

    assert len(loaded) == 1
    assert loaded[0].project_directory == entry.project_directory
    assert loaded[0].coordinate_unit == "micrometer"
    assert loaded[0].subject_pattern == "*.ply"
    assert loaded[0].project_name == "medaka"


def test_stored_document_declares_its_boundary(tmp_path: Path) -> None:
    store = tmp_path / "recent.json"
    record_recent_project(_entry(tmp_path, "medaka"), store)

    document = json.loads(store.read_text(encoding="utf-8"))

    assert document["store_version"] == "0.1"
    assert document["kind"] == "diffeoforge_desktop_recent_projects"
    assert document["scientific_boundary"] == "interface_convenience_state_not_run_evidence"


def test_most_recent_project_is_first_and_never_duplicated(tmp_path: Path) -> None:
    store = tmp_path / "recent.json"
    first = _entry(tmp_path, "mandibles")
    second = _entry(tmp_path, "medaka")

    record_recent_project(first, store)
    record_recent_project(second, store)
    record_recent_project(first, store)

    loaded = load_recent_projects(store)
    assert [item.project_name for item in loaded] == ["mandibles", "medaka"]


def test_store_is_capped(tmp_path: Path) -> None:
    store = tmp_path / "recent.json"
    for index in range(MAXIMUM_ENTRIES + 3):
        record_recent_project(_entry(tmp_path, f"project-{index:02d}"), store)

    loaded = load_recent_projects(store)
    assert len(loaded) == MAXIMUM_ENTRIES
    assert loaded[0].project_name == f"project-{MAXIMUM_ENTRIES + 2:02d}"


def test_entry_without_configuration_is_not_offered(tmp_path: Path) -> None:
    store = tmp_path / "recent.json"
    entry = _entry(tmp_path, "medaka")
    record_recent_project(entry, store)

    (entry.project_directory / "atlas.yaml").unlink()

    assert len(load_recent_projects(store)) == 1
    assert available_recent_projects(store) == ()


def test_entry_without_mesh_folder_is_not_offered(tmp_path: Path) -> None:
    store = tmp_path / "recent.json"
    entry = _entry(tmp_path, "medaka")
    record_recent_project(entry, store)

    for child in entry.mesh_directory.iterdir():  # pragma: no cover - defensive
        child.unlink()
    entry.mesh_directory.rmdir()

    assert available_recent_projects(store) == ()


def test_modern_projects_resolve_their_own_configuration_name(tmp_path: Path) -> None:
    store = tmp_path / "recent.json"
    entry = _entry(tmp_path, "modern", engine=MODERN_ENGINE)
    record_recent_project(entry, store)

    loaded = available_recent_projects(store)
    assert len(loaded) == 1
    assert loaded[0].configuration_path.name == "modern-atlas.yaml"


@pytest.mark.parametrize(
    "payload",
    [
        "",
        "not json at all",
        "[]",
        json.dumps({"store_version": "0.2", "kind": "x", "entries": []}),
        json.dumps({"store_version": "0.1", "kind": "wrong", "entries": []}),
    ],
)
def test_unusable_store_is_treated_as_no_history(tmp_path: Path, payload: str) -> None:
    store = tmp_path / "recent.json"
    store.write_text(payload, encoding="utf-8")

    assert load_recent_projects(store) == ()


def test_missing_store_is_not_an_error(tmp_path: Path) -> None:
    assert load_recent_projects(tmp_path / "absent.json") == ()


def test_unusable_store_is_replaced_rather_than_repaired(tmp_path: Path) -> None:
    store = tmp_path / "recent.json"
    store.write_text("{ broken", encoding="utf-8")

    record_recent_project(_entry(tmp_path, "medaka"), store)

    loaded = load_recent_projects(store)
    assert [item.project_name for item in loaded] == ["medaka"]


def test_unknown_engine_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        recent_project_from_inputs(
            engine="something_else",
            project_directory=tmp_path,
            mesh_directory=tmp_path,
            subject_pattern="*.vtk",
            coordinate_unit="millimeter",
        )


def test_store_path_honours_an_explicit_state_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DIFFEOFORGE_STATE_HOME", str(tmp_path / "state"))

    assert default_store_path() == tmp_path / "state" / "recent-projects.json"


def test_store_never_lands_inside_a_project(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DIFFEOFORGE_STATE_HOME", raising=False)

    path = default_store_path()

    assert path.name == "recent-projects.json"
    assert "diffeoforge" in str(path).lower()
