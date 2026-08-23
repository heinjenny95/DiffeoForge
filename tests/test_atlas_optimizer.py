from __future__ import annotations

import json
import math
import runpy
from dataclasses import replace
from itertools import pairwise
from pathlib import Path

import pytest

torch = pytest.importorskip("torch")
engine = pytest.importorskip("diffeoforge.engine")

optimize_atlas = engine.optimize_atlas

DTYPE = torch.float64
REFERENCE_FIXTURE = (
    Path(__file__).parents[1]
    / "reference"
    / "modern-engine-v0.2"
    / "deformetrica-4.3.0-objective.json"
)
SMOKE_FIXTURE = (
    Path(__file__).parents[1] / "reference" / "modern-engine-v0.4" / "cc0-full-atlas-smoke.json"
)


def _problem(
    *,
    subjects: int = 2,
    identical: bool = False,
) -> tuple[tuple, dict]:
    fixture = json.loads(REFERENCE_FIXTURE.read_text(encoding="utf-8"))
    values = fixture["inputs"]
    template = torch.tensor(values["template_vertices"], dtype=DTYPE)
    reference_target = torch.tensor(values["target_vertices"], dtype=DTYPE)
    triangles = torch.tensor(values["triangles"], dtype=torch.int64)
    control_points = torch.tensor(values["control_points"], dtype=DTYPE)
    translations = (
        torch.tensor([0.0, 0.0, 0.0], dtype=DTYPE),
        torch.tensor([0.01, -0.015, 0.02], dtype=DTYPE),
    )
    target = template if identical else reference_target
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


def test_every_accepted_block_monotonically_improves_the_objective() -> None:
    arguments, keywords = _problem()

    result = optimize_atlas(
        *arguments,
        **keywords,
        max_cycles=2,
        gradient_tolerance=0.0,
    )

    assert result.termination_reason == "max_cycles"
    assert result.converged is False
    assert result.failed_block is None
    assert result.cycles_completed == 2
    assert [record.block for record in result.history[1:]] == [
        "momenta",
        "template",
        "control_points",
        "momenta",
        "template",
        "control_points",
    ]
    assert all(record.status == "accepted" for record in result.history[1:])
    assert all(later.objective > earlier.objective for earlier, later in pairwise(result.history))
    assert all(
        record.objective == pytest.approx(record.attachment + record.regularity)
        for record in result.history
    )
    assert result.total_line_search_evaluations == sum(
        record.line_search_evaluations for record in result.history
    )
    decisions = len(result.history) - 1
    accepted = sum(record.status == "accepted" for record in result.history)
    assert result.objective_evaluations == decisions + result.total_line_search_evaluations
    assert result.gradient_evaluations == decisions + accepted
    assert result.candidate_gradient_evaluations == accepted
    assert result.settings.max_cycles == 2
    assert result.settings.block_order == ("momenta", "template", "control_points")
    assert result.settings.momenta_step_size == 0.1
    assert result.settings.step_initialization == "fixed"
    assert result.settings.direction_update == "steepest"
    assert result.settings.lbfgs_history_size == 10
    assert result.settings.lbfgs_initial_step_size == 1.0
    assert result.settings.relative_objective_tolerance is None


def test_previous_accepted_step_avoids_repeating_rejected_candidates() -> None:
    arguments, keywords = _problem()

    fixed = optimize_atlas(
        *arguments,
        **keywords,
        max_cycles=4,
        block_order=("momenta",),
        gradient_tolerance=0.0,
        step_initialization="fixed",
    )
    reused = optimize_atlas(
        *arguments,
        **keywords,
        max_cycles=4,
        block_order=("momenta",),
        gradient_tolerance=0.0,
        step_initialization="previous_accepted",
    )

    assert reused.settings.step_initialization == "previous_accepted"
    assert reused.total_line_search_evaluations < fixed.total_line_search_evaluations
    assert all(later.objective > earlier.objective for earlier, later in pairwise(reused.history))
    accepted_steps = [record.accepted_step_size for record in reused.history[1:]]
    assert accepted_steps == sorted(accepted_steps, reverse=True)
    accepted = sum(record.status == "accepted" for record in reused.history)
    assert reused.objective_evaluations == 1 + reused.total_line_search_evaluations
    assert reused.gradient_evaluations == 1 + accepted
    assert reused.candidate_gradient_evaluations == accepted


