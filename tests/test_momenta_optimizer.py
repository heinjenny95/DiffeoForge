from __future__ import annotations

import json
import math
import runpy
from itertools import pairwise
from pathlib import Path

import pytest

torch = pytest.importorskip("torch")
engine = pytest.importorskip("diffeoforge.engine")

optimize_momenta = engine.optimize_momenta

DTYPE = torch.float64
REFERENCE_FIXTURE = (
    Path(__file__).parents[1]
    / "reference"
    / "modern-engine-v0.2"
    / "deformetrica-4.3.0-objective.json"
)
SMOKE_FIXTURE = (
    Path(__file__).parents[1]
    / "reference"
    / "modern-engine-v0.3"
    / "cc0-momenta-smoke.json"
)


def _problem(subjects: int = 2) -> tuple[tuple, dict]:
    fixture = json.loads(REFERENCE_FIXTURE.read_text(encoding="utf-8"))
    values = fixture["inputs"]
    template = torch.tensor(values["template_vertices"], dtype=DTYPE)
    target = torch.tensor(values["target_vertices"], dtype=DTYPE)
    triangles = torch.tensor(values["triangles"], dtype=torch.int64)
    control_points = torch.tensor(values["control_points"], dtype=DTYPE)
    translations = (
        torch.tensor([0.0, 0.0, 0.0], dtype=DTYPE),
        torch.tensor([0.01, -0.015, 0.02], dtype=DTYPE),
    )
    targets = tuple((target + translations[index], triangles) for index in range(subjects))
    momenta = torch.zeros((subjects, *control_points.shape), dtype=DTYPE)
    arguments = (template, triangles, targets, control_points, momenta)
    keywords = {
        "deformation_kernel_width": values["deformation_width"],
        "attachment_kernel_width": values["attachment_width"],
        "noise_variance": values["noise_variance"],
        "number_of_time_points": values["number_of_time_points"],
        "attachment_type": "current",
    }
    return arguments, keywords


def test_optimizer_improves_objective_monotonically_and_records_every_state() -> None:
    arguments, keywords = _problem()

    result = optimize_momenta(
        *arguments,
        **keywords,
        max_iterations=8,
        initial_step_size=0.1,
        gradient_tolerance=0.0,
    )

    objectives = [record.objective for record in result.history]
    assert result.termination_reason == "max_iterations"
    assert result.converged is False
    assert len(result.history) == 9
    assert all(later > earlier for earlier, later in pairwise(objectives))
    assert result.history[0].accepted_step_size is None
    assert all(record.accepted_step_size is not None for record in result.history[1:])
    assert all(len(record.residuals) == 2 for record in result.history)
    assert all(
        record.objective == pytest.approx(record.attachment + record.regularity)
        for record in result.history
    )
    assert result.total_line_search_evaluations == sum(
        record.line_search_evaluations for record in result.history
    )


def test_optimizer_is_bitwise_repeatable_and_does_not_mutate_inputs() -> None:
    arguments, keywords = _problem()
    initial_momenta = arguments[-1]
    original = initial_momenta.clone()

    first = optimize_momenta(*arguments, **keywords, max_iterations=5)
    second = optimize_momenta(*arguments, **keywords, max_iterations=5)

    assert torch.equal(initial_momenta, original)
    assert torch.equal(first.momenta, second.momenta)
    assert first.history == second.history
    assert first.termination_reason == second.termination_reason
    assert first.momenta.requires_grad is False


def test_zero_momenta_are_stationary_for_identical_template_and_target() -> None:
    arguments, keywords = _problem(subjects=1)
    template, triangles, _, control_points, momenta = arguments

    result = optimize_momenta(
        template,
        triangles,
        ((template, triangles),),
        control_points,
        momenta,
        **keywords,
    )

    assert result.termination_reason == "gradient_tolerance"
    assert result.converged is True
    assert len(result.history) == 1
    assert result.history[0].gradient_norm < 1e-8
    assert torch.equal(result.momenta, momenta)


def test_zero_iterations_returns_the_fully_evaluated_initial_state() -> None:
    arguments, keywords = _problem(subjects=1)

    result = optimize_momenta(*arguments, **keywords, max_iterations=0)

    assert result.termination_reason == "max_iterations"
    assert result.converged is False
    assert len(result.history) == 1
    assert math.isfinite(result.history[0].objective)
    assert result.total_line_search_evaluations == 0


