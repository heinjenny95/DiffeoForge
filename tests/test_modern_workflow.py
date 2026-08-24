from __future__ import annotations

import copy
import csv
import json
from itertools import pairwise
from pathlib import Path

import pytest
import yaml

np = pytest.importorskip("numpy")
torch = pytest.importorskip("torch")
workflow = pytest.importorskip("diffeoforge.modern_workflow")

from diffeoforge.cli import main  # noqa: E402
from diffeoforge.config import ConfigurationError  # noqa: E402
from diffeoforge.mesh import read_vtk_polydata, sha256_file, write_vtk_polydata  # noqa: E402
from diffeoforge.private_runs import (  # noqa: E402
    LEASE_NAME,
    MARKER_NAME,
    acquire_private_run_lease,
)

ROOT = Path(__file__).parents[1]
MESH_DIRECTORY = ROOT / "examples" / "synthetic" / "meshes"
FIXED_TIME = "2026-07-16T12:00:00+00:00"


def _configuration(*, output: str = "unused-run", landmarks: str | None = None) -> dict:
    return {
        "schema_version": "0.1",
        "project": {"name": "workflow-test"},
        "input": {
            "directory": str(MESH_DIRECTORY),
            "subject_pattern": "subject-*.vtk",
            "template": str(MESH_DIRECTORY / "template.vtk"),
            "units": "unitless",
        },
        "preprocessing": {
            "procrustes": {
                "enabled": landmarks is not None,
                "landmarks_file": landmarks,
                "scale_to_unit_centroid_size": True,
                "allow_reflection": False,
                "tolerance": 1e-10,
                "max_iterations": 100,
            }
        },
        "quality_control": {
            "require_no_duplicate_faces": True,
            "require_no_isolated_vertices": True,
            "require_edge_manifold": True,
            "require_consistent_orientation": True,
            "require_single_component": False,
            "require_closed_surface": False,
            "reject_zero_area_faces": True,
            "minimum_triangle_angle_degrees": None,
            "maximum_triangle_edge_ratio": None,
            "minimum_face_area_ratio": None,
            "maximum_face_area_ratio": None,
        },
        "initialization": {
            "control_points": {
                "method": "farthest_template_vertices",
                "count": 9,
            },
            "momenta": "zeros",
        },
        "model": {
            "attachment": {"type": "current", "kernel_width": 0.45},
            "deformation": {
                "kernel_width": 0.6,
                "timepoints": 5,
                "shooting_integrator": "rk2",
                "flow_integrator": "deformetrica_heun",
            },
            "noise_variance": 0.01,
        },
        "optimization": {
            "max_cycles": 1,
            "block_order": ["momenta", "template", "control_points"],
            "momenta_step_size": 0.01,
            "template_step_size": 0.001,
            "control_points_step_size": 0.001,
            "backtracking_factor": 0.5,
            "armijo_constant": 0.0001,
            "gradient_tolerance": 1e-8,
            "minimum_step_size": 1e-12,
            "max_line_search_iterations": 20,
        },
        "analysis": {
            "pca_components": None,
            "deformation_standard_deviations": 2.0,
            "deformation_components": 3,
        },
        "runtime": {
            "device": "cpu",
            "precision": "float64",
            "threads": 1,
            "random_seed": 20260715,
            "pairwise_evaluation": {
                "mode": "dense",
                "query_tile_size": None,
                "source_tile_size": None,
            },
        },
        "output": {"directory": output},
    }


def _write_config(path: Path, **kwargs) -> Path:
    path.write_text(yaml.safe_dump(_configuration(**kwargs), sort_keys=False), encoding="utf-8")
    return path


def _payload_bytes(directory: Path) -> dict[str, bytes]:
    return {
        path.relative_to(directory).as_posix(): path.read_bytes()
        for path in directory.rglob("*")
        if path.is_file()
    }


def _write_landmarks(path: Path, *, reverse_one_subject: bool = False) -> Path:
    meshes = [MESH_DIRECTORY / "template.vtk", *sorted(MESH_DIRECTORY.glob("subject-*.vtk"))]
    indices = (0, 40, 80)
    labels = ("anterior", "dorsal", "posterior")
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(workflow.LANDMARK_COLUMNS)
        for mesh_index, mesh in enumerate(meshes):
            points = read_vtk_polydata(mesh).vertices
            rows = list(zip(labels, indices, strict=True))
            if reverse_one_subject and mesh_index == 2:
                rows.reverse()
            for label, point_index in rows:
                writer.writerow((mesh.name, label, *points[point_index]))
    return path


def test_example_configuration_is_valid_and_public_schema_is_packaged() -> None:
    loaded = workflow.load_modern_workflow_config(ROOT / "examples/minimal-modern-atlas.yaml")

    assert loaded["runtime"] == {
        "device": "cpu",
        "precision": "float64",
        "threads": 1,
        "random_seed": 20260715,
        "pairwise_evaluation": {
            "mode": "dense",
            "query_tile_size": None,
            "source_tile_size": None,
        },
    }
    assert loaded["analysis"] == {
        "pca_components": None,
        "deformation_standard_deviations": 2.0,
        "deformation_components": 3,
    }
    schema = workflow._schema("modern-workflow-config-v0.1.json")
    assert schema["title"] == "DiffeoForge modern workflow configuration"


def test_legacy_config_without_pairwise_record_remains_dense_and_valid() -> None:
    legacy = _configuration()
    del legacy["runtime"]["pairwise_evaluation"]

    workflow.validate_modern_workflow_config(legacy)
    plan = workflow.pairwise_evaluation_from_config(legacy)

    assert plan.mode == "dense"
    assert plan.as_manifest() == {
        "mode": "dense",
        "query_tile_size": None,
        "source_tile_size": None,
    }


def test_config_v02_requires_explicit_pairwise_record() -> None:
    invalid = _configuration()
    invalid["schema_version"] = "0.2"
    del invalid["runtime"]["pairwise_evaluation"]

    with pytest.raises(ConfigurationError, match="pairwise_evaluation"):
        workflow.validate_modern_workflow_config(invalid)