def test_lbfgs_direction_is_deterministic_monotone_and_improves_after_ten_cycles() -> None:
    arguments, keywords = _problem(subjects=1)

    steepest = optimize_atlas(
        *arguments,
        **keywords,
        max_cycles=10,
        block_order=("momenta",),
        gradient_tolerance=0.0,
        step_initialization="previous_accepted",
        direction_update="steepest",
    )
    first = optimize_atlas(
        *arguments,
        **keywords,
        max_cycles=10,
        block_order=("momenta",),
        gradient_tolerance=0.0,
        step_initialization="previous_accepted",
        direction_update="lbfgs",
        lbfgs_history_size=5,
    )
    second = optimize_atlas(
        *arguments,
        **keywords,
        max_cycles=10,
        block_order=("momenta",),
        gradient_tolerance=0.0,
        step_initialization="previous_accepted",
        direction_update="lbfgs",
        lbfgs_history_size=5,
    )

    assert first.settings.direction_update == "lbfgs"
    assert first.settings.lbfgs_history_size == 5
    assert first.history == second.history
    assert torch.equal(first.momenta, second.momenta)
    assert all(later.objective > earlier.objective for earlier, later in pairwise(first.history))
    assert first.history[-1].objective > steepest.history[-1].objective
    assert first.history[-1].gradient_norm < steepest.history[-1].gradient_norm


def test_lbfgs_reaches_declared_tolerance_that_steepest_does_not() -> None:
    arguments, keywords = _problem(subjects=1)
    shared = {
        "max_cycles": 35,
        "block_order": ("momenta",),
        "gradient_tolerance": 1e-4,
        "step_initialization": "previous_accepted",
    }

    steepest = optimize_atlas(
        *arguments,
        **keywords,
        **shared,
        direction_update="steepest",
    )
    lbfgs = optimize_atlas(
        *arguments,
        **keywords,
        **shared,
        direction_update="lbfgs",
        lbfgs_history_size=5,
    )

    assert steepest.converged is False
    assert steepest.termination_reason == "max_cycles"
    assert lbfgs.converged is True
    assert lbfgs.termination_reason == "gradient_tolerance"
    assert lbfgs.history[-1].status == "stationary"
    assert lbfgs.history[-1].gradient_norm <= 1e-4
    assert lbfgs.cycles_completed < steepest.cycles_completed


def test_relative_objective_tolerance_matches_deformetrica_change_ratio() -> None:
    arguments, keywords = _problem(subjects=1)
    tolerance = 0.1

    result = optimize_atlas(
        *arguments,
        **keywords,
        max_cycles=35,
        block_order=("momenta",),
        gradient_tolerance=0.0,
        step_initialization="previous_accepted",
        direction_update="lbfgs",
        lbfgs_history_size=5,
        relative_objective_tolerance=tolerance,
    )

    assert result.converged is True
    assert result.termination_reason == "relative_objective_tolerance"
    assert result.cycles_completed == 5
    objectives = [record.objective for record in result.history]
    initial = objectives[0]
    for previous, current in pairwise(objectives[:-1]):
        assert abs(current - previous) >= tolerance * abs(current - initial)
    assert abs(objectives[-1] - objectives[-2]) < tolerance * abs(objectives[-1] - initial)


