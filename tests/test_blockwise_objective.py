from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

torch = pytest.importorskip("torch")
engine = pytest.importorskip("diffeoforge.engine")

GaussianTilePlan = engine.GaussianTilePlan
atlas_objective = engine.atlas_objective
optimize_atlas = engine.optimize_atlas
subject_objective = engine.subject_objective

from diffeoforge.mesh import read_vtk_polydata  # noqa: E402

DTYPE = torch.float64
REFERENCE_FIXTURE = (
    Path(__file__).parents[1]
    / "reference"
    / "modern-engine-v0.2"
    / "deformetrica-4.3.0-objective.json"
)
CC0_MESH_DIRECTORY = Path(__file__).parents[1] / "examples" / "synthetic" / "meshes"
MODERN_EXAMPLE = Path(__file__).parents[1] / "examples" / "minimal-modern-atlas.yaml"


@pytest.fixture(scope="module")
def reference() -> dict:
    return json.loads(REFERENCE_FIXTURE.read_text(encoding="utf-8"))


def _subject_inputs(reference: dict, *, requires_grad: bool) -> dict[str, torch.Tensor]:
    values = reference["inputs"]
    return {
        "template": torch.tensor(
            values["template_vertices"], dtype=DTYPE, requires_grad=requires_grad
        ),
        "target": torch.tensor(values["target_vertices"], dtype=DTYPE),
        "triangles": torch.tensor(values["triangles"], dtype=torch.int64),
        "control_points": torch.tensor(
            values["control_points"], dtype=DTYPE, requires_grad=requires_grad
        ),
        "momenta": torch.tensor(values["momenta"], dtype=DTYPE, requires_grad=requires_grad),
    }


def _subject(reference: dict, attachment_type: str, plan: GaussianTilePlan | None):
    values = reference["inputs"]
    inputs = _subject_inputs(reference, requires_grad=True)
    result = subject_objective(
        inputs["template"],
        inputs["triangles"],
        inputs["target"],
        inputs["triangles"],
        inputs["control_points"],
        inputs["momenta"],
        deformation_kernel_width=values["deformation_width"],
        attachment_kernel_width=values["attachment_width"],
        noise_variance=values["noise_variance"],
        number_of_time_points=values["number_of_time_points"],
        attachment_type=attachment_type,
        shooting_integrator=values["shooting_integrator"],
        flow_integrator=values["flow_integrator"],
        gaussian_tile_plan=plan,
    )
    gradients = torch.autograd.grad(
        result.total,
        (inputs["template"], inputs["control_points"], inputs["momenta"]),
    )
    return result, gradients


@pytest.mark.parametrize("attachment_type", ["current", "varifold"])
@pytest.mark.parametrize("autograd_strategy", ["standard", "recompute"])
def test_full_subject_blockwise_forward_and_all_gradients_match_dense(
    reference: dict,
    attachment_type: str,
    autograd_strategy: str,
) -> None:
    dense, dense_gradients = _subject(reference, attachment_type, None)
    blockwise, blockwise_gradients = _subject(
        reference,
        attachment_type,
        GaussianTilePlan(2, 3, autograd_strategy),
    )
    options = {"rtol": 2e-12, "atol": 2e-13}

    torch.testing.assert_close(
        blockwise.trajectory.control_points,
        dense.trajectory.control_points,
        **options,
    )
    torch.testing.assert_close(
        blockwise.trajectory.momenta,
        dense.trajectory.momenta,
        **options,
    )
    torch.testing.assert_close(blockwise.template_path, dense.template_path, **options)
    for name in ("residual", "attachment", "regularity", "total"):
        torch.testing.assert_close(getattr(blockwise, name), getattr(dense, name), **options)
    for blockwise_gradient, dense_gradient in zip(
        blockwise_gradients,
        dense_gradients,
        strict=True,
    ):
        torch.testing.assert_close(blockwise_gradient, dense_gradient, **options)