def test_config_v04_requires_declared_step_strategy_and_versions_file_momenta() -> None:
    current = _configuration()
    current["schema_version"] = "0.4"
    with pytest.raises(ConfigurationError, match="step_initialization"):
        workflow.validate_modern_workflow_config(current)

    current["optimization"]["step_initialization"] = "previous_accepted"
    current["initialization"]["momenta"] = {
        "method": "file",
        "path": "momenta.csv",
    }
    workflow.validate_modern_workflow_config(current)

    current["schema_version"] = "0.3"
    with pytest.raises(ConfigurationError, match="momenta"):
        workflow.validate_modern_workflow_config(current)


def test_legacy_dense_manifest_without_pairwise_record_remains_verifiable() -> None:
    legacy = _configuration()
    del legacy["runtime"]["pairwise_evaluation"]
    manifest = {"engine": {"id": "diffeoforge_modern_dense"}}

    workflow._verify_pairwise_provenance(manifest, legacy)

    current = _configuration()
    current["schema_version"] = "0.2"
    with pytest.raises(workflow.ModernWorkflowError, match="provenance"):
        workflow._verify_pairwise_provenance(manifest, current)


@pytest.mark.parametrize(
    "pairwise",
    [
        {"mode": "dense", "query_tile_size": 32, "source_tile_size": None},
        {"mode": "blockwise", "query_tile_size": None, "source_tile_size": 32},
        {"mode": "blockwise", "query_tile_size": 0, "source_tile_size": 32},
        {"mode": "automatic", "query_tile_size": None, "source_tile_size": None},
    ],
)
def test_schema_rejects_incoherent_pairwise_execution_before_work(
    pairwise: dict,
) -> None:
    invalid = _configuration()
    invalid["runtime"]["pairwise_evaluation"] = pairwise

    with pytest.raises(ConfigurationError, match="pairwise_evaluation"):
        workflow.validate_modern_workflow_config(invalid)


def test_lbfgs_accepts_multiblock_configuration_and_requires_wolfe_coherence() -> None:
    invalid = _configuration()
    invalid["optimization"].update(
        {
            "direction_update": "lbfgs",
            "lbfgs_history_size": 5,
            "lbfgs_curvature_tolerance": 1e-12,
            "lbfgs_initial_step_size": 1.0,
        }
    )
    workflow.validate_modern_workflow_config(invalid)

    invalid["optimization"]["direction_update"] = "steepest"
    invalid["optimization"]["line_search_condition"] = "strong_wolfe"
    with pytest.raises(ConfigurationError, match="requires.*direction_update=lbfgs"):
        workflow.validate_modern_workflow_config(invalid)

    invalid["optimization"]["direction_update"] = "lbfgs"
    invalid["optimization"]["strong_wolfe_maximum_step_size"] = 0.5
    with pytest.raises(ConfigurationError, match="maximum_step_size"):
        workflow.validate_modern_workflow_config(invalid)

    invalid = _configuration()
    invalid["optimization"]["block_order"] = ["template"]
    invalid["optimization"]["momenta_updates_per_cycle"] = 2
    with pytest.raises(ConfigurationError, match="momenta_updates_per_cycle"):
        workflow.validate_modern_workflow_config(invalid)

    invalid = _configuration()
    invalid["optimization"]["subject_batch_workers"] = 2
    with pytest.raises(ConfigurationError, match="subject_batch_size"):
        workflow.validate_modern_workflow_config(invalid)

    invalid = _configuration()
    invalid["optimization"]["subject_batch_size"] = 1
    invalid["optimization"]["subject_batch_workers"] = 65
    with pytest.raises(ConfigurationError, match="subject_batch_workers"):
        workflow.validate_modern_workflow_config(invalid)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("checkpoint_interval_cycles", 0),
        ("checkpoint_interval_cycles", 1.5),
        ("checkpoint_retention", "automatic"),
    ],
)
def test_checkpoint_policy_rejects_implicit_or_invalid_values(
    name: str,
    value: object,
) -> None:
    invalid = _configuration()
    invalid["optimization"][name] = value

    with pytest.raises(ConfigurationError, match=name):
        workflow.validate_modern_workflow_config(invalid)


def test_farthest_template_initialization_is_repeatable_and_explicit() -> None:
    vertices = np.array(read_vtk_polydata(MESH_DIRECTORY / "template.vtk").vertices)

    first = workflow.farthest_template_vertex_indices(vertices, 9)
    second = workflow.farthest_template_vertex_indices(vertices.copy(), 9)

    assert first == second
    assert len(first) == len(set(first)) == 9
    with pytest.raises(ValueError, match="exceeds"):
        workflow.farthest_template_vertex_indices(vertices, vertices.shape[0] + 1)


def test_generated_checkpoint_policy_retains_only_the_latest_recovery_point(
    tmp_path: Path,
) -> None:
    config_path = workflow.initialize_modern_workflow(
        MESH_DIRECTORY,
        units="unitless",
        config_path=tmp_path / "bounded-checkpoints.yaml",
        template=MESH_DIRECTORY / "template.vtk",
        subject_pattern="subject-*.vtk",
        attachment_kernel_width=0.45,
        deformation_kernel_width=0.6,
        noise_variance=0.01,
        max_cycles=6,
        threads=1,
    )
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["optimization"]["block_order"] = ["momenta"]
    config["optimization"]["gradient_tolerance"] = 0.0
    config_path.write_text(
        yaml.safe_dump(config, sort_keys=False),
        encoding="utf-8",
        newline="\n",
    )

    run = workflow.run_modern_workflow(
        config_path,
        destination=tmp_path / "bounded-checkpoints-run",
        created_at=FIXED_TIME,
    )
    manifest = workflow.verify_modern_workflow(run)
    bundle = workflow.verify_modern_atlas_bundle(run / manifest["result_bundle"]["path"])
    completed_cycles = bundle["optimizer"]["cycles_completed"]

    assert completed_cycles == 6
    assert manifest["optimizer_checkpoint_policy"] == {
        "interval_cycles": 5,
        "retention": "latest",
    }
    assert [record["cycle"] for record in manifest["optimizer_checkpoints"]] == [6]
    assert [path.name for path in (run / "checkpoints").iterdir()] == ["cycle-000006"]


