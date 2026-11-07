"""Deformetrica-compatible Sobolev smoothing for template gradients."""

from __future__ import annotations

import math
from numbers import Real

import torch

from diffeoforge.engine.dense import (
    GaussianTilePlan,
    gaussian_convolve,
    gaussian_convolve_blockwise,
)


def sobolev_template_gradient(
    template_vertices: torch.Tensor,
    euclidean_gradient: torch.Tensor,
    *,
    deformation_kernel_width: float,
    kernel_width_ratio: float = 1.0,
    gaussian_tile_plan: GaussianTilePlan | None = None,
) -> torch.Tensor:
    """Return ``K(T, T) g`` using the Deformetrica Gaussian convention.

    Deformetrica 4.3 optionally replaces the Euclidean gradient of template
    landmark points by a Gaussian convolution evaluated at the current
    template points. The smoothing width is the deformation-kernel width
    multiplied by an explicit ratio. Inputs are never mutated and the result
    is detached because this operator transforms an already evaluated
    optimizer gradient rather than extending the objective graph.
    """

    if isinstance(deformation_kernel_width, bool) or not isinstance(
        deformation_kernel_width, Real
    ):
        raise TypeError("deformation_kernel_width must be a real scalar")
    if isinstance(kernel_width_ratio, bool) or not isinstance(kernel_width_ratio, Real):
        raise TypeError("kernel_width_ratio must be a real scalar")
    width = float(deformation_kernel_width)
    ratio = float(kernel_width_ratio)
    if not math.isfinite(width) or width <= 0.0:
        raise ValueError("deformation_kernel_width must be finite and greater than zero")
    if not math.isfinite(ratio) or ratio <= 0.0:
        raise ValueError("kernel_width_ratio must be finite and greater than zero")
    if gaussian_tile_plan is not None and not isinstance(
        gaussian_tile_plan, GaussianTilePlan
    ):
        raise TypeError("gaussian_tile_plan must be a GaussianTilePlan or None")

    smoothing_width = width * ratio
    if not math.isfinite(smoothing_width) or smoothing_width <= 0.0:
        raise ValueError("effective Sobolev kernel width must be finite and greater than zero")

    with torch.no_grad():
        if gaussian_tile_plan is None:
            smoothed = gaussian_convolve(
                template_vertices,
                template_vertices,
                euclidean_gradient,
                smoothing_width,
            )
        else:
            smoothed = gaussian_convolve_blockwise(
                template_vertices,
                template_vertices,
                euclidean_gradient,
                smoothing_width,
                query_tile_size=gaussian_tile_plan.query_rows,
                source_tile_size=gaussian_tile_plan.source_rows,
                autograd_strategy=gaussian_tile_plan.autograd_strategy,
            )
    return smoothed.detach()
