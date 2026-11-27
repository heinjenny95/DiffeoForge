"""Display-only Validation Lab accounting; never confers scientific acceptance."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


def backend_status(run_directory: Path | None, *, verified: bool) -> str:
    """A local backend receipt is an observation, not verified analysis evidence."""
    if verified:
        return "completed"
    if run_directory is None:
        return "unknown"
    try:
        result = json.loads((run_directory / "result.json").read_text(encoding="utf-8"))
        if result.get("status") == "completed" and result.get("return_code") == 0:
            return "completed"
        return "failed" if result.get("status") == "failed" else "unknown"
    except (OSError, ValueError, AttributeError):
        return "unknown"


def ledger_start(events: Sequence[Mapping[str, Any]]) -> str | None:
    """Do not substitute a resume timestamp for an unknown legacy original start."""
    for event in events:
        if event.get("event") == "run_inherited":
            return None  # Inheritance time is not the source study's original start.
        if event.get("event") == "run_started":
            stamp = event.get("recorded_at")
            return stamp if isinstance(stamp, str) else None
    return None


def wall_seconds(start: str | None, *, end: str | None = None, now: datetime) -> float | None:
    try:
        first = datetime.fromisoformat(start) if start else None
        last = datetime.fromisoformat(end) if end else now
        if first is None or first.tzinfo is None or last.tzinfo is None:
            return None
        return max(0.0, (last - first).total_seconds())
    except (ValueError, TypeError):
        return None


@dataclass(frozen=True)
class ValidationProgress:
    training_verified: int
    training_total: int
    holdout_verified: int
    holdout_total: int
    backend_finished: int
    evidence_pending: int
    evidence_failed: int
    execution_failed: int
    interrupted: int
    active: int
    pending: int
    reports_complete: bool

    @property
    def verified(self) -> int:
        return self.training_verified + self.holdout_verified

    @property
    def total(self) -> int:
        return self.training_total + self.holdout_total


def validation_progress(
    training: Any,
    holdout: Any = None,
    *,
    active_mode: str | None = None,
    active_run_id: str | None = None,
    evidence_run_id: str | None = None,
) -> ValidationProgress:
    """Count frozen run slots, not attempts, iterations, or estimated compute work."""
    counts: Counter[str] = Counter()
    modes = (("training", training.runs), ("holdout", holdout.runs if holdout else ()))
    for mode, runs in modes:
        for run in runs:
            verified = run.status == "completed" and run.evidence is not None
            backend = verified or run.backend_status == "completed"
            if backend:
                counts["backend"] += 1
            if verified:
                counts[mode] += 1
            elif mode == active_mode and run.run_id == evidence_run_id:
                counts["evidence_pending"] += 1
                if not backend:
                    counts["backend"] += 1
            elif mode == active_mode and run.run_id == active_run_id:
                counts["active"] += 1
            elif backend:
                counts["evidence_failed" if run.status == "failed" else "evidence_pending"] += 1
            elif run.status == "orphaned" or run.terminal_event == "run_interrupted":
                counts["interrupted"] += 1
            elif run.status == "failed":
                counts["execution_failed"] += 1
            else:
                counts["pending"] += 1
    holdout_total = len(training.plan.finalists)
    if holdout is None:
        counts["pending"] += holdout_total
    return ValidationProgress(
        counts["training"],
        len(training.runs),
        counts["holdout"],
        holdout_total,
        counts["backend"],
        counts["evidence_pending"],
        counts["evidence_failed"],
        counts["execution_failed"],
        counts["interrupted"],
        counts["active"],
        counts["pending"],
        training.status == "completed" and holdout is not None and holdout.status == "completed",
    )
