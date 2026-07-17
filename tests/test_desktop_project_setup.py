from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path

import pytest

from diffeoforge.config import ConfigurationError
from diffeoforge.desktop.project_setup import (
    DesktopEngine,
    ProjectSetupRequest,
    create_project,
)

ROOT = Path(__file__).parents[1]
MESH_DIRECTORY = ROOT / "examples" / "synthetic" / "meshes"


def test_reference_project_setup_uses_shared_core_and_writes_preflight(tmp_path: Path) -> None:
    result = create_project(
        ProjectSetupRequest(
            mesh_directory=MESH_DIRECTORY,
            project_directory=tmp_path / "reference project",
            units="millimeter",
            engine=DesktopEngine.DEFORMETRICA_REFERENCE,
        )
    )

    assert result.engine is DesktopEngine.DEFORMETRICA_REFERENCE
    assert result.subject_count == 5
    assert result.template_path.name == "template.vtk"
    assert result.config_path == tmp_path / "reference project" / "atlas.yaml"
    assert result.config_path.is_file()
    assert result.report_path == result.config_path.with_suffix(".preflight.html")
    assert result.report_path.is_file()
    assert any("did not execute Deformetrica" in notice for notice in result.notices)


def test_project_setup_handles_spaces_and_non_ascii_paths(tmp_path: Path) -> None:
    mesh_directory = tmp_path / "Käfer Daten" / "meshes"
    shutil.copytree(MESH_DIRECTORY, mesh_directory)
    project_directory = tmp_path / "Projekt für Käfer"

    result = create_project(
        ProjectSetupRequest(
            mesh_directory=mesh_directory,
            project_directory=project_directory,
            units="micrometer",
            engine=DesktopEngine.DEFORMETRICA_REFERENCE,
            project_name="Käfer Atlas",
        )
    )

    assert result.config_path.parent == project_directory
    assert "Käfer Atlas" in result.config_path.read_text(encoding="utf-8")
    assert str(mesh_directory.resolve()) in result.report_path.read_text(encoding="utf-8")


def test_project_setup_never_overwrites_an_existing_configuration(tmp_path: Path) -> None:
    project_directory = tmp_path / "owned"
    project_directory.mkdir()
    config_path = project_directory / "atlas.yaml"
    config_path.write_text("owned by researcher\n", encoding="utf-8")

    request = ProjectSetupRequest(
        mesh_directory=MESH_DIRECTORY,
        project_directory=project_directory,
        units="unitless",
        engine=DesktopEngine.DEFORMETRICA_REFERENCE,
    )
    with pytest.raises(ConfigurationError, match="will not be overwritten"):
        create_project(request)

    assert config_path.read_text(encoding="utf-8") == "owned by researcher\n"


def test_reference_project_rejects_modern_only_landmarks_before_writing(tmp_path: Path) -> None:
    project_directory = tmp_path / "reference"
    with pytest.raises(ConfigurationError, match="only for the modern CPU"):
        create_project(
            ProjectSetupRequest(
                mesh_directory=MESH_DIRECTORY,
                project_directory=project_directory,
                units="unitless",
                engine=DesktopEngine.DEFORMETRICA_REFERENCE,
                landmarks_file=tmp_path / "landmarks.csv",
            )
        )

    assert not project_directory.exists()


def test_modern_project_setup_uses_existing_workflow_service(tmp_path: Path) -> None:
    if importlib.util.find_spec("numpy") is None or importlib.util.find_spec("torch") is None:
        pytest.skip("modern-engine dependencies are not installed")

    result = create_project(
        ProjectSetupRequest(
            mesh_directory=MESH_DIRECTORY,
            project_directory=tmp_path / "modern project",
            units="unitless",
            engine=DesktopEngine.MODERN_CPU,
        )
    )

    assert result.engine is DesktopEngine.MODERN_CPU
    assert result.subject_count == 5
    assert result.config_path.name == "modern-atlas.yaml"
    assert result.config_path.is_file()
    assert result.report_path is None
    assert any("did not run an atlas" in notice for notice in result.notices)
