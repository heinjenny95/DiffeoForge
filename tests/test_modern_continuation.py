from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

pytest.importorskip("numpy")
pytest.importorskip("torch")

from diffeoforge.cli import main  # noqa: E402
from diffeoforge.modern_continuation import (  # noqa: E402
    CONFIG_NAME,
    ModernContinuationError,
    verify_modern_continuation,
    verify_modern_continuation_run,
)
from diffeoforge.modern_workflow import (  # noqa: E402
    initialize_modern_workflow,
    run_modern_workflow,
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
    assert main(
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
    ) == 0
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
    assert plan["config"]["expected_engine_implementation"] == "0.5"
    assert config["schema_version"] == "0.4"
    assert config["initialization"]["momenta"] == {
        "method": "file",
        "path": "inputs/momenta.csv",
    }
    assert config["optimization"]["step_initialization"] == "previous_accepted"

    successor_run = run_modern_workflow(
        plan_root / CONFIG_NAME,
        destination=tmp_path / "successor-run",
        created_at=FIXED_TIME,
    )
    verified = verify_modern_continuation_run(plan_root, successor_run)
    assert main(
        [
            "modern-continuation-verify-run",
            str(plan_root),
            str(successor_run),
        ]
    ) == 0
    run_output = capsys.readouterr()
    assert "matches the parent final state within" in run_output.out

    assert verified["initial_objective_matches"] is True
    assert verified["workflow"]["engine"]["implementation_version"] == "0.5"
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
