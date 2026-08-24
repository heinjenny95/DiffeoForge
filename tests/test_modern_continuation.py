from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

pytest.importorskip("numpy")
pytest.importorskip("torch")

from diffeoforge.cli import main  # noqa: E402
from diffeoforge.modern_bundle import verify_modern_atlas_bundle  # noqa: E402
from diffeoforge.modern_continuation import (  # noqa: E402
    CONFIG_NAME,
    ModernContinuationError,
    create_modern_continuation,
    verify_modern_continuation,
    verify_modern_continuation_run,
)
from diffeoforge.modern_workflow import (  # noqa: E402
    initialize_modern_workflow,
    run_modern_workflow,
    verify_modern_workflow,
)

ROOT = Path(__file__).parents[1]
MESH_DIRECTORY = ROOT / "examples" / "synthetic" / "meshes"
FIXED_TIME = "2026-08-22T16:00:00+00:00"


def test_completed_modern_run_can_continue_from_its_exact_final_state(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    parent_config = initialize_modern_workflow(
        MESH_DIRECTORY,
        units="unitless",
        config_path=tmp_path / "parent.yaml",
        template=MESH_DIRECTORY / "template.vtk",
        subject_pattern="subject-*.vtk",
        attachment_kernel_width=0.45,
        deformation_kernel_width=0.6,
        noise_variance=0.01,
        max_cycles=1,
        threads=1,
    )
    parent_run = run_modern_workflow(
        parent_config,
        destination=tmp_path / "parent-run",
        created_at=FIXED_TIME,
    )
    plan_root = tmp_path / "continuation-plan"
    assert (
        main(
            [
                "modern-continuation-init",
                str(parent_run),
                "--output",
                str(plan_root),
                "--cycles",
                "1",
                "--threads",
                "1",
            ]
        )
        == 0
    )
    created_output = capsys.readouterr()
    assert "No successor optimizer was run" in created_output.out
    assert main(["modern-continuation-verify", str(plan_root)]) == 0
    verified_output = capsys.readouterr()
    assert "remains prospective" in verified_output.out
    plan = verify_modern_continuation(plan_root)
    config = yaml.safe_load((plan_root / CONFIG_NAME).read_text(encoding="utf-8"))

    assert plan["status"] == "prospective_no_successor_result"
    assert plan["parent"]["termination_reason"] == "max_cycles"
    assert plan["continuation"]["step_initialization"] == "previous_accepted"
    assert plan["config"]["expected_engine_implementation"] == "1.5"
    assert config["schema_version"] == "0.5"
    assert config["initialization"]["momenta"] == {
        "method": "file",
        "path": plan["initial_state"]["momenta"]["path"],
    }
    assert config["optimization"]["step_initialization"] == "previous_accepted"
    assert (
        config["optimization"]["resume_state"]["checkpoint_manifest_sha256"]
        == plan["optimizer_state"]["checkpoint_manifest_sha256"]
    )

    successor_run = run_modern_workflow(
        plan_root / CONFIG_NAME,
        destination=tmp_path / "successor-run",
        created_at=FIXED_TIME,
    )
    verified = verify_modern_continuation_run(plan_root, successor_run)
    assert (
        main(
            [
                "modern-continuation-verify-run",
                str(plan_root),
                str(successor_run),
            ]
        )
        == 0
    )
    run_output = capsys.readouterr()
    assert "matches the parent final state within" in run_output.out

    assert verified["initial_objective_matches"] is True
    assert verified["workflow"]["engine"]["implementation_version"] == "1.5"
    assert verified["initial_objective"] == pytest.approx(
        verified["parent_final_objective"], rel=1e-12, abs=1e-12
    )
    assert verified["bundle"]["optimizer"]["settings"]["step_initialization"] == (
        "previous_accepted"
    )

    undeclared = plan_root / "nested" / "modern-continuation-plan.json"
    undeclared.parent.mkdir()
    undeclared.write_text("{}\n", encoding="utf-8")
    with pytest.raises(ModernContinuationError, match="inventory differs"):
        verify_modern_continuation(plan_root)
    undeclared.unlink()

    manifest_path = plan_root / "modern-continuation-plan.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    momenta = plan_root / manifest["initial_state"]["momenta"]["path"]
    momenta.write_bytes(momenta.read_bytes() + b"tamper")
    with pytest.raises(ModernContinuationError, match="artifact differs"):
        verify_modern_continuation(plan_root)


def test_fixed_step_parent_retains_its_historical_continuation_semantics(
    tmp_path: Path,
) -> None:
    parent_config = initialize_modern_workflow(
        MESH_DIRECTORY,
        units="unitless",
        config_path=tmp_path / "fixed-parent.yaml",
        template=MESH_DIRECTORY / "template.vtk",
        subject_pattern="subject-*.vtk",
        attachment_kernel_width=0.45,
        deformation_kernel_width=0.6,
        noise_variance=0.01,
        max_cycles=1,
        threads=1,
    )
    value = yaml.safe_load(parent_config.read_text(encoding="utf-8"))
    value["optimization"]["step_initialization"] = "fixed"
    parent_config.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")
    parent_run = run_modern_workflow(
        parent_config,
        destination=tmp_path / "fixed-parent-run",
        created_at=FIXED_TIME,
    )

    plan_root = create_modern_continuation(
        parent_run,
        tmp_path / "fixed-continuation-plan",
        max_cycles=1,
        created_at=FIXED_TIME,
    )
    plan = verify_modern_continuation(plan_root)
    config = yaml.safe_load((plan_root / CONFIG_NAME).read_text(encoding="utf-8"))

    assert plan["continuation"]["step_initialization"] == "fixed"
    assert config["optimization"]["step_initialization"] == "fixed"


def test_relative_objective_run_continues_with_serialized_baselines(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = initialize_modern_workflow(
        MESH_DIRECTORY,
        units="unitless",
        config_path=tmp_path / "relative-parent.yaml",
        template=MESH_DIRECTORY / "template.vtk",
        subject_pattern="subject-*.vtk",
        attachment_kernel_width=0.45,
        deformation_kernel_width=0.6,
        noise_variance=0.01,
        max_cycles=1,
        threads=1,
    )
    value = yaml.safe_load(config.read_text(encoding="utf-8"))
    value["optimization"]["gradient_tolerance"] = 0.0
    value["optimization"]["relative_objective_tolerance"] = 0.0001
    config.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")
    parent = run_modern_workflow(
        config,
        destination=tmp_path / "relative-parent-run",
        created_at=FIXED_TIME,
    )

    output = tmp_path / "relative-continuation"
    assert (
        main(["modern-continuation-init", str(parent), "--output", str(output), "--cycles", "1"])
        == 0
    )
    created = capsys.readouterr()
    assert "No successor optimizer was run" in created.out
    plan = verify_modern_continuation(output)
    successor = run_modern_workflow(
        output / CONFIG_NAME,
        destination=tmp_path / "relative-successor",
        created_at=FIXED_TIME,
    )
    verified = verify_modern_continuation_run(output, successor)

    assert plan["optimizer_state"]["checkpoint_manifest_sha256"]
    assert verified["initial_objective_matches"] is True
    assert verified["bundle"]["optimizer"]["settings"]["relative_objective_tolerance"] == 0.0001


def test_lbfgs_continuation_is_bit_exact_with_uninterrupted_run(
    tmp_path: Path,
) -> None:
    parent_config = initialize_modern_workflow(
        MESH_DIRECTORY,
        units="unitless",
        config_path=tmp_path / "lbfgs-parent.yaml",
        template=MESH_DIRECTORY / "template.vtk",
        subject_pattern="subject-*.vtk",
        attachment_kernel_width=0.45,
        deformation_kernel_width=0.6,
        noise_variance=0.01,
        max_cycles=2,
        threads=1,
    )
    config = yaml.safe_load(parent_config.read_text(encoding="utf-8"))
    config["optimization"]["block_order"] = ["momenta"]
    config["optimization"]["direction_update"] = "lbfgs"
    config["optimization"]["gradient_tolerance"] = 0.0
    config["optimization"]["relative_objective_tolerance"] = None
    config["optimization"]["line_search_condition"] = "armijo"
    parent_config.write_text(
        yaml.safe_dump(config, sort_keys=False),
        encoding="utf-8",
        newline="\n",
    )
    uninterrupted_config = tmp_path / "lbfgs-uninterrupted.yaml"
    config["optimization"]["max_cycles"] = 4
    uninterrupted_config.write_text(
        yaml.safe_dump(config, sort_keys=False),
        encoding="utf-8",
        newline="\n",
    )

    parent = run_modern_workflow(
        parent_config,
        destination=tmp_path / "lbfgs-parent-run",
        created_at=FIXED_TIME,
    )
    plan_root = tmp_path / "lbfgs-continuation"
    create_modern_continuation(parent, plan_root, max_cycles=2, threads=1)
    successor = run_modern_workflow(
        plan_root / CONFIG_NAME,
        destination=tmp_path / "lbfgs-successor-run",
        created_at=FIXED_TIME,
    )
    uninterrupted = run_modern_workflow(
        uninterrupted_config,
        destination=tmp_path / "lbfgs-uninterrupted-run",
        created_at=FIXED_TIME,
    )

    successor_workflow = verify_modern_workflow(successor)
    uninterrupted_workflow = verify_modern_workflow(uninterrupted)
    successor_bundle_root = successor / successor_workflow["result_bundle"]["path"]
    uninterrupted_bundle_root = uninterrupted / uninterrupted_workflow["result_bundle"]["path"]
    successor_bundle = verify_modern_atlas_bundle(successor_bundle_root)
    uninterrupted_bundle = verify_modern_atlas_bundle(uninterrupted_bundle_root)

    assert (
        successor_bundle["optimizer"]["final_objective"]
        == (uninterrupted_bundle["optimizer"]["final_objective"])
    )
    assert (
        successor_bundle_root / successor_bundle["parameters"]["momenta_path"]
    ).read_bytes() == (
        uninterrupted_bundle_root / uninterrupted_bundle["parameters"]["momenta_path"]
    ).read_bytes()
    assert verify_modern_continuation_run(plan_root, successor)["initial_objective_matches"] is True
