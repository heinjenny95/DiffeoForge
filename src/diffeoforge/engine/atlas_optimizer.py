"""Deterministic block-coordinate optimizer for the experimental atlas engine."""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from numbers import Integral, Real
from typing import Literal

import torch

from diffeoforge.engine.dense import (
    GaussianTilePlan,
    PreparedSurfaceAttachmentTarget,
    prepare_surface_attachment_target,
)
from diffeoforge.engine.objective import (
    AttachmentType,
    FlowIntegrator,
    ShootingIntegrator,
    atlas_objective,
)

AtlasParameterBlock = Literal["momenta", "template", "control_points"]
AtlasStepInitialization = Literal["fixed", "previous_accepted"]
AtlasDirectionUpdate = Literal["steepest", "lbfgs"]
AtlasLineSearchCondition = Literal["armijo", "strong_wolfe"]
AtlasAttemptStatus = Literal["initial", "accepted", "stationary", "failed"]
AtlasTerminationReason = Literal[
    "gradient_tolerance",
    "relative_objective_tolerance",
    "max_cycles",
    "line_search_failed",
]
AtlasCompletedCycleTerminationReason = Literal[
    "gradient_tolerance",
    "relative_objective_tolerance",
]

_ALL_BLOCKS: tuple[AtlasParameterBlock, ...] = (
    "momenta",
    "template",
    "control_points",
)


@dataclass(frozen=True)
class AtlasOptimizationRecord:
    """One observable optimizer decision and the resulting accepted state."""

    cycle: int
    block: AtlasParameterBlock | None
    status: AtlasAttemptStatus
    objective: float
    attachment: float
    regularity: float
    residuals: tuple[float, ...]
    gradient_norm: float | None
    accepted_step_size: float | None
    line_search_evaluations: int


AtlasProgressCallback = Callable[[AtlasOptimizationRecord], None]
AtlasCancellationCallback = Callable[[], bool]


class AtlasOptimizationCancelled(RuntimeError):
    """Raised when a caller requests cancellation at a safe optimizer boundary."""


@dataclass(frozen=True)
class AtlasCycleCheckpoint:
    """Detached state committed after one complete optimizer cycle."""

    record: AtlasOptimizationRecord
    template_vertices: torch.Tensor
    control_points: torch.Tensor
    momenta: torch.Tensor
    next_step_sizes: dict[AtlasParameterBlock, float]
    initial_cycle_objective: float
    prior_cycle_objective: float
    current_cycle_objective: float
    lbfgs_history: tuple[tuple[torch.Tensor, torch.Tensor], ...]
    reusable_gradient: torch.Tensor | None
    completed_cycle_termination_reason: AtlasCompletedCycleTerminationReason | None


@dataclass(frozen=True)
class AtlasOptimizerResumeState:
    """Exact optimizer state required after one complete accepted cycle."""

    initial_cycle_objective: float
    current_cycle_objective: float
    next_step_sizes: dict[AtlasParameterBlock, float]
    lbfgs_history: tuple[tuple[torch.Tensor, torch.Tensor], ...] = ()
    reusable_gradient: torch.Tensor | None = None
    completed_cycle_termination_reason: AtlasCompletedCycleTerminationReason | None = None


AtlasCheckpointCallback = Callable[[AtlasCycleCheckpoint], None]


@dataclass(frozen=True)
class AtlasOptimizerSettings:
    """Normalized settings that fully declare the transparent optimizer."""

    max_cycles: int
    block_order: tuple[AtlasParameterBlock, ...]
    momenta_step_size: float
    template_step_size: float
    control_points_step_size: float
    backtracking_factor: float
    armijo_constant: float
    gradient_tolerance: float
    minimum_step_size: float
    max_line_search_iterations: int
    step_initialization: AtlasStepInitialization = "fixed"
    direction_update: AtlasDirectionUpdate = "steepest"
    lbfgs_history_size: int = 10
    lbfgs_curvature_tolerance: float = 1e-12
    lbfgs_initial_step_size: float = 1.0
    line_search_condition: AtlasLineSearchCondition = "armijo"
    strong_wolfe_curvature_constant: float = 0.9
    strong_wolfe_maximum_step_size: float = 10.0
    relative_objective_tolerance: float | None = None
    subject_batch_size: int | None = None


@dataclass(frozen=True)
class AtlasOptimizationResult:
    """Detached final atlas parameters and the complete block-decision history."""

    template_vertices: torch.Tensor
    control_points: torch.Tensor
    momenta: torch.Tensor
    history: tuple[AtlasOptimizationRecord, ...]
    termination_reason: AtlasTerminationReason
    converged: bool
    failed_block: AtlasParameterBlock | None
    cycles_completed: int
    total_line_search_evaluations: int
    settings: AtlasOptimizerSettings
    objective_evaluations: int = 0
    gradient_evaluations: int = 0
    candidate_gradient_evaluations: int = 0


@dataclass(frozen=True)
class _State:
    template_vertices: torch.Tensor
    control_points: torch.Tensor
    momenta: torch.Tensor
    objective: torch.Tensor
    attachment: torch.Tensor
    regularity: torch.Tensor
    residuals: torch.Tensor

    def record(
        self,
        cycle: int,
        *,
        block: AtlasParameterBlock | None,
        status: AtlasAttemptStatus,
        gradient_norm: torch.Tensor | None,
        accepted_step_size: float | None,
        line_search_evaluations: int,
    ) -> AtlasOptimizationRecord:
        return AtlasOptimizationRecord(
            cycle=cycle,
            block=block,
            status=status,
            objective=float(self.objective),
            attachment=float(self.attachment),
            regularity=float(self.regularity),
            residuals=tuple(float(value) for value in self.residuals),
            gradient_norm=None if gradient_norm is None else float(gradient_norm),
            accepted_step_size=accepted_step_size,
            line_search_evaluations=line_search_evaluations,
        )


