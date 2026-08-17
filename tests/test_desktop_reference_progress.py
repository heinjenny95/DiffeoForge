from __future__ import annotations

import pytest

from diffeoforge.desktop.reference_progress import ReferenceProgressTracker


def _iteration(value: int) -> str:
    return f"---------------- Iteration: {value} ----------------\n"


def _objective(value: float) -> str:
    return (
        f">> Log-likelihood = {value:.3E} "
        "[ attachment = -8.000E+00 ; regularity = -2.000E+00 ]\n"
    )


def test_reference_progress_reports_observed_rate_eta_to_cap_only_after_warmup() -> None:
    tracker = ReferenceProgressTracker(100)
    observations = []
    for iteration, elapsed in ((0, 10.0), (1, 15.0), (2, 21.0), (3, 28.0)):
        assert tracker.observe(_iteration(iteration), elapsed_seconds=elapsed) is None
        observations.append(
            tracker.observe(_objective(-10 + iteration), elapsed_seconds=elapsed)
        )

    assert all(item is not None for item in observations)
    assert observations[2].estimate_status == "warming_up"
    final = observations[3]
    assert final.estimate_status == "observed_rate_to_iteration_cap"
    assert final.seconds_per_iteration == pytest.approx(6.0)
    assert final.eta_to_iteration_cap_seconds == pytest.approx(97 * 6.0)
    assert final.fraction_of_iteration_cap == pytest.approx(0.03)


def test_reference_progress_ignores_unpaired_and_regressing_iterations() -> None:
    tracker = ReferenceProgressTracker(50)
    assert tracker.observe(_objective(-10), elapsed_seconds=1) is None
    assert tracker.observe(_iteration(2), elapsed_seconds=2) is None
    first = tracker.observe(_objective(-9), elapsed_seconds=3)
    assert first is not None and first.iteration == 2
    assert tracker.observe(_iteration(1), elapsed_seconds=4) is None
    assert tracker.observe(_objective(-8), elapsed_seconds=5) is None


def test_reference_progress_reports_likely_convergence_window_from_decay() -> None:
    tracker = ReferenceProgressTracker(100, convergence_tolerance=0.0001)
    final = None
    for iteration in range(13):
        objective = -100.0 + 10.0 * (1.0 - 2.718281828 ** (-0.45 * iteration))
        assert tracker.observe(_iteration(iteration), elapsed_seconds=iteration * 5.0) is None
        final = tracker.observe(_objective(objective), elapsed_seconds=iteration * 5.0)

    assert final is not None
    assert final.likely_convergence_iteration_lower is not None
    assert final.likely_convergence_iteration_upper is not None
    assert final.eta_to_likely_convergence_lower_seconds is not None
    assert final.eta_to_likely_convergence_upper_seconds is not None
    assert final.eta_to_iteration_cap_seconds > (
        final.eta_to_likely_convergence_upper_seconds
    )


def test_reference_progress_flags_sustained_resource_contention() -> None:
    tracker = ReferenceProgressTracker(100)
    final = None
    elapsed = 0.0
    for iteration, increment in enumerate((5, 5, 5, 5, 20, 20, 20, 20)):
        elapsed += increment
        assert tracker.observe(_iteration(iteration), elapsed_seconds=elapsed) is None
        final = tracker.observe(_objective(-100 + iteration), elapsed_seconds=elapsed)

    assert final is not None
    assert final.resource_contention_detected is True
    assert final.estimate_status == "observed_rate_to_cap_with_resource_contention"
