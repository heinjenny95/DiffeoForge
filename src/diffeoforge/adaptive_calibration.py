"""Bounded, specimen-aware decisions for adaptive pilot parameter search.

This module proposes experiments, never anatomical approval. Runtime and
deformation energy do not enter its fit ordering. All changes are relative to
the dataset's current settings, with explicit limits and a finite run budget.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass

FIT_PARAMETERS = (
    "attachment_kernel_width",
    "deformation_kernel_width",
    "initial_control_point_spacing",
    "noise_std",
)


@dataclass(frozen=True)
class AdaptiveSearchPolicy:
    maximum_new_runs: int = 12
    maximum_rounds: int = 3
    iterations_per_run: int = 300
    minimum_relative_progress: float = 0.01

    def __post_init__(self) -> None:
        for name in ("maximum_new_runs", "maximum_rounds", "iterations_per_run"):
            value = getattr(self, name)
            if type(value) is not int or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        if (
            not math.isfinite(self.minimum_relative_progress)
            or not 0 <= self.minimum_relative_progress < 1
        ):
            raise ValueError("minimum_relative_progress must lie in [0, 1)")


@dataclass(frozen=True)
class FitObservation:
    candidate_id: str
    values: Mapping[str, float]
    subject_fit: Mapping[str, float]
    completed: bool = True
    invalid_faces: int = 0
    converged: bool = True
    review_approved: bool | None = None

    @property
    def fit_key(self) -> tuple[float, float, str]:
        values = tuple(self.subject_fit.values())
        return max(values), sum(values) / len(values), self.candidate_id


@dataclass(frozen=True)
class FitTrial:
    trial_id: str
    label: str
    values: Mapping[str, float]
    iterations: int
    initialization: str
    reason: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class AdaptiveFitDecision:
    center_id: str | None
    trials: tuple[FitTrial, ...]
    stop_reason: str | None
    regressions: Mapping[str, tuple[str, ...]]
    rationale: str


def _valid_observation(row: FitObservation, expected: set[str]) -> bool:
    return (
        row.completed
        and row.review_approved is not False
        and type(row.invalid_faces) is int
        and row.invalid_faces == 0
        and set(row.subject_fit) == expected
        and all(
            type(value) in (int, float) and math.isfinite(value) and value >= 0
            for value in row.subject_fit.values()
        )
        and set(row.values) >= set(FIT_PARAMETERS)
        and all(
            type(row.values[name]) in (int, float)
            and math.isfinite(row.values[name])
            and row.values[name] > 0
            for name in FIT_PARAMETERS
        )
    )


def specimen_regressions(candidate: FitObservation, baseline: FitObservation) -> tuple[str, ...]:
    """Use only floating-point slack, not an invented biological tolerance."""
    if set(candidate.subject_fit) != set(baseline.subject_fit):
        raise ValueError("Cannot compare different pilot cohorts")
    return tuple(
        sorted(
            name
            for name, value in candidate.subject_fit.items()
            if value > baseline.subject_fit[name]
            and not math.isclose(value, baseline.subject_fit[name], rel_tol=1e-9, abs_tol=1e-12)
        )
    )


def adaptive_fit_decision(
    observations: Sequence[FitObservation],
    *,
    expected_subjects: Sequence[str],
    policy: AdaptiveSearchPolicy,
    bounds: Mapping[str, tuple[float, float]],
    round_index: int,
    new_runs_used: int,
    previous_center_id: str | None = None,
    tested_trial_keys: Sequence[str] = (),
) -> AdaptiveFitDecision:
    """Choose a center and a finite next batch from actual per-specimen results.

    A cap-limited but finite fit may seed further work; it is not thereby
    eligible for stage advancement. Better fit of one subject cannot silently
    trade away another subject when moving the automatic search center.
    """
    if type(round_index) is not int or round_index < 0:
        raise ValueError("round_index must be a nonnegative integer")
    if type(new_runs_used) is not int or new_runs_used < 0:
        raise ValueError("new_runs_used must be a nonnegative integer")
    expected = set(expected_subjects)
    if not expected or len(expected) != len(expected_subjects):
        raise ValueError("The pilot cohort must contain unique named subjects")
    if len({r.candidate_id for r in observations}) != len(observations):
        raise ValueError("Candidate identifiers must be unique")
    if set(bounds) != set(FIT_PARAMETERS):
        raise ValueError("Bounds must cover exactly the four fit parameters")
    for name, interval in bounds.items():
        if (
            len(interval) != 2
            or any(type(v) not in (float, int) or not math.isfinite(v) for v in interval)
            or not 0 < interval[0] < interval[1]
        ):
            raise ValueError(f"Invalid search bounds for {name}")
    valid = [row for row in observations if _valid_observation(row, expected)]
    if not valid:
        return AdaptiveFitDecision(
            None, (), "no_valid_fit_evidence", {}, "Complete per-specimen fit evidence is required."
        )
    previous = next((r for r in valid if r.candidate_id == previous_center_id), None)
    rejected_previous = any(
        r.candidate_id == previous_center_id and r.review_approved is False for r in observations
    )
    if previous_center_id is not None and previous is None and not rejected_previous:
        raise ValueError("The previous search center no longer has valid bound evidence")
    if any(r.review_approved is True for r in valid) and (
        previous is None or previous.review_approved is not True
    ):
        previous = None  # Explicit anatomical acceptance outranks an unreviewed proxy center.
    regressions = {
        row.candidate_id: specimen_regressions(row, previous)
        for row in valid
        if previous is not None
    }
    candidates = [row for row in valid if not regressions.get(row.candidate_id)]
    center = min(
        candidates,
        key=lambda row: (
            row.review_approved is not True,
            *row.fit_key[:2],
            row.candidate_id != previous_center_id,
            row.candidate_id,
        ),
    )
    if new_runs_used >= policy.maximum_new_runs or round_index >= policy.maximum_rounds:
        return AdaptiveFitDecision(
            center.candidate_id,
            (),
            "budget_reached",
            regressions,
            "The declared search budget is exhausted; inspect the fits.",
        )
    if previous is not None and round_index > 0:
        old = previous.fit_key[:2]
        new = center.fit_key[:2]
        improvements = [(a - b) / max(a, 1e-15) for a, b in zip(old, new, strict=True)]
        if max(improvements) < policy.minimum_relative_progress:
            tradeoff = any(
                regressions.get(row.candidate_id) and row.fit_key[:2] < previous.fit_key[:2]
                for row in valid
            )
            reason = "specimen_tradeoff" if tradeoff else "fit_plateau"
            return AdaptiveFitDecision(
                center.candidate_id,
                (),
                reason,
                regressions,
                "No sufficient measured progress without worsening another specimen. "
                "This is a search stop, not an anatomical pass.",
            )

    # Probe several plausible causes; the metric alone cannot diagnose one.
    # Continue from learned geometry for unchanged control grid/kernel; spatial
    # model changes require a fresh field, not mislabelled reuse of the old fit.
    factor = 2.0 if round_index == 0 else math.sqrt(2.0)
    experiments = [
        (
            "continue",
            {},
            "warm",
            "Test additional optimization before attributing error to parameters.",
        ),
        ("stronger-fit", {"noise_std": 1 / factor}, "warm", "Test stronger surface matching."),
        (
            "finer-detail",
            {"attachment_kernel_width": 1 / factor},
            "warm",
            "Test finer surface detail.",
        ),
        (
            "detail-and-fit",
            {"attachment_kernel_width": 1 / factor, "noise_std": 1 / factor},
            "warm",
            "Test the interaction between matching detail and fit weight.",
        ),
        (
            "local-deformation",
            {"deformation_kernel_width": 1 / factor},
            "zero",
            "Test more local deformation without reusing an incompatible field.",
        ),
        (
            "global-deformation",
            {"deformation_kernel_width": factor},
            "zero",
            "Test whether broader motion fits large shape differences better.",
        ),
        (
            "denser-controls",
            {"initial_control_point_spacing": 1 / factor},
            "zero",
            "Test control-grid capacity with a new compatible field.",
        ),
    ]
    trials = []
    tested = set(tested_trial_keys)
    for label, factors, initialization, reason in experiments:
        values = {
            name: float(center.values[name]) * factors.get(name, 1.0) for name in FIT_PARAMETERS
        }
        if any(not bounds[name][0] <= value <= bounds[name][1] for name, value in values.items()):
            continue
        identity = {
            "center": center.candidate_id,
            "values": values,
            "initialization": initialization,
            "iterations": policy.iterations_per_run,
        }
        key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:16]
        trial_id = f"adaptive-{key}"
        if trial_id in tested:
            continue
        trials.append(
            FitTrial(trial_id, label, values, policy.iterations_per_run, initialization, reason)
        )
        if len(trials) >= policy.maximum_new_runs - new_runs_used:
            break
    return AdaptiveFitDecision(
        center.candidate_id,
        tuple(trials),
        None if trials else "no_new_trial_within_bounds",
        regressions,
        "Compare fit of every specimen. Keep old results; move the automatic "
        "center only when no specimen regresses. Final anatomy still needs review.",
    )
