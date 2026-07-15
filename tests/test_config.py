from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from diffeoforge.config import (
    ConfigurationError,
    load_config,
    validate_input_paths,
    validate_schema,
)


@pytest.fixture
def valid_config() -> dict:
    return {
        "schema_version": "0.1",
        "project": {"name": "test-atlas"},
        "input": {
            "directory": "./meshes",
            "subject_pattern": "subject-*.vtk",
            "template": "./meshes/template.vtk",
            "units": "unitless",
        },
        "model": {
            "type": "deterministic_atlas",
            "dimension": 3,
            "object_id": "surface",
            "attachment": {"type": "current", "kernel_width": 0.1},
            "deformation": {
                "kernel_width": 0.1,
                "timepoints": 10,
                "initial_control_point_spacing": 0.1,
                "use_rk2": False,
            },
            "noise_std": 0.05,
        },
        "optimization": {
            "method": "gradient_ascent",
            "max_iterations": 100,
            "initial_step_size": 0.01,
            "convergence_tolerance": 0.0001,
            "downsampling_factor": 1,
            "max_line_search_iterations": 10,
            "save_every_n_iterations": 100,
            "print_every_n_iterations": 1,
            "scale_initial_step_size": True,
            "use_sobolev_gradient": True,
            "sobolev_kernel_width_ratio": 1.0,
            "freeze_template": False,
            "freeze_control_points": False,
        },
        "runtime": {
            "backend": "deformetrica_reference",
            "device": "cpu",
            "threads": 4,
            "processes": 1,
            "precision": "float32",
            "random_seed": 20260715,
            "kernel_backend": "keops",
            "verbosity": "INFO",
            "launcher": {"type": "native", "executable": "deformetrica"},
        },
        "output": {"directory": "./runs", "retain_flow_meshes": True},
    }


def write_config(path: Path, config: dict) -> Path:
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return path


def test_valid_schema_is_accepted(valid_config: dict) -> None:
    validate_schema(valid_config)


def test_non_positive_kernel_width_is_rejected(valid_config: dict) -> None:
    invalid = deepcopy(valid_config)
    invalid["model"]["deformation"]["kernel_width"] = 0

    with pytest.raises(ConfigurationError, match="less than or equal to the minimum"):
        validate_schema(invalid)


def test_unknown_keys_are_rejected(valid_config: dict) -> None:
    invalid = deepcopy(valid_config)
    invalid["model"]["undocumented_magic"] = True

    with pytest.raises(ConfigurationError, match="Additional properties"):
        validate_schema(invalid)


def test_input_preflight_resolves_paths_and_excludes_template(
    tmp_path: Path, valid_config: dict
) -> None:
    mesh_dir = tmp_path / "meshes"
    mesh_dir.mkdir()
    (mesh_dir / "template.vtk").write_text("template", encoding="utf-8")
    (mesh_dir / "subject-a.vtk").write_text("a", encoding="utf-8")
    (mesh_dir / "subject-b.vtk").write_text("b", encoding="utf-8")
    config_path = write_config(tmp_path / "atlas.yaml", valid_config)

    loaded = load_config(config_path)
    summary = validate_input_paths(loaded, config_path)

    assert summary.subject_count == 2
    assert summary.template == (mesh_dir / "template.vtk").resolve()
    assert [path.name for path in summary.subjects] == ["subject-a.vtk", "subject-b.vtk"]


def test_input_preflight_requires_subjects(tmp_path: Path, valid_config: dict) -> None:
    mesh_dir = tmp_path / "meshes"
    mesh_dir.mkdir()
    (mesh_dir / "template.vtk").write_text("template", encoding="utf-8")
    config_path = write_config(tmp_path / "atlas.yaml", valid_config)

    with pytest.raises(ConfigurationError, match="No subject VTK files"):
        validate_input_paths(load_config(config_path), config_path)
