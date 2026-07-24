from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from pathlib import Path

from diffeoforge.desktop.reference_runtime_estimate import (
    estimate_reference_runtime,
)
from diffeoforge.report import collect_preflight

ROOT = Path(__file__).resolve().parents[1]


def test_reference_runtime_estimate_is_broad_and_parameter_bound() -> None:
    preflight = collect_preflight(ROOT / "examples" / "minimal-atlas-container.yaml")

    estimate = estimate_reference_runtime(preflight)

    assert estimate.lower_seconds < estimate.typical_seconds < estimate.upper_seconds
    assert estimate.lower_iterations < estimate.typical_iterations
    assert estimate.maximum_iterations == 100
    assert estimate.confidence == "very_low"


def test_reference_runtime_estimate_grows_strongly_with_surface_resolution() -> None:
    preflight = collect_preflight(ROOT / "examples" / "minimal-atlas-container.yaml")
    dense = replace(
        preflight,
        template=replace(
            preflight.template,
            points=preflight.template.points * 10,
            cells=preflight.template.cells * 10,
        ),
        subjects=tuple(
            replace(
                subject,
                points=subject.points * 10,
                cells=subject.cells * 10,
            )
            for subject in preflight.subjects
        ),
    )

    ordinary = estimate_reference_runtime(preflight)
    high_resolution = estimate_reference_runtime(dense)

    assert high_resolution.pair_evaluations_per_iteration == (
        ordinary.pair_evaluations_per_iteration * 100
    )
    assert (
        high_resolution.seconds_per_iteration
        > ordinary.seconds_per_iteration * 2
    )
    assert high_resolution.typical_seconds > ordinary.typical_seconds


def test_reference_runtime_estimate_accounts_for_configured_threads() -> None:
    preflight = collect_preflight(ROOT / "examples" / "minimal-atlas-container.yaml")
    config = deepcopy(preflight.config)
    config["runtime"]["threads"] = 16

    four_threads = estimate_reference_runtime(preflight)
    sixteen_threads = estimate_reference_runtime(replace(preflight, config=config))

    assert sixteen_threads.typical_seconds < four_threads.typical_seconds