def test_lbfgs_resume_state_reproduces_an_uninterrupted_trajectory_exactly() -> None:
    arguments, keywords = _problem(subjects=1)
    settings = {
        "block_order": ("momenta",),
        "gradient_tolerance": 0.0,
        "step_initialization": "previous_accepted",
        "direction_update": "lbfgs",
        "lbfgs_history_size": 5,
        "line_search_condition": "strong_wolfe",
        "strong_wolfe_curvature_constant": 0.9,
        "strong_wolfe_maximum_step_size": 10.0,
        "relative_objective_tolerance": 1e-12,
    }
    uninterrupted = optimize_atlas(
        *arguments,
        **keywords,
        **settings,
        max_cycles=12,
    )
    checkpoints = []
    first = optimize_atlas(
        *arguments,
        **keywords,
        **settings,
        max_cycles=5,
        checkpoint_callback=checkpoints.append,
    )
    checkpoint = checkpoints[-1]
    resume_state = engine.AtlasOptimizerResumeState(
        initial_cycle_objective=checkpoint.initial_cycle_objective,
        current_cycle_objective=checkpoint.current_cycle_objective,
        next_step_sizes=checkpoint.next_step_sizes,
        lbfgs_history=checkpoint.lbfgs_history,
        reusable_gradient=checkpoint.reusable_gradient,
        completed_cycle_termination_reason=checkpoint.completed_cycle_termination_reason,
    )
    resumed = optimize_atlas(
        checkpoint.template_vertices,
        arguments[1],
        arguments[2],
        checkpoint.control_points,
        checkpoint.momenta,
        **keywords,
        **settings,
        max_cycles=7,
        resume_state=resume_state,
    )

    assert first.history == uninterrupted.history[:6]
    assert resumed.history[0].objective == checkpoint.record.objective
    uninterrupted_tail = [
        replace(record, cycle=index) for index, record in enumerate(uninterrupted.history[6:], 1)
    ]
    assert uninterrupted_tail == list(resumed.history[1:])
    assert torch.equal(resumed.template_vertices, uninterrupted.template_vertices)
    assert torch.equal(resumed.control_points, uninterrupted.control_points)
    assert torch.equal(resumed.momenta, uninterrupted.momenta)


def test_resume_state_preserves_a_completed_cycle_convergence_decision() -> None:
    arguments, keywords = _problem(subjects=1)
    checkpoints = []
    settings = {
        "block_order": ("momenta",),
        "gradient_tolerance": 0.0,
        "step_initialization": "previous_accepted",
        "direction_update": "lbfgs",
        "lbfgs_history_size": 5,
        "relative_objective_tolerance": 0.1,
    }
    converged = optimize_atlas(
        *arguments,
        **keywords,
        **settings,
        max_cycles=35,
        checkpoint_callback=checkpoints.append,
    )
    checkpoint = checkpoints[-1]
    assert checkpoint.completed_cycle_termination_reason == "relative_objective_tolerance"

    resumed = optimize_atlas(
        checkpoint.template_vertices,
        arguments[1],
        arguments[2],
        checkpoint.control_points,
        checkpoint.momenta,
        **keywords,
        **settings,
        max_cycles=10,
        resume_state=engine.AtlasOptimizerResumeState(
            initial_cycle_objective=checkpoint.initial_cycle_objective,
            current_cycle_objective=checkpoint.current_cycle_objective,
            next_step_sizes=checkpoint.next_step_sizes,
            lbfgs_history=checkpoint.lbfgs_history,
            reusable_gradient=checkpoint.reusable_gradient,
            completed_cycle_termination_reason=checkpoint.completed_cycle_termination_reason,
        ),
    )

    assert resumed.converged is True
    assert resumed.termination_reason == "relative_objective_tolerance"
    assert resumed.cycles_completed == 0
    assert len(resumed.history) == 1
    assert torch.equal(resumed.momenta, converged.momenta)


def test_strong_wolfe_lbfgs_is_repeatable_monotone_and_uses_gradient_trials() -> None:
    arguments, keywords = _problem(subjects=1)
    settings = {
        "max_cycles": 12,
        "block_order": ("momenta",),
        "gradient_tolerance": 0.0,
        "step_initialization": "previous_accepted",
        "direction_update": "lbfgs",
        "lbfgs_history_size": 5,
        "line_search_condition": "strong_wolfe",
        "strong_wolfe_curvature_constant": 0.9,
        "strong_wolfe_maximum_step_size": 10.0,
    }

    first = optimize_atlas(*arguments, **keywords, **settings)
    second = optimize_atlas(*arguments, **keywords, **settings)

    assert first.settings.line_search_condition == "strong_wolfe"
    assert first.settings.strong_wolfe_curvature_constant == 0.9
    assert first.settings.strong_wolfe_maximum_step_size == 10.0
    assert first.history == second.history
    assert torch.equal(first.momenta, second.momenta)
    assert first.termination_reason == "max_cycles"
    assert all(later.objective > earlier.objective for earlier, later in pairwise(first.history))
    assert first.candidate_gradient_evaluations == first.total_line_search_evaluations
    assert first.gradient_evaluations == 1 + first.total_line_search_evaluations
    assert all(
        record.accepted_step_size is None or record.accepted_step_size <= 10.0
        for record in first.history
    )


