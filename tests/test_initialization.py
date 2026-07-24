from __future__ import annotations

from pathlib import Path

import pytest

from diffeoforge.cli import main
from diffeoforge.config import ConfigurationError, load_config, validate_input_paths
from diffeoforge.initialization import (
    EXPLORATORY_RATIOS,
    detect_template,
    initialize_project,
)

REPOSITORY_ROOT = Path(__file__).parents[1]
MESH_DIRECTORY = REPOSITORY_ROOT / "examples" / "synthetic" / "meshes"


@pytest.mark.parametrize("extension", (".vtk", ".ply", ".obj", ".stl"))
def test_template_detection_accepts_each_supported_source_extension(
    tmp_path: Path,
    extension: str,
) -> None:
    expected = tmp_path / f"template{extension}"
    expected.write_bytes(b"identity-only fixture")

    assert detect_template(tmp_path) == expected.resolve()


def test_template_detection_rejects_ambiguous_supported_formats(tmp_path: Path) -> None:
    (tmp_path / "template.obj").write_bytes(b"obj")
    (tmp_path / "Template.ply").write_bytes(b"ply")

    with pytest.raises(ConfigurationError, match="More than one supported"):
        detect_template(tmp_path)


def test_init_creates_valid_transparent_geometry_scaled_config(tmp_path: Path) -> None:
    config_path = tmp_path / "atlas.yaml"

    result = initialize_project(
        MESH_DIRECTORY,
        units="millimeter",
        config_path=config_path,
    )

    loaded = load_config(config_path)
    inputs = validate_input_paths(loaded, config_path)
    diagonal = result.preflight.template.bounding_box_diagonal
    assert inputs.subject_count == 5
    assert inputs.template.name == "template.vtk"
    assert loaded["runtime"]["launcher"]["type"] == "container"
    assert loaded["model"]["attachment"]["kernel_width"] == pytest.approx(
        diagonal * EXPLORATORY_RATIOS["attachment_kernel_width"], rel=1e-7
    )
    assert set(result.derived_parameters) == set(EXPLORATORY_RATIOS)
    text = config_path.read_text(encoding="utf-8")
    assert "not scientifically validated defaults" in text
    assert "attachment_kernel_width" in text


def test_explicit_model_parameters_are_not_labelled_as_derived(tmp_path: Path) -> None:
    result = initialize_project(
        MESH_DIRECTORY,
        units="unitless",
        config_path=tmp_path / "explicit.yaml",
        attachment_kernel_width=0.45,
        deformation_kernel_width=0.6,
        initial_control_point_spacing=0.6,
        noise_std=0.1,
    )

    assert result.derived_parameters == ()
    assert result.config["model"]["attachment"]["kernel_width"] == 0.45
    assert "exploratory starting values" not in result.config_path.read_text(encoding="utf-8")


def test_advanced_scale_ratios_and_optimizer_values_are_persisted(tmp_path: Path) -> None:
    ratios = {
        "attachment_kernel_width": 0.04,
        "deformation_kernel_width": 0.08,
        "initial_control_point_spacing": 0.07,
        "noise_std": 0.01,
    }
    result = initialize_project(
        MESH_DIRECTORY,
        units="millimeter",
        config_path=tmp_path / "advanced.yaml",
        parameter_profile="advanced",
        parameter_ratios=ratios,
        max_iterations=321,
        initial_step_size=0.0025,
        convergence_tolerance=0.000002,
    )

    config = load_config(result.config_path)
    diagonal = result.preflight.template.bounding_box_diagonal
    assert config["project"]["parameter_provenance"] == {
        "profile": "advanced",
        "scale_reference": "template_bounding_box_diagonal",
        "ratios": ratios,
        "sources": {
            "attachment_kernel_width": "template_diagonal_ratio",
            "deformation_kernel_width": "template_diagonal_ratio",
            "initial_control_point_spacing": "template_diagonal_ratio",
            "noise_std": "template_diagonal_ratio",
        },
    }
    assert config["model"]["attachment"]["kernel_width"] == pytest.approx(
        diagonal * ratios["attachment_kernel_width"], rel=1e-7
    )
    assert config["model"]["deformation"]["kernel_width"] == pytest.approx(
        diagonal * ratios["deformation_kernel_width"], rel=1e-7
    )
    assert config["optimization"]["max_iterations"] == 321
    assert config["optimization"]["initial_step_size"] == 0.0025
    assert config["optimization"]["convergence_tolerance"] == 0.000002
    assert "0.04 x template diagonal" in result.config_path.read_text(encoding="utf-8")


def test_init_refuses_to_overwrite_configuration(tmp_path: Path) -> None:
    config_path = tmp_path / "atlas.yaml"
    config_path.write_text("owned by user\n", encoding="utf-8")

    with pytest.raises(ConfigurationError, match="will not be overwritten"):
        initialize_project(MESH_DIRECTORY, units="unitless", config_path=config_path)

    assert config_path.read_text(encoding="utf-8") == "owned by user\n"

    with pytest.raises(ConfigurationError, match="not recognized"):
        initialize_project(
            MESH_DIRECTORY,
            units="unitless",
            config_path=config_path,
            overwrite=True,
        )
    assert config_path.read_text(encoding="utf-8") == "owned by user\n"


def test_init_cli_creates_config_and_html_report(capsys, tmp_path: Path) -> None:
    config_path = tmp_path / "atlas.yaml"

    return_code = main(
        [
            "init",
            str(MESH_DIRECTORY),
            "--units",
            "unitless",
            "--config",
            str(config_path),
        ]
    )

    captured = capsys.readouterr()
    assert return_code == 0
    assert config_path.is_file()
    assert config_path.with_suffix(".preflight.html").is_file()
    assert "Subject meshes: 5" in captured.out
    assert "exploratory geometry-scaled values" in captured.out
    assert "Preflight report:" in captured.out
