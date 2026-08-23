from __future__ import annotations

import json
from pathlib import Path

import pytest

torch = pytest.importorskip("torch")

from diffeoforge.engine import optimize_atlas  # noqa: E402
from diffeoforge.mesh import sha256_file  # noqa: E402
from diffeoforge.modern_checkpoint import (  # noqa: E402
    MANIFEST_NAME,
    SIDECAR_NAME,
    ModernCheckpointError,
    load_modern_checkpoint_resume_state,
    verify_modern_cycle_checkpoint,
    write_modern_cycle_checkpoint,
)

DTYPE = torch.float64


def _problem():
    template = torch.tensor(
        ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
        dtype=DTYPE,
    )
    triangles = torch.tensor(
        ((0, 2, 1), (0, 1, 3), (0, 3, 2), (1, 2, 3)),
        dtype=torch.int64,
    )
    target = template.clone()
    target[3] += torch.tensor((0.04, -0.02, 0.03), dtype=DTYPE)
    controls = template[:2].clone()
    momenta = torch.zeros((1, 2, 3), dtype=DTYPE)
    return template, triangles, ((target, triangles),), controls, momenta


def _workflow_binding(root: Path) -> dict:
    config = root / "config" / "source.yaml"
    effective = root / "config" / "effective.json"
    template = root / "input" / "template.vtk"
    subject = root / "input" / "subject.vtk"
    config.parent.mkdir(parents=True)
    template.parent.mkdir(parents=True)
    config.write_text("schema_version: '0.4'\n", encoding="utf-8")
    effective.write_text("{}\n", encoding="utf-8")
    template.write_text("template input\n", encoding="utf-8")
    subject.write_text("subject input\n", encoding="utf-8")

    def record(path: Path) -> dict[str, str]:
        return {"path": path.relative_to(root).as_posix(), "sha256": sha256_file(path)}

    return {
        "engine_implementation": "0.2",
        "source_config": record(config),
        "effective_config": record(effective),
        "template_input": record(template),
        "subjects": [{"label": "subject.vtk", **record(subject)}],
        "block_order": ["momenta"],
        "max_cycles": 2,
    }


def test_cycle_checkpoint_is_atomic_bound_and_tamper_evident(tmp_path: Path) -> None:
    arguments = _problem()
    observed = []
    optimize_atlas(
        *arguments,
        deformation_kernel_width=0.8,
        attachment_kernel_width=0.7,
        noise_variance=0.1,
        number_of_time_points=2,
        max_cycles=2,
        block_order=("momenta",),
        gradient_tolerance=0.0,
        step_initialization="previous_accepted",
        checkpoint_callback=observed.append,
    )
    workflow_root = tmp_path / "private-workflow"
    binding = _workflow_binding(workflow_root)
    destination = write_modern_cycle_checkpoint(
        tmp_path / "checkpoint-cycle-2",
        observed[-1],
        arguments[1],
        ["subject.vtk"],
        binding,
        created_at="2026-08-22T17:00:00+00:00",
    )
    manifest = verify_modern_cycle_checkpoint(destination, workflow_root=workflow_root)

    assert manifest["cycle"] == 2
    assert manifest["checkpoint_version"] == "0.2"
    assert manifest["status"] == "private_complete_cycle_not_a_result"
    assert manifest["binding"] == binding
    assert manifest["state"]["momenta"]["subjects"] == 1
    assert manifest["optimizer_state"]["next_step_sizes"]["momenta"] > 0
    resume_state = load_modern_checkpoint_resume_state(destination)
    assert resume_state.initial_cycle_objective == observed[-1].initial_cycle_objective
    assert resume_state.current_cycle_objective == observed[-1].current_cycle_objective
    assert torch.equal(resume_state.reusable_gradient, observed[-1].reusable_gradient)

    (workflow_root / binding["source_config"]["path"]).write_text("changed\n", encoding="utf-8")
    with pytest.raises(ModernCheckpointError, match="Bound source_config differs"):
        verify_modern_cycle_checkpoint(destination, workflow_root=workflow_root)

    momenta = destination / manifest["state"]["momenta"]["path"]
    momenta.write_bytes(momenta.read_bytes() + b"tamper")
    with pytest.raises(ModernCheckpointError, match="artifact differs"):
        verify_modern_cycle_checkpoint(destination)


def test_checkpoint_manifest_rejects_state_metadata_forgery(tmp_path: Path) -> None:
    arguments = _problem()
    observed = []
    optimize_atlas(
        *arguments,
        deformation_kernel_width=0.8,
        attachment_kernel_width=0.7,
        noise_variance=0.1,
        number_of_time_points=2,
        max_cycles=1,
        block_order=("momenta",),
        gradient_tolerance=0.0,
        checkpoint_callback=observed.append,
    )
    workflow_root = tmp_path / "private-workflow"
    destination = write_modern_cycle_checkpoint(
        tmp_path / "checkpoint",
        observed[-1],
        arguments[1],
        ["subject.vtk"],
        _workflow_binding(workflow_root) | {"max_cycles": 1},
    )
    manifest_path = destination / MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["state"]["momenta"]["subjects"] = 2
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (destination / SIDECAR_NAME).write_text(
        f"{sha256_file(manifest_path)}  {MANIFEST_NAME}\n",
        encoding="ascii",
    )

    with pytest.raises(ModernCheckpointError, match="momenta are invalid"):
        verify_modern_cycle_checkpoint(destination)


def test_lbfgs_checkpoint_round_trips_curvature_history_without_pickle(
    tmp_path: Path,
) -> None:
    arguments = _problem()
    observed = []
    optimize_atlas(
        *arguments,
        deformation_kernel_width=0.8,
        attachment_kernel_width=0.7,
        noise_variance=0.1,
        number_of_time_points=2,
        max_cycles=4,
        block_order=("momenta",),
        gradient_tolerance=0.0,
        direction_update="lbfgs",
        lbfgs_history_size=3,
        checkpoint_callback=observed.append,
    )
    workflow_root = tmp_path / "private-workflow"
    destination = write_modern_cycle_checkpoint(
        tmp_path / "lbfgs-checkpoint",
        observed[-1],
        arguments[1],
        ["subject.vtk"],
        _workflow_binding(workflow_root) | {"max_cycles": 4},
    )
    manifest = verify_modern_cycle_checkpoint(destination, workflow_root=workflow_root)
    loaded = load_modern_checkpoint_resume_state(destination)

    assert len(loaded.lbfgs_history) == 3
    assert len(manifest["optimizer_state"]["tensor_store"]["entries"]) == 7
    assert manifest["optimizer_state"]["tensor_store"]["dtype"] == "float64-le"
    for expected, actual in zip(
        observed[-1].lbfgs_history,
        loaded.lbfgs_history,
        strict=True,
    ):
        assert torch.equal(expected[0], actual[0])
        assert torch.equal(expected[1], actual[1])

    tensor_store = destination / manifest["optimizer_state"]["tensor_store"]["path"]
    tensor_store.write_bytes(tensor_store.read_bytes() + b"tamper")
    with pytest.raises(ModernCheckpointError, match="tensor store differs"):
        load_modern_checkpoint_resume_state(destination)