def test_single_block_boundary_reuse_preserves_fresh_cycle_decisions_exactly() -> None:
    arguments, keywords = _problem(subjects=1)
    combined = optimize_atlas(
        *arguments,
        **keywords,
        max_cycles=3,
        block_order=("momenta",),
        gradient_tolerance=0.0,
    )

    momenta = arguments[4]
    restarted_records = []
    restarted_objective_evaluations = 0
    restarted_gradient_evaluations = 0
    for _ in range(3):
        restarted = optimize_atlas(
            *arguments[:4],
            momenta,
            **keywords,
            max_cycles=1,
            block_order=("momenta",),
            gradient_tolerance=0.0,
        )
        momenta = restarted.momenta
        restarted_records.append(restarted.history[-1])
        restarted_objective_evaluations += restarted.objective_evaluations
        restarted_gradient_evaluations += restarted.gradient_evaluations

    combined_records = combined.history[1:]
    assert torch.equal(combined.momenta, momenta)
    assert [record.status for record in combined_records] == [
        record.status for record in restarted_records
    ]
    assert [record.objective for record in combined_records] == [
        record.objective for record in restarted_records
    ]
    assert [record.gradient_norm for record in combined_records] == [
        record.gradient_norm for record in restarted_records
    ]
    assert [record.accepted_step_size for record in combined_records] == [
        record.accepted_step_size for record in restarted_records
    ]
    assert [record.line_search_evaluations for record in combined_records] == [
        record.line_search_evaluations for record in restarted_records
    ]
    assert combined.objective_evaluations == restarted_objective_evaluations - 2
    assert combined.gradient_evaluations == restarted_gradient_evaluations - 2


def test_optimizer_is_repeatable_detached_and_does_not_mutate_inputs() -> None:
    arguments, keywords = _problem()
    originals = tuple(
        value.clone() if isinstance(value, torch.Tensor) else value for value in arguments
    )

    first = optimize_atlas(*arguments, **keywords, max_cycles=2)
    second = optimize_atlas(*arguments, **keywords, max_cycles=2)

    for original, observed in zip(originals, arguments, strict=True):
        if isinstance(original, torch.Tensor):
            assert torch.equal(observed, original)
    assert torch.equal(first.template_vertices, second.template_vertices)
    assert torch.equal(first.control_points, second.control_points)
    assert torch.equal(first.momenta, second.momenta)
    assert first.history == second.history
    for tensor, source in zip(
        (first.template_vertices, first.control_points, first.momenta),
        (arguments[0], arguments[3], arguments[4]),
        strict=True,
    ):
        assert tensor.requires_grad is False
        assert tensor.shape == source.shape
        assert tensor.dtype == source.dtype
        assert tensor.device == source.device


def test_progress_observer_mirrors_committed_history_without_changing_results() -> None:
    arguments, keywords = _problem()
    observed = []

    with_progress = optimize_atlas(
        *arguments,
        **keywords,
        max_cycles=2,
        progress_callback=observed.append,
    )
    without_progress = optimize_atlas(*arguments, **keywords, max_cycles=2)

    assert tuple(observed) == with_progress.history
    assert with_progress.history == without_progress.history
    assert torch.equal(with_progress.template_vertices, without_progress.template_vertices)
    assert torch.equal(with_progress.control_points, without_progress.control_points)
    assert torch.equal(with_progress.momenta, without_progress.momenta)


