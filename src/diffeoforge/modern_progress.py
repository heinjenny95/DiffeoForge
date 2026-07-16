"""Versioned read-only progress events for the modern workflow."""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from dataclasses import dataclass
from importlib.resources import files
from typing import Any, Literal

import jsonschema

PROGRESS_VERSION = "0.1"
TOTAL_WORKFLOW_STAGES = 7
ModernProgressPhase = Literal[
    "workflow",
    "inputs",
    "preprocessing",
    "quality",
    "initialization",
    "optimization",
    "bundle",
    "verification",
]
ModernProgressStatus = Literal["started", "completed", "decision"]
OptimizerDecisionStatus = Literal["initial", "accepted", "stationary", "failed"]
OptimizerBlock = Literal["momenta", "template", "control_points"]
_COMPLETED_STAGE_BY_PHASE = {
    "inputs": 1,
    "preprocessing": 2,
    "quality": 3,
    "initialization": 4,
    "optimization": 5,
    "bundle": 6,
    "verification": 7,
}


def _schema() -> dict[str, Any]:
    resource = files("diffeoforge.schema").joinpath("modern-progress-v0.1.json")
    return json.loads(resource.read_text(encoding="utf-8"))


def validate_modern_progress_event(event: dict[str, Any]) -> None:
    """Validate one serialized progress event against the public strict schema."""

    jsonschema.Draft202012Validator(_schema()).validate(event)


def _finite(name: str, value: float | None) -> None:
    if value is not None and not math.isfinite(value):
        raise ValueError(f"{name} must be finite or None")


@dataclass(frozen=True)
class ModernOptimizerProgress:
    """One committed optimizer decision exposed to a workflow observer."""

    completed_decisions: int
    maximum_decisions: int
    cycle: int
    max_cycles: int
    block: OptimizerBlock | None
    status: OptimizerDecisionStatus
    objective: float
    attachment: float
    regularity: float
    gradient_norm: float | None
    accepted_step_size: float | None
    line_search_evaluations: int

    def __post_init__(self) -> None:
        if self.maximum_decisions != self.max_cycles * 3:
            raise ValueError("maximum_decisions must equal max_cycles * 3 parameter blocks")
        if not 0 <= self.completed_decisions <= self.maximum_decisions:
            raise ValueError("completed_decisions must be within the configured maximum")
        if not 0 <= self.cycle <= self.max_cycles:
            raise ValueError("cycle must be within max_cycles")
        if self.status == "initial":
            if self.cycle != 0 or self.block is not None or self.completed_decisions != 0:
                raise ValueError("initial optimizer progress must describe cycle zero")
        elif self.cycle < 1 or self.block is None:
            raise ValueError("non-initial optimizer progress requires a cycle and block")
        if self.status == "accepted" and self.accepted_step_size is None:
            raise ValueError("accepted optimizer progress requires an accepted step size")
        if self.status != "accepted" and self.accepted_step_size is not None:
            raise ValueError("only accepted optimizer progress may contain a step size")
        for name, value in (
            ("objective", self.objective),
            ("attachment", self.attachment),
            ("regularity", self.regularity),
            ("gradient_norm", self.gradient_norm),
            ("accepted_step_size", self.accepted_step_size),
        ):
            _finite(name, value)

    def as_dict(self) -> dict[str, Any]:
        return {
            "completed_decisions": self.completed_decisions,
            "maximum_decisions": self.maximum_decisions,
            "cycle": self.cycle,
            "max_cycles": self.max_cycles,
            "block": self.block,
            "status": self.status,
            "objective": self.objective,
            "attachment": self.attachment,
            "regularity": self.regularity,
            "gradient_norm": self.gradient_norm,
            "accepted_step_size": self.accepted_step_size,
            "line_search_evaluations": self.line_search_evaluations,
        }


@dataclass(frozen=True)
class ModernProgressEvent:
    """One deterministic stage or committed optimizer-decision event."""

    sequence: int
    phase: ModernProgressPhase
    status: ModernProgressStatus
    message: str
    completed_stages: int
    optimizer: ModernOptimizerProgress | None = None

    def __post_init__(self) -> None:
        if self.sequence < 0:
            raise ValueError("sequence must be nonnegative")
        if not self.message.strip():
            raise ValueError("message must not be blank")
        if self.phase == "workflow":
            expected_statuses = {"started"}
            expected_completed = 0
        elif self.phase == "optimization":
            expected_statuses = {"started", "completed", "decision"}
            expected_completed = 4 if self.status != "completed" else 5
        else:
            expected_statuses = {"completed"}
            expected_completed = _COMPLETED_STAGE_BY_PHASE[self.phase]
        if self.status not in expected_statuses or self.completed_stages != expected_completed:
            raise ValueError("phase, status, and completed_stages are inconsistent")
        validate_modern_progress_event(self.as_dict())

    @property
    def progress_version(self) -> str:
        return PROGRESS_VERSION

    @property
    def total_stages(self) -> int:
        return TOTAL_WORKFLOW_STAGES

    def as_dict(self) -> dict[str, Any]:
        return {
            "progress_version": self.progress_version,
            "sequence": self.sequence,
            "phase": self.phase,
            "status": self.status,
            "message": self.message,
            "completed_stages": self.completed_stages,
            "total_stages": self.total_stages,
            "optimizer": None if self.optimizer is None else self.optimizer.as_dict(),
        }


ModernProgressCallback = Callable[[ModernProgressEvent], None]
