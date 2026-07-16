"""Deterministic block-coordinate optimizer for the experimental atlas engine."""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from numbers import Integral, Real
from typing import Literal

import torch

from diffeoforge.engine.dense import GaussianTilePlan
from diffeoforge.engine.objective import (
    AttachmentType,
    FlowIntegrator,
    ShootingIntegrator,
    atlas_objective,
)

AtlasParameterBlock = Literal["momenta", "template", "control_points"]
AtlasAttemptStatus = Literal["initial", "accepted", "stationary", "failed"]
AtlasTerminationReason = Literal[
    "gradient_tolerance",
    "max_cycles",
    "line_search_failed",
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
    if len(normalized) != len(_ALL_BLOCKS) or set(normalized) != set(_ALL_BLOCKS):
        raise ValueError(
            "block_order must contain momenta, template, and control_points exactly once"
        )
    return normalized  # type: ignore[return-value]


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
    progress_callback: AtlasProgressCallback | None = None,
) -> AtlasOptimizationResult:
    """Maximize the atlas objective over all three declared parameter blocks.

    Blocks are updated sequentially. Each accepted candidate must satisfy an
    ascent Armijo condition for the current block. No adaptive or hidden
    optimizer state is used. This is a correctness prototype, not a claim of
    Deformetrica optimizer-trajectory equivalence or production convergence.
    """

    cycles = _integer("max_cycles", max_cycles, minimum=0)
    if progress_callback is not None and not callable(progress_callback):
        raise TypeError("progress_callback must be callable or None")
    line_search_limit = _integer(
        "max_line_search_iterations", max_line_search_iterations, minimum=1
    )
    order = _block_order(block_order)
    step_sizes = {
        "momenta": _finite_real("momenta_step_size", momenta_step_size, minimum=0.0),
        "template": _finite_real("template_step_size", template_step_size, minimum=0.0),
        "control_points": _finite_real(
            "control_points_step_size", control_points_step_size, minimum=0.0
        ),
    }
    shrink = _finite_real("backtracking_factor", backtracking_factor, minimum=0.0, maximum=1.0)
    armijo = _finite_real("armijo_constant", armijo_constant, minimum=0.0, maximum=1.0)
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
    )
    for name, value in (
        ("initial_template_vertices", initial_template_vertices),
        ("initial_control_points", initial_control_points),
        ("initial_momenta", initial_momenta),
    ):
        if not isinstance(value, torch.Tensor):
            raise TypeError(f"{name} must be a torch.Tensor")

    target_sequence = tuple(targets)
    objective_keywords = {
        "deformation_kernel_width": deformation_kernel_width,
        "attachment_kernel_width": attachment_kernel_width,
        "noise_variance": noise_variance,
        "number_of_time_points": number_of_time_points,
        "attachment_type": attachment_type,
        "shooting_integrator": shooting_integrator,
        "flow_integrator": flow_integrator,
        "gaussian_tile_plan": gaussian_tile_plan,
    }

    def evaluate(
        template_vertices: torch.Tensor,
        control_points: torch.Tensor,
        momenta: torch.Tensor,
        block: AtlasParameterBlock,
    ) -> _BlockEvaluation | None:
        parameters = {
            "template": template_vertices.detach().clone(),
            "control_points": control_points.detach().clone(),
            "momenta": momenta.detach().clone(),
        }
        variable = parameters[block].requires_grad_(True)
        parameters[block] = variable
        with torch.enable_grad():
            objective = atlas_objective(
                parameters["template"],
                template_triangles,
                target_sequence,
                parameters["control_points"],
                parameters["momenta"],
                **objective_keywords,
            )
            if not bool(torch.isfinite(objective.total)):
                return None
            (gradient,) = torch.autograd.grad(objective.total, variable)
        if not bool(torch.isfinite(gradient).all()):
            return None
        gradient_norm = torch.linalg.vector_norm(gradient)
        if not bool(torch.isfinite(gradient_norm)):
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
        return _BlockEvaluation(
            state=state,
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

    initial = evaluate(
        initial_template_vertices,
        initial_control_points,
        initial_momenta,
        order[0],
    )
    if initial is None:
        raise FloatingPointError("initial atlas parameters produced a non-finite objective")
    current = initial.state
    initial_record = current.record(
        0,
        block=None,
        status="initial",
        gradient_norm=None,
        accepted_step_size=None,
        line_search_evaluations=0,
    )
    history = [initial_record]
    if progress_callback is not None:
        progress_callback(initial_record)
    total_line_search_evaluations = 0

    def result(
        termination_reason: AtlasTerminationReason,
        *,
        converged: bool,
        failed_block: AtlasParameterBlock | None,
        cycles_completed: int,
    ) -> AtlasOptimizationResult:
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
        )

    for cycle in range(1, cycles + 1):
        stationary_blocks = 0
        for block in order:
            evaluated = evaluate(
                current.template_vertices,
                current.control_points,
                current.momenta,
                block,
            )
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

            step_size = step_sizes[block]
            directional_derivative = evaluated.gradient_norm.square()
            accepted: _BlockEvaluation | None = None
            evaluations = 0
            for _ in range(line_search_limit):
                if step_size < minimum_step:
                    break
                evaluations += 1
                total_line_search_evaluations += 1
                current_value = {
                    "template": current.template_vertices,
                    "control_points": current.control_points,
                    "momenta": current.momenta,
                }[block]
                candidate_parameters = replace_block(
                    current,
                    block,
                    current_value + step_size * evaluated.gradient,
                )
                try:
                    candidate = evaluate(*candidate_parameters, block)
                except ValueError:
                    candidate = None
                if candidate is not None:
                    required = current.objective + armijo * step_size * directional_derivative
                    if bool(candidate.state.objective >= required):
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

        if stationary_blocks == len(order):
            return result(
                "gradient_tolerance",
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
