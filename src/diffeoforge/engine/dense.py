"""Dense PyTorch correctness baseline for the experimental modern engine.

This module re-expresses the focused Deformetrica 4.3 operations listed in GitHub issue #12:
the Gaussian kernel, Hamiltonian control-point shooting, landmark flow, and current/varifold
surface attachments. The dense implementation is intentionally simple and inspectable. Its
quadratic memory use makes it a numerical oracle, not yet a production-scale atlas engine.

The Gaussian convention follows Deformetrica 4.3 exactly: ``exp(-||x-y||^2 / width^2)``.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from numbers import Integral, Real
from typing import Literal

try:
    import torch
except ModuleNotFoundError as exc:  # pragma: no cover - exercised in packaging smoke tests
    raise ModuleNotFoundError(
        "The experimental modern engine requires PyTorch. "
        'Install DiffeoForge with the "modern-engine" extra.'
    ) from exc

from torch.utils.checkpoint import checkpoint

TileAutogradStrategy = Literal["standard", "recompute"]


@dataclass(frozen=True)
class ShootingTrajectory:
    """Control-point and momenta states at equally spaced times from zero to one."""

    control_points: torch.Tensor
    momenta: torch.Tensor

    @property
    def number_of_time_points(self) -> int:
        """Return the number of stored states, including both endpoints."""

        return self.control_points.shape[0]


def _validate_float_matrix(name: str, value: torch.Tensor, *, columns: int | None = None) -> None:
    if not isinstance(value, torch.Tensor):
        raise TypeError(f"{name} must be a torch.Tensor")
    if value.ndim != 2:
        raise ValueError(f"{name} must be a rank-2 tensor")
    if value.shape[0] == 0:
        raise ValueError(f"{name} must contain at least one row")
    if columns is not None and value.shape[1] != columns:
        raise ValueError(f"{name} must have shape (n, {columns})")
    if not value.is_floating_point():
        raise TypeError(f"{name} must use a floating-point dtype")
    if not bool(torch.isfinite(value).all()):
        raise ValueError(f"{name} must contain only finite values")


def _validate_compatible(name: str, value: torch.Tensor, reference: torch.Tensor) -> None:
    if value.dtype != reference.dtype:
        raise TypeError(f"{name} must use dtype {reference.dtype}, got {value.dtype}")
    if value.device != reference.device:
        raise ValueError(f"{name} must be on device {reference.device}, got {value.device}")


def _validate_width(width: float) -> float:
    if isinstance(width, bool) or not isinstance(width, Real):
        raise TypeError("kernel_width must be a real scalar")
    normalized = float(width)
    if not math.isfinite(normalized) or normalized <= 0:
        raise ValueError("kernel_width must be finite and greater than zero")
    return normalized


def _validate_time_points(number_of_time_points: int) -> int:
    if isinstance(number_of_time_points, bool) or not isinstance(number_of_time_points, Integral):
        raise TypeError("number_of_time_points must be an integer")
    normalized = int(number_of_time_points)
    if normalized < 2:
        raise ValueError("number_of_time_points must be at least 2")
    return normalized


def _validate_tile_size(name: str, value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral):
        raise TypeError(f"{name} must be an integer")
    normalized = int(value)
    if normalized < 1:
        raise ValueError(f"{name} must be at least 1")
    return normalized


def _validate_tile_autograd_strategy(value: TileAutogradStrategy) -> TileAutogradStrategy:
    if not isinstance(value, str):
        raise TypeError("autograd_strategy must be a string")
    if value not in {"standard", "recompute"}:
        raise ValueError("autograd_strategy must be 'standard' or 'recompute'")
    return value


def _evaluate_tile(
    function: Callable[..., torch.Tensor],
    tensors: tuple[torch.Tensor, ...],
    strategy: TileAutogradStrategy,
) -> torch.Tensor:
    if (
        strategy == "standard"
        or not torch.is_grad_enabled()
        or not any(tensor.requires_grad for tensor in tensors)
    ):
        return function(*tensors)
    return checkpoint(
        function,
        *tensors,
        use_reentrant=False,
        preserve_rng_state=False,
    )


@dataclass(frozen=True)
class GaussianTilePlan:
    """Explicit row bounds and autograd strategy for exact blockwise operations."""

    query_rows: int
    source_rows: int
    autograd_strategy: TileAutogradStrategy = "standard"

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "query_rows",
            _validate_tile_size("query_rows", self.query_rows),
        )
        object.__setattr__(
            self,
            "source_rows",
            _validate_tile_size("source_rows", self.source_rows),
        )
        object.__setattr__(
            self,
            "autograd_strategy",
            _validate_tile_autograd_strategy(self.autograd_strategy),
        )

    def maximum_xyz_difference_tensor_bytes(self, *, bytes_per_float: int = 8) -> int:
        """Return the exact declared tile bound ``query × source × 3 × bytes``."""

        element_bytes = _validate_tile_size("bytes_per_float", bytes_per_float)
        return self.query_rows * self.source_rows * 3 * element_bytes


def _gaussian_tile(
    x: torch.Tensor,
    y: torch.Tensor,
    width: float,
) -> tuple[torch.Tensor, torch.Tensor]:
    differences = x[:, None, :] - y[None, :, :]
    squared_distances = torch.sum(differences.square(), dim=2)
    return differences, torch.exp(-squared_distances / (width * width))


def gaussian_kernel(x: torch.Tensor, y: torch.Tensor, kernel_width: float) -> torch.Tensor:
    """Return the dense Deformetrica-convention Gaussian kernel matrix."""

    _validate_float_matrix("x", x, columns=3)
    _validate_float_matrix("y", y, columns=3)
    _validate_compatible("y", y, x)
    width = _validate_width(kernel_width)
    _, kernel = _gaussian_tile(x, y, width)
    return kernel


def gaussian_convolve(
    x: torch.Tensor,
    y: torch.Tensor,
    weights: torch.Tensor,
    kernel_width: float,
) -> torch.Tensor:
    """Apply the dense Gaussian kernel from source points ``y`` to query points ``x``."""

    _validate_float_matrix("weights", weights)
    _validate_float_matrix("y", y, columns=3)
    if weights.shape[0] != y.shape[0]:
        raise ValueError("weights must have one row per point in y")
    _validate_compatible("weights", weights, y)
    return gaussian_kernel(x, y, kernel_width) @ weights


def gaussian_convolve_blockwise(
    x: torch.Tensor,
    y: torch.Tensor,
    weights: torch.Tensor,
    kernel_width: float,
    *,
    query_tile_size: int,
    source_tile_size: int,
    autograd_strategy: TileAutogradStrategy = "standard",
) -> torch.Tensor:
    """Apply the exact Gaussian convolution through explicit bounded tiles.

    ``recompute`` retains tile inputs for backward and reconstructs pairwise
    intermediates there. It is an explicit compute-for-graph-retention tradeoff,
    not a peak-memory guarantee.
    """

    _validate_float_matrix("x", x, columns=3)
    _validate_float_matrix("y", y, columns=3)
    _validate_float_matrix("weights", weights)
    _validate_compatible("y", y, x)
    _validate_compatible("weights", weights, x)
    if weights.shape[0] != y.shape[0]:
        raise ValueError("weights must have one row per point in y")
    width = _validate_width(kernel_width)
    plan = GaussianTilePlan(query_tile_size, source_tile_size, autograd_strategy)

    def evaluate(query: torch.Tensor, source: torch.Tensor, source_weights: torch.Tensor):
        _, kernel = _gaussian_tile(query, source, width)
        return kernel @ source_weights

    outputs = []
    for query_start in range(0, x.shape[0], plan.query_rows):
        query = x[query_start : query_start + plan.query_rows]
        result = torch.zeros(
            (query.shape[0], weights.shape[1]),
            dtype=x.dtype,
            device=x.device,
        )
        for source_start in range(0, y.shape[0], plan.source_rows):
            source = y[source_start : source_start + plan.source_rows]
            source_weights = weights[source_start : source_start + plan.source_rows]
            result = result + _evaluate_tile(
                evaluate,
                (query, source, source_weights),
                plan.autograd_strategy,
            )
        outputs.append(result)
    return torch.cat(outputs, dim=0)


def gaussian_convolve_gradient(
    left_weights: torch.Tensor,
    x: torch.Tensor,
    y: torch.Tensor | None = None,
    right_weights: torch.Tensor | None = None,
    kernel_width: float = 1.0,
) -> torch.Tensor:
    """Differentiate ``sum(left * K(x, y) @ right)`` with respect to ``x``.

    With omitted ``y`` and ``right_weights``, this is the partial kernel derivative used by
    Deformetrica's geodesic equations. It equals the gradient of one half of the symmetric
    deformation energy with respect to the control points.
    """

    if y is None:
        y = x
    if right_weights is None:
        right_weights = left_weights
    _validate_float_matrix("x", x, columns=3)
    _validate_float_matrix("y", y, columns=3)
    _validate_float_matrix("left_weights", left_weights)
    _validate_float_matrix("right_weights", right_weights)
    _validate_compatible("y", y, x)
    _validate_compatible("left_weights", left_weights, x)
    _validate_compatible("right_weights", right_weights, x)
    if left_weights.shape[0] != x.shape[0]:
        raise ValueError("left_weights must have one row per point in x")
    if right_weights.shape[0] != y.shape[0]:
        raise ValueError("right_weights must have one row per point in y")
    if left_weights.shape[1] != right_weights.shape[1]:
        raise ValueError("left_weights and right_weights must have the same column count")

    width = _validate_width(kernel_width)
    differences = x[:, None, :] - y[None, :, :]
    coefficients = (left_weights @ right_weights.T) * gaussian_kernel(x, y, width)
    return (-2.0 / (width * width)) * torch.sum(coefficients[:, :, None] * differences, dim=1)


def gaussian_convolve_gradient_blockwise(
    left_weights: torch.Tensor,
    x: torch.Tensor,
    y: torch.Tensor | None = None,
    right_weights: torch.Tensor | None = None,
    kernel_width: float = 1.0,
    *,
    query_tile_size: int,
    source_tile_size: int,
    autograd_strategy: TileAutogradStrategy = "standard",
) -> torch.Tensor:
    """Evaluate the exact explicit Gaussian x-gradient through bounded tiles."""

    if y is None:
        y = x
    if right_weights is None:
        right_weights = left_weights
    _validate_float_matrix("x", x, columns=3)
    _validate_float_matrix("y", y, columns=3)
    _validate_float_matrix("left_weights", left_weights)
    _validate_float_matrix("right_weights", right_weights)
    _validate_compatible("y", y, x)
    _validate_compatible("left_weights", left_weights, x)
    _validate_compatible("right_weights", right_weights, x)
    if left_weights.shape[0] != x.shape[0]:
        raise ValueError("left_weights must have one row per point in x")
    if right_weights.shape[0] != y.shape[0]:
        raise ValueError("right_weights must have one row per point in y")
    if left_weights.shape[1] != right_weights.shape[1]:
        raise ValueError("left_weights and right_weights must have the same column count")
    width = _validate_width(kernel_width)
    plan = GaussianTilePlan(query_tile_size, source_tile_size, autograd_strategy)
    outputs = []
    scale = -2.0 / (width * width)

    def evaluate(
        query_weights: torch.Tensor,
        query: torch.Tensor,
        source: torch.Tensor,
        source_weights: torch.Tensor,
    ) -> torch.Tensor:
        differences, kernel = _gaussian_tile(query, source, width)
        coefficients = (query_weights @ source_weights.T) * kernel
        return scale * torch.sum(coefficients[:, :, None] * differences, dim=1)

    for query_start in range(0, x.shape[0], plan.query_rows):
        query = x[query_start : query_start + plan.query_rows]
        query_weights = left_weights[query_start : query_start + plan.query_rows]
        result = torch.zeros_like(query)
        for source_start in range(0, y.shape[0], plan.source_rows):
            source = y[source_start : source_start + plan.source_rows]
            source_weights = right_weights[source_start : source_start + plan.source_rows]
            result = result + _evaluate_tile(
                evaluate,
                (query_weights, query, source, source_weights),
                plan.autograd_strategy,
            )
        outputs.append(result)
    return torch.cat(outputs, dim=0)


def _validate_gaussian_tile_plan(
    value: GaussianTilePlan | None,
) -> GaussianTilePlan | None:
    if value is not None and not isinstance(value, GaussianTilePlan):
        raise TypeError("gaussian_tile_plan must be a GaussianTilePlan or None")
    return value


def _gaussian_convolve_with_plan(
    x: torch.Tensor,
    y: torch.Tensor,
    weights: torch.Tensor,
    kernel_width: float,
    plan: GaussianTilePlan | None,
) -> torch.Tensor:
    if plan is None:
        return gaussian_convolve(x, y, weights, kernel_width)
    return gaussian_convolve_blockwise(
        x,
        y,
        weights,
        kernel_width,
        query_tile_size=plan.query_rows,
        source_tile_size=plan.source_rows,
        autograd_strategy=plan.autograd_strategy,
    )


def _gaussian_convolve_gradient_with_plan(
    left_weights: torch.Tensor,
    x: torch.Tensor,
    kernel_width: float,
    plan: GaussianTilePlan | None,
) -> torch.Tensor:
    if plan is None:
        return gaussian_convolve_gradient(
            left_weights,
            x,
            kernel_width=kernel_width,
        )
    return gaussian_convolve_gradient_blockwise(
        left_weights,
        x,
        kernel_width=kernel_width,
        query_tile_size=plan.query_rows,
        source_tile_size=plan.source_rows,
        autograd_strategy=plan.autograd_strategy,
    )


def deformation_energy(
    control_points: torch.Tensor,
    momenta: torch.Tensor,
    kernel_width: float,
    *,
    gaussian_tile_plan: GaussianTilePlan | None = None,
) -> torch.Tensor:
    """Return the Deformetrica deformation norm squared ``p^T K(q,q) p``."""

    plan = _validate_gaussian_tile_plan(gaussian_tile_plan)
    _validate_float_matrix("control_points", control_points, columns=3)
    _validate_float_matrix("momenta", momenta, columns=3)
    _validate_compatible("momenta", momenta, control_points)
    if momenta.shape != control_points.shape:
        raise ValueError("momenta must have the same shape as control_points")
    velocity = _gaussian_convolve_with_plan(
        control_points,
        control_points,
        momenta,
        kernel_width,
        plan,
    )
    return torch.sum(momenta * velocity)


def _rk2_shooting_step(
    control_points: torch.Tensor,
    momenta: torch.Tensor,
    kernel_width: float,
    step: float,
    gaussian_tile_plan: GaussianTilePlan | None,
) -> tuple[torch.Tensor, torch.Tensor]:
    points_velocity = _gaussian_convolve_with_plan(
        control_points,
        control_points,
        momenta,
        kernel_width,
        gaussian_tile_plan,
    )
    momenta_velocity = -_gaussian_convolve_gradient_with_plan(
        momenta,
        control_points,
        kernel_width,
        gaussian_tile_plan,
    )
    midpoint_points = control_points + 0.5 * step * points_velocity
    midpoint_momenta = momenta + 0.5 * step * momenta_velocity
    next_points = control_points + step * _gaussian_convolve_with_plan(
        midpoint_points,
        midpoint_points,
        midpoint_momenta,
        kernel_width,
        gaussian_tile_plan,
    )
    next_momenta = momenta - step * _gaussian_convolve_gradient_with_plan(
        midpoint_momenta,
        midpoint_points,
        kernel_width,
        gaussian_tile_plan,
    )
    return next_points, next_momenta


def shoot(
    control_points: torch.Tensor,
    momenta: torch.Tensor,
    kernel_width: float,
    number_of_time_points: int,
    *,
    integrator: Literal["euler", "rk2"] = "rk2",
    gaussian_tile_plan: GaussianTilePlan | None = None,
) -> ShootingTrajectory:
    """Integrate control points and momenta from time zero to one."""

    plan = _validate_gaussian_tile_plan(gaussian_tile_plan)
    _validate_float_matrix("control_points", control_points, columns=3)
    _validate_float_matrix("momenta", momenta, columns=3)
    _validate_compatible("momenta", momenta, control_points)
    if momenta.shape != control_points.shape:
        raise ValueError("momenta must have the same shape as control_points")
    width = _validate_width(kernel_width)
    time_points = _validate_time_points(number_of_time_points)
    if integrator not in {"euler", "rk2"}:
        raise ValueError("integrator must be 'euler' or 'rk2'")

    step = 1.0 / (time_points - 1)
    points_state = control_points
    momenta_state = momenta
    points_path = [points_state]
    momenta_path = [momenta_state]

    for _ in range(time_points - 1):
        points_velocity = _gaussian_convolve_with_plan(
            points_state,
            points_state,
            momenta_state,
            width,
            plan,
        )
        momenta_velocity = -_gaussian_convolve_gradient_with_plan(
            momenta_state,
            points_state,
            width,
            plan,
        )
        if integrator == "euler":
            next_points = points_state + step * points_velocity
            next_momenta = momenta_state + step * momenta_velocity
        else:
            next_points, next_momenta = _rk2_shooting_step(
                points_state,
                momenta_state,
                width,
                step,
                plan,
            )
        points_state = next_points
        momenta_state = next_momenta
        points_path.append(points_state)
        momenta_path.append(momenta_state)

    return ShootingTrajectory(
        control_points=torch.stack(points_path),
        momenta=torch.stack(momenta_path),
    )


def flow_points(
    points: torch.Tensor,
    trajectory: ShootingTrajectory,
    kernel_width: float,
    *,
    integrator: Literal["euler", "heun", "deformetrica_heun"] = "heun",
    gaussian_tile_plan: GaussianTilePlan | None = None,
) -> torch.Tensor:
    """Flow template/landmark points along a stored shooting trajectory.

    ``heun`` is the standard predictor-corrector method. ``deformetrica_heun``
    reproduces Deformetrica 4.3's final-step extrapolation beyond the stored
    trajectory and exists only to make that observable legacy behavior explicit.
    """

    plan = _validate_gaussian_tile_plan(gaussian_tile_plan)
    _validate_float_matrix("points", points, columns=3)
    if not isinstance(trajectory, ShootingTrajectory):
        raise TypeError("trajectory must be a ShootingTrajectory")
    if not isinstance(trajectory.control_points, torch.Tensor) or not isinstance(
        trajectory.momenta, torch.Tensor
    ):
        raise TypeError("trajectory states must be torch.Tensor instances")
    if trajectory.control_points.ndim != 3 or trajectory.momenta.ndim != 3:
        raise ValueError("trajectory tensors must have shape (time, points, 3)")
    if trajectory.control_points.shape[1] == 0 or trajectory.control_points.shape[2] != 3:
        raise ValueError("trajectory tensors must have shape (time, points, 3)")
    if trajectory.control_points.shape != trajectory.momenta.shape:
        raise ValueError("trajectory control points and momenta must have identical shapes")
    if trajectory.control_points.shape[0] < 2:
        raise ValueError("trajectory must contain at least two time points")
    _validate_float_matrix(
        "trajectory.control_points",
        trajectory.control_points.reshape(-1, 3),
        columns=3,
    )
    _validate_float_matrix(
        "trajectory.momenta",
        trajectory.momenta.reshape(-1, 3),
        columns=3,
    )
    _validate_compatible("trajectory.control_points", trajectory.control_points, points)
    _validate_compatible("trajectory.momenta", trajectory.momenta, points)
    width = _validate_width(kernel_width)
    if integrator not in {"euler", "heun", "deformetrica_heun"}:
        raise ValueError("integrator must be 'euler', 'heun', or 'deformetrica_heun'")

    step = 1.0 / (trajectory.control_points.shape[0] - 1)
    state = points
    path = [state]
    for index in range(trajectory.control_points.shape[0] - 1):
        velocity = _gaussian_convolve_with_plan(
            state,
            trajectory.control_points[index],
            trajectory.momenta[index],
            width,
            plan,
        )
        if integrator == "euler":
            next_state = state + step * velocity
        else:
            predictor = state + step * velocity
            next_control_points = trajectory.control_points[index + 1]
            next_momenta = trajectory.momenta[index + 1]
            if (
                integrator == "deformetrica_heun"
                and index == trajectory.control_points.shape[0] - 2
            ):
                next_control_points, next_momenta = _rk2_shooting_step(
                    trajectory.control_points[-1],
                    trajectory.momenta[-1],
                    width,
                    step,
                    plan,
                )
            next_velocity = _gaussian_convolve_with_plan(
                predictor,
                next_control_points,
                next_momenta,
                width,
                plan,
            )
            next_state = state + 0.5 * step * (velocity + next_velocity)
        state = next_state
        path.append(state)
    return torch.stack(path)


def _validate_triangles(triangles: torch.Tensor, vertices: torch.Tensor) -> None:
    if not isinstance(triangles, torch.Tensor):
        raise TypeError("triangles must be a torch.Tensor")
    if triangles.ndim != 2 or triangles.shape[1] != 3:
        raise ValueError("triangles must have shape (n, 3)")
    if triangles.shape[0] == 0:
        raise ValueError("triangles must contain at least one face")
    if triangles.dtype != torch.int64:
        raise TypeError("triangles must use torch.int64 connectivity")
    if triangles.device != vertices.device:
        raise ValueError("triangles and vertices must be on the same device")
    if int(torch.min(triangles)) < 0 or int(torch.max(triangles)) >= vertices.shape[0]:
        raise ValueError("triangles contain an out-of-range vertex index")


def triangle_centers_and_area_normals(
    vertices: torch.Tensor,
    triangles: torch.Tensor,
) -> tuple[torch.Tensor, torch.Tensor]:
    """Return triangle centroids and oriented area-weighted normals."""

    _validate_float_matrix("vertices", vertices, columns=3)
    _validate_triangles(triangles, vertices)
    a = vertices[triangles[:, 0]]
    b = vertices[triangles[:, 1]]
    c = vertices[triangles[:, 2]]
    centers = (a + b + c) / 3.0
    normals = torch.linalg.cross(b - a, c - a, dim=1) / 2.0
    if bool(torch.any(torch.linalg.vector_norm(normals, dim=1) == 0)):
        raise ValueError("triangles contain a degenerate zero-area face")
    return centers, normals


def _surface_geometry(
    vertices: torch.Tensor,
    triangles: torch.Tensor,
    *,
    reference_vertices: torch.Tensor | None = None,
) -> tuple[torch.Tensor, torch.Tensor]:
    geometry = triangle_centers_and_area_normals(vertices, triangles)
    if reference_vertices is not None:
        _validate_compatible("vertices", vertices, reference_vertices)
    return geometry


def _current_inner_product(
    centers_a: torch.Tensor,
    normals_a: torch.Tensor,
    centers_b: torch.Tensor,
    normals_b: torch.Tensor,
    kernel_width: float,
) -> torch.Tensor:
    return torch.sum(normals_a * gaussian_convolve(centers_a, centers_b, normals_b, kernel_width))


def current_squared_distance(
    vertices_a: torch.Tensor,
    triangles_a: torch.Tensor,
    vertices_b: torch.Tensor,
    triangles_b: torch.Tensor,
    kernel_width: float,
) -> torch.Tensor:
    """Return the orientation-sensitive current squared distance between surfaces."""

    centers_a, normals_a = _surface_geometry(vertices_a, triangles_a)
    centers_b, normals_b = _surface_geometry(vertices_b, triangles_b, reference_vertices=vertices_a)
    self_a = _current_inner_product(centers_a, normals_a, centers_a, normals_a, kernel_width)
    self_b = _current_inner_product(centers_b, normals_b, centers_b, normals_b, kernel_width)
    cross = _current_inner_product(centers_a, normals_a, centers_b, normals_b, kernel_width)
    return self_a + self_b - 2.0 * cross


def _current_inner_product_blockwise(
    centers_a: torch.Tensor,
    normals_a: torch.Tensor,
    centers_b: torch.Tensor,
    normals_b: torch.Tensor,
    kernel_width: float,
    plan: GaussianTilePlan,
) -> torch.Tensor:
    convolved = gaussian_convolve_blockwise(
        centers_a,
        centers_b,
        normals_b,
        kernel_width,
        query_tile_size=plan.query_rows,
        source_tile_size=plan.source_rows,
        autograd_strategy=plan.autograd_strategy,
    )
    return torch.sum(normals_a * convolved)


def current_squared_distance_blockwise(
    vertices_a: torch.Tensor,
    triangles_a: torch.Tensor,
    vertices_b: torch.Tensor,
    triangles_b: torch.Tensor,
    kernel_width: float,
    *,
    query_tile_size: int,
    source_tile_size: int,
    autograd_strategy: TileAutogradStrategy = "standard",
) -> torch.Tensor:
    """Return the exact Current distance without full face-pair matrices."""

    plan = GaussianTilePlan(query_tile_size, source_tile_size, autograd_strategy)
    centers_a, normals_a = _surface_geometry(vertices_a, triangles_a)
    centers_b, normals_b = _surface_geometry(
        vertices_b,
        triangles_b,
        reference_vertices=vertices_a,
    )
    self_a = _current_inner_product_blockwise(
        centers_a, normals_a, centers_a, normals_a, kernel_width, plan
    )
    self_b = _current_inner_product_blockwise(
        centers_b, normals_b, centers_b, normals_b, kernel_width, plan
    )
    cross = _current_inner_product_blockwise(
        centers_a, normals_a, centers_b, normals_b, kernel_width, plan
    )
    return self_a + self_b - 2.0 * cross


def _varifold_inner_product(
    centers_a: torch.Tensor,
    normals_a: torch.Tensor,
    centers_b: torch.Tensor,
    normals_b: torch.Tensor,
    kernel_width: float,
) -> torch.Tensor:
    areas_a = torch.linalg.vector_norm(normals_a, dim=1, keepdim=True)
    areas_b = torch.linalg.vector_norm(normals_b, dim=1, keepdim=True)
    unit_a = normals_a / areas_a
    unit_b = normals_b / areas_b
    orientation_similarity = (unit_a @ unit_b.T).square()
    weighted_kernel = gaussian_kernel(centers_a, centers_b, kernel_width) * orientation_similarity
    return torch.sum(areas_a * (weighted_kernel @ areas_b))


def varifold_squared_distance(
    vertices_a: torch.Tensor,
    triangles_a: torch.Tensor,
    vertices_b: torch.Tensor,
    triangles_b: torch.Tensor,
    kernel_width: float,
) -> torch.Tensor:
    """Return the orientation-insensitive varifold squared distance between surfaces."""

    centers_a, normals_a = _surface_geometry(vertices_a, triangles_a)
    centers_b, normals_b = _surface_geometry(vertices_b, triangles_b, reference_vertices=vertices_a)
    self_a = _varifold_inner_product(centers_a, normals_a, centers_a, normals_a, kernel_width)
    self_b = _varifold_inner_product(centers_b, normals_b, centers_b, normals_b, kernel_width)
    cross = _varifold_inner_product(centers_a, normals_a, centers_b, normals_b, kernel_width)
    return self_a + self_b - 2.0 * cross


def _varifold_inner_product_blockwise(
    centers_a: torch.Tensor,
    normals_a: torch.Tensor,
    centers_b: torch.Tensor,
    normals_b: torch.Tensor,
    kernel_width: float,
    plan: GaussianTilePlan,
) -> torch.Tensor:
    width = _validate_width(kernel_width)
    areas_a = torch.linalg.vector_norm(normals_a, dim=1, keepdim=True)
    areas_b = torch.linalg.vector_norm(normals_b, dim=1, keepdim=True)
    unit_a = normals_a / areas_a
    unit_b = normals_b / areas_b
    result = torch.zeros((), dtype=centers_a.dtype, device=centers_a.device)

    def evaluate(
        query_centers: torch.Tensor,
        query_areas: torch.Tensor,
        query_units: torch.Tensor,
        source_centers: torch.Tensor,
        source_areas: torch.Tensor,
        source_units: torch.Tensor,
    ) -> torch.Tensor:
        _, kernel = _gaussian_tile(query_centers, source_centers, width)
        orientation = (query_units @ source_units.T).square()
        return torch.sum(query_areas * ((kernel * orientation) @ source_areas))

    for query_start in range(0, centers_a.shape[0], plan.query_rows):
        query_centers = centers_a[query_start : query_start + plan.query_rows]
        query_areas = areas_a[query_start : query_start + plan.query_rows]
        query_units = unit_a[query_start : query_start + plan.query_rows]
        for source_start in range(0, centers_b.shape[0], plan.source_rows):
            source_centers = centers_b[source_start : source_start + plan.source_rows]
            source_areas = areas_b[source_start : source_start + plan.source_rows]
            source_units = unit_b[source_start : source_start + plan.source_rows]
            result = result + _evaluate_tile(
                evaluate,
                (
                    query_centers,
                    query_areas,
                    query_units,
                    source_centers,
                    source_areas,
                    source_units,
                ),
                plan.autograd_strategy,
            )
    return result


def varifold_squared_distance_blockwise(
    vertices_a: torch.Tensor,
    triangles_a: torch.Tensor,
    vertices_b: torch.Tensor,
    triangles_b: torch.Tensor,
    kernel_width: float,
    *,
    query_tile_size: int,
    source_tile_size: int,
    autograd_strategy: TileAutogradStrategy = "standard",
) -> torch.Tensor:
    """Return the exact Varifold distance without full face-pair matrices."""

    plan = GaussianTilePlan(query_tile_size, source_tile_size, autograd_strategy)
    centers_a, normals_a = _surface_geometry(vertices_a, triangles_a)
    centers_b, normals_b = _surface_geometry(
        vertices_b,
        triangles_b,
        reference_vertices=vertices_a,
    )
    self_a = _varifold_inner_product_blockwise(
        centers_a, normals_a, centers_a, normals_a, kernel_width, plan
    )
    self_b = _varifold_inner_product_blockwise(
        centers_b, normals_b, centers_b, normals_b, kernel_width, plan
    )
    cross = _varifold_inner_product_blockwise(
        centers_a, normals_a, centers_b, normals_b, kernel_width, plan
    )
    return self_a + self_b - 2.0 * cross