def test_external_control_points_and_momenta_only_are_verified(tmp_path: Path) -> None:
    control_path = tmp_path / "reference-control-points.txt"
    vertices = read_vtk_polydata(MESH_DIRECTORY / "template.vtk").vertices
    control_path.write_text(
        "".join(" ".join(format(value, ".17g") for value in row) + "\n" for row in vertices[:9]),
        encoding="utf-8",
    )
    config_value = _configuration(output=str(tmp_path / "unused"))
    config_value["schema_version"] = "0.3"
    config_value["initialization"]["control_points"] = {
        "method": "file",
        "count": 9,
        "path": control_path.name,
    }
    config_value["optimization"]["block_order"] = ["momenta"]
    config_value["runtime"]["pairwise_evaluation"] = {
        "mode": "blockwise",
        "query_tile_size": 32,
        "source_tile_size": 32,
        "autograd_strategy": "recompute",
    }
    config = tmp_path / "fixed-reference.yaml"
    config.write_text(yaml.safe_dump(config_value, sort_keys=False), encoding="utf-8")

    progress = []
    run = workflow.run_modern_workflow(
        config,
        destination=tmp_path / "fixed-reference-run",
        created_at=FIXED_TIME,
        progress_callback=progress.append,
    )
    manifest = workflow.verify_modern_workflow(run)

    assert manifest["engine"]["id"] == "diffeoforge_modern_blockwise_recompute"
    assert manifest["initialization"]["control_points"] == {
        "method": "file",
        "count": 9,
        "source_sha256": sha256_file(control_path),
        "copied_path": "input/initialization/control-points.txt",
    }
    effective = json.loads((run / "config" / "effective-config.json").read_text())
    assert effective["optimization"]["block_order"] == ["momenta"]
    optimizer_progress = [event.optimizer for event in progress if event.optimizer is not None]
    assert [item.completed_decisions for item in optimizer_progress] == [0, 1]
    assert {item.maximum_decisions for item in optimizer_progress} == {1}
    assert [record["cycle"] for record in manifest["optimizer_checkpoints"]] == [1]
    checkpoint_path = run / manifest["optimizer_checkpoints"][0]["path"]
    checkpoint = workflow.verify_modern_cycle_checkpoint(
        checkpoint_path,
        workflow_root=run,
    )
    assert checkpoint["record"]["objective"] == pytest.approx(
        workflow.verify_modern_atlas_bundle(run / manifest["result_bundle"]["path"])[
            "optimizer"
        ]["final_objective"]
    )

    first_bundle = run / manifest["result_bundle"]["path"]
    first_bundle_manifest = json.loads(
        (first_bundle / "bundle-manifest.json").read_text(encoding="utf-8")
    )
    initial_momenta = first_bundle / first_bundle_manifest["parameters"]["momenta_path"]
    continuation_value = copy.deepcopy(config_value)
    continuation_value["schema_version"] = "0.4"
    continuation_value["initialization"]["momenta"] = {
        "method": "file",
        "path": str(initial_momenta),
    }
    continuation_value["optimization"]["max_cycles"] = 1
    continuation_value["optimization"]["gradient_tolerance"] = 1e100
    continuation_value["optimization"]["step_initialization"] = "previous_accepted"
    continuation_config = tmp_path / "continuation.yaml"
    continuation_config.write_text(
        yaml.safe_dump(continuation_value, sort_keys=False), encoding="utf-8"
    )

    continuation = workflow.run_modern_workflow(
        continuation_config,
        destination=tmp_path / "continuation-run",
        created_at=FIXED_TIME,
    )
    continuation_manifest = workflow.verify_modern_workflow(continuation)
    observed_initialization = continuation_manifest["initialization"]["momenta"]
    assert observed_initialization == {
        "method": "file",
        "source_sha256": sha256_file(initial_momenta),
        "copied_path": "input/initialization/momenta.csv",
        "subjects": 5,
        "control_points": 9,
        "dimensions": 3,
    }
    continuation_bundle = continuation / continuation_manifest["result_bundle"]["path"]
    continuation_bundle_manifest = json.loads(
        (continuation_bundle / "bundle-manifest.json").read_text(encoding="utf-8")
    )
    assert continuation_bundle_manifest["optimizer"]["settings"][
        "step_initialization"
    ] == "previous_accepted"
    assert continuation_bundle_manifest["optimizer"]["final_objective"] == pytest.approx(
        first_bundle_manifest["optimizer"]["final_objective"], rel=1e-12, abs=1e-12
    )


def test_lbfgs_momenta_workflow_is_explicit_repeatable_and_verified(tmp_path: Path) -> None:
    config_value = _configuration(output=str(tmp_path / "unused"))
    config_value["optimization"].update(
        {
            "max_cycles": 4,
            "block_order": ["momenta"],
            "direction_update": "lbfgs",
            "lbfgs_history_size": 3,
            "lbfgs_curvature_tolerance": 1e-12,
            "lbfgs_initial_step_size": 1.0,
            "step_initialization": "previous_accepted",
            "relative_objective_tolerance": 0.5,
        }
    )
    config = tmp_path / "lbfgs.yaml"
    config.write_text(yaml.safe_dump(config_value, sort_keys=False), encoding="utf-8")

    first = workflow.run_modern_workflow(
        config,
        destination=tmp_path / "lbfgs-first",
        created_at=FIXED_TIME,
    )
    second = workflow.run_modern_workflow(
        config,
        destination=tmp_path / "lbfgs-second",
        created_at=FIXED_TIME,
    )
    first_manifest = workflow.verify_modern_workflow(first)
    second_manifest = workflow.verify_modern_workflow(second)
    first_bundle = workflow.verify_modern_atlas_bundle(
        first / first_manifest["result_bundle"]["path"]
    )
    second_bundle = workflow.verify_modern_atlas_bundle(
        second / second_manifest["result_bundle"]["path"]
    )

    assert first_bundle["optimizer"]["settings"]["direction_update"] == "lbfgs"
    assert first_bundle["optimizer"]["settings"]["lbfgs_history_size"] == 3
    assert first_bundle["optimizer"]["settings"]["lbfgs_initial_step_size"] == 1.0
    assert first_bundle["optimizer"]["settings"]["relative_objective_tolerance"] == 0.5
    assert first_bundle["optimizer"]["termination_reason"] == "relative_objective_tolerance"
    assert first_bundle["optimizer"]["converged"] is True
    assert first_bundle["optimizer"]["final_objective"] == second_bundle["optimizer"][
        "final_objective"
    ]
    assert first_bundle["optimizer"]["final_regularity"] == second_bundle["optimizer"][
        "final_regularity"
    ]