@dataclass(frozen=True)
class _BlockEvaluation:
    state: _State
    gradient: torch.Tensor
    gradient_norm: torch.Tensor


@dataclass(frozen=True)
class _PendingBlockEvaluation:
    """One finite objective graph whose block gradient has not been requested."""

    state: _State
    total: torch.Tensor
    variable: torch.Tensor | None
    block: AtlasParameterBlock


def _integer(name: str, value: int, *, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral):
        raise TypeError(f"{name} must be an integer")
    normalized = int(value)
    if normalized < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    return normalized


def _finite_real(
    name: str,
    value: float,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
    inclusive_minimum: bool = False,
) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError(f"{name} must be a real scalar")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ValueError(f"{name} must be finite")
    if minimum is not None:
        invalid = normalized < minimum if inclusive_minimum else normalized <= minimum
        if invalid:
            comparison = "at least" if inclusive_minimum else "greater than"
            raise ValueError(f"{name} must be {comparison} {minimum}")
    if maximum is not None and normalized >= maximum:
        raise ValueError(f"{name} must be less than {maximum}")
    return normalized


def _block_order(value: Sequence[str]) -> tuple[AtlasParameterBlock, ...]:
    if isinstance(value, (str, bytes)):
        raise TypeError("block_order must be a sequence of parameter-block names")
    normalized = tuple(value)
    if (
        not normalized
        or len(normalized) != len(set(normalized))
        or not set(normalized) <= set(_ALL_BLOCKS)
    ):
        raise ValueError(
            "block_order must contain one or more unique entries selected from "
            "momenta, template, and control_points"
        )
    return normalized  # type: ignore[return-value]


def _lbfgs_ascent_direction(
    gradient: torch.Tensor,
    history: Sequence[tuple[torch.Tensor, torch.Tensor]],
) -> torch.Tensor:
    """Return an L-BFGS ascent direction for a maximization objective.

    The stored ``y`` values are gradients of the equivalent minimization
    objective ``-f``. The standard two-loop recursion therefore operates on
    ``-gradient`` and its negated result is an ascent direction for ``f``.
    A non-finite or non-ascent result fails closed to steepest ascent.
    """

    if not history:
        return gradient
    q = -gradient.clone()
    reverse_alphas: list[torch.Tensor] = []
    for step, gradient_delta in reversed(history):
        inverse_curvature = torch.reciprocal(torch.sum(step * gradient_delta))
        alpha = inverse_curvature * torch.sum(step * q)
        reverse_alphas.append(alpha)
        q = q - alpha * gradient_delta
    last_step, last_gradient_delta = history[-1]
    scale = torch.sum(last_step * last_gradient_delta) / torch.sum(last_gradient_delta.square())
    inverse_hessian_gradient = scale * q
    for (step, gradient_delta), alpha in zip(
        history,
        reversed(reverse_alphas),
        strict=True,
    ):
        inverse_curvature = torch.reciprocal(torch.sum(step * gradient_delta))
        beta = inverse_curvature * torch.sum(gradient_delta * inverse_hessian_gradient)
        inverse_hessian_gradient = inverse_hessian_gradient + step * (alpha - beta)
    direction = -inverse_hessian_gradient
    directional_derivative = torch.sum(gradient * direction)
    if (
        not bool(torch.isfinite(direction).all())
        or not bool(torch.isfinite(directional_derivative))
        or float(directional_derivative) <= 0.0
    ):
        return gradient
    return direction


