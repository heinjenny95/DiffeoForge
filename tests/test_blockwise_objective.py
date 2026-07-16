from __future__ import annotations

import json
from pathlib import Path

import pytest

torch = pytest.importorskip("torch")
engine = pytest.importorskip("diffeoforge.engine")

GaussianTilePlan = engine.GaussianTilePlan
atlas_objective = engine.atlas_objective
optimize_atlas = engine.optimize_atlas
subject_objective = engine.subject_objective

DTYPE = torch.float64
REFERENCE_FIXTURE = (
    Path(__file__).parents[1]
    / "reference"
    / "modern-engine-v0.2"
    / "deformetrica-4.3.0-objective.json"
)


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


def _subject(reference: dict, attachment_type: str, *, blockwise: bool):
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
        gaussian_tile_plan=GaussianTilePlan(2, 3) if blockwise else None,
    )
    gradients = torch.autograd.grad(
        result.total,
        (inputs["template"], inputs["control_points"], inputs["momenta"]),
    )
    return result, gradients


@pytest.mark.parametrize("attachment_type", ["current", "varifold"])
def test_full_subject_blockwise_forward_and_all_gradients_match_dense(
    reference: dict,
    attachment_type: str,
) -> None:
    dense, dense_gradients = _subject(reference, attachment_type, blockwise=False)
    blockwise, blockwise_gradients = _subject(reference, attachment_type, blockwise=True)
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


def test_atlas_blockwise_objective_and_all_parameter_gradients_match_dense(
    reference: dict,
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
    blockwise, blockwise_gradients = evaluate(GaussianTilePlan(3, 2))
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
def test_one_cycle_blockwise_optimizer_matches_dense_decisions_and_parameters(
    reference: dict,
    attachment_type: str,
) -> None:
    arguments, keywords = _atlas_problem(reference)
    keywords["attachment_type"] = attachment_type
    dense = optimize_atlas(*arguments, **keywords, max_cycles=1)
    blockwise = optimize_atlas(
        *arguments,
        **keywords,
        max_cycles=1,
        gaussian_tile_plan=GaussianTilePlan(2, 3),
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