def test_multiblock_lbfgs_workflow_writes_exact_v03_checkpoint(tmp_path: Path) -> None:
    config_value = _configuration(output=str(tmp_path / "unused"))
    config_value["optimization"].update(
        {
            "max_cycles": 3,
            "momenta_updates_per_cycle": 2,
            "direction_update": "lbfgs",
            "lbfgs_history_size": 3,
            "lbfgs_curvature_tolerance": 1e-12,
            "lbfgs_initial_step_size": 1.0,
            "step_initialization": "previous_accepted",
            "gradient_tolerance": 0.0,
            "checkpoint_interval_cycles": 1,
            "checkpoint_retention": "latest",
        }
    )
    config = tmp_path / "multiblock-lbfgs.yaml"
    config.write_text(yaml.safe_dump(config_value, sort_keys=False), encoding="utf-8")

    progress = []
    run = workflow.run_modern_workflow(
        config,
        destination=tmp_path / "multiblock-lbfgs-run",
        created_at=FIXED_TIME,
        progress_callback=progress.append,
    )
    manifest = workflow.verify_modern_workflow(run)
    bundle = workflow.verify_modern_atlas_bundle(
        run / manifest["result_bundle"]["path"]
    )
    checkpoint_path = run / manifest["optimizer_checkpoints"][0]["path"]
    checkpoint = workflow.verify_modern_cycle_checkpoint(
        checkpoint_path,
        workflow_root=run,
    )
    resume_state = workflow.load_modern_checkpoint_resume_state(checkpoint_path)

    assert bundle["optimizer"]["settings"]["block_order"] == [
        "momenta",
        "template",
        "control_points",
    ]
    assert bundle["optimizer"]["settings"]["direction_update"] == "lbfgs"
    assert bundle["optimizer"]["settings"]["momenta_updates_per_cycle"] == 2
    assert checkpoint["checkpoint_version"] == "0.3"
    assert checkpoint["binding"]["engine_implementation"] == "1.4"
    assert checkpoint["binding"]["momenta_updates_per_cycle"] == 2
    assert checkpoint["binding"]["subject_batch_size"] is None
    assert checkpoint["binding"]["subject_batch_workers"] == 1
    assert set(resume_state.lbfgs_histories) == {
        "momenta",
        "template",
        "control_points",
    }
    assert all(resume_state.lbfgs_histories.values())
    bundle_root = run / manifest["result_bundle"]["path"]
    with (bundle_root / bundle["optimizer"]["history_path"]).open(
        encoding="utf-8", newline=""
    ) as handle:
        history = list(csv.DictReader(handle))
    assert [record["block"] for record in history[1:]] == [
        "momenta",
        "momenta",
        "template",
        "control_points",
    ] * 3
    optimizer_progress = [event.optimizer for event in progress if event.optimizer is not None]
    assert [item.completed_decisions for item in optimizer_progress] == list(range(13))
    assert {item.maximum_decisions for item in optimizer_progress} == {12}


def test_subject_batched_workflow_is_explicit_and_numerically_matches_full_cohort(
    tmp_path: Path,
) -> None:
    full_value = _configuration(output=str(tmp_path / "unused-full"))
    full_config = tmp_path / "full.yaml"
    full_config.write_text(yaml.safe_dump(full_value, sort_keys=False), encoding="utf-8")
    serial_batched_value = copy.deepcopy(full_value)
    serial_batched_value["optimization"]["subject_batch_size"] = 2
    serial_batched_config = tmp_path / "serial-batched.yaml"
    serial_batched_config.write_text(
        yaml.safe_dump(serial_batched_value, sort_keys=False),
        encoding="utf-8",
    )
    batched_value = copy.deepcopy(serial_batched_value)
    batched_value["optimization"]["subject_batch_workers"] = 2
    batched_config = tmp_path / "batched.yaml"
    batched_config.write_text(
        yaml.safe_dump(batched_value, sort_keys=False),
        encoding="utf-8",
    )

    full_run = workflow.run_modern_workflow(
        full_config,
        destination=tmp_path / "full-run",
        created_at=FIXED_TIME,
    )
    serial_batched_run = workflow.run_modern_workflow(
        serial_batched_config,
        destination=tmp_path / "serial-batched-run",
        created_at=FIXED_TIME,
    )
    batched_run = workflow.run_modern_workflow(
        batched_config,
        destination=tmp_path / "batched-run",
        created_at=FIXED_TIME,
    )
    full_manifest = workflow.verify_modern_workflow(full_run)
    serial_batched_manifest = workflow.verify_modern_workflow(serial_batched_run)
    batched_manifest = workflow.verify_modern_workflow(batched_run)
    full_bundle = workflow.verify_modern_atlas_bundle(
        full_run / full_manifest["result_bundle"]["path"]
    )
    serial_batched_bundle = workflow.verify_modern_atlas_bundle(
        serial_batched_run / serial_batched_manifest["result_bundle"]["path"]
    )
    batched_bundle = workflow.verify_modern_atlas_bundle(
        batched_run / batched_manifest["result_bundle"]["path"]
    )

    assert batched_bundle["optimizer"]["settings"]["subject_batch_size"] == 2
    assert batched_bundle["optimizer"]["settings"]["subject_batch_workers"] == 2
    assert serial_batched_bundle["optimizer"]["settings"]["subject_batch_workers"] == 1
    assert full_bundle["optimizer"]["settings"]["subject_batch_size"] is None
    assert full_bundle["optimizer"]["settings"]["subject_batch_workers"] == 1
    assert batched_bundle["optimizer"]["settings"]["shared_step_scaling"] == "none"
    for field in ("final_objective", "final_attachment", "final_regularity"):
        assert batched_bundle["optimizer"][field] == serial_batched_bundle["optimizer"][field]
        assert serial_batched_bundle["optimizer"][field] == pytest.approx(
            full_bundle["optimizer"][field],
            rel=1e-12,
            abs=1e-12,
        )
    assert sha256_file(
        batched_run
        / batched_manifest["result_bundle"]["path"]
        / batched_bundle["optimizer"]["history_path"]
    ) == sha256_file(
        serial_batched_run
        / serial_batched_manifest["result_bundle"]["path"]
        / serial_batched_bundle["optimizer"]["history_path"]
    )


