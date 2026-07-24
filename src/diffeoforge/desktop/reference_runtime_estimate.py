"""Conservative pre-run planning ranges for Deformetrica reference atlases."""

from __future__ import annotations

import math
from dataclasses import dataclass

from diffeoforge.report import PreflightResult

_REFERENCE_PAIR_EVALUATIONS_PER_SECOND = 200_000_000.0


@dataclass(frozen=True)
class ReferenceRuntimeEstimate:
    """One deliberately broad, non-benchmark pre-run planning estimate."""

    lower_seconds: float
    typical_seconds: float
    upper_seconds: float
    seconds_per_iteration: float
    lower_iterations: int
    typical_iterations: int
    maximum_iterations: int
    pair_evaluations_per_iteration: int
    confidence: str = "very_low"

    def __post_init__(self) -> None:
        numeric = (
            self.lower_seconds,
            self.typical_seconds,
            self.upper_seconds,
            self.seconds_per_iteration,
        )
        if not all(math.isfinite(value) and value > 0 for value in numeric):
            raise ValueError("runtime estimate durations must be positive and finite")
        if not self.lower_seconds <= self.typical_seconds <= self.upper_seconds:
            raise ValueError("runtime estimate bounds must contain the typical value")
        if not (
            1
            <= self.lower_iterations
            <= self.typical_iterations
            <= self.maximum_iterations
        ):
            raise ValueError("runtime estimate iteration assumptions are inconsistent")
        if self.pair_evaluations_per_iteration < 1:
            raise ValueError("runtime estimate workload must be positive")


def estimate_reference_runtime(
    preflight: PreflightResult,
) -> ReferenceRuntimeEstimate:
    """Estimate a broad range from cohort geometry and effective parameters.

    This is an engineering planning heuristic, not a hardware benchmark or a
    convergence prediction. The live estimate replaces it after optimizer output
    has been observed.
    """

    if not isinstance(preflight, PreflightResult):
        raise TypeError("preflight must be a PreflightResult")
    config = preflight.config
    model = config["model"]
    deformation = model["deformation"]
    optimization = config["optimization"]
    runtime = config["runtime"]

    template_faces = int(preflight.template.cells)
    subject_faces = tuple(int(subject.cells) for subject in preflight.subjects)
    pair_evaluations = template_faces * template_faces + sum(
        faces * faces + template_faces * faces for faces in subject_faces
    )

    timepoints = int(deformation["timepoints"])
    trajectory_factor = 0.70 + 0.30 * (timepoints / 10.0)
    if bool(deformation["use_rk2"]):
        trajectory_factor *= 1.45

    diagonal = float(preflight.template.bounding_box_diagonal)
    spacing_ratio = float(deformation["initial_control_point_spacing"]) / diagonal
    relative_control_density = min(
        8.0,
        max(0.25, (0.15 / spacing_ratio) ** 3),
    )
    control_factor = 0.75 + 0.25 * relative_control_density

    threads = max(1, int(runtime["threads"]))
    thread_factor = (4.0 / threads) ** 0.70
    seconds_per_iteration = (
        0.10
        + pair_evaluations
        / _REFERENCE_PAIR_EVALUATIONS_PER_SECOND
        * trajectory_factor
        * control_factor
        * thread_factor
    )

    maximum_iterations = int(optimization["max_iterations"])
    lower_iterations = min(
        maximum_iterations,
        max(3, round(maximum_iterations * 0.15)),
    )
    typical_iterations = min(
        maximum_iterations,
        max(8, round(maximum_iterations * 0.40)),
    )
    total_faces = template_faces + sum(subject_faces)
    setup_seconds = 25.0 + total_faces / 20_000.0
    lower_seconds = setup_seconds + seconds_per_iteration * lower_iterations * 0.35
    typical_seconds = setup_seconds + seconds_per_iteration * typical_iterations
    upper_seconds = setup_seconds + seconds_per_iteration * maximum_iterations * 2.0

    return ReferenceRuntimeEstimate(
        lower_seconds=lower_seconds,
        typical_seconds=typical_seconds,
        upper_seconds=upper_seconds,
        seconds_per_iteration=seconds_per_iteration,
        lower_iterations=lower_iterations,
        typical_iterations=typical_iterations,
        maximum_iterations=maximum_iterations,
        pair_evaluations_per_iteration=pair_evaluations,
    )