def test_cycle_checkpoint_is_detached_complete_and_cannot_mutate_optimizer() -> None:
    arguments, keywords = _problem()
    observed = []

    def checkpoint(value) -> None:
        observed.append(
            (
                value.record,
                value.template_vertices.clone(),
                value.control_points.clone(),
                value.momenta.clone(),
                dict(value.next_step_sizes),
            )
        )
        value.template_vertices.add_(1000.0)
        value.control_points.add_(1000.0)
        value.momenta.add_(1000.0)
        value.next_step_sizes["momenta"] = 1000.0

    with_checkpoints = optimize_atlas(
        *arguments,
        **keywords,
        max_cycles=2,
        step_initialization="previous_accepted",
        checkpoint_callback=checkpoint,
    )
    without_checkpoints = optimize_atlas(
        *arguments,
        **keywords,
        max_cycles=2,
        step_initialization="previous_accepted",
    )

    assert [item[0].cycle for item in observed] == [1, 2]
    assert all(item[0].block == "control_points" for item in observed)
    assert torch.equal(observed[-1][1], without_checkpoints.template_vertices)
    assert torch.equal(observed[-1][2], without_checkpoints.control_points)
    assert torch.equal(observed[-1][3], without_checkpoints.momenta)
    assert set(observed[-1][4]) == {"momenta", "template", "control_points"}
    assert with_checkpoints.history == without_checkpoints.history
    assert torch.equal(with_checkpoints.template_vertices, without_checkpoints.template_vertices)
    assert torch.equal(with_checkpoints.control_points, without_checkpoints.control_points)
    assert torch.equal(with_checkpoints.momenta, without_checkpoints.momenta)


def test_cooperative_cancellation_stops_before_an_uncommitted_block() -> None:
    arguments, keywords = _problem()
    observed = []
    cancellation = {"requested": False}

    def observe(record) -> None:
        observed.append(record)
        cancellation["requested"] = True

    with pytest.raises(engine.AtlasOptimizationCancelled, match="cancellation requested"):
        optimize_atlas(
            *arguments,
            **keywords,
            max_cycles=2,
            progress_callback=observe,
            cancel_requested=lambda: cancellation["requested"],
        )

    assert [record.status for record in observed] == ["initial"]


def test_cancellation_callback_must_return_bool() -> None:
    arguments, keywords = _problem(subjects=1)

    with pytest.raises(TypeError, match="must return bool"):
        optimize_atlas(*arguments, **keywords, cancel_requested=lambda: 1)


def test_checkpoint_callback_must_be_callable() -> None:
    arguments, keywords = _problem(subjects=1)

    with pytest.raises(TypeError, match="checkpoint_callback"):
        optimize_atlas(*arguments, **keywords, checkpoint_callback=1)


def test_progress_observer_reports_failed_decision_not_rejected_candidates() -> None:
    arguments, keywords = _problem(subjects=1)
    observed = []

    result = optimize_atlas(
        *arguments,
        **keywords,
        max_cycles=3,
        momenta_step_size=10.0,
        template_step_size=10.0,
        control_points_step_size=10.0,
        max_line_search_iterations=1,
        progress_callback=observed.append,
    )

    assert [record.status for record in observed] == ["initial", "failed"]
    assert tuple(observed) == result.history
    assert result.total_line_search_evaluations == 1


def test_identical_subject_is_stationary_for_every_block() -> None:
    arguments, keywords = _problem(subjects=1, identical=True)

    result = optimize_atlas(*arguments, **keywords, max_cycles=5)

    assert result.termination_reason == "gradient_tolerance"
    assert result.converged is True
    assert result.cycles_completed == 1
    assert [record.status for record in result.history] == [
        "initial",
        "stationary",
        "stationary",
        "stationary",
    ]
    assert all((record.gradient_norm or 0.0) < 1e-8 for record in result.history[1:])
    assert torch.equal(result.template_vertices, arguments[0])
    assert torch.equal(result.control_points, arguments[3])
    assert torch.equal(result.momenta, arguments[4])


def test_zero_cycles_returns_fully_evaluated_initial_state() -> None:
    arguments, keywords = _problem(subjects=1)

    result = optimize_atlas(*arguments, **keywords, max_cycles=0)

    assert result.termination_reason == "max_cycles"
    assert result.cycles_completed == 0
    assert len(result.history) == 1
    assert result.history[0].status == "initial"
    assert math.isfinite(result.history[0].objective)
    assert result.total_line_search_evaluations == 0
    assert result.objective_evaluations == 1
    assert result.gradient_evaluations == 1
    assert result.candidate_gradient_evaluations == 0