def test_strong_wolfe_workflow_records_and_verifies_line_search(tmp_path: Path) -> None:
    config_value = _configuration(output=str(tmp_path / "unused"))
    config_value["optimization"].update(
        {
            "max_cycles": 3,
            "block_order": ["momenta"],
            "direction_update": "lbfgs",
            "lbfgs_history_size": 3,
            "lbfgs_curvature_tolerance": 1e-12,
            "lbfgs_initial_step_size": 1.0,
            "line_search_condition": "strong_wolfe",
            "strong_wolfe_curvature_constant": 0.9,
            "strong_wolfe_maximum_step_size": 10.0,
            "step_initialization": "previous_accepted",
        }
    )
    config = tmp_path / "strong-wolfe.yaml"
    config.write_text(yaml.safe_dump(config_value, sort_keys=False), encoding="utf-8")

    destination = workflow.run_modern_workflow(
        config,
        destination=tmp_path / "strong-wolfe-run",
        created_at=FIXED_TIME,
    )
    manifest = workflow.verify_modern_workflow(destination)
    bundle = workflow.verify_modern_atlas_bundle(destination / manifest["result_bundle"]["path"])

    settings = bundle["optimizer"]["settings"]
    assert settings["line_search_condition"] == "strong_wolfe"
    assert settings["strong_wolfe_curvature_constant"] == 0.9
    assert settings["strong_wolfe_maximum_step_size"] == 10.0
    history_path = (
        destination
        / manifest["result_bundle"]["path"]
        / bundle["optimizer"]["history_path"]
    )
    with history_path.open("r", encoding="utf-8", newline="") as handle:
        objectives = [float(record["objective"]) for record in csv.DictReader(handle)]
    assert all(later >= earlier for earlier, later in pairwise(objectives))


def test_strong_wolfe_failure_stops_before_bundle_publication(tmp_path: Path) -> None:
    config_value = _configuration(output=str(tmp_path / "unused"))
    config_value["optimization"].update(
        {
            "max_cycles": 1,
            "block_order": ["momenta"],
            "direction_update": "lbfgs",
            "line_search_condition": "strong_wolfe",
            "strong_wolfe_curvature_constant": 0.5,
            "strong_wolfe_maximum_step_size": 10.0,
        }
    )
    config = tmp_path / "strong-wolfe-failure.yaml"
    config.write_text(yaml.safe_dump(config_value, sort_keys=False), encoding="utf-8")

    with pytest.raises(workflow.ModernWorkflowError, match="line search could not accept"):
        workflow.run_modern_workflow(
            config,
            destination=tmp_path / "strong-wolfe-failure-run",
            created_at=FIXED_TIME,
        )
    assert not (tmp_path / "strong-wolfe-failure-run").exists()


def test_momenta_initialization_rejects_changed_subject_order(tmp_path: Path) -> None:
    labels = ("subject-a.vtk", "subject-b.vtk")
    path = tmp_path / "momenta.csv"
    rows = [["subject_label", "control_point", "x", "y", "z"]]
    for label in reversed(labels):
        rows.extend([[label, str(index), "0", "0", "0"] for index in range(2)])
    with path.open("w", encoding="utf-8", newline="") as handle:
        csv.writer(handle, lineterminator="\n").writerows(rows)

    with pytest.raises(ConfigurationError, match="subject order"):
        workflow._read_momenta_rows(path, labels, 2)


def test_five_subject_workflow_is_verified_and_byte_repeatable(tmp_path: Path) -> None:
    config = _write_config(tmp_path / "workflow.yaml")
    progress = []
    first = workflow.run_modern_workflow(
        config,
        destination=tmp_path / "first",
        created_at=FIXED_TIME,
        progress_callback=progress.append,
    )
    second = workflow.run_modern_workflow(
        config,
        destination=tmp_path / "second",
        created_at=FIXED_TIME,
        cancel_requested=lambda: False,
    )

    first_manifest = workflow.verify_modern_workflow(first)
    second_manifest = workflow.verify_modern_workflow(second)
    assert first_manifest == second_manifest
    assert _payload_bytes(first) == _payload_bytes(second)
    assert [event.sequence for event in progress] == list(range(len(progress)))
    assert [(event.phase, event.status) for event in progress[:6]] == [
        ("workflow", "started"),
        ("inputs", "completed"),
        ("preprocessing", "completed"),
        ("quality", "completed"),
        ("initialization", "completed"),
        ("optimization", "started"),
    ]
    assert [(event.phase, event.status) for event in progress[-3:]] == [
        ("optimization", "completed"),
        ("bundle", "completed"),
        ("verification", "completed"),
    ]
    optimizer_progress = [event.optimizer for event in progress if event.optimizer is not None]
    assert [item.completed_decisions for item in optimizer_progress] == [0, 1, 2, 3]
    assert {item.maximum_decisions for item in optimizer_progress} == {3}
    assert all("eta" not in event.as_dict() for event in progress)
    assert progress[-1].completed_stages == 7
    assert len(first_manifest["input"]["subjects"]) == 5
    assert first_manifest["preprocessing"]["id"] == "none"
    assert first_manifest["initialization"]["control_points"]["count"] == 9
    assert first_manifest["quality"]["assessed_meshes"] == 12
    input_quality = json.loads(
        (first / first_manifest["quality"]["report_path"]).read_text(encoding="utf-8")
    )
    assert {record["stage"] for record in input_quality["meshes"]} == {
        "raw",
        "effective",
    }
    assert all(record["comparison_to_reference"] is None for record in input_quality["meshes"])
    assert first_manifest["result_bundle"]["bundle_version"] == "0.1"
    assert (
        first / first_manifest["result_bundle"]["path"] / "analysis" / "pca-scores.csv"
    ).is_file()
    bundle = first / first_manifest["result_bundle"]["path"]
    bundle_manifest = workflow.verify_modern_atlas_bundle(bundle)
    assert (bundle / bundle_manifest["pca"]["plots"]["scree_path"]).is_file()
    assert (bundle / bundle_manifest["pca"]["plots"]["scores_path"]).is_file()
    assert bundle_manifest["pca"]["deformations"]["standard_deviations"] == 2.0
    assert bundle_manifest["quality"]["assessed_meshes"] > len(
        first_manifest["input"]["subjects"]
    )
    for source, record in zip(
        sorted(MESH_DIRECTORY.glob("subject-*.vtk")),
        first_manifest["input"]["subjects"],
        strict=True,
    ):
        assert record["label"] == source.name
        assert record["sha256"] == sha256_file(source)


