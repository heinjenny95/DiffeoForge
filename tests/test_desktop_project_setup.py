from __future__ import annotations

import csv
import importlib.util
import json
import shutil
from pathlib import Path

import pytest
import yaml

from diffeoforge.analysis.landmarks import LANDMARK_COLUMNS
from diffeoforge.backends.deformetrica_reference import render_engine_file_bytes
from diffeoforge.config import ConfigurationError, load_config
from diffeoforge.desktop.project_setup import (
    DesktopEngine,
    ProjectSetupRequest,
    create_project,
)
from diffeoforge.mesh import read_vtk_polydata, sha256_file
from diffeoforge.preprocessing import preview_landmark_alignment

ROOT = Path(__file__).parents[1]
MESH_DIRECTORY = ROOT / "examples" / "synthetic" / "meshes"


def _write_landmarks(path: Path) -> Path:
    meshes = [MESH_DIRECTORY / "template.vtk", *sorted(MESH_DIRECTORY.glob("subject-*.vtk"))]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(LANDMARK_COLUMNS)
        for mesh in meshes:
            points = read_vtk_polydata(mesh).vertices
            for label, index in zip(("a", "b", "c"), (0, 40, 80), strict=True):
                writer.writerow((mesh.name, label, *points[index]))
    return path


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


def test_reference_project_setup_persists_visible_parameter_selection(tmp_path: Path) -> None:
    ratios = {
        "attachment_kernel_width": 0.05,
        "deformation_kernel_width": 0.10,
        "initial_control_point_spacing": 0.10,
        "noise_std": 0.0125,
    }
    result = create_project(
        ProjectSetupRequest(
            mesh_directory=MESH_DIRECTORY,
            project_directory=tmp_path / "high-detail",
            units="millimeter",
            engine=DesktopEngine.DEFORMETRICA_REFERENCE,
            reference_parameter_profile="high_detail",
            reference_parameter_ratios=ratios,
            reference_max_iterations=200,
            reference_initial_step_size=0.01,
            reference_convergence_tolerance=0.0001,
            reference_attachment_type="varifold",
            reference_timepoints=17,
            reference_use_rk2=True,
            reference_max_line_search_iterations=23,
            reference_save_every_n_iterations=7,
            reference_print_every_n_iterations=3,
            reference_scale_initial_step_size=False,
            reference_use_sobolev_gradient=False,
            reference_sobolev_kernel_width_ratio=1.75,
            reference_freeze_template=True,
            reference_freeze_control_points=True,
            reference_threads=6,
            reference_random_seed=42,
        )
    )

    config = yaml.safe_load(result.config_path.read_text(encoding="utf-8"))
    assert config["project"]["parameter_provenance"]["profile"] == "high_detail"
    assert config["project"]["parameter_provenance"]["ratios"] == ratios
    assert config["optimization"]["max_iterations"] == 200
    assert config["model"]["attachment"]["type"] == "varifold"
    assert config["model"]["deformation"]["timepoints"] == 17
    assert config["model"]["deformation"]["use_rk2"] is True
    assert config["optimization"]["max_line_search_iterations"] == 23
    assert config["optimization"]["save_every_n_iterations"] == 7
    assert config["optimization"]["print_every_n_iterations"] == 3
    assert config["optimization"]["scale_initial_step_size"] is False
    assert config["optimization"]["use_sobolev_gradient"] is False
    assert config["optimization"]["sobolev_kernel_width_ratio"] == 1.75
    assert config["optimization"]["freeze_template"] is True
    assert config["optimization"]["freeze_control_points"] is True
    assert config["runtime"]["threads"] == 6
    assert config["runtime"]["random_seed"] == 42
    rendered = render_engine_file_bytes(
        load_config(result.config_path),
        Path("input/template.vtk"),
        (Path("input/subject.vtk"),),
    )
    model_xml = rendered["model.xml"].decode("utf-8")
    optimization_xml = rendered["optimization_parameters.xml"].decode("utf-8")
    assert "<attachment-type>varifold</attachment-type>" in model_xml
    assert "<number-of-timepoints>17</number-of-timepoints>" in model_xml
    assert "<max-line-search-iterations>23</max-line-search-iterations>" in optimization_xml
    assert "<use-rk2>On</use-rk2>" in optimization_xml
    assert "<freeze-template>On</freeze-template>" in optimization_xml
    assert "<freeze-control-points>On</freeze-control-points>" in optimization_xml


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