def test_failed_first_block_preserves_all_initial_parameters() -> None:
    arguments, keywords = _problem(subjects=1)

    result = optimize_atlas(
        *arguments,
        **keywords,
        max_cycles=3,
        momenta_step_size=10.0,
        template_step_size=10.0,
        control_points_step_size=10.0,
        max_line_search_iterations=1,
    )

    assert result.termination_reason == "line_search_failed"
    assert result.failed_block == "momenta"
    assert result.cycles_completed == 0
    assert result.history[-1].status == "failed"
    assert result.history[-1].line_search_evaluations == 1
    assert torch.equal(result.template_vertices, arguments[0])
    assert torch.equal(result.control_points, arguments[3])
    assert torch.equal(result.momenta, arguments[4])


def test_rejected_atlas_candidate_does_not_request_an_unused_gradient(
    monkeypatch,
) -> None:
    arguments, keywords = _problem(subjects=1)
    original_grad = torch.autograd.grad
    calls = 0

    def counted_grad(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original_grad(*args, **kwargs)

    monkeypatch.setattr(torch.autograd, "grad", counted_grad)
    result = optimize_atlas(
        *arguments,
        **keywords,
        max_cycles=3,
        momenta_step_size=10.0,
        template_step_size=10.0,
        control_points_step_size=10.0,
        max_line_search_iterations=1,
    )

    assert result.termination_reason == "line_search_failed"
    assert result.total_line_search_evaluations == 1
    assert result.objective_evaluations == 2
    assert result.gradient_evaluations == 1
    assert result.candidate_gradient_evaluations == 0
    assert calls == 1


def test_all_parameter_blocks_move_on_a_nontrivial_problem() -> None:
    arguments, keywords = _problem()
    template, _, _, control_points, momenta = arguments

    result = optimize_atlas(*arguments, **keywords, max_cycles=2)

    assert torch.linalg.vector_norm(result.template_vertices - template) > 0
    assert torch.linalg.vector_norm(result.control_points - control_points) > 0
    assert torch.linalg.vector_norm(result.momenta - momenta) > 0


def test_translated_subject_moves_template_toward_the_declared_translation() -> None:
    arguments, keywords = _problem(subjects=1, identical=True)
    template, triangles, _, control_points, momenta = arguments
    translation = torch.tensor([0.03, -0.02, 0.04], dtype=DTYPE)

    result = optimize_atlas(
        template,
        triangles,
        ((template + translation, triangles),),
        control_points,
        momenta,
        **keywords,
        max_cycles=1,
        gradient_tolerance=0.0,
    )

    mean_template_displacement = torch.mean(result.template_vertices - template, dim=0)
    assert torch.dot(mean_template_displacement, translation) > 0
    assert torch.linalg.vector_norm(result.control_points - control_points) > 0
    assert result.history[1].block == "momenta"
    assert result.history[1].status == "accepted"


def test_declared_block_order_is_honored() -> None:
    arguments, keywords = _problem()

    result = optimize_atlas(
        *arguments,
        **keywords,
        max_cycles=1,
        block_order=("template", "momenta", "control_points"),
    )

    assert [record.block for record in result.history[1:]] == [
        "template",
        "momenta",
        "control_points",
    ]


def test_optimizer_remains_differentiable_internally_under_no_grad() -> None:
    arguments, keywords = _problem(subjects=1)

    with torch.no_grad():
        result = optimize_atlas(*arguments, **keywords, max_cycles=1)

    assert any(record.status == "accepted" for record in result.history)
    assert result.history[-1].objective > result.history[0].objective


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"max_cycles": -1}, "max_cycles"),
        ({"max_line_search_iterations": 0}, "max_line_search_iterations"),
        ({"momenta_step_size": 0.0}, "momenta_step_size"),
        ({"template_step_size": 0.0}, "template_step_size"),
        ({"control_points_step_size": 0.0}, "control_points_step_size"),
        ({"backtracking_factor": 0.0}, "backtracking_factor"),
        ({"backtracking_factor": 1.0}, "backtracking_factor"),
        ({"armijo_constant": 0.0}, "armijo_constant"),
        ({"gradient_tolerance": -1.0}, "gradient_tolerance"),
        ({"minimum_step_size": 0.0}, "minimum_step_size"),
        ({"minimum_step_size": 0.02, "template_step_size": 0.01}, "minimum_step_size"),
        (
            {"block_order": ("momenta", "template", "template")},
            "block_order",
        ),
        ({"step_initialization": "automatic"}, "step_initialization"),
        ({"direction_update": "automatic"}, "direction_update"),
        ({"direction_update": "lbfgs"}, "exactly one parameter block"),
        ({"line_search_condition": "automatic"}, "line_search_condition"),
        ({"line_search_condition": "strong_wolfe"}, "requires direction_update=lbfgs"),
        ({"lbfgs_history_size": 0}, "lbfgs_history_size"),
        ({"lbfgs_curvature_tolerance": -1.0}, "lbfgs_curvature_tolerance"),
        ({"lbfgs_initial_step_size": 0.0}, "lbfgs_initial_step_size"),
        ({"strong_wolfe_curvature_constant": 0.0}, "strong_wolfe_curvature_constant"),
        (
            {"strong_wolfe_maximum_step_size": 0.5},
            "strong_wolfe_maximum_step_size",
        ),
        ({"relative_objective_tolerance": 0.0}, "relative_objective_tolerance"),
        ({"relative_objective_tolerance": 1.0}, "relative_objective_tolerance"),
    ],
)
def test_invalid_optimizer_settings_fail_explicitly(override: dict, message: str) -> None:
    arguments, keywords = _problem(subjects=1)

    with pytest.raises((TypeError, ValueError), match=message):
        optimize_atlas(*arguments, **keywords, **override)


