from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import yaml

pytest.importorskip("numpy")
pytest.importorskip("torch")

from diffeoforge.cli import main  # noqa: E402
from diffeoforge.modern_checkpoint_recovery import (  # noqa: E402
    CONFIG_NAME,
    PLAN_NAME,
    ModernCheckpointRecoveryError,
    create_modern_checkpoint_recovery,
    verify_modern_checkpoint_recovery,
    verify_modern_checkpoint_recovery_run,
)
from diffeoforge.modern_workflow import (  # noqa: E402
    initialize_modern_workflow,
    run_modern_workflow,
)
from diffeoforge.private_runs import acquire_private_run_lease  # noqa: E402

ROOT = Path(__file__).parents[1]
MESH_DIRECTORY = ROOT / "examples" / "synthetic" / "meshes"
FIXED_TIME = "2026-08-22T17:30:00+00:00"


def _payload_bytes(directory: Path) -> dict[str, bytes]:
    return {
        path.relative_to(directory).as_posix(): path.read_bytes()
        for path in directory.rglob("*")
        if path.is_file()
    }


def test_abandoned_complete_cycle_can_be_frozen_and_published_as_successor(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = initialize_modern_workflow(
        MESH_DIRECTORY,
        units="unitless",
        config_path=tmp_path / "source.yaml",
        template=MESH_DIRECTORY / "template.vtk",
        subject_pattern="subject-*.vtk",
        attachment_kernel_width=0.45,
        deformation_kernel_width=0.6,
        noise_variance=0.01,
        max_cycles=1,
        threads=1,
    )
    completed = run_modern_workflow(
        config,
        destination=tmp_path / "completed-source",
        created_at=FIXED_TIME,
    )
    abandoned_destination = tmp_path / "interrupted-run"
    abandoned = tmp_path / f".{abandoned_destination.name}.tmp-{'a' * 32}"
    shutil.copytree(completed, abandoned)
    lease = acquire_private_run_lease(
        abandoned,
        abandoned_destination,
        operation="modern_workflow",
    )
    lease.close()
    source_before = _payload_bytes(abandoned)

    plan_root = tmp_path / "recovery-plan"
    assert (
        main(
            [
                "modern-checkpoint-recovery-init",
                str(abandoned),
                "--output",
                str(plan_root),
                "--threads",
                "1",
            ]
        )
        == 0
    )
    created_output = capsys.readouterr()
    assert "abandoned directory was not modified" in created_output.out
    assert _payload_bytes(abandoned) == source_before

    assert main(["modern-checkpoint-recovery-verify", str(plan_root)]) == 0
    verified_output = capsys.readouterr()
    assert "remains prospective" in verified_output.out
    plan = verify_modern_checkpoint_recovery(plan_root)
    recovery_config = yaml.safe_load((plan_root / CONFIG_NAME).read_text(encoding="utf-8"))
    assert plan["source"]["checkpoint_cycle"] == 1
    assert plan["source"]["original_cycle_cap"] == 1
    assert plan["continuation"]["max_cycles"] == 0
    assert recovery_config["schema_version"] == "0.5"
    assert recovery_config["preprocessing"]["procrustes"]["enabled"] is False
    assert recovery_config["initialization"]["momenta"]["method"] == "file"
    assert (
        recovery_config["optimization"]["resume_state"]["checkpoint_manifest_sha256"]
        == plan["source"]["checkpoint_manifest_sha256"]
    )

    successor = run_modern_workflow(
        plan_root / CONFIG_NAME,
        destination=tmp_path / "recovered-run",
        created_at=FIXED_TIME,
    )
    verified = verify_modern_checkpoint_recovery_run(plan_root, successor)
    assert (
        main(
            [
                "modern-checkpoint-recovery-verify-run",
                str(plan_root),
                str(successor),
            ]
        )
        == 0
    )
    run_output = capsys.readouterr()
    assert "matches the frozen complete-cycle checkpoint" in run_output.out
    assert verified["initial_objective_matches"] is True
    assert verified["initial_objective"] == pytest.approx(
        verified["checkpoint_objective"], rel=1e-12, abs=1e-12
    )

    manifest_path = plan_root / PLAN_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    checkpoint_template = plan_root / next(
        record["path"]
        for record in manifest["artifacts"]
        if record["path"].endswith("estimated-template.vtk")
    )
    checkpoint_template.write_bytes(checkpoint_template.read_bytes() + b"tamper")
    with pytest.raises(ModernCheckpointRecoveryError, match="artifact differs"):
        verify_modern_checkpoint_recovery(plan_root)


def test_recovery_rejects_a_live_private_run(tmp_path: Path) -> None:
    destination = tmp_path / "live-run"
    private = tmp_path / f".{destination.name}.tmp-{'b' * 32}"
    private.mkdir()
    lease = acquire_private_run_lease(private, destination, operation="modern_workflow")
    try:
        assert (
            main(
                [
                    "modern-checkpoint-recovery-init",
                    str(private),
                    "--output",
                    str(tmp_path / "must-not-exist"),
                ]
            )
            == 2
        )
        assert not (tmp_path / "must-not-exist").exists()
    finally:
        lease.close()


def test_relative_objective_checkpoint_recovers_with_serialized_baselines(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = initialize_modern_workflow(
        MESH_DIRECTORY,
        units="unitless",
        config_path=tmp_path / "relative-source.yaml",
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
    completed = run_modern_workflow(
        config,
        destination=tmp_path / "relative-completed",
        created_at=FIXED_TIME,
    )
    destination = tmp_path / "relative-interrupted"
    private = tmp_path / f".{destination.name}.tmp-{'c' * 32}"
    shutil.copytree(completed, private)
    lease = acquire_private_run_lease(private, destination, operation="modern_workflow")
    lease.close()

    output = tmp_path / "relative-recovery"
    assert main(["modern-checkpoint-recovery-init", str(private), "--output", str(output)]) == 0
    created = capsys.readouterr()
    assert "abandoned directory was not modified" in created.out
    plan = verify_modern_checkpoint_recovery(output)
    successor = run_modern_workflow(
        output / CONFIG_NAME,
        destination=tmp_path / "relative-recovered-run",
        created_at=FIXED_TIME,
    )
    verified = verify_modern_checkpoint_recovery_run(output, successor)

    assert plan["source"]["checkpoint_cycle"] == 1
    assert verified["initial_objective_matches"] is True
    assert verified["bundle"]["optimizer"]["settings"]["relative_objective_tolerance"] == 0.0001


def test_recovery_accepts_both_verified_checkpoints_from_retirement_crash_window(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = initialize_modern_workflow(
        MESH_DIRECTORY,
        units="unitless",
        config_path=tmp_path / "retirement-source.yaml",
        template=MESH_DIRECTORY / "template.vtk",
        subject_pattern="subject-*.vtk",
        attachment_kernel_width=0.45,
        deformation_kernel_width=0.6,
        noise_variance=0.01,
        max_cycles=4,
        threads=1,
    )
    value = yaml.safe_load(config.read_text(encoding="utf-8"))
    value["optimization"]["block_order"] = ["momenta"]
    value["optimization"]["gradient_tolerance"] = 0.0
    value["optimization"]["checkpoint_interval_cycles"] = 2
    config.write_text(
        yaml.safe_dump(value, sort_keys=False),
        encoding="utf-8",
        newline="\n",
    )
    original_rename = Path.rename

    def interrupt_before_retirement(source: Path, destination: Path) -> Path:
        if source.name == "cycle-000002" and destination.name.startswith(
            ".retired-cycle-000002-"
        ):
            raise KeyboardInterrupt("simulated hard exit before checkpoint retirement")
        return original_rename(source, destination)

    monkeypatch.setattr(Path, "rename", interrupt_before_retirement)
    intended = tmp_path / "retirement-run"
    with pytest.raises(KeyboardInterrupt, match="simulated hard exit"):
        run_modern_workflow(config, destination=intended, created_at=FIXED_TIME)
    monkeypatch.setattr(Path, "rename", original_rename)

    private_candidates = list(tmp_path.glob(".retirement-run.tmp-*"))
    assert len(private_candidates) == 1
    private = private_candidates[0]
    assert sorted(path.name for path in (private / "checkpoints").iterdir()) == [
        "cycle-000002",
        "cycle-000004",
    ]
    recovery = create_modern_checkpoint_recovery(
        private,
        tmp_path / "retirement-recovery",
        max_cycles=0,
        threads=1,
        created_at=FIXED_TIME,
    )
    plan = verify_modern_checkpoint_recovery(recovery)

    assert plan["source"]["checkpoint_cycle"] == 4
