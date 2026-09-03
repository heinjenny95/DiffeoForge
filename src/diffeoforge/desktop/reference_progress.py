"""Conservative progress and ETA estimates from Deformetrica log lines."""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass

from diffeoforge.runs import CONVERGENCE_RE, ITERATION_RE


@dataclass(frozen=True)
class DesktopReferenceProgress:
    """One parsed optimizer observation with a clearly bounded ETA meaning."""

    iteration: int
    maximum_iterations: int
    log_likelihood: float
    attachment: float
    regularity: float
    elapsed_seconds: float
    seconds_per_iteration: float | None
    eta_to_iteration_cap_seconds: float | None
    estimate_status: str
    likely_convergence_iteration_lower: int | None = None
    likely_convergence_iteration_upper: int | None = None
    eta_to_likely_convergence_lower_seconds: float | None = None
    eta_to_likely_convergence_upper_seconds: float | None = None
    resource_contention_detected: bool = False

    def as_dict(self) -> dict[str, int | float | str | None]:
        return {
            "iteration": self.iteration,
            "maximum_iterations": self.maximum_iterations,
            "log_likelihood": self.log_likelihood,
            "attachment": self.attachment,
            "regularity": self.regularity,
            "elapsed_seconds": self.elapsed_seconds,
            "seconds_per_iteration": self.seconds_per_iteration,
            "eta_to_iteration_cap_seconds": self.eta_to_iteration_cap_seconds,
            "estimate_status": self.estimate_status,
            "likely_convergence_iteration_lower": (
                self.likely_convergence_iteration_lower
            ),
            "likely_convergence_iteration_upper": (
                self.likely_convergence_iteration_upper
            ),
            "eta_to_likely_convergence_lower_seconds": (
                self.eta_to_likely_convergence_lower_seconds
            ),
            "eta_to_likely_convergence_upper_seconds": (
                self.eta_to_likely_convergence_upper_seconds
            ),
            "resource_contention_detected": self.resource_contention_detected,
        }

    @property
    def fraction_of_iteration_cap(self) -> float:
        return min(1.0, self.iteration / self.maximum_iterations)


