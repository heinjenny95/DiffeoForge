from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from diffeoforge.config import ConfigurationError
from diffeoforge.mesh import sha256_file
from diffeoforge.runs import prepare_run, run_status, verify_prepared_run


def write_tetrahedron(path: Path) -> Path:
    path.write_text(
        """# vtk DataFile Version 3.0
tetrahedron
ASCII
DATASET POLYDATA
POINTS 4 float
0 0 0
1 0 0
0 1 0
0 0 1
POLYGONS 4 16
3 0 2 1
3 0 1 3
3 1 2 3
3 2 0 3
""",
        encoding="ascii",
    )
    return path


def write_run_config(tmp_path: Path) -> Path:
    mesh_directory = tmp_path / "meshes"
    mesh_directory.mkdir()
    write_tetrahedron(mesh_directory / "template.vtk")
    write_tetrahedron(mesh_directory / "subject-a.vtk")
    write_tetrahedron(mesh_directory / "subject-b.vtk")
    config = {
        "schema_version": "0.1",
        "project": {"name": "immutable-test"},
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
                "timepoints": 5,
                "initial_control_point_spacing": 0.1,
                "use_rk2": False,
            },
            "noise_std": 0.05,
        },
        "optimization": {
            "method": "gradient_ascent",
            "max_iterations": 2,
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
            "threads": 2,
            "processes": 1,
            "precision": "float32",
            "random_seed": 20260715,
            "kernel_backend": "keops",
            "verbosity": "INFO",
            "launcher": {"type": "native", "executable": "deformetrica"},
        },
        "output": {"directory": "./runs", "retain_flow_meshes": True},
    }
    config_path = tmp_path / "atlas.yaml"
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return config_path


def test_prepare_creates_verifiable_immutable_run(tmp_path: Path) -> None:
    config_path = write_run_config(tmp_path)

    run_directory = prepare_run(config_path, run_id="fixed-run")
    manifest = verify_prepared_run(run_directory)

    assert run_directory == tmp_path / "runs" / "fixed-run"
    assert manifest["input_count"] == {"templates": 1, "subjects": 2}
    assert (run_directory / "engine" / "model.xml").is_file()
    assert (run_directory / "engine" / "data_set.xml").is_file()
    assert (run_directory / "engine" / "optimization_parameters.xml").is_file()
    assert not any((run_directory / "output").iterdir())
    model_xml = (run_directory / "engine" / "model.xml").read_text(encoding="utf-8")
    optimization_xml = (
        run_directory / "engine" / "optimization_parameters.xml"
    ).read_text(encoding="utf-8")
    assert "<initial-cp-spacing>0.1</initial-cp-spacing>" in model_xml
    assert "<dtype>float32</dtype>" in model_xml
    assert "<convergence-tolerance>0.0001</convergence-tolerance>" in optimization_xml
    assert "<max-line-search-iterations>10</max-line-search-iterations>" in optimization_xml
    assert "<state-file>" not in optimization_xml
    assert manifest["backend"]["engine_constants"] == {
        "line_search_expand": 1.5,
        "line_search_shrink": 0.5,
        "state_file": "output/deformetrica-state.p",
    }
    expected_manifest_hash = (run_directory / "manifest.sha256").read_text().split()[0]
    assert sha256_file(run_directory / "manifest.json") == expected_manifest_hash
    assert run_status(run_directory)["status"] == "prepared"


def test_prepare_refuses_to_overwrite_existing_run(tmp_path: Path) -> None:
    config_path = write_run_config(tmp_path)
    prepare_run(config_path, run_id="fixed-run")

    with pytest.raises(ConfigurationError, match="already exists"):
        prepare_run(config_path, run_id="fixed-run")


def test_tampered_staged_input_is_detected_before_execution(tmp_path: Path) -> None:
    run_directory = prepare_run(write_run_config(tmp_path), run_id="fixed-run")
    manifest = json.loads((run_directory / "manifest.json").read_text(encoding="utf-8"))
    subject = next(item for item in manifest["inputs"] if item["role"] == "subject")
    staged = run_directory.joinpath(*Path(subject["staged_path"]).parts)
    staged.write_bytes(staged.read_bytes() + b"tampered")

    with pytest.raises(ConfigurationError, match="checksum mismatch"):
        verify_prepared_run(run_directory)


def test_manifest_schema_is_checked_even_with_updated_checksum(tmp_path: Path) -> None:
    run_directory = prepare_run(write_run_config(tmp_path), run_id="fixed-run")
    manifest_path = run_directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    del manifest["backend"]["engine_constants"]
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (run_directory / "manifest.sha256").write_text(
        f"{sha256_file(manifest_path)}  manifest.json\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match="manifest schema validation failed"):
        run_status(run_directory)


def test_manifest_optional_constant_is_backward_compatible(tmp_path: Path) -> None:
    run_directory = prepare_run(write_run_config(tmp_path), run_id="fixed-run")
    manifest_path = run_directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    del manifest["backend"]["engine_constants"]["state_file"]
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (run_directory / "manifest.sha256").write_text(
        f"{sha256_file(manifest_path)}  manifest.json\n",
        encoding="utf-8",
    )

    assert run_status(run_directory)["status"] == "prepared"
