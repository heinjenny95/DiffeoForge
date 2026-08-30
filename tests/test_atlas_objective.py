from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

torch = pytest.importorskip("torch")
engine = pytest.importorskip("diffeoforge.engine")

atlas_objective = engine.atlas_objective
current_squared_distance = engine.current_squared_distance
flow_points = engine.flow_points
shoot = engine.shoot
subject_objective = engine.subject_objective
varifold_squared_distance = engine.varifold_squared_distance

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


def _tensor(values, *, requires_grad: bool = False) -> torch.Tensor:
    return torch.tensor(values, dtype=DTYPE, requires_grad=requires_grad)


def _inputs(reference: dict, *, requires_grad: bool = False) -> dict:
    values = reference["inputs"]
    return {
        "template": _tensor(values["template_vertices"], requires_grad=requires_grad),
        "target": _tensor(values["target_vertices"]),
        "triangles": torch.tensor(values["triangles"], dtype=torch.int64),
        "control_points": _tensor(values["control_points"], requires_grad=requires_grad),
        "momenta": _tensor(values["momenta"], requires_grad=requires_grad),
    }


def _subject(reference: dict, attachment_type: str, *, requires_grad: bool = False):
    values = reference["inputs"]
    inputs = _inputs(reference, requires_grad=requires_grad)
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
    )
    return inputs, result


@pytest.mark.parametrize(
    ("attachment_type", "distance_function"),
    [
        ("current", current_squared_distance),
        ("varifold", varifold_squared_distance),
    ],
)
def test_static_attachments_and_gradients_match_deformetrica_reference(
    reference: dict,
    attachment_type: str,
    distance_function,
) -> None:
    values = reference["inputs"]
    inputs = _inputs(reference)
    source = inputs["template"].requires_grad_(True)
    distance = distance_function(
        source,
        inputs["triangles"],
        inputs["target"],
        inputs["triangles"],
        values["attachment_width"],
    )
    (gradient,) = torch.autograd.grad(distance, source)
    expected = reference["expected"]["static"][attachment_type]
    tolerance = reference["tolerance"]

    torch.testing.assert_close(
        distance,
        _tensor(expected["distance"]),
        rtol=tolerance["relative"],
        atol=tolerance["absolute"],
    )
    torch.testing.assert_close(
        gradient,
        _tensor(expected["source_gradient"]),
        rtol=tolerance["relative"],
        atol=tolerance["absolute"],
    )


@pytest.mark.parametrize("attachment_type", ["current", "varifold"])
def test_full_subject_objective_and_gradients_match_deformetrica_reference(
    reference: dict,
    attachment_type: str,
) -> None:
    inputs, result = _subject(reference, attachment_type, requires_grad=True)
    gradients = torch.autograd.grad(
        result.total,
        (inputs["template"], inputs["control_points"], inputs["momenta"]),
    )
    expected = reference["expected"]["subject"][attachment_type]
    tolerance = reference["tolerance"]
    options = {"rtol": tolerance["relative"], "atol": tolerance["absolute"]}

    torch.testing.assert_close(result.endpoint_vertices, _tensor(expected["endpoint"]), **options)
    for name in ("residual", "attachment", "regularity", "total"):
        torch.testing.assert_close(getattr(result, name), _tensor(expected[name]), **options)
    for gradient, name in zip(
        gradients,
        ("template_gradient", "control_points_gradient", "momenta_gradient"),
        strict=True,
    ):
        torch.testing.assert_close(gradient, _tensor(expected[name]), **options)


def test_machine_readable_objective_reference_harness_passes(reference: dict) -> None:
    from diffeoforge.engine.reference import compare_reference_fixture

    report = compare_reference_fixture(REFERENCE_FIXTURE)

    assert report["schema_version"] == "0.2"
    assert report["overall_pass"] is True
    assert report["fixture"]["baseline"] == reference["baseline"]
    assert len(report["comparisons"]) == 20
    assert max(
        comparison["max_absolute_error"] for comparison in report["comparisons"].values()
    ) < 2e-14