def _atlas_problem(reference: dict) -> tuple[tuple, dict]:
    values = reference["inputs"]
    inputs = _subject_inputs(reference, requires_grad=False)
    second_target = inputs["target"] + torch.tensor([0.015, -0.01, 0.02], dtype=DTYPE)
    momenta = torch.stack((inputs["momenta"], -0.4 * inputs["momenta"]))
    arguments = (
        inputs["template"],
        inputs["triangles"],
        (
            (inputs["target"], inputs["triangles"]),
            (second_target, inputs["triangles"]),
        ),
        inputs["control_points"],
        momenta,
    )
    keywords = {
        "deformation_kernel_width": values["deformation_width"],
        "attachment_kernel_width": values["attachment_width"],
        "noise_variance": values["noise_variance"],
        "number_of_time_points": values["number_of_time_points"],
        "attachment_type": "varifold",
        "shooting_integrator": values["shooting_integrator"],
        "flow_integrator": values["flow_integrator"],
    }
    return arguments, keywords


@pytest.mark.parametrize("autograd_strategy", ["standard", "recompute"])
def test_atlas_blockwise_objective_and_all_parameter_gradients_match_dense(
    reference: dict,
    autograd_strategy: str,
) -> None:
    arguments, keywords = _atlas_problem(reference)

    def evaluate(plan):
        variables = tuple(
            value.detach().clone().requires_grad_(True)
            if isinstance(value, torch.Tensor) and value.dtype == DTYPE
            else value
            for value in arguments
        )
        result = atlas_objective(*variables, **keywords, gaussian_tile_plan=plan)
        gradients = torch.autograd.grad(
            result.total,
            (variables[0], variables[3], variables[4]),
        )
        return result, gradients

    dense, dense_gradients = evaluate(None)
    blockwise, blockwise_gradients = evaluate(
        GaussianTilePlan(3, 2, autograd_strategy)
    )
    options = {"rtol": 3e-12, "atol": 3e-13}

    torch.testing.assert_close(blockwise.residuals, dense.residuals, **options)
    for name in ("attachment", "regularity", "total"):
        torch.testing.assert_close(getattr(blockwise, name), getattr(dense, name), **options)
    for blockwise_gradient, dense_gradient in zip(
        blockwise_gradients,
        dense_gradients,
        strict=True,
    ):
        torch.testing.assert_close(blockwise_gradient, dense_gradient, **options)


@pytest.mark.parametrize("attachment_type", ["current", "varifold"])
@pytest.mark.parametrize("autograd_strategy", ["standard", "recompute"])
def test_one_cycle_blockwise_optimizer_matches_dense_decisions_and_parameters(
    reference: dict,
    attachment_type: str,
    autograd_strategy: str,
) -> None:
    arguments, keywords = _atlas_problem(reference)
    keywords["attachment_type"] = attachment_type
    dense = optimize_atlas(*arguments, **keywords, max_cycles=1)
    blockwise = optimize_atlas(
        *arguments,
        **keywords,
        max_cycles=1,
        gaussian_tile_plan=GaussianTilePlan(2, 3, autograd_strategy),
    )
    options = {"rtol": 2e-10, "atol": 2e-11}

    assert blockwise.termination_reason == dense.termination_reason
    assert blockwise.converged == dense.converged
    assert blockwise.failed_block == dense.failed_block
    assert blockwise.cycles_completed == dense.cycles_completed
    assert blockwise.total_line_search_evaluations == dense.total_line_search_evaluations
    assert len(blockwise.history) == len(dense.history)
    for blockwise_record, dense_record in zip(
        blockwise.history,
        dense.history,
        strict=True,
    ):
        assert (
            blockwise_record.cycle,
            blockwise_record.block,
            blockwise_record.status,
            blockwise_record.accepted_step_size,
            blockwise_record.line_search_evaluations,
        ) == (
            dense_record.cycle,
            dense_record.block,
            dense_record.status,
            dense_record.accepted_step_size,
            dense_record.line_search_evaluations,
        )
        assert blockwise_record.objective == pytest.approx(
            dense_record.objective, rel=2e-10, abs=2e-11
        )
        assert blockwise_record.attachment == pytest.approx(
            dense_record.attachment, rel=2e-10, abs=2e-11
        )
        assert blockwise_record.regularity == pytest.approx(
            dense_record.regularity, rel=2e-10, abs=2e-11
        )
        assert blockwise_record.residuals == pytest.approx(
            dense_record.residuals, rel=2e-10, abs=2e-11
        )
        assert blockwise_record.gradient_norm == pytest.approx(
            dense_record.gradient_norm, rel=2e-10, abs=2e-11
        )
    torch.testing.assert_close(
        blockwise.template_vertices,
        dense.template_vertices,
        **options,
    )
    torch.testing.assert_close(
        blockwise.control_points,
        dense.control_points,
        **options,
    )
    torch.testing.assert_close(blockwise.momenta, dense.momenta, **options)