def _strong_wolfe_ascent_search(
    initial: _BlockEvaluation,
    direction: torch.Tensor,
    *,
    initial_step_size: float,
    minimum_step_size: float,
    maximum_step_size: float,
    armijo_constant: float,
    curvature_constant: float,
    maximum_evaluations: int,
    evaluate: Callable[[float], _BlockEvaluation | None],
) -> tuple[_BlockEvaluation | None, float | None, int]:
    """Bracket and bisect a step satisfying the strong Wolfe conditions.

    The implementation is expressed for maximization. Trial points must satisfy
    sufficient increase and reduce the absolute directional derivative. Every
    trial requests both objective and gradient evidence; no objective-only
    candidate can be accepted. Invalid trial states behave as an upper bracket.
    """

    initial_derivative = float(torch.sum(initial.gradient * direction))
    if not math.isfinite(initial_derivative) or initial_derivative <= 0.0:
        return None, None, 0
    initial_objective = float(initial.state.objective)

    def sufficient_increase(step_size: float, objective: float) -> bool:
        required = initial_objective + armijo_constant * step_size * initial_derivative
        return objective >= required

    def curvature_satisfied(derivative: float) -> bool:
        return abs(derivative) <= curvature_constant * initial_derivative

    evaluations = 0
    previous_step = 0.0
    previous_evaluation = initial
    step_size = min(initial_step_size, maximum_step_size)
    bracket: tuple[float, _BlockEvaluation, float, _BlockEvaluation | None] | None = None

    while evaluations < maximum_evaluations:
        if step_size < minimum_step_size:
            break
        candidate = evaluate(step_size)
        evaluations += 1
        if candidate is None:
            bracket = (previous_step, previous_evaluation, step_size, None)
            break
        candidate_objective = float(candidate.state.objective)
        candidate_derivative = float(torch.sum(candidate.gradient * direction))
        if not math.isfinite(candidate_derivative):
            bracket = (previous_step, previous_evaluation, step_size, None)
            break
        if not sufficient_increase(step_size, candidate_objective) or (
            previous_step > 0.0
            and candidate_objective <= float(previous_evaluation.state.objective)
        ):
            bracket = (previous_step, previous_evaluation, step_size, candidate)
            break
        if curvature_satisfied(candidate_derivative):
            return candidate, step_size, evaluations
        if candidate_derivative <= 0.0:
            bracket = (step_size, candidate, previous_step, previous_evaluation)
            break
        if step_size >= maximum_step_size:
            break
        previous_step = step_size
        previous_evaluation = candidate
        step_size = min(step_size * 2.0, maximum_step_size)

    while bracket is not None and evaluations < maximum_evaluations:
        first_step, first_evaluation, second_step, second_evaluation = bracket
        if abs(second_step - first_step) < minimum_step_size:
            break
        if second_evaluation is not None and float(second_evaluation.state.objective) > float(
            first_evaluation.state.objective
        ):
            low_step, low_evaluation = second_step, second_evaluation
            high_step, high_evaluation = first_step, first_evaluation
        else:
            low_step, low_evaluation = first_step, first_evaluation
            high_step, high_evaluation = second_step, second_evaluation
        trial_step = 0.5 * (low_step + high_step)
        if trial_step < minimum_step_size:
            break
        candidate = evaluate(trial_step)
        evaluations += 1
        if candidate is None:
            bracket = (low_step, low_evaluation, trial_step, None)
            continue
        candidate_objective = float(candidate.state.objective)
        candidate_derivative = float(torch.sum(candidate.gradient * direction))
        if not math.isfinite(candidate_derivative):
            bracket = (low_step, low_evaluation, trial_step, None)
            continue
        if not sufficient_increase(trial_step, candidate_objective) or candidate_objective <= float(
            low_evaluation.state.objective
        ):
            bracket = (low_step, low_evaluation, trial_step, candidate)
            continue
        if curvature_satisfied(candidate_derivative):
            return candidate, trial_step, evaluations
        if candidate_derivative * (high_step - low_step) >= 0.0:
            high_step, high_evaluation = low_step, low_evaluation
        bracket = (trial_step, candidate, high_step, high_evaluation)

    return None, None, evaluations