def _numeric_csv(path: Path, first_numeric_column: int) -> np.ndarray:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle))[1:]
    return np.array(
        [[float(value) for value in row[first_numeric_column:]] for row in rows],
        dtype=np.float64,
    )


def _bundle_vtk_paths(manifest: dict) -> list[str]:
    deformations = manifest["pca"]["deformations"]
    return [
        manifest["template"]["path"],
        *(record["reconstruction_path"] for record in manifest["subjects"]),
        deformations["mean_path"],
        *(
            path
            for component in deformations["components"]
            for path in (component["minus_path"], component["plus_path"])
        ),
    ]


def test_blockwise_full_workflow_and_artifacts_match_dense_with_distinct_provenance(
    tmp_path: Path,
) -> None:
    dense_config = _configuration(output="unused-dense")
    blockwise_config = copy.deepcopy(dense_config)
    blockwise_config["runtime"]["pairwise_evaluation"] = {
        "mode": "blockwise",
        "query_tile_size": 64,
        "source_tile_size": 64,
    }
    dense_path = tmp_path / "dense.yaml"
    blockwise_path = tmp_path / "blockwise.yaml"
    dense_path.write_text(yaml.safe_dump(dense_config, sort_keys=False), encoding="utf-8")
    blockwise_path.write_text(
        yaml.safe_dump(blockwise_config, sort_keys=False), encoding="utf-8"
    )

    dense_run = workflow.run_modern_workflow(
        dense_path,
        destination=tmp_path / "dense-run",
        created_at=FIXED_TIME,
    )
    blockwise_run = workflow.run_modern_workflow(
        blockwise_path,
        destination=tmp_path / "blockwise-run",
        created_at=FIXED_TIME,
    )
    dense_manifest = workflow.verify_modern_workflow(dense_run)
    blockwise_manifest = workflow.verify_modern_workflow(blockwise_run)

    assert dense_manifest["engine"]["id"] == "diffeoforge_modern_dense"
    assert dense_manifest["engine"]["implementation_version"] == (
        workflow.ENGINE_IMPLEMENTATION_VERSION
    )
    assert dense_manifest["engine"]["pairwise_evaluation"]["mode"] == "dense"
    assert blockwise_manifest["engine"]["id"] == "diffeoforge_modern_blockwise"
    assert blockwise_manifest["engine"]["pairwise_evaluation"] == {
        "mode": "blockwise",
        "query_tile_size": 64,
        "source_tile_size": 64,
    }

    dense_bundle = dense_run / dense_manifest["result_bundle"]["path"]
    blockwise_bundle = blockwise_run / blockwise_manifest["result_bundle"]["path"]
    dense_bundle_manifest = workflow.verify_modern_atlas_bundle(dense_bundle)
    blockwise_bundle_manifest = workflow.verify_modern_atlas_bundle(blockwise_bundle)
    assert dense_bundle_manifest["engine"]["pairwise_evaluation"]["mode"] == "dense"
    assert dense_bundle_manifest["engine"]["implementation_version"] == (
        dense_manifest["engine"]["implementation_version"]
    )
    assert blockwise_bundle_manifest["engine"]["pairwise_evaluation"] == {
        "mode": "blockwise",
        "query_tile_size": 64,
        "source_tile_size": 64,
    }

    for key, first_numeric_column in (
        ("control_points_path", 1),
        ("momenta_path", 2),
    ):
        np.testing.assert_allclose(
            _numeric_csv(
                blockwise_bundle / blockwise_bundle_manifest["parameters"][key],
                first_numeric_column,
            ),
            _numeric_csv(
                dense_bundle / dense_bundle_manifest["parameters"][key],
                first_numeric_column,
            ),
            rtol=2e-10,
            atol=2e-11,
        )

    assert _bundle_vtk_paths(blockwise_bundle_manifest) == _bundle_vtk_paths(
        dense_bundle_manifest
    )
    for relative in _bundle_vtk_paths(dense_bundle_manifest):
        dense_mesh = read_vtk_polydata(dense_bundle / relative)
        blockwise_mesh = read_vtk_polydata(blockwise_bundle / relative)
        assert np.array_equal(blockwise_mesh.triangles, dense_mesh.triangles)
        np.testing.assert_allclose(
            blockwise_mesh.vertices,
            dense_mesh.vertices,
            rtol=2e-10,
            atol=2e-11,
        )

    manifest_path = dense_run / workflow.MANIFEST_NAME
    forged = json.loads(manifest_path.read_text(encoding="utf-8"))
    forged["engine"]["id"] = "diffeoforge_modern_blockwise"
    forged["engine"]["pairwise_evaluation"] = {
        "mode": "blockwise",
        "query_tile_size": 64,
        "source_tile_size": 64,
    }
    manifest_path.write_text(
        json.dumps(forged, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (dense_run / workflow.MANIFEST_SIDECAR_NAME).write_text(
        f"{sha256_file(manifest_path)}  {workflow.MANIFEST_NAME}\n",
        encoding="ascii",
    )
    with pytest.raises(workflow.ModernWorkflowError, match="effective"):
        workflow.verify_modern_workflow(dense_run)


def test_optional_labelled_landmarks_align_complete_meshes_and_are_recorded(
    tmp_path: Path,
) -> None:
    landmarks = _write_landmarks(tmp_path / "landmarks.csv")
    config = _write_config(
        tmp_path / "workflow.yaml",
        landmarks=str(landmarks),
    )

    run = workflow.run_modern_workflow(
        config, destination=tmp_path / "aligned-run", created_at=FIXED_TIME
    )
    manifest = workflow.verify_modern_workflow(run)

    assert manifest["preprocessing"] == {
        "id": "generalized_procrustes",
        "landmarks_path": "input/landmarks.csv",
        "alignment_path": "preprocessing/procrustes.json",
        "converged": True,
        "termination_reason": "tolerance",
    }
    evidence = json.loads(
        (run / manifest["preprocessing"]["alignment_path"]).read_text(encoding="utf-8")
    )
    assert evidence["landmark_labels"] == ["anterior", "dorsal", "posterior"]
    assert len(evidence["specimens"]) == 6
    assert all(record["aligned_path"] is not None for record in evidence["specimens"])
    assert all(
        record["aligned_path"] is not None
        for record in [manifest["input"]["template"], *manifest["input"]["subjects"]]
    )


def test_inconsistent_landmark_order_fails_without_publishing(tmp_path: Path) -> None:
    landmarks = _write_landmarks(tmp_path / "landmarks.csv", reverse_one_subject=True)
    config = _write_config(tmp_path / "workflow.yaml", landmarks=str(landmarks))
    destination = tmp_path / "rejected"

    with pytest.raises(ConfigurationError, match="same row order"):
        workflow.run_modern_workflow(config, destination=destination)

    assert not destination.exists()
    assert not list(tmp_path.glob(".rejected.tmp-*"))


def test_modern_init_rejects_invalid_mesh_topology_before_writing_config(
    tmp_path: Path,
) -> None:
    mesh_directory = tmp_path / "meshes"
    mesh_directory.mkdir()
    vertices = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)]
    triangles = [(0, 2, 1), (0, 1, 3), (1, 2, 3), (2, 0, 3)]
    write_vtk_polydata(mesh_directory / "template.vtk", vertices, triangles)
    write_vtk_polydata(mesh_directory / "subject-01.vtk", vertices, triangles)
    write_vtk_polydata(
        mesh_directory / "subject-02.vtk",
        vertices,
        [*triangles, triangles[0]],
    )
    config = tmp_path / "modern.yaml"

    with pytest.raises(ConfigurationError, match="Mesh quality gate failed"):
        workflow.initialize_modern_workflow(
            mesh_directory,
            units="unitless",
            config_path=config,
            control_point_count=4,
        )

    assert not config.exists()