def test_recompute_reduces_cc0_objective_forward_saved_tensor_payload() -> None:
    config = yaml.safe_load(MODERN_EXAMPLE.read_text(encoding="utf-8"))
    template_mesh = read_vtk_polydata(CC0_MESH_DIRECTORY / "template.vtk")
    target_mesh = read_vtk_polydata(CC0_MESH_DIRECTORY / "subject-01.vtk")
    base_template = torch.tensor(template_mesh.vertices, dtype=DTYPE)
    template_triangles = torch.tensor(template_mesh.triangles, dtype=torch.int64)
    target = torch.tensor(target_mesh.vertices, dtype=DTYPE)
    target_triangles = torch.tensor(target_mesh.triangles, dtype=torch.int64)
    deformation = config["model"]["deformation"]
    attachment = config["model"]["attachment"]

    def observe(strategy: str):
        template = base_template.clone().requires_grad_(True)
        control_points = base_template[[0, 32, 64, 96, 128]].clone().requires_grad_(True)
        momenta = torch.zeros((1, 5, 3), dtype=DTYPE, requires_grad=True)
        saved: list[tuple[int, tuple[int, ...]]] = []

        def pack(tensor: torch.Tensor):
            saved.append((tensor.numel() * tensor.element_size(), tuple(tensor.shape)))
            return tensor

        with torch.autograd.graph.saved_tensors_hooks(pack, lambda tensor: tensor):
            result = atlas_objective(
                template,
                template_triangles,
                ((target, target_triangles),),
                control_points,
                momenta,
                deformation_kernel_width=deformation["kernel_width"],
                attachment_kernel_width=attachment["kernel_width"],
                noise_variance=config["model"]["noise_variance"],
                number_of_time_points=deformation["timepoints"],
                attachment_type=attachment["type"],
                shooting_integrator=deformation["shooting_integrator"],
                flow_integrator=deformation["flow_integrator"],
                gaussian_tile_plan=GaussianTilePlan(64, 64, strategy),
            )
        gradients = torch.autograd.grad(
            result.total,
            (template, control_points, momenta),
        )
        return result.total, gradients, saved

    standard, standard_gradients, standard_saved = observe("standard")
    recomputed, recomputed_gradients, recomputed_saved = observe("recompute")

    torch.testing.assert_close(recomputed, standard, rtol=0, atol=0)
    for actual, expected in zip(recomputed_gradients, standard_gradients, strict=True):
        torch.testing.assert_close(actual, expected, rtol=0, atol=0)
    assert any(shape == (64, 64, 3) for _, shape in standard_saved)
    assert all(shape != (64, 64, 3) for _, shape in recomputed_saved)
    assert max(size for size, _ in recomputed_saved) < max(
        size for size, _ in standard_saved
    )
    assert sum(size for size, _ in recomputed_saved) < sum(
        size for size, _ in standard_saved
    )


def test_invalid_tile_plan_fails_before_subject_numerics(reference: dict) -> None:
    values = reference["inputs"]
    inputs = _subject_inputs(reference, requires_grad=False)

    with pytest.raises(TypeError, match="gaussian_tile_plan"):
        subject_objective(
            inputs["template"],
            inputs["triangles"],
            inputs["target"],
            inputs["triangles"],
            inputs["control_points"],
            inputs["momenta"],
            deformation_kernel_width=values["deformation_width"],
            attachment_kernel_width=values["attachment_width"],
            noise_variance=values["noise_variance"],
            number_of_time_points=values["number_of_time_points"],
            gaussian_tile_plan=object(),
        )