class ReferenceProgressTracker:
    """Parse one Deformetrica stream without claiming a convergence-time forecast."""

    def __init__(
        self,
        maximum_iterations: int,
        *,
        window: int = 10,
        convergence_tolerance: float = 0.0001,
        output_overhead_seconds: float = 0.0,
    ) -> None:
        if isinstance(maximum_iterations, bool) or maximum_iterations < 1:
            raise ValueError("maximum_iterations must be a positive integer")
        if isinstance(window, bool) or window < 2:
            raise ValueError("window must be an integer of at least 2")
        self.maximum_iterations = int(maximum_iterations)
        self.window = int(window)
        self.convergence_tolerance = float(convergence_tolerance)
        self.output_overhead_seconds = float(output_overhead_seconds)
        if (
            not math.isfinite(self.convergence_tolerance)
            or self.convergence_tolerance <= 0
        ):
            raise ValueError("convergence_tolerance must be positive and finite")
        if (
            not math.isfinite(self.output_overhead_seconds)
            or self.output_overhead_seconds < 0
        ):
            raise ValueError("output_overhead_seconds must be finite and nonnegative")
        self._pending_iteration: int | None = None
        self._samples: list[tuple[int, float, float]] = []
        self._smoothed_seconds_per_iteration: float | None = None

    def _likely_convergence_window(self) -> tuple[int, int] | None:
        changes: list[tuple[int, float]] = []
        for (earlier_iteration, _earlier_elapsed, earlier_objective), (
            later_iteration,
            _later_elapsed,
            later_objective,
        ) in zip(self._samples, self._samples[1:], strict=False):
            relative = abs(later_objective - earlier_objective) / max(
                abs(earlier_objective),
                1.0,
            )
            if later_iteration > earlier_iteration and relative > 0:
                changes.append((later_iteration, relative))
        if len(changes) < 5:
            return None
        current_iteration = self._samples[-1][0]
        if changes[-1][1] <= self.convergence_tolerance:
            return current_iteration, min(self.maximum_iterations, current_iteration + 2)
        recent = changes[-min(self.window, len(changes)) :]
        x_values = [float(iteration) for iteration, _change in recent]
        y_values = [math.log(change) for _iteration, change in recent]
        x_mean = statistics.mean(x_values)
        y_mean = statistics.mean(y_values)
        denominator = sum((value - x_mean) ** 2 for value in x_values)
        if denominator <= 0:
            return None
        slope = sum(
            (x_value - x_mean) * (y_value - y_mean)
            for x_value, y_value in zip(x_values, y_values, strict=True)
        ) / denominator
        if slope >= -0.005:
            return None
        intercept = y_mean - slope * x_mean
        predicted = (math.log(self.convergence_tolerance) - intercept) / slope
        if not math.isfinite(predicted) or predicted <= current_iteration:
            return None
        if predicted > self.maximum_iterations * 1.25:
            return None
        residuals = [
            y_value - (intercept + slope * x_value)
            for x_value, y_value in zip(x_values, y_values, strict=True)
        ]
        residual_spread = statistics.pstdev(residuals) if len(residuals) > 1 else 0.0
        uncertainty = max(2, math.ceil(2.0 * residual_spread / abs(slope)))
        center = round(predicted)
        lower = max(current_iteration + 1, center - uncertainty)
        upper = min(self.maximum_iterations, center + uncertainty)
        if lower > upper:
            return None
        return lower, upper

    def observe(
        self,
        line: str,
        *,
        elapsed_seconds: float,
    ) -> DesktopReferenceProgress | None:
        """Return a progress observation when a complete objective line is seen."""

        if not isinstance(line, str):
            raise TypeError("line must be a string")
        elapsed = float(elapsed_seconds)
        if not math.isfinite(elapsed) or elapsed < 0:
            raise ValueError("elapsed_seconds must be finite and nonnegative")
        iteration_match = ITERATION_RE.search(line)
        if iteration_match:
            self._pending_iteration = int(iteration_match.group(1))
            return None
        convergence_match = CONVERGENCE_RE.search(line)
        if convergence_match is None or self._pending_iteration is None:
            return None

        iteration = self._pending_iteration
        self._pending_iteration = None
        if self._samples and iteration <= self._samples[-1][0]:
            return None
        objective = float(convergence_match.group(1))
        self._samples.append((iteration, elapsed, objective))

        rate_samples = self._samples[-(self.window + 1) :]
        rates = [
            (later_elapsed - earlier_elapsed) / (later_iteration - earlier_iteration)
            for (
                earlier_iteration,
                earlier_elapsed,
                _earlier_objective,
            ), (later_iteration, later_elapsed, _later_objective) in zip(
                rate_samples,
                rate_samples[1:],
                strict=False,
            )
            # Very small demo runs can flush several completed iterations in one
            # scheduler tick.  A zero wall-time delta is not a measured rate and
            # must remain in warm-up instead of violating the worker protocol's
            # strictly-positive seconds-per-iteration contract.
            if later_iteration > earlier_iteration and later_elapsed > earlier_elapsed
        ]
        seconds_per_iteration: float | None = None
        eta: float | None = None
        status = "warming_up"
        contention = False
        convergence_window: tuple[int, int] | None = None
        likely_eta_lower: float | None = None
        likely_eta_upper: float | None = None
        if len(rates) >= 3:
            observed_rate = float(statistics.median(rates))
            if self._smoothed_seconds_per_iteration is None:
                self._smoothed_seconds_per_iteration = observed_rate
            else:
                # Damp one-off scheduler/logging spikes while allowing a sustained
                # hardware or workload change to move the estimate over several samples.
                self._smoothed_seconds_per_iteration = (
                    0.7 * self._smoothed_seconds_per_iteration + 0.3 * observed_rate
                )
            seconds_per_iteration = self._smoothed_seconds_per_iteration
            eta = (
                max(0.0, self.maximum_iterations - iteration)
                * seconds_per_iteration
                + self.output_overhead_seconds
            )
            status = "observed_rate_to_iteration_cap"
            if len(rates) >= 6:
                historical = float(statistics.median(rates[:-3]))
                recent_rate = float(statistics.median(rates[-3:]))
                contention = historical > 0 and recent_rate > historical * 1.5
                if contention:
                    status = "observed_rate_to_cap_with_resource_contention"
            convergence_window = self._likely_convergence_window()
            if convergence_window is not None:
                likely_eta_lower = (
                    max(0, convergence_window[0] - iteration)
                    * seconds_per_iteration
                    + self.output_overhead_seconds
                )
                likely_eta_upper = (
                    max(0, convergence_window[1] - iteration)
                    * seconds_per_iteration
                    + self.output_overhead_seconds
                )

        return DesktopReferenceProgress(
            iteration=iteration,
            maximum_iterations=self.maximum_iterations,
            log_likelihood=objective,
            attachment=float(convergence_match.group(2)),
            regularity=float(convergence_match.group(3)),
            elapsed_seconds=elapsed,
            seconds_per_iteration=seconds_per_iteration,
            eta_to_iteration_cap_seconds=eta,
            estimate_status=status,
            likely_convergence_iteration_lower=(
                None if convergence_window is None else convergence_window[0]
            ),
            likely_convergence_iteration_upper=(
                None if convergence_window is None else convergence_window[1]
            ),
            eta_to_likely_convergence_lower_seconds=likely_eta_lower,
            eta_to_likely_convergence_upper_seconds=likely_eta_upper,
            resource_contention_detected=contention,
        )