def test_bundle_failure_is_atomic_and_existing_destination_is_never_reused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _write_config(tmp_path / "workflow.yaml")
    destination = tmp_path / "failed"

    def fail(*_args, **_kwargs):
        raise RuntimeError("injected bundle failure")

    monkeypatch.setattr(workflow, "write_modern_atlas_bundle", fail)
    with pytest.raises(RuntimeError, match="injected"):
        workflow.run_modern_workflow(config, destination=destination)
    assert not destination.exists()
    assert not list(tmp_path.glob(".failed.tmp-*"))

    destination.mkdir()
    marker = destination / "keep.txt"
    marker.write_text("user data", encoding="utf-8")
    with pytest.raises(FileExistsError):
        workflow.run_modern_workflow(config, destination=destination)
    assert marker.read_text(encoding="utf-8") == "user data"


def test_existing_private_candidate_blocks_before_computation_and_is_preserved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _write_config(tmp_path / "workflow.yaml")
    destination = tmp_path / "blocked"
    private = tmp_path / f".{destination.name}.tmp-{'a' * 32}"
    private.mkdir()
    lease = acquire_private_run_lease(private, destination, operation="modern_workflow")
    marker_before = (private / MARKER_NAME).read_bytes()
    lease_size_before = (private / LEASE_NAME).stat().st_size
    called = False

    def should_not_compute(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("optimizer must not start")

    monkeypatch.setattr(workflow, "optimize_atlas", should_not_compute)
    try:
        with pytest.raises(workflow.ModernWorkflowError, match="active"):
            workflow.run_modern_workflow(config, destination=destination)
    finally:
        lease.close()

    assert called is False
    assert not destination.exists()
    assert (private / MARKER_NAME).read_bytes() == marker_before
    assert (private / LEASE_NAME).stat().st_size == lease_size_before


def test_final_outer_verification_failure_removes_temporary_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _write_config(tmp_path / "workflow.yaml")
    destination = tmp_path / "unpublished"

    def fail(_directory):
        raise workflow.ModernWorkflowError("injected final verification failure")

    monkeypatch.setattr(workflow, "verify_modern_workflow", fail)
    with pytest.raises(workflow.ModernWorkflowError, match="final verification"):
        workflow.run_modern_workflow(config, destination=destination)

    assert not destination.exists()
    assert not list(tmp_path.glob(".unpublished.tmp-*"))


def test_verifier_rejects_extra_or_tampered_files(tmp_path: Path) -> None:
    config = _write_config(tmp_path / "workflow.yaml")
    run = workflow.run_modern_workflow(config, destination=tmp_path / "run", created_at=FIXED_TIME)
    assert not (run / MARKER_NAME).exists()
    assert not (run / LEASE_NAME).exists()
    extra = run / "nested" / workflow.MANIFEST_NAME
    extra.parent.mkdir()
    extra.write_text("unexpected", encoding="utf-8")
    with pytest.raises(workflow.ModernWorkflowError, match="extra"):
        workflow.verify_modern_workflow(run)
    extra.unlink()

    raw = next((run / "input" / "raw").glob("subject-*.vtk"))
    raw.write_bytes(raw.read_bytes() + b"\n")
    with pytest.raises(workflow.ModernWorkflowError, match="size differs"):
        workflow.verify_modern_workflow(run)


def test_workflow_verifier_recomputes_input_mesh_quality(tmp_path: Path) -> None:
    config = _write_config(tmp_path / "workflow.yaml")
    run = workflow.run_modern_workflow(
        config,
        destination=tmp_path / "run",
        created_at=FIXED_TIME,
    )
    manifest_path = run / workflow.MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    quality_path = run / manifest["quality"]["report_path"]
    quality = json.loads(quality_path.read_text(encoding="utf-8"))
    quality["meshes"][0]["metrics"]["boundary_edges"] += 1
    quality_path.write_text(
        json.dumps(quality, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    artifact = next(
        record
        for record in manifest["artifacts"]
        if record["path"] == manifest["quality"]["report_path"]
    )
    artifact["bytes"] = quality_path.stat().st_size
    artifact["sha256"] = sha256_file(quality_path)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (run / workflow.MANIFEST_SIDECAR_NAME).write_text(
        f"{sha256_file(manifest_path)}  {workflow.MANIFEST_NAME}\n",
        encoding="ascii",
    )

    with pytest.raises(workflow.ModernWorkflowError, match="recomputed geometry"):
        workflow.verify_modern_workflow(run)


def test_artifact_resolver_rejects_traversal_and_windows_drive_paths(tmp_path: Path) -> None:
    with pytest.raises(workflow.ModernWorkflowError, match="Unsafe"):
        workflow._resolve_artifact(tmp_path, "../outside.txt")
    with pytest.raises(workflow.ModernWorkflowError, match="Unsafe"):
        workflow._resolve_artifact(tmp_path, "C:/outside.txt")


def test_modern_init_and_cli_run_form_a_public_folder_to_bundle_path(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = tmp_path / "modern.yaml"
    init_code = main(
        [
            "modern-init",
            str(MESH_DIRECTORY),
            "--units",
            "unitless",
            "--template",
            str(MESH_DIRECTORY / "template.vtk"),
            "--subject-pattern",
            "subject-*.vtk",
            "--config",
            str(config),
            "--output-directory",
            str(tmp_path / "cli-run"),
            "--control-points",
            "9",
            "--attachment-kernel-width",
            "0.45",
            "--deformation-kernel-width",
            "0.6",
            "--noise-variance",
            "0.01",
            "--max-cycles",
            "1",
            "--threads",
            "1",
        ]
    )
    init_output = capsys.readouterr()
    assert init_code == 0
    assert "configuration created" in init_output.out
    assert config.read_text(encoding="utf-8").startswith(workflow.CONFIG_MARKER)
    assert yaml.safe_load(config.read_text(encoding="utf-8"))["analysis"] == {
        "pca_components": None,
        "deformation_standard_deviations": 2.0,
        "deformation_components": 3,
    }
    assert yaml.safe_load(config.read_text(encoding="utf-8"))["runtime"][
        "pairwise_evaluation"
    ] == {
        "mode": "dense",
        "query_tile_size": None,
        "source_tile_size": None,
    }

    return_code = main(["modern-run", str(config)])
    captured = capsys.readouterr()

    assert return_code == 0
    assert "Modern workflow completed" in captured.out
    assert "Subject meshes: 5" in captured.out
    assert "PCA scree plot:" in captured.out
    assert "PCA scores plot:" in captured.out
    assert "PCA PC2 vs PC3 plot:" in captured.out
    assert "PCA deformation meshes:" in captured.out
    assert "Progress [7/7 stages] verification completed" in captured.out
    assert workflow.verify_modern_workflow(tmp_path / "cli-run")["project"]["name"]

    verify_code = main(["modern-verify", str(tmp_path / "cli-run")])
    verify_output = capsys.readouterr()
    assert verify_code == 0
    assert "Modern workflow verified" in verify_output.out
    assert "PCA scree plot:" in verify_output.out
    assert "PCA PC2 vs PC3 plot:" in verify_output.out


def test_modern_init_cli_generates_only_coherent_blockwise_plans(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = tmp_path / "blockwise.yaml"
    common = [
        "modern-init",
        str(MESH_DIRECTORY),
        "--units",
        "unitless",
        "--template",
        str(MESH_DIRECTORY / "template.vtk"),
        "--subject-pattern",
        "subject-*.vtk",
        "--control-points",
        "9",
    ]

    assert (
        main(
            [
                *common,
                "--config",
                str(config),
                "--pairwise-mode",
                "blockwise",
                "--query-tile-size",
                "32",
                "--source-tile-size",
                "64",
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert yaml.safe_load(config.read_text(encoding="utf-8"))["runtime"][
        "pairwise_evaluation"
    ] == {
        "mode": "blockwise",
        "query_tile_size": 32,
        "source_tile_size": 64,
    }

    invalid = tmp_path / "invalid.yaml"
    assert (
        main(
            [
                *common,
                "--config",
                str(invalid),
                "--pairwise-mode",
                "dense",
                "--query-tile-size",
                "32",
            ]
        )
        == 2
    )
    captured = capsys.readouterr()
    assert "dense mode requires null" in captured.err
    assert not invalid.exists()


def test_schema_requires_landmarks_exactly_when_procrustes_is_enabled() -> None:
    invalid = _configuration()
    invalid["preprocessing"]["procrustes"]["enabled"] = True

    with pytest.raises(ConfigurationError, match="landmarks_file"):
        workflow.validate_modern_workflow_config(invalid)


def test_pca_dimensions_are_rejected_before_optimizer_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invalid = _configuration()
    invalid["analysis"]["pca_components"] = 5
    invalid["analysis"]["deformation_components"] = 5
    config = tmp_path / "invalid-pca.yaml"
    config.write_text(yaml.safe_dump(invalid, sort_keys=False), encoding="utf-8")

    def fail(*_args, **_kwargs):
        raise AssertionError("optimizer must not start")

    monkeypatch.setattr(workflow, "optimize_atlas", fail)
    with pytest.raises(ConfigurationError, match="pca_components cannot exceed 4"):
        workflow.run_modern_workflow(config, destination=tmp_path / "rejected")

    assert not (tmp_path / "rejected").exists()


def test_progress_callback_failure_preserves_atomic_nonpublication(tmp_path: Path) -> None:
    config = _write_config(tmp_path / "workflow.yaml")
    destination = tmp_path / "unpublished"

    def fail_on_quality(event) -> None:
        if event.phase == "quality":
            raise RuntimeError("observer failed")

    with pytest.raises(RuntimeError, match="observer failed"):
        workflow.run_modern_workflow(
            config,
            destination=destination,
            progress_callback=fail_on_quality,
        )

    assert not destination.exists()
    assert not tuple(tmp_path.glob(".unpublished.tmp-*"))


def test_cooperative_cancellation_removes_private_work_and_publishes_nothing(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path / "workflow.yaml")
    destination = tmp_path / "cancelled"
    cancellation = {"requested": False}
    progress = []

    def observe(event) -> None:
        progress.append(event)
        if event.phase == "quality":
            cancellation["requested"] = True

    with pytest.raises(workflow.ModernWorkflowCancelled, match="cancellation requested"):
        workflow.run_modern_workflow(
            config,
            destination=destination,
            progress_callback=observe,
            cancel_requested=lambda: cancellation["requested"],
        )

    assert [(event.phase, event.status) for event in progress] == [
        ("workflow", "started"),
        ("inputs", "completed"),
        ("preprocessing", "completed"),
        ("quality", "completed"),
    ]
    assert not destination.exists()
    assert not tuple(tmp_path.glob(".cancelled.tmp-*"))


def test_workflow_cancellation_callback_must_return_bool(tmp_path: Path) -> None:
    config = _write_config(tmp_path / "workflow.yaml")
    destination = tmp_path / "cancelled"

    with pytest.raises(TypeError, match="must return bool"):
        workflow.run_modern_workflow(
            config,
            destination=destination,
            cancel_requested=lambda: "yes",
        )

    assert not destination.exists()
    assert not tuple(tmp_path.glob(".cancelled.tmp-*"))
