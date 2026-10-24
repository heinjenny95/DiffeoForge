"""Conservative pre-run planning ranges for Deformetrica reference atlases."""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass

from diffeoforge.report import PreflightResult

_REFERENCE_PAIR_EVALUATIONS_PER_SECOND = 200_000_000.0
_KEOPS_GPU_KERNEL_TIME_FACTOR = 0.12


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
    basis: str = "engineering_heuristic"
    pilot_observation_count: int = 0
    postprocessing_lower_seconds: float = 10.0
    postprocessing_typical_seconds: float = 30.0
    postprocessing_upper_seconds: float = 120.0

    def __post_init__(self) -> None:
        numeric = (
            self.lower_seconds,
            self.typical_seconds,
            self.upper_seconds,
            self.seconds_per_iteration,
            self.postprocessing_lower_seconds,
            self.postprocessing_typical_seconds,
            self.postprocessing_upper_seconds,
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
        if not (
            self.postprocessing_lower_seconds
            <= self.postprocessing_typical_seconds
            <= self.postprocessing_upper_seconds
        ):
            raise ValueError("postprocessing estimate bounds are inconsistent")


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
    gpu_kernels = runtime["device"] == "cuda"
    if gpu_kernels:
        seconds_per_iteration *= _KEOPS_GPU_KERNEL_TIME_FACTOR

    maximum_iterations = int(optimization["max_iterations"])
    total_faces = template_faces + sum(subject_faces)
    subject_count = len(subject_faces)
    postprocessing_lower = 8.0 + total_faces / 100_000.0
    postprocessing_typical = 20.0 + total_faces / 30_000.0 + subject_count * 0.25
    postprocessing_upper = 60.0 + total_faces / 8_000.0 + subject_count * 1.5
    calibration_result = (
        config.get("project", {})
        .get("parameter_provenance", {})
        .get("recommendation", {})
        .get("calibration_result", {})
    )
    runtime_calibration = (
        calibration_result.get("runtime_calibration", {})
        if isinstance(calibration_result, dict)
        else {}
    )
    observations = (
        runtime_calibration.get("observations", [])
        if isinstance(runtime_calibration, dict)
        else []
    )
    pilot_subject_count = (
        int(runtime_calibration.get("pilot_subject_count", 0))
        if isinstance(runtime_calibration, dict)
        else 0
    )
    calibrated_samples: list[tuple[float, int]] = []
    if pilot_subject_count > 0 and isinstance(observations, list):
        for observation in observations:
            if not isinstance(observation, dict):
                continue
            try:
                duration = float(observation["runtime_seconds"])
                final_iteration = int(observation["final_iteration"])
            except (KeyError, TypeError, ValueError):
                continue
            if math.isfinite(duration) and duration > 0 and final_iteration >= 1:
                calibrated_samples.append((duration, final_iteration))
    if len(calibrated_samples) >= 3:
        scaled_rates = sorted(
            duration / (final_iteration + 1) / pilot_subject_count
            * len(preflight.subjects)
            for duration, final_iteration in calibrated_samples
        )
        observed_iterations = sorted(
            min(maximum_iterations, final_iteration)
            for _duration, final_iteration in calibrated_samples
        )
        seconds_per_iteration = float(statistics.median(scaled_rates))
        lower_iterations = max(
            3,
            observed_iterations[round((len(observed_iterations) - 1) * 0.20)],
        )
        typical_iterations = max(
            lower_iterations,
            round(statistics.median(observed_iterations)),
        )
        upper_iterations = min(
            maximum_iterations,
            max(
                typical_iterations,
                observed_iterations[
                    round((len(observed_iterations) - 1) * 0.90)
                ],
            ),
        )
        lower_seconds = (
            seconds_per_iteration * (lower_iterations + 1) * 0.8
            + postprocessing_lower
        )
        typical_seconds = (
            seconds_per_iteration * (typical_iterations + 1)
            + postprocessing_typical
        )
        upper_seconds = (
            seconds_per_iteration * (upper_iterations + 1) * 1.4
            + postprocessing_upper
        )
        return ReferenceRuntimeEstimate(
            lower_seconds=lower_seconds,
            typical_seconds=typical_seconds,
            upper_seconds=upper_seconds,
            seconds_per_iteration=seconds_per_iteration,
            lower_iterations=lower_iterations,
            typical_iterations=typical_iterations,
            maximum_iterations=maximum_iterations,
            pair_evaluations_per_iteration=pair_evaluations,
            confidence="pilot_calibrated",
            basis="same-project_pilot_observations",
            pilot_observation_count=len(calibrated_samples),
            postprocessing_lower_seconds=postprocessing_lower,
            postprocessing_typical_seconds=postprocessing_typical,
            postprocessing_upper_seconds=postprocessing_upper,
        )

    lower_iterations = min(
        maximum_iterations,
        max(5, round(maximum_iterations * 0.20)),
    )
    typical_iterations = min(
        maximum_iterations,
        max(12, round(maximum_iterations * 0.60)),
    )
    setup_seconds = 25.0 + total_faces / 20_000.0
    if gpu_kernels:
        # A cold PyKeOps cache may compile formula-specific CUDA kernels once.
        setup_seconds += 90.0
    lower_seconds = (
        setup_seconds
        + seconds_per_iteration * lower_iterations * 0.35
        + postprocessing_lower
    )
    typical_seconds = (
        setup_seconds
        + seconds_per_iteration * typical_iterations
        + postprocessing_typical
    )
    upper_seconds = (
        setup_seconds
        + seconds_per_iteration * maximum_iterations * 2.0
        + postprocessing_upper
    )

    return ReferenceRuntimeEstimate(
        lower_seconds=lower_seconds,
        typical_seconds=typical_seconds,
        upper_seconds=upper_seconds,
        seconds_per_iteration=seconds_per_iteration,
        lower_iterations=lower_iterations,
        typical_iterations=typical_iterations,
        maximum_iterations=maximum_iterations,
        pair_evaluations_per_iteration=pair_evaluations,
        postprocessing_lower_seconds=postprocessing_lower,
        postprocessing_typical_seconds=postprocessing_typical,
        postprocessing_upper_seconds=postprocessing_upper,
    )