def test_nonfinite_initial_parameter_fails_before_optimization() -> None:
    arguments, keywords = _problem(subjects=1)
    invalid_template = arguments[0].clone()
    invalid_template[0, 0] = torch.nan

    with pytest.raises(ValueError, match="finite"):
        optimize_atlas(invalid_template, *arguments[1:], **keywords)


def test_committed_cc0_full_atlas_smoke_matches_versioned_evidence() -> None:
    expected = json.loads(SMOKE_FIXTURE.read_text(encoding="utf-8"))
    tool = runpy.run_path(
        str(Path(__file__).parents[1] / "tools" / "run_full_atlas_optimizer_smoke.py")
    )
    observed = tool["run_smoke"]()

    assert observed["schema_version"] == expected["schema_version"]
    assert observed["scientific_boundary"] == expected["scientific_boundary"]
    assert observed["inputs"] == expected["inputs"]
    assert observed["settings"] == expected["settings"]
    assert observed["result"]["termination_reason"] == "max_cycles"
    assert observed["result"]["converged"] is False
    assert observed["result"]["failed_block"] is None
    assert observed["result"]["cycles_completed"] == 3
    assert (
        observed["result"]["total_line_search_evaluations"]
        == expected["result"]["total_line_search_evaluations"]
    )
    assert all(len(value) == 64 for value in observed["result"]["parameter_sha256"].values())
    for name, value in observed["result"]["parameter_delta_norms"].items():
        assert value == pytest.approx(
            expected["result"]["parameter_delta_norms"][name],
            rel=1e-9,
            abs=1e-12,
        )
        assert value > 0
    for actual_record, expected_record in zip(
        observed["result"]["history"],
        expected["result"]["history"],
        strict=True,
    ):
        for name in (
            "cycle",
            "block",
            "status",
            "accepted_step_size",
            "line_search_evaluations",
        ):
            assert actual_record[name] == expected_record[name]
        for name in ("objective", "attachment", "regularity", "gradient_norm"):
            assert actual_record[name] == pytest.approx(expected_record[name], rel=1e-9, abs=1e-11)
        assert actual_record["residuals"] == pytest.approx(
            expected_record["residuals"], rel=1e-9, abs=1e-11
        )
