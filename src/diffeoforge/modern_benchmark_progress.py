"""Versioned read-only progress events for frozen benchmark studies."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from importlib.resources import files
from typing import Any, Literal

import jsonschema

PROGRESS_VERSION = "0.1"
StudyProgressStatus = Literal[
    "study_started",
    "study_resumed",
    "condition_started",
    "condition_completed",
    "condition_reconciled",
    "study_interrupted",
    "study_completed",
    "study_already_complete",
]
TileAutogradStrategy = Literal["standard", "recompute"]


class StudyProgressObserverError(RuntimeError):
    """Raised when a synchronous progress observer fails."""


def _schema() -> dict[str, Any]:
    resource = files("diffeoforge.schema").joinpath(
        "modern-benchmark-study-progress-v0.1.json"
    )
    return json.loads(resource.read_text(encoding="utf-8"))


def validate_study_progress_event(event: dict[str, Any]) -> None:
    """Validate one serialized observer event against the strict public schema."""

    jsonschema.Draft202012Validator(_schema()).validate(event)


@dataclass(frozen=True)
class StudyProgressCondition:
    sequence: int
    condition_id: str
    pair_id: str
    subject_count: int
    tile_autograd_strategy: TileAutogradStrategy

    def __post_init__(self) -> None:
        if self.sequence < 1:
            raise ValueError("condition sequence must be positive")
        if not self.condition_id or not self.pair_id:
            raise ValueError("condition identity must not be blank")
        if self.subject_count < 1:
            raise ValueError("condition subject count must be positive")
        if self.tile_autograd_strategy not in {"standard", "recompute"}:
            raise ValueError("condition tile autograd strategy is invalid")

    @classmethod
    def from_design(cls, condition: dict[str, Any]) -> StudyProgressCondition:
        return cls(
            sequence=condition["sequence"],
            condition_id=condition["condition_id"],
            pair_id=condition["pair_id"],
            subject_count=condition["subject_count"],
            tile_autograd_strategy=condition["tile_autograd_strategy"],
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "condition_id": self.condition_id,
            "pair_id": self.pair_id,
            "subject_count": self.subject_count,
            "tile_autograd_strategy": self.tile_autograd_strategy,
        }


@dataclass(frozen=True)
class StudyProgressEvent:
    """One exact lifecycle or condition-count observation; never an ETA."""

    sequence: int
    status: StudyProgressStatus
    message: str
    completed_conditions: int
    total_conditions: int
    condition: StudyProgressCondition | None = None

    def __post_init__(self) -> None:
        if self.sequence < 0:
            raise ValueError("progress sequence must be nonnegative")
        if not self.message.strip():
            raise ValueError("progress message must not be blank")
        if self.total_conditions < 1:
            raise ValueError("total condition count must be positive")
        if not 0 <= self.completed_conditions <= self.total_conditions:
            raise ValueError("completed condition count is outside the frozen total")
        condition_statuses = {
            "condition_started",
            "condition_completed",
            "condition_reconciled",
            "study_interrupted",
        }
        if (self.status in condition_statuses) != (self.condition is not None):
            raise ValueError("progress status and condition presence are inconsistent")
        if self.condition is not None:
            if self.condition.sequence > self.total_conditions:
                raise ValueError("condition sequence exceeds the frozen total")
            expected = (
                self.condition.sequence
                if self.status in {"condition_completed", "condition_reconciled"}
                else self.condition.sequence - 1
            )
            if self.completed_conditions != expected:
                raise ValueError("condition progress count is inconsistent with its sequence")
        if self.status == "study_started" and self.completed_conditions != 0:
            raise ValueError("a newly started study has no completed conditions")
        if self.status in {"study_completed", "study_already_complete"} and (
            self.completed_conditions != self.total_conditions
        ):
            raise ValueError("completed study progress requires every condition")
        validate_study_progress_event(self.as_dict())

    @property
    def progress_version(self) -> str:
        return PROGRESS_VERSION

    def as_dict(self) -> dict[str, Any]:
        return {
            "progress_version": self.progress_version,
            "sequence": self.sequence,
            "status": self.status,
            "message": self.message,
            "completed_conditions": self.completed_conditions,
            "total_conditions": self.total_conditions,
            "condition": None if self.condition is None else self.condition.as_dict(),
        }


StudyProgressCallback = Callable[[StudyProgressEvent], None]