def test_backtracking_reduces_aggressive_steps_before_acceptance() -> None:
    arguments, keywords = _problem()

    result = optimize_momenta(
        *arguments,
        **keywords,
        max_iterations=1,
        initial_step_size=10.0,
        max_line_search_iterations=20,
    )

    accepted = result.history[1]
    assert accepted.line_search_evaluations > 1
    assert accepted.accepted_step_size < 10.0
    assert accepted.objective > result.history[0].objective


def test_failed_line_search_preserves_last_accepted_state() -> None:
    arguments, keywords = _problem(subjects=1)
    initial_momenta = arguments[-1]

    result = optimize_momenta(
        *arguments,
        **keywords,
        max_iterations=3,
        initial_step_size=10.0,
        max_line_search_iterations=1,
    )

    assert result.termination_reason == "line_search_failed"
    assert result.converged is False
    assert len(result.history) == 1
    assert result.total_line_search_evaluations == 1
    assert torch.equal(result.momenta, initial_momenta)


def test_optimizer_remains_differentiable_internally_under_no_grad() -> None:
    arguments, keywords = _problem(subjects=1)

    with torch.no_grad():
        result = optimize_momenta(*arguments, **keywords, max_iterations=1)

    assert len(result.history) == 2
    assert result.history[1].objective > result.history[0].objective


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"max_iterations": -1}, "max_iterations"),
        ({"max_line_search_iterations": 0}, "max_line_search_iterations"),
        ({"initial_step_size": 0.0}, "initial_step_size"),
        ({"backtracking_factor": 0.0}, "backtracking_factor"),
        ({"backtracking_factor": 1.0}, "backtracking_factor"),
        ({"armijo_constant": 0.0}, "armijo_constant"),
        ({"armijo_constant": 1.0}, "armijo_constant"),
        ({"gradient_tolerance": -1.0}, "gradient_tolerance"),
        ({"minimum_step_size": 0.0}, "minimum_step_size"),
        ({"minimum_step_size": 0.2, "initial_step_size": 0.1}, "minimum_step_size"),
    ],
)
def test_invalid_optimizer_settings_fail_explicitly(
    override: dict,
    message: str,
) -> None:
    arguments, keywords = _problem(subjects=1)

    with pytest.raises((TypeError, ValueError), match=message):
        optimize_momenta(*arguments, **keywords, **override)


def test_nonfinite_initial_momenta_fail_before_optimization() -> None:
    arguments, keywords = _problem(subjects=1)
    invalid = arguments[-1].clone()
    invalid[0, 0, 0] = torch.nan

    with pytest.raises(ValueError, match="finite"):
        optimize_momenta(*arguments[:-1], invalid, **keywords)


def test_committed_cc0_smoke_matches_versioned_evidence() -> None:
    expected = json.loads(SMOKE_FIXTURE.read_text(encoding="utf-8"))
    tool = runpy.run_path(
        str(Path(__file__).parents[1] / "tools" / "run_modern_optimizer_smoke.py")
    )
    run_smoke = tool["run_smoke"]
    observed = run_smoke()

    assert observed["schema_version"] == expected["schema_version"]
    assert observed["scientific_boundary"] == expected["scientific_boundary"]
    assert observed["inputs"] == expected["inputs"]
    assert observed["settings"] == expected["settings"]
    assert observed["result"]["termination_reason"] == "max_iterations"
    assert observed["result"]["converged"] is False
    assert (
        observed["result"]["total_line_search_evaluations"]
        == expected["result"]["total_line_search_evaluations"]
    )
    assert len(observed["result"]["momenta_sha256"]) == 64
    for actual_record, expected_record in zip(
        observed["result"]["history"],
        expected["result"]["history"],
        strict=True,
    ):
        assert actual_record["iteration"] == expected_record["iteration"]
        assert actual_record["accepted_step_size"] == expected_record["accepted_step_size"]
        assert (
            actual_record["line_search_evaluations"]
            == expected_record["line_search_evaluations"]
        )
        for name in ("objective", "attachment", "regularity", "gradient_norm"):
            assert actual_record[name] == pytest.approx(
                expected_record[name], rel=1e-10, abs=1e-12
            )
        assert actual_record["residuals"] == pytest.approx(
            expected_record["residuals"], rel=1e-10, abs=1e-12
        )