def test_legacy_flow_integrator_is_explicit_and_distinct(reference: dict) -> None:
    values = reference["inputs"]
    inputs = _inputs(reference)
    trajectory = shoot(
        inputs["control_points"],
        inputs["momenta"],
        values["deformation_width"],
        values["number_of_time_points"],
        integrator="rk2",
    )

    standard = flow_points(
        inputs["template"], trajectory, values["deformation_width"], integrator="heun"
    )
    legacy = flow_points(
        inputs["template"],
        trajectory,
        values["deformation_width"],
        integrator="deformetrica_heun",
    )

    assert float(torch.max(torch.abs(standard[-1] - legacy[-1]))) > 1e-8
    torch.testing.assert_close(
        legacy[-1],
        _tensor(reference["expected"]["subject"]["current"]["endpoint"]),
        rtol=1e-12,
        atol=1e-14,
    )


def test_subject_momenta_gradient_passes_finite_difference_check(reference: dict) -> None:
    values = reference["inputs"]
    inputs = _inputs(reference)
    momenta = inputs["momenta"].requires_grad_(True)

    def objective(candidate: torch.Tensor) -> torch.Tensor:
        return subject_objective(
            inputs["template"],
            inputs["triangles"],
            inputs["target"],
            inputs["triangles"],
            inputs["control_points"],
            candidate,
            deformation_kernel_width=values["deformation_width"],
            attachment_kernel_width=values["attachment_width"],
            noise_variance=values["noise_variance"],
            number_of_time_points=values["number_of_time_points"],
            attachment_type="current",
        ).total

    assert torch.autograd.gradcheck(
        objective,
        (momenta,),
        eps=1e-6,
        atol=2e-5,
        rtol=2e-4,
    )


def test_atlas_objective_is_unaveraged_ordered_deterministic_sum(reference: dict) -> None:
    values = reference["inputs"]
    inputs = _inputs(reference)
    second_target = inputs["target"] + _tensor([0.015, -0.01, 0.02])
    momenta = torch.stack((inputs["momenta"], -0.4 * inputs["momenta"])).requires_grad_(True)
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
    }

    first = atlas_objective(*arguments, **keywords)
    second = atlas_objective(*arguments, **keywords)
    (gradient,) = torch.autograd.grad(first.total, momenta)

    assert len(first.subjects) == 2
    assert torch.equal(first.residuals, torch.stack([item.residual for item in first.subjects]))
    assert torch.equal(first.total, sum(item.total for item in first.subjects))
    assert torch.equal(first.total, second.total)
    assert bool(torch.isfinite(gradient).all())
    assert torch.count_nonzero(gradient) > 0


@pytest.mark.parametrize("variance", [0.0, -1.0, math.inf, math.nan])
def test_invalid_noise_variance_fails_explicitly(reference: dict, variance: float) -> None:
    values = reference["inputs"]
    inputs = _inputs(reference)

    with pytest.raises(ValueError, match="noise_variance"):
        subject_objective(
            inputs["template"],
            inputs["triangles"],
            inputs["target"],
            inputs["triangles"],
            inputs["control_points"],
            inputs["momenta"],
            deformation_kernel_width=values["deformation_width"],
            attachment_kernel_width=values["attachment_width"],
            noise_variance=variance,
            number_of_time_points=values["number_of_time_points"],
        )


def test_invalid_atlas_inputs_fail_explicitly(reference: dict) -> None:
    values = reference["inputs"]
    inputs = _inputs(reference)
    keywords = {
        "deformation_kernel_width": values["deformation_width"],
        "attachment_kernel_width": values["attachment_width"],
        "noise_variance": values["noise_variance"],
        "number_of_time_points": values["number_of_time_points"],
    }

    with pytest.raises(ValueError, match="at least one"):
        atlas_objective(
            inputs["template"],
            inputs["triangles"],
            (),
            inputs["control_points"],
            inputs["momenta"].unsqueeze(0),
            **keywords,
        )
    with pytest.raises(ValueError, match="same number"):
        atlas_objective(
            inputs["template"],
            inputs["triangles"],
            ((inputs["target"], inputs["triangles"]),),
            inputs["control_points"],
            torch.stack((inputs["momenta"], inputs["momenta"])),
            **keywords,
        )
    with pytest.raises(ValueError, match="attachment_type"):
        subject_objective(
            inputs["template"],
            inputs["triangles"],
            inputs["target"],
            inputs["triangles"],
            inputs["control_points"],
            inputs["momenta"],
            attachment_type="bogus",
            **keywords,
        )
