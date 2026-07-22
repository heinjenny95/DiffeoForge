"""Transparent deterministic optimizers for the experimental modern engine."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from numbers import Integral, Real
from typing import Literal

import torch

from diffeoforge.engine.dense import prepare_surface_attachment_target
from diffeoforge.engine.objective import (
    AttachmentType,
    FlowIntegrator,
    ShootingIntegrator,
    atlas_objective,
)

TerminationReason = Literal[
    "gradient_tolerance",
    "max_iterations",
    "line_search_failed",
]


@dataclass(frozen=True)
class OptimizationRecord:
    """One accepted optimizer state, including its observable diagnostics."""

    iteration: int
    objective: float
    attachment: float
    regularity: float
    residuals: tuple[float, ...]
    gradient_norm: float
    accepted_step_size: float | None
    line_search_evaluations: int


@dataclass(frozen=True)
class MomentaOptimizationResult:
    """Final momenta and complete accepted-state history."""

    momenta: torch.Tensor
    history: tuple[OptimizationRecord, ...]
    termination_reason: TerminationReason
    converged: bool
    total_line_search_evaluations: int


@dataclass(frozen=True)
class _Evaluation:
    momenta: torch.Tensor
    gradient: torch.Tensor
    objective: torch.Tensor
    attachment: torch.Tensor
    regularity: torch.Tensor
    residuals: torch.Tensor
    gradient_norm: torch.Tensor

    def record(
        self,
        iteration: int,
        *,
        accepted_step_size: float | None,
        line_search_evaluations: int,
    ) -> OptimizationRecord:
        return OptimizationRecord(
            iteration=iteration,
            objective=float(self.objective.detach()),
            attachment=float(self.attachment.detach()),
            regularity=float(self.regularity.detach()),
            residuals=tuple(float(value) for value in self.residuals.detach()),
            gradient_norm=float(self.gradient_norm.detach()),
            accepted_step_size=accepted_step_size,
            line_search_evaluations=line_search_evaluations,
        )


@dataclass(frozen=True)
class _PendingEvaluation:
    """One finite objective graph whose momenta gradient has not been requested."""

    momenta: torch.Tensor
    total: torch.Tensor
    attachment: torch.Tensor
    regularity: torch.Tensor
    residuals: torch.Tensor


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


def optimize_momenta(
    template_vertices: torch.Tensor,
    template_triangles: torch.Tensor,
    targets: Sequence[tuple[torch.Tensor, torch.Tensor]],
    control_points: torch.Tensor,
    initial_momenta: torch.Tensor,
    *,
    deformation_kernel_width: float,
    attachment_kernel_width: float,
    noise_variance: float,
    number_of_time_points: int,
    attachment_type: AttachmentType = "current",
    shooting_integrator: ShootingIntegrator = "rk2",
    flow_integrator: FlowIntegrator = "deformetrica_heun",
    max_iterations: int = 25,
    initial_step_size: float = 0.1,
    backtracking_factor: float = 0.5,
    armijo_constant: float = 1e-4,
    gradient_tolerance: float = 1e-8,
    minimum_step_size: float = 1e-12,
    max_line_search_iterations: int = 20,
) -> MomentaOptimizationResult:
    """Maximize the atlas objective over per-subject momenta only.

    Accepted steps satisfy the ascent Armijo condition. Template vertices and
    control points are intentionally fixed; this function is a correctness
    prototype, not yet a complete deterministic-atlas estimator.
    """

    iterations = _integer("max_iterations", max_iterations, minimum=0)
    line_search_limit = _integer(
        "max_line_search_iterations", max_line_search_iterations, minimum=1
    )
    first_step = _finite_real("initial_step_size", initial_step_size, minimum=0.0)
    shrink = _finite_real("backtracking_factor", backtracking_factor, minimum=0.0, maximum=1.0)
    armijo = _finite_real("armijo_constant", armijo_constant, minimum=0.0, maximum=1.0)
    gradient_threshold = _finite_real(
        "gradient_tolerance",
        gradient_tolerance,
        minimum=0.0,
        inclusive_minimum=True,
    )
    minimum_step = _finite_real("minimum_step_size", minimum_step_size, minimum=0.0)
    if minimum_step > first_step:
        raise ValueError("minimum_step_size must not exceed initial_step_size")
    if not isinstance(initial_momenta, torch.Tensor):
        raise TypeError("initial_momenta must be a torch.Tensor")

    target_sequence = tuple(targets)
    prepared_targets = tuple(
        prepare_surface_attachment_target(
            target_vertices,
            target_triangles,
            attachment_kernel_width,
            attachment_type=attachment_type,
        )
        for target_vertices, target_triangles in target_sequence
    )

    def evaluate_objective(candidate: torch.Tensor) -> _PendingEvaluation | None:
        variable = candidate.detach().clone().requires_grad_(True)
        with torch.enable_grad():
            objective = atlas_objective(
                template_vertices,
                template_triangles,
                target_sequence,
                control_points,
                variable,
                deformation_kernel_width=deformation_kernel_width,
                attachment_kernel_width=attachment_kernel_width,
                noise_variance=noise_variance,
                number_of_time_points=number_of_time_points,
                attachment_type=attachment_type,
                shooting_integrator=shooting_integrator,
                flow_integrator=flow_integrator,
                prepared_targets=prepared_targets,
            )
            if not bool(torch.isfinite(objective.total)):
                return None
        return _PendingEvaluation(
            momenta=variable,
            total=objective.total,
            attachment=objective.attachment.detach(),
            regularity=objective.regularity.detach(),
            residuals=objective.residuals.detach(),
        )

    def evaluate_gradient(pending: _PendingEvaluation) -> _Evaluation | None:
        with torch.enable_grad():
            (gradient,) = torch.autograd.grad(pending.total, pending.momenta)
        if not bool(torch.isfinite(gradient).all()):
            return None
        gradient_norm = torch.linalg.vector_norm(gradient)
        if not bool(torch.isfinite(gradient_norm)):
            return None
        return _Evaluation(
            momenta=pending.momenta.detach(),
            gradient=gradient.detach(),
            objective=pending.total.detach(),
            attachment=pending.attachment,
            regularity=pending.regularity,
            residuals=pending.residuals,
            gradient_norm=gradient_norm.detach(),
        )

    initial_pending = evaluate_objective(initial_momenta)
    current = None if initial_pending is None else evaluate_gradient(initial_pending)
    if current is None:
        raise FloatingPointError("initial momenta produced a non-finite objective or gradient")
    history = [
        current.record(
            0,
            accepted_step_size=None,
            line_search_evaluations=0,
        )
    ]
    total_line_search_evaluations = 0
    if float(current.gradient_norm) <= gradient_threshold:
        return MomentaOptimizationResult(
            momenta=current.momenta.clone(),
            history=tuple(history),
            termination_reason="gradient_tolerance",
            converged=True,
            total_line_search_evaluations=0,
        )

    for iteration in range(1, iterations + 1):
        step_size = first_step
        directional_derivative = current.gradient_norm.square()
        accepted: _Evaluation | None = None
        evaluations = 0
        for _ in range(line_search_limit):
            if step_size < minimum_step:
                break
            evaluations += 1
            total_line_search_evaluations += 1
            candidate_pending = evaluate_objective(current.momenta + step_size * current.gradient)
            if candidate_pending is not None:
                required = current.objective + armijo * step_size * directional_derivative
                if bool(candidate_pending.total.detach() >= required):
                    candidate = evaluate_gradient(candidate_pending)
                    if candidate is not None:
                        accepted = candidate
                        break
            step_size *= shrink

        if accepted is None:
            return MomentaOptimizationResult(
                momenta=current.momenta.clone(),
                history=tuple(history),
                termination_reason="line_search_failed",
                converged=False,
                total_line_search_evaluations=total_line_search_evaluations,
            )

        current = accepted
        history.append(
            current.record(
                iteration,
                accepted_step_size=step_size,
                line_search_evaluations=evaluations,
            )
        )
        if float(current.gradient_norm) <= gradient_threshold:
            return MomentaOptimizationResult(
                momenta=current.momenta.clone(),
                history=tuple(history),
                termination_reason="gradient_tolerance",
                converged=True,
                total_line_search_evaluations=total_line_search_evaluations,
            )

    return MomentaOptimizationResult(
        momenta=current.momenta.clone(),
        history=tuple(history),
        termination_reason="max_iterations",
        converged=False,
        total_line_search_evaluations=total_line_search_evaluations,
    )
