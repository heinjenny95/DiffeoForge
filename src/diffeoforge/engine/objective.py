"""Differentiable deterministic surface-atlas objective components."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from numbers import Real
from typing import Literal

import torch

from diffeoforge.engine.dense import (
    ShootingTrajectory,
    current_squared_distance,
    deformation_energy,
    flow_points,
    shoot,
    varifold_squared_distance,
)

AttachmentType = Literal["current", "varifold"]
ShootingIntegrator = Literal["euler", "rk2"]
FlowIntegrator = Literal["euler", "heun", "deformetrica_heun"]


@dataclass(frozen=True)
class SubjectObjective:
    """Observable components of one subject's deterministic-atlas contribution."""

    trajectory: ShootingTrajectory
    template_path: torch.Tensor
    residual: torch.Tensor
    attachment: torch.Tensor
    regularity: torch.Tensor
    total: torch.Tensor

    @property
    def endpoint_vertices(self) -> torch.Tensor:
        """Return the subject-specific deformed template endpoint."""

        return self.template_path[-1]


@dataclass(frozen=True)
class AtlasObjective:
    """Unaveraged sum of deterministic-atlas contributions across subjects."""

    subjects: tuple[SubjectObjective, ...]
    residuals: torch.Tensor
    attachment: torch.Tensor
    regularity: torch.Tensor
    total: torch.Tensor


def _positive_scalar(name: str, value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError(f"{name} must be a real scalar")
    normalized = float(value)
    if not math.isfinite(normalized) or normalized <= 0:
        raise ValueError(f"{name} must be finite and greater than zero")
    return normalized


def subject_objective(
    template_vertices: torch.Tensor,
    template_triangles: torch.Tensor,
    target_vertices: torch.Tensor,
    target_triangles: torch.Tensor,
    control_points: torch.Tensor,
    momenta: torch.Tensor,
    *,
    deformation_kernel_width: float,
    attachment_kernel_width: float,
    noise_variance: float,
    number_of_time_points: int,
    attachment_type: AttachmentType = "current",
    shooting_integrator: ShootingIntegrator = "rk2",
    flow_integrator: FlowIntegrator = "deformetrica_heun",
) -> SubjectObjective:
    """Compute one Deformetrica-convention subject log-likelihood contribution.

    The signs and scaling intentionally match Deformetrica 4.3: attachment is
    ``-distance / noise_variance`` and regularity is ``-p^T K(q,q) p``.
    """

    variance = _positive_scalar("noise_variance", noise_variance)
    if attachment_type not in {"current", "varifold"}:
        raise ValueError("attachment_type must be 'current' or 'varifold'")
    trajectory = shoot(
        control_points,
        momenta,
        deformation_kernel_width,
        number_of_time_points,
        integrator=shooting_integrator,
    )
    template_path = flow_points(
        template_vertices,
        trajectory,
        deformation_kernel_width,
        integrator=flow_integrator,
    )
    distance_function = (
        current_squared_distance if attachment_type == "current" else varifold_squared_distance
    )
    residual = distance_function(
        template_path[-1],
        template_triangles,
        target_vertices,
        target_triangles,
        attachment_kernel_width,
    )
    attachment = -residual / variance
    regularity = -deformation_energy(control_points, momenta, deformation_kernel_width)
    return SubjectObjective(
        trajectory=trajectory,
        template_path=template_path,
        residual=residual,
        attachment=attachment,
        regularity=regularity,
        total=attachment + regularity,
    )


def atlas_objective(
    template_vertices: torch.Tensor,
    template_triangles: torch.Tensor,
    targets: Sequence[tuple[torch.Tensor, torch.Tensor]],
    control_points: torch.Tensor,
    momenta: torch.Tensor,
    *,
    deformation_kernel_width: float,
    attachment_kernel_width: float,
    noise_variance: float,
    number_of_time_points: int,
    attachment_type: AttachmentType = "current",
    shooting_integrator: ShootingIntegrator = "rk2",
    flow_integrator: FlowIntegrator = "deformetrica_heun",
) -> AtlasObjective:
    """Sum the objective over subjects without hidden averaging or reordering."""

    if not isinstance(momenta, torch.Tensor):
        raise TypeError("momenta must be a torch.Tensor")
    if momenta.ndim != 3 or momenta.shape[2] != 3:
        raise ValueError("momenta must have shape (subjects, control_points, 3)")
    target_sequence = tuple(targets)
    if not target_sequence:
        raise ValueError("targets must contain at least one subject")
    if len(target_sequence) != momenta.shape[0]:
        raise ValueError("targets and momenta must contain the same number of subjects")

    subjects = tuple(
        subject_objective(
            template_vertices,
            template_triangles,
            target_vertices,
            target_triangles,
            control_points,
            momenta[index],
            deformation_kernel_width=deformation_kernel_width,
            attachment_kernel_width=attachment_kernel_width,
            noise_variance=noise_variance,
            number_of_time_points=number_of_time_points,
            attachment_type=attachment_type,
            shooting_integrator=shooting_integrator,
            flow_integrator=flow_integrator,
        )
        for index, (target_vertices, target_triangles) in enumerate(target_sequence)
    )
    residuals = torch.stack([subject.residual for subject in subjects])
    attachment = torch.stack([subject.attachment for subject in subjects]).sum()
    regularity = torch.stack([subject.regularity for subject in subjects]).sum()
    return AtlasObjective(
        subjects=subjects,
        residuals=residuals,
        attachment=attachment,
        regularity=regularity,
        total=attachment + regularity,
    )