def test_reference_project_applies_landmarks_before_deformetrica_without_editing_raw_meshes(
    tmp_path: Path,
) -> None:
    project_directory = tmp_path / "reference"
    sources = (MESH_DIRECTORY / "template.vtk", *sorted(MESH_DIRECTORY.glob("subject-*.vtk")))
    hashes_before = {path: sha256_file(path) for path in sources}
    result = create_project(
        ProjectSetupRequest(
            mesh_directory=MESH_DIRECTORY,
            project_directory=project_directory,
            units="unitless",
            engine=DesktopEngine.DEFORMETRICA_REFERENCE,
            landmarks_file=_write_landmarks(tmp_path / "landmarks.csv"),
            procrustes_scale_to_unit_centroid_size=False,
            procrustes_allow_reflection=True,
            procrustes_tolerance=1e-8,
            procrustes_max_iterations=250,
        )
    )

    assert result.preprocessing_report_path is not None
    assert result.preprocessing_report_path.is_file()
    assert result.template_path.parent.name.startswith("aligned-")
    assert {path: sha256_file(path) for path in sources} == hashes_before
    evidence = json.loads(result.preprocessing_report_path.read_text(encoding="utf-8"))
    assert evidence["settings"] == {
        "allow_reflection": True,
        "max_iterations": 250,
        "scale_to_unit_centroid_size": False,
        "tolerance": 1e-8,
    }
    config = yaml.safe_load(result.config_path.read_text(encoding="utf-8"))
    assert "preprocessing/aligned-" in config["input"]["directory"]
    assert any("Raw meshes were not modified" in notice for notice in result.notices)


def test_project_creation_is_bound_to_approved_procrustes_preview(
    tmp_path: Path,
) -> None:
    landmarks = _write_landmarks(tmp_path / "landmarks.csv")
    preview = preview_landmark_alignment(
        MESH_DIRECTORY,
        landmarks_file=landmarks,
        tolerance=1e-8,
    )
    approved_project = tmp_path / "approved"
    result = create_project(
        ProjectSetupRequest(
            mesh_directory=MESH_DIRECTORY,
            project_directory=approved_project,
            units="unitless",
            engine=DesktopEngine.DEFORMETRICA_REFERENCE,
            landmarks_file=landmarks,
            procrustes_tolerance=1e-8,
            approved_procrustes_fingerprint=preview.fingerprint,
        )
    )
    assert result.preprocessing_report_path is not None

    changed_project = tmp_path / "changed"
    with pytest.raises(ConfigurationError, match="approved preview"):
        create_project(
            ProjectSetupRequest(
                mesh_directory=MESH_DIRECTORY,
                project_directory=changed_project,
                units="unitless",
                engine=DesktopEngine.DEFORMETRICA_REFERENCE,
                landmarks_file=landmarks,
                procrustes_tolerance=1e-7,
                approved_procrustes_fingerprint=preview.fingerprint,
            )
        )
    assert not (changed_project / "atlas.yaml").exists()


@pytest.mark.parametrize("fingerprint", ["too-short", "g" * 64])
def test_project_setup_rejects_invalid_procrustes_preview_fingerprint(
    fingerprint: str,
    tmp_path: Path,
) -> None:
    project = tmp_path / "invalid fingerprint"
    with pytest.raises(ConfigurationError, match="64 hexadecimal"):
        create_project(
            ProjectSetupRequest(
                mesh_directory=MESH_DIRECTORY,
                project_directory=project,
                units="unitless",
                engine=DesktopEngine.DEFORMETRICA_REFERENCE,
                landmarks_file=_write_landmarks(tmp_path / "landmarks.csv"),
                approved_procrustes_fingerprint=fingerprint,
            )
        )
    assert not project.exists()


def test_project_setup_rejects_preview_fingerprint_without_landmarks(
    tmp_path: Path,
) -> None:
    project = tmp_path / "missing landmarks"
    with pytest.raises(ConfigurationError, match="requires a landmark file"):
        create_project(
            ProjectSetupRequest(
                mesh_directory=MESH_DIRECTORY,
                project_directory=project,
                units="unitless",
                engine=DesktopEngine.DEFORMETRICA_REFERENCE,
                approved_procrustes_fingerprint="a" * 64,
            )
        )
    assert not project.exists()


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


def test_desktop_project_setup_rejects_nonfinite_procrustes_tolerance(
    tmp_path: Path,
) -> None:
    with pytest.raises(ConfigurationError, match="procrustes_tolerance"):
        create_project(
            ProjectSetupRequest(
                mesh_directory=MESH_DIRECTORY,
                project_directory=tmp_path / "invalid procrustes",
                units="unitless",
                engine=DesktopEngine.DEFORMETRICA_REFERENCE,
                procrustes_tolerance=float("nan"),
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
    assert any("not total RAM or computation time" in notice for notice in result.notices)
