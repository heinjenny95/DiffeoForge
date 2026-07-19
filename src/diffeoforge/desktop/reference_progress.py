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

    @property
    def fraction_of_iteration_cap(self) -> float:
        return min(1.0, self.iteration / self.maximum_iterations)


class ReferenceProgressTracker:
    """Parse one Deformetrica stream without claiming a convergence-time forecast."""

    def __init__(self, maximum_iterations: int, *, window: int = 10) -> None:
        if isinstance(maximum_iterations, bool) or maximum_iterations < 1:
            raise ValueError("maximum_iterations must be a positive integer")
        if isinstance(window, bool) or window < 2:
            raise ValueError("window must be an integer of at least 2")
        self.maximum_iterations = int(maximum_iterations)
        self.window = int(window)
        self._pending_iteration: int | None = None
        self._samples: list[tuple[int, float]] = []

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
        self._samples.append((iteration, elapsed))
        self._samples = self._samples[-self.window :]

        rates = [
            (later_elapsed - earlier_elapsed) / (later_iteration - earlier_iteration)
            for (earlier_iteration, earlier_elapsed), (later_iteration, later_elapsed) in zip(
                self._samples,
                self._samples[1:],
                strict=False,
            )
            if later_iteration > earlier_iteration and later_elapsed >= earlier_elapsed
        ]
        seconds_per_iteration: float | None = None
        eta: float | None = None
        status = "warming_up"
        if len(rates) >= 3:
            seconds_per_iteration = float(statistics.median(rates))
            eta = max(0.0, self.maximum_iterations - iteration) * seconds_per_iteration
            status = "observed_rate_to_iteration_cap"

        return DesktopReferenceProgress(
            iteration=iteration,
            maximum_iterations=self.maximum_iterations,
            log_likelihood=float(convergence_match.group(1)),
            attachment=float(convergence_match.group(2)),
            regularity=float(convergence_match.group(3)),
            elapsed_seconds=elapsed,
            seconds_per_iteration=seconds_per_iteration,
            eta_to_iteration_cap_seconds=eta,
            estimate_status=status,
        )
