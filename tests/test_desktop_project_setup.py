from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path

import pytest
import yaml

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


def test_confirmed_overwrite_replaces_only_a_generated_modern_configuration(
    tmp_path: Path,
) -> None:
    if importlib.util.find_spec("numpy") is None or importlib.util.find_spec("torch") is None:
        pytest.skip("modern-engine dependencies are not installed")
    project_directory = tmp_path / "replace generated"
    initial = create_project(
        ProjectSetupRequest(
            mesh_directory=MESH_DIRECTORY,
            project_directory=project_directory,
            units="unitless",
            engine=DesktopEngine.MODERN_CPU,
            project_name="Old project name",
        )
    )
    before = initial.config_path.read_bytes()

    replaced = create_project(
        ProjectSetupRequest(
            mesh_directory=MESH_DIRECTORY,
            project_directory=project_directory,
            units="unitless",
            engine=DesktopEngine.MODERN_CPU,
            project_name="New project name",
            overwrite_existing_configuration=True,
        )
    )

    after = replaced.config_path.read_bytes()
    assert after != before
    assert b"New project name" in after
    assert b"Old project name" not in after
    assert any("explicit confirmation" in notice for notice in replaced.notices)


def test_confirmed_overwrite_still_refuses_a_researcher_owned_modern_file(
    tmp_path: Path,
) -> None:
    if importlib.util.find_spec("numpy") is None or importlib.util.find_spec("torch") is None:
        pytest.skip("modern-engine dependencies are not installed")
    project_directory = tmp_path / "owned modern"
    project_directory.mkdir()
    config_path = project_directory / "modern-atlas.yaml"
    original = b"researcher_owned: true\n"
    config_path.write_bytes(original)

    with pytest.raises(ConfigurationError, match="not a generated modern workflow"):
        create_project(
            ProjectSetupRequest(
                mesh_directory=MESH_DIRECTORY,
                project_directory=project_directory,
                units="unitless",
                engine=DesktopEngine.MODERN_CPU,
                overwrite_existing_configuration=True,
            )
        )

    assert config_path.read_bytes() == original


def test_failed_atomic_modern_overwrite_preserves_the_previous_configuration(
    monkeypatch, tmp_path: Path
) -> None:
    if importlib.util.find_spec("numpy") is None or importlib.util.find_spec("torch") is None:
        pytest.skip("modern-engine dependencies are not installed")
    project_directory = tmp_path / "atomic replace"
    initial = create_project(
        ProjectSetupRequest(
            mesh_directory=MESH_DIRECTORY,
            project_directory=project_directory,
            units="unitless",
            engine=DesktopEngine.MODERN_CPU,
            project_name="Preserve me",
        )
    )
    original = initial.config_path.read_bytes()

    def fail_replace(*_args, **_kwargs) -> None:
        raise OSError("simulated atomic publish failure")

    monkeypatch.setattr("diffeoforge.atomic_io.os.replace", fail_replace)
    with pytest.raises(ConfigurationError, match="simulated atomic publish failure"):
        create_project(
            ProjectSetupRequest(
                mesh_directory=MESH_DIRECTORY,
                project_directory=project_directory,
                units="unitless",
                engine=DesktopEngine.MODERN_CPU,
                project_name="Must not leak",
                overwrite_existing_configuration=True,
            )
        )

    assert initial.config_path.read_bytes() == original
    assert list(project_directory.glob(".modern-atlas.yaml.*.tmp")) == []


def test_reference_overwrite_prechecks_report_ownership_before_config_mutation(
    tmp_path: Path,
) -> None:
    project_directory = tmp_path / "reference ownership"
    initial = create_project(
        ProjectSetupRequest(
            mesh_directory=MESH_DIRECTORY,
            project_directory=project_directory,
            units="unitless",
            engine=DesktopEngine.DEFORMETRICA_REFERENCE,
            project_name="Preserved reference project",
        )
    )
    original_config = initial.config_path.read_bytes()
    assert initial.report_path is not None
    initial.report_path.write_text("researcher-owned HTML\n", encoding="utf-8")

    with pytest.raises(ConfigurationError, match="not recognized"):
        create_project(
            ProjectSetupRequest(
                mesh_directory=MESH_DIRECTORY,
                project_directory=project_directory,
                units="unitless",
                engine=DesktopEngine.DEFORMETRICA_REFERENCE,
                project_name="Must not replace the configuration",
                overwrite_existing_configuration=True,
            )
        )

    assert initial.config_path.read_bytes() == original_config
    assert initial.report_path.read_text(encoding="utf-8") == "researcher-owned HTML\n"


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
    assert any("technical pilot" in notice for notice in result.notices)


def test_modern_project_setup_records_explicit_convergence_attempt(tmp_path: Path) -> None:
    if importlib.util.find_spec("numpy") is None or importlib.util.find_spec("torch") is None:
        pytest.skip("modern-engine dependencies are not installed")

    result = create_project(
        ProjectSetupRequest(
            mesh_directory=MESH_DIRECTORY,
            project_directory=tmp_path / "convergence attempt",
            units="unitless",
            engine=DesktopEngine.MODERN_CPU,
            max_cycles=50,
        )
    )
    config = yaml.safe_load(result.config_path.read_text(encoding="utf-8"))

    assert config["optimization"]["max_cycles"] == 50
    assert any("does not guarantee convergence" in notice for notice in result.notices)


def test_desktop_project_setup_rejects_invalid_cycle_cap(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="max_cycles must be a positive integer"):
        create_project(
            ProjectSetupRequest(
                mesh_directory=MESH_DIRECTORY,
                project_directory=tmp_path / "invalid cycles",
                units="unitless",
                engine=DesktopEngine.MODERN_CPU,
                max_cycles=0,
            )
        )


def test_modern_project_setup_records_an_explicit_blockwise_high_face_plan(
    tmp_path: Path,
) -> None:
    if importlib.util.find_spec("numpy") is None or importlib.util.find_spec("torch") is None:
        pytest.skip("modern-engine dependencies are not installed")

    result = create_project(
        ProjectSetupRequest(
            mesh_directory=MESH_DIRECTORY,
            project_directory=tmp_path / "blockwise project",
            units="unitless",
            engine=DesktopEngine.MODERN_CPU,
            pairwise_mode="blockwise",
            query_tile_size=256,
            source_tile_size=256,
        )
    )
    config = yaml.safe_load(result.config_path.read_text(encoding="utf-8"))

    assert config["schema_version"] == "0.2"
    assert config["runtime"]["pairwise_evaluation"] == {
        "mode": "blockwise",
        "query_tile_size": 256,
        "source_tile_size": 256,
    }
    assert any("not total RAM or runtime" in notice for notice in result.notices)