def optimize_atlas(
    initial_template_vertices: torch.Tensor,
    template_triangles: torch.Tensor,
    targets: Sequence[tuple[torch.Tensor, torch.Tensor]],
    initial_control_points: torch.Tensor,
    initial_momenta: torch.Tensor,
    *,
    deformation_kernel_width: float,
    attachment_kernel_width: float,
    noise_variance: float,
    number_of_time_points: int,
    attachment_type: AttachmentType = "current",
    shooting_integrator: ShootingIntegrator = "rk2",
    flow_integrator: FlowIntegrator = "deformetrica_heun",
    gaussian_tile_plan: GaussianTilePlan | None = None,
    prepared_targets: Sequence[PreparedSurfaceAttachmentTarget] | None = None,
    max_cycles: int = 10,
    block_order: Sequence[AtlasParameterBlock] = _ALL_BLOCKS,
    momenta_step_size: float = 0.1,
    template_step_size: float = 0.01,
    control_points_step_size: float = 0.01,
    backtracking_factor: float = 0.5,
    armijo_constant: float = 1e-4,
    gradient_tolerance: float = 1e-8,
    minimum_step_size: float = 1e-12,
    max_line_search_iterations: int = 20,
    step_initialization: AtlasStepInitialization = "fixed",
    direction_update: AtlasDirectionUpdate = "steepest",
    lbfgs_history_size: int = 10,
    lbfgs_curvature_tolerance: float = 1e-12,
    lbfgs_initial_step_size: float = 1.0,
    line_search_condition: AtlasLineSearchCondition = "armijo",
    strong_wolfe_curvature_constant: float = 0.9,
    strong_wolfe_maximum_step_size: float = 10.0,
    relative_objective_tolerance: float | None = None,
    subject_batch_size: int | None = None,
    resume_state: AtlasOptimizerResumeState | None = None,
    progress_callback: AtlasProgressCallback | None = None,
    checkpoint_callback: AtlasCheckpointCallback | None = None,
    cancel_requested: AtlasCancellationCallback | None = None,
) -> AtlasOptimizationResult:
    """Maximize the atlas objective over the selected parameter blocks.

    Blocks are updated sequentially. Each accepted candidate must satisfy the
    declared ascent line-search condition. ``previous_accepted`` may
    reuse the last accepted step as the next declared line-search start; that
    state is deterministic and recorded in the accepted history. This is a
    correctness prototype, not a claim of Deformetrica optimizer-trajectory
    equivalence or production convergence.
    """

    cycles = _integer("max_cycles", max_cycles, minimum=0)
    if resume_state is not None and not isinstance(resume_state, AtlasOptimizerResumeState):
        raise TypeError("resume_state must be an AtlasOptimizerResumeState or None")
    if progress_callback is not None and not callable(progress_callback):
        raise TypeError("progress_callback must be callable or None")
    if checkpoint_callback is not None and not callable(checkpoint_callback):
        raise TypeError("checkpoint_callback must be callable or None")
    if cancel_requested is not None and not callable(cancel_requested):
        raise TypeError("cancel_requested must be callable or None")

    def check_cancellation() -> None:
        if cancel_requested is None:
            return
        requested = cancel_requested()
        if not isinstance(requested, bool):
            raise TypeError("cancel_requested must return bool")
        if requested:
            raise AtlasOptimizationCancelled("Atlas optimization cancellation requested")

    line_search_limit = _integer(
        "max_line_search_iterations", max_line_search_iterations, minimum=1
    )
    order = _block_order(block_order)
    if step_initialization not in ("fixed", "previous_accepted"):
        raise ValueError("step_initialization must be fixed or previous_accepted")
    if direction_update not in ("steepest", "lbfgs"):
        raise ValueError("direction_update must be steepest or lbfgs")
    if line_search_condition not in ("armijo", "strong_wolfe"):
        raise ValueError("line_search_condition must be armijo or strong_wolfe")
    history_size = _integer("lbfgs_history_size", lbfgs_history_size, minimum=1)
    curvature_tolerance = _finite_real(
        "lbfgs_curvature_tolerance",
        lbfgs_curvature_tolerance,
        minimum=0.0,
        inclusive_minimum=True,
    )
    lbfgs_step_size = _finite_real(
        "lbfgs_initial_step_size",
        lbfgs_initial_step_size,
        minimum=0.0,
    )
    if direction_update == "lbfgs" and len(order) != 1:
        raise ValueError("direction_update=lbfgs currently requires exactly one parameter block")
    if line_search_condition == "strong_wolfe" and direction_update != "lbfgs":
        raise ValueError(
            "line_search_condition=strong_wolfe currently requires direction_update=lbfgs"
        )
    step_sizes = {
        "momenta": _finite_real("momenta_step_size", momenta_step_size, minimum=0.0),
        "template": _finite_real("template_step_size", template_step_size, minimum=0.0),
        "control_points": _finite_real(
            "control_points_step_size", control_points_step_size, minimum=0.0
        ),
    }
    shrink = _finite_real("backtracking_factor", backtracking_factor, minimum=0.0, maximum=1.0)
    armijo = _finite_real("armijo_constant", armijo_constant, minimum=0.0, maximum=1.0)
    wolfe_curvature = _finite_real(
        "strong_wolfe_curvature_constant",
        strong_wolfe_curvature_constant,
        minimum=armijo,
        maximum=1.0,
    )
    wolfe_maximum_step = _finite_real(
        "strong_wolfe_maximum_step_size",
        strong_wolfe_maximum_step_size,
        minimum=0.0,
    )
    if wolfe_maximum_step < lbfgs_step_size:
        raise ValueError(
            "strong_wolfe_maximum_step_size must not be smaller than lbfgs_initial_step_size"
        )
    objective_change_tolerance = (
        None
        if relative_objective_tolerance is None
        else _finite_real(
            "relative_objective_tolerance",
            relative_objective_tolerance,
            minimum=0.0,
            maximum=1.0,
        )
    )
    normalized_subject_batch_size = (
        None
        if subject_batch_size is None
        else _integer("subject_batch_size", subject_batch_size, minimum=1)
    )
    gradient_threshold = _finite_real(
        "gradient_tolerance",
        gradient_tolerance,
        minimum=0.0,
        inclusive_minimum=True,
    )
    minimum_step = _finite_real("minimum_step_size", minimum_step_size, minimum=0.0)
    if any(minimum_step > step for step in step_sizes.values()):
        raise ValueError("minimum_step_size must not exceed any block step size")
    optimizer_settings = AtlasOptimizerSettings(
        max_cycles=cycles,
        block_order=order,
        momenta_step_size=step_sizes["momenta"],
        template_step_size=step_sizes["template"],
        control_points_step_size=step_sizes["control_points"],
        backtracking_factor=shrink,
        armijo_constant=armijo,
        gradient_tolerance=gradient_threshold,
        minimum_step_size=minimum_step,
        max_line_search_iterations=line_search_limit,
        step_initialization=step_initialization,
        direction_update=direction_update,
        lbfgs_history_size=history_size,
        lbfgs_curvature_tolerance=curvature_tolerance,
        lbfgs_initial_step_size=lbfgs_step_size,
        line_search_condition=line_search_condition,
        strong_wolfe_curvature_constant=wolfe_curvature,
        strong_wolfe_maximum_step_size=wolfe_maximum_step,
        relative_objective_tolerance=objective_change_tolerance,
        subject_batch_size=normalized_subject_batch_size,
    )
    for name, value in (
        ("initial_template_vertices", initial_template_vertices),
        ("initial_control_points", initial_control_points),
        ("initial_momenta", initial_momenta),
    ):
        if not isinstance(value, torch.Tensor):
            raise TypeError(f"{name} must be a torch.Tensor")

    target_sequence = tuple(targets)
    if prepared_targets is None:
        prepared_target_values = []
        for target_vertices, target_triangles in target_sequence:
            check_cancellation()
            prepared_target_values.append(
                prepare_surface_attachment_target(
                    target_vertices,
                    target_triangles,
                    attachment_kernel_width,
                    attachment_type=attachment_type,
                    gaussian_tile_plan=gaussian_tile_plan,
                )
            )
        prepared_target_sequence = tuple(prepared_target_values)
    else:
        prepared_target_sequence = tuple(prepared_targets)
        if len(prepared_target_sequence) != len(target_sequence):
            raise ValueError(
                "prepared_targets and targets must contain the same number of subjects"
            )
        for (target_vertices, target_triangles), prepared_target in zip(
            target_sequence,
            prepared_target_sequence,
            strict=True,
        ):
            check_cancellation()
            if not isinstance(prepared_target, PreparedSurfaceAttachmentTarget):
                raise TypeError(
                    "prepared_targets must contain PreparedSurfaceAttachmentTarget values"
                )
            prepared_target.validate_target(target_vertices, target_triangles)
            if prepared_target.attachment_type != attachment_type:
                raise ValueError("prepared target attachment type does not match attachment_type")
            if prepared_target.kernel_width != float(attachment_kernel_width):
                raise ValueError(
                    "prepared target kernel width does not match attachment_kernel_width"
                )
            if prepared_target.gaussian_tile_plan != gaussian_tile_plan:
                raise ValueError("prepared target tile plan does not match gaussian_tile_plan")
    check_cancellation()
    objective_keywords = {
        "deformation_kernel_width": deformation_kernel_width,
        "attachment_kernel_width": attachment_kernel_width,
        "noise_variance": noise_variance,
        "number_of_time_points": number_of_time_points,
        "attachment_type": attachment_type,
        "shooting_integrator": shooting_integrator,
        "flow_integrator": flow_integrator,
        "gaussian_tile_plan": gaussian_tile_plan,
        "prepared_targets": prepared_target_sequence,
    }
    objective_evaluations = 0
    gradient_evaluations = 0
    candidate_gradient_evaluations = 0

    def subject_slices() -> tuple[slice, ...]:
        size = normalized_subject_batch_size
        if size is None or size >= len(target_sequence):
            return (slice(0, len(target_sequence)),)
        return tuple(
            slice(start, min(start + size, len(target_sequence)))
            for start in range(0, len(target_sequence), size)
        )

    batch_slices = subject_slices()

    def evaluate_batched_objective(
        template_vertices: torch.Tensor,
        control_points: torch.Tensor,
        momenta: torch.Tensor,
    ) -> _State | None:
        totals: list[torch.Tensor] = []
        attachments: list[torch.Tensor] = []
        regularities: list[torch.Tensor] = []
        residuals: list[torch.Tensor] = []
        with torch.no_grad():
            for subject_slice in batch_slices:
                check_cancellation()
                objective = atlas_objective(
                    template_vertices,
                    template_triangles,
                    target_sequence[subject_slice],
                    control_points,
                    momenta[subject_slice],
                    **{
                        **objective_keywords,
                        "prepared_targets": prepared_target_sequence[subject_slice],
                    },
                )
                if not bool(torch.isfinite(objective.total)):
                    return None
                totals.append(objective.total.detach())
                attachments.append(objective.attachment.detach())
                regularities.append(objective.regularity.detach())
                residuals.append(objective.residuals.detach())
        return _State(
            template_vertices=template_vertices.detach(),
            control_points=control_points.detach(),
            momenta=momenta.detach(),
            objective=torch.stack(totals).sum(),
            attachment=torch.stack(attachments).sum(),
            regularity=torch.stack(regularities).sum(),
            residuals=torch.cat(residuals),
        )

    def evaluate_batched_gradient(
        state: _State,
        block: AtlasParameterBlock,
    ) -> torch.Tensor | None:
        gradients: list[torch.Tensor] = []
        for subject_slice in batch_slices:
            check_cancellation()
            template_vertices = state.template_vertices.detach().clone()
            control_points = state.control_points.detach().clone()
            momenta = state.momenta[subject_slice].detach().clone()
            parameters = {
                "template": template_vertices,
                "control_points": control_points,
                "momenta": momenta,
            }
            variable = parameters[block].requires_grad_(True)
            parameters[block] = variable
            with torch.enable_grad():
                objective = atlas_objective(
                    parameters["template"],
                    template_triangles,
                    target_sequence[subject_slice],
                    parameters["control_points"],
                    parameters["momenta"],
                    **{
                        **objective_keywords,
                        "prepared_targets": prepared_target_sequence[subject_slice],
                    },
                )
                if not bool(torch.isfinite(objective.total)):
                    return None
                (gradient,) = torch.autograd.grad(objective.total, variable)
            if not bool(torch.isfinite(gradient).all()):
                return None
            gradients.append(gradient.detach())
        if block == "momenta":
            return torch.cat(gradients)
        return torch.stack(gradients).sum(dim=0)

    def evaluate_objective(
        template_vertices: torch.Tensor,
        control_points: torch.Tensor,
        momenta: torch.Tensor,
        block: AtlasParameterBlock,
    ) -> _PendingBlockEvaluation | None:
        nonlocal objective_evaluations
        check_cancellation()
        if normalized_subject_batch_size is not None:
            objective_evaluations += 1
            state = evaluate_batched_objective(
                template_vertices.detach().clone(),
                control_points.detach().clone(),
                momenta.detach().clone(),
            )
            if state is None:
                return None
            return _PendingBlockEvaluation(
                state=state,
                total=state.objective,
                variable=None,
                block=block,
            )
        parameters = {
            "template": template_vertices.detach().clone(),
            "control_points": control_points.detach().clone(),
            "momenta": momenta.detach().clone(),
        }
        variable = parameters[block].requires_grad_(True)
        parameters[block] = variable
        with torch.enable_grad():
            objective_evaluations += 1
            objective = atlas_objective(
                parameters["template"],
                template_triangles,
                target_sequence,
                parameters["control_points"],
                parameters["momenta"],
                **objective_keywords,
            )
            check_cancellation()
            if not bool(torch.isfinite(objective.total)):
                return None
        state = _State(
            template_vertices=parameters["template"].detach(),
            control_points=parameters["control_points"].detach(),
            momenta=parameters["momenta"].detach(),
            objective=objective.total.detach(),
            attachment=objective.attachment.detach(),
            regularity=objective.regularity.detach(),
            residuals=objective.residuals.detach(),
        )
        return _PendingBlockEvaluation(
            state=state,
            total=objective.total,
            variable=variable,
            block=block,
        )

    def evaluate_gradient(
        pending: _PendingBlockEvaluation,
    ) -> _BlockEvaluation | None:
        nonlocal gradient_evaluations, objective_evaluations
        check_cancellation()
        if pending.variable is None:
            objective_evaluations += 1
            gradient_evaluations += 1
            gradient = evaluate_batched_gradient(pending.state, pending.block)
            if gradient is None:
                return None
        else:
            with torch.enable_grad():
                gradient_evaluations += 1
                (gradient,) = torch.autograd.grad(pending.total, pending.variable)
        check_cancellation()
        if not bool(torch.isfinite(gradient).all()):
            return None
        gradient_norm = torch.linalg.vector_norm(gradient)
        if not bool(torch.isfinite(gradient_norm)):
            return None
        return _BlockEvaluation(
            state=pending.state,
            gradient=gradient.detach(),
            gradient_norm=gradient_norm.detach(),
        )

    def replace_block(
        state: _State,
        block: AtlasParameterBlock,
        value: torch.Tensor,
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        return (
            value if block == "template" else state.template_vertices,
            value if block == "control_points" else state.control_points,
            value if block == "momenta" else state.momenta,
        )

    initial_pending = evaluate_objective(
        initial_template_vertices,
        initial_control_points,
        initial_momenta,
        order[0],
    )
    initial = None if initial_pending is None else evaluate_gradient(initial_pending)
    if initial is None:
        raise FloatingPointError("initial atlas parameters produced a non-finite objective")
    current = initial.state
    observed_initial_objective = float(current.objective)
    normalized_resume_history: list[tuple[torch.Tensor, torch.Tensor]] = []
    normalized_resume_gradient: torch.Tensor | None = None
    if resume_state is not None:
        for name, value in (
            ("resume initial_cycle_objective", resume_state.initial_cycle_objective),
            ("resume current_cycle_objective", resume_state.current_cycle_objective),
        ):
            if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value):
                raise ValueError(f"{name} must be finite")
        if float(resume_state.current_cycle_objective) != observed_initial_objective:
            raise ValueError("resume current objective differs from the recomputed initial state")
        if set(resume_state.next_step_sizes) != set(order):
            raise ValueError("resume next-step blocks differ from block_order")
        for block, value in resume_state.next_step_sizes.items():
            if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value):
                raise ValueError(f"resume next step for {block} must be finite")
            if float(value) <= 0.0:
                raise ValueError(f"resume next step for {block} must be positive")
        if len(resume_state.lbfgs_history) > history_size:
            raise ValueError("resume L-BFGS history exceeds lbfgs_history_size")
        expected_history_shape = tuple(
            {
                "template": initial_template_vertices,
                "control_points": initial_control_points,
                "momenta": initial_momenta,
            }[order[0]].shape
        )
        for index, pair in enumerate(resume_state.lbfgs_history):
            if not isinstance(pair, tuple) or len(pair) != 2:
                raise TypeError("resume L-BFGS history must contain (step, gradient_delta) pairs")
            step, gradient_delta = pair
            for label, tensor in (("step", step), ("gradient_delta", gradient_delta)):
                if not isinstance(tensor, torch.Tensor):
                    raise TypeError(f"resume L-BFGS {label} {index} must be a torch.Tensor")
                if (
                    tuple(tensor.shape) != expected_history_shape
                    or tensor.device.type != "cpu"
                    or tensor.dtype != torch.float64
                    or tensor.requires_grad
                    or not bool(torch.isfinite(tensor).all())
                ):
                    raise ValueError(
                        f"resume L-BFGS {label} {index} must be detached finite CPU float64 "
                        "with the momenta shape"
                    )
            normalized_resume_history.append((step.clone(), gradient_delta.clone()))
        if direction_update != "lbfgs" and normalized_resume_history:
            raise ValueError("resume L-BFGS history requires direction_update=lbfgs")
        if resume_state.reusable_gradient is not None:
            candidate = resume_state.reusable_gradient
            expected_gradient_shape = expected_history_shape if len(order) == 1 else ()
            if (
                len(order) != 1
                or not isinstance(candidate, torch.Tensor)
                or tuple(candidate.shape) != expected_gradient_shape
                or candidate.device.type != "cpu"
                or candidate.dtype != torch.float64
                or candidate.requires_grad
                or not bool(torch.isfinite(candidate).all())
            ):
                raise ValueError(
                    "resume reusable_gradient must be detached finite CPU float64 with the "
                    "single optimized block shape"
                )
            if not torch.equal(candidate, initial.gradient):
                raise ValueError("resume gradient differs from the recomputed initial gradient")
            normalized_resume_gradient = candidate.clone()
        if resume_state.completed_cycle_termination_reason not in (
            None,
            "gradient_tolerance",
            "relative_objective_tolerance",
        ):
            raise ValueError("resume completed-cycle termination reason is invalid")
        if (
            resume_state.completed_cycle_termination_reason == "relative_objective_tolerance"
            and objective_change_tolerance is None
        ):
            raise ValueError(
                "resume relative-objective termination requires relative_objective_tolerance"
            )
    initial_record = current.record(
        0,
        block=None,
        status="initial",
        gradient_norm=None,
        accepted_step_size=None,
        line_search_evaluations=0,
    )
    history = [initial_record]
    initial_cycle_objective = (
        observed_initial_objective
        if resume_state is None
        else float(resume_state.initial_cycle_objective)
    )
    previous_cycle_objective = (
        observed_initial_objective
        if resume_state is None
        else float(resume_state.current_cycle_objective)
    )
    if progress_callback is not None:
        progress_callback(initial_record)
    total_line_search_evaluations = 0
    next_step_sizes = (
        dict(step_sizes)
        if resume_state is None
        else {block: float(resume_state.next_step_sizes[block]) for block in order}
    )
    reusable_single_block_evaluation: _BlockEvaluation | None = None
    if normalized_resume_gradient is not None:
        reusable_single_block_evaluation = _BlockEvaluation(
            state=current,
            gradient=normalized_resume_gradient,
            gradient_norm=torch.linalg.vector_norm(normalized_resume_gradient),
        )
    lbfgs_history = normalized_resume_history

    def emit_cycle_checkpoint(
        record: AtlasOptimizationRecord,
        *,
        prior_cycle_objective: float,
        current_cycle_objective: float,
        completed_cycle_termination_reason: AtlasCompletedCycleTerminationReason | None,
    ) -> None:
        if checkpoint_callback is None:
            return
        reusable_gradient = (
            None
            if reusable_single_block_evaluation is None
            else reusable_single_block_evaluation.gradient.clone()
        )
        checkpoint_callback(
            AtlasCycleCheckpoint(
                record=record,
                template_vertices=current.template_vertices.clone(),
                control_points=current.control_points.clone(),
                momenta=current.momenta.clone(),
                next_step_sizes={block: next_step_sizes[block] for block in order},
                initial_cycle_objective=initial_cycle_objective,
                prior_cycle_objective=prior_cycle_objective,
                current_cycle_objective=current_cycle_objective,
                lbfgs_history=tuple(
                    (step.clone(), gradient_delta.clone()) for step, gradient_delta in lbfgs_history
                ),
                reusable_gradient=reusable_gradient,
                completed_cycle_termination_reason=completed_cycle_termination_reason,
            )
        )

    def result(
        termination_reason: AtlasTerminationReason,
        *,
        converged: bool,
        failed_block: AtlasParameterBlock | None,
        cycles_completed: int,
    ) -> AtlasOptimizationResult:
        check_cancellation()
        return AtlasOptimizationResult(
            template_vertices=current.template_vertices.clone(),
            control_points=current.control_points.clone(),
            momenta=current.momenta.clone(),
            history=tuple(history),
            termination_reason=termination_reason,
            converged=converged,
            failed_block=failed_block,
            cycles_completed=cycles_completed,
            total_line_search_evaluations=total_line_search_evaluations,
            settings=optimizer_settings,
            objective_evaluations=objective_evaluations,
            gradient_evaluations=gradient_evaluations,
            candidate_gradient_evaluations=candidate_gradient_evaluations,
        )

    if resume_state is not None and resume_state.completed_cycle_termination_reason is not None:
        return result(
            resume_state.completed_cycle_termination_reason,
            converged=True,
            failed_block=None,
            cycles_completed=0,
        )

    for cycle in range(1, cycles + 1):
        stationary_blocks = 0
        for block in order:
            if cycle == 1 and block == order[0]:
                evaluated = initial
                initial = None
            elif len(order) == 1 and reusable_single_block_evaluation is not None:
                # The accepted candidate already carries the exact gradient for
                # this sole block. Re-evaluating it at the next cycle boundary
                # changes no state or decision and can dominate surface runs.
                check_cancellation()
                evaluated = reusable_single_block_evaluation
                reusable_single_block_evaluation = None
            else:
                pending = evaluate_objective(
                    current.template_vertices,
                    current.control_points,
                    current.momenta,
                    block,
                )
                evaluated = None if pending is None else evaluate_gradient(pending)
            if evaluated is None:
                raise FloatingPointError(
                    f"accepted atlas state produced a non-finite {block} gradient"
                )
            current = evaluated.state
            if float(evaluated.gradient_norm) <= gradient_threshold:
                stationary_blocks += 1
                record = current.record(
                    cycle,
                    block=block,
                    status="stationary",
                    gradient_norm=evaluated.gradient_norm,
                    accepted_step_size=None,
                    line_search_evaluations=0,
                )
                history.append(record)
                if progress_callback is not None:
                    progress_callback(record)
                continue

            step_size = (
                lbfgs_step_size
                if direction_update == "lbfgs" and lbfgs_history
                else next_step_sizes[block]
            )
            direction = (
                _lbfgs_ascent_direction(evaluated.gradient, lbfgs_history)
                if direction_update == "lbfgs"
                else evaluated.gradient
            )
            directional_derivative = torch.sum(evaluated.gradient * direction)
            accepted: _BlockEvaluation | None = None
            evaluations = 0
            current_value = {
                "template": current.template_vertices,
                "control_points": current.control_points,
                "momenta": current.momenta,
            }[block]

            def candidate_at(
                candidate_step_size: float,
                *,
                accepted_state: _State = current,
                active_block: AtlasParameterBlock = block,
                base_value: torch.Tensor = current_value,
                search_direction: torch.Tensor = direction,
            ) -> _BlockEvaluation | None:
                nonlocal candidate_gradient_evaluations
                candidate_parameters = replace_block(
                    accepted_state,
                    active_block,
                    base_value + candidate_step_size * search_direction,
                )
                try:
                    candidate_pending = evaluate_objective(*candidate_parameters, active_block)
                except ValueError:
                    return None
                if candidate_pending is None:
                    return None
                try:
                    candidate_gradient_evaluations += 1
                    return evaluate_gradient(candidate_pending)
                except ValueError:
                    return None

            if line_search_condition == "strong_wolfe":
                accepted, accepted_step_size, evaluations = _strong_wolfe_ascent_search(
                    evaluated,
                    direction,
                    initial_step_size=step_size,
                    minimum_step_size=minimum_step,
                    maximum_step_size=wolfe_maximum_step,
                    armijo_constant=armijo,
                    curvature_constant=wolfe_curvature,
                    maximum_evaluations=line_search_limit,
                    evaluate=candidate_at,
                )
                total_line_search_evaluations += evaluations
                if accepted_step_size is not None:
                    step_size = accepted_step_size
            else:
                for _ in range(line_search_limit):
                    if step_size < minimum_step:
                        break
                    evaluations += 1
                    total_line_search_evaluations += 1
                    candidate_parameters = replace_block(
                        current,
                        block,
                        current_value + step_size * direction,
                    )
                    try:
                        candidate_pending = evaluate_objective(*candidate_parameters, block)
                    except ValueError:
                        candidate_pending = None
                    if candidate_pending is not None:
                        required = current.objective + armijo * step_size * directional_derivative
                        if bool(candidate_pending.state.objective >= required):
                            try:
                                candidate_gradient_evaluations += 1
                                candidate = evaluate_gradient(candidate_pending)
                            except ValueError:
                                candidate = None
                            if candidate is not None:
                                accepted = candidate
                                break
                    step_size *= shrink

            if accepted is None:
                record = current.record(
                    cycle,
                    block=block,
                    status="failed",
                    gradient_norm=evaluated.gradient_norm,
                    accepted_step_size=None,
                    line_search_evaluations=evaluations,
                )
                history.append(record)
                if progress_callback is not None:
                    progress_callback(record)
                return result(
                    "line_search_failed",
                    converged=False,
                    failed_block=block,
                    cycles_completed=cycle - 1,
                )

            current = accepted.state
            if direction_update == "lbfgs":
                step = (step_size * direction).detach()
                # L-BFGS is applied to the equivalent minimization objective
                # -f, so y = grad(-f_new) - grad(-f_old).
                gradient_delta = (evaluated.gradient - accepted.gradient).detach()
                curvature = torch.sum(step * gradient_delta)
                curvature_scale = torch.linalg.vector_norm(step) * torch.linalg.vector_norm(
                    gradient_delta
                )
                if (
                    bool(torch.isfinite(curvature))
                    and bool(torch.isfinite(curvature_scale))
                    and float(curvature) > curvature_tolerance * float(curvature_scale)
                ):
                    lbfgs_history.append((step, gradient_delta))
                    if len(lbfgs_history) > history_size:
                        del lbfgs_history[0]
            if len(order) == 1:
                reusable_single_block_evaluation = accepted
            if step_initialization == "previous_accepted":
                next_step_sizes[block] = step_size
            record = current.record(
                cycle,
                block=block,
                status="accepted",
                gradient_norm=accepted.gradient_norm,
                accepted_step_size=step_size,
                line_search_evaluations=evaluations,
            )
            history.append(record)
            if progress_callback is not None:
                progress_callback(record)
        current_cycle_objective = float(current.objective)
        completed_reason: AtlasCompletedCycleTerminationReason | None = None
        if stationary_blocks == len(order):
            completed_reason = "gradient_tolerance"
        elif objective_change_tolerance is not None:
            latest_change = abs(current_cycle_objective - previous_cycle_objective)
            cumulative_change = abs(current_cycle_objective - initial_cycle_objective)
            if cumulative_change > 0.0 and latest_change < (
                objective_change_tolerance * cumulative_change
            ):
                completed_reason = "relative_objective_tolerance"
        emit_cycle_checkpoint(
            history[-1],
            prior_cycle_objective=previous_cycle_objective,
            current_cycle_objective=current_cycle_objective,
            completed_cycle_termination_reason=completed_reason,
        )
        previous_cycle_objective = current_cycle_objective
        if completed_reason == "gradient_tolerance":
            return result(
                "gradient_tolerance",
                converged=True,
                failed_block=None,
                cycles_completed=cycle,
            )
        if completed_reason == "relative_objective_tolerance":
            return result(
                "relative_objective_tolerance",
                converged=True,
                failed_block=None,
                cycles_completed=cycle,
            )

    return result(
        "max_cycles",
        converged=False,
        failed_block=None,
        cycles_completed=cycles,
    )
