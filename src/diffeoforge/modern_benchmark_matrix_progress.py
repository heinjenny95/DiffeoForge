"""Versioned read-only progress events for frozen matrix benchmark studies."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from importlib.resources import files
from typing import Any, Literal

import jsonschema

MATRIX_PROGRESS_VERSION = "0.2"
MatrixStudyProgressStatus = Literal[
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


class MatrixStudyProgressObserverError(RuntimeError):
    """Raised when a synchronous matrix progress observer fails."""


def _schema() -> dict[str, Any]:
    resource = files("diffeoforge.schema").joinpath(
        "modern-benchmark-study-progress-v0.2.json"
    )
    return json.loads(resource.read_text(encoding="utf-8"))


def validate_matrix_study_progress_event(event: dict[str, Any]) -> None:
    """Validate one serialized matrix observer event against its strict schema."""

    jsonschema.Draft202012Validator(_schema()).validate(event)


@dataclass(frozen=True)
class MatrixStudyProgressCondition:
    sequence: int
    condition_id: str
    cell_id: str
    subject_count: int
    query_tile_size: int
    source_tile_size: int
    tile_autograd_strategy: TileAutogradStrategy

    def __post_init__(self) -> None:
        if self.sequence < 1:
            raise ValueError("condition sequence must be positive")
        if not self.condition_id or not self.cell_id:
            raise ValueError("condition identity must not be blank")
        if self.subject_count < 1:
            raise ValueError("condition subject count must be positive")
        if self.query_tile_size < 1 or self.source_tile_size < 1:
            raise ValueError("condition tile dimensions must be positive")
        if self.tile_autograd_strategy not in {"standard", "recompute"}:
            raise ValueError("condition tile autograd strategy is invalid")

    @classmethod
    def from_design(cls, condition: dict[str, Any]) -> MatrixStudyProgressCondition:
        plan = condition["effective_pairwise_evaluation"]
        return cls(
            sequence=condition["sequence"],
            condition_id=condition["condition_id"],
            cell_id=condition["cell_id"],
            subject_count=condition["subject_count"],
            query_tile_size=plan["query_tile_size"],
            source_tile_size=plan["source_tile_size"],
            tile_autograd_strategy=condition["tile_autograd_strategy"],
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "condition_id": self.condition_id,
            "cell_id": self.cell_id,
            "subject_count": self.subject_count,
            "effective_pairwise_evaluation": {
                "mode": "blockwise",
                "query_tile_size": self.query_tile_size,
                "source_tile_size": self.source_tile_size,
            },
            "tile_autograd_strategy": self.tile_autograd_strategy,
        }


@dataclass(frozen=True)
class MatrixStudyProgressEvent:
    """One exact matrix lifecycle or condition-count observation; never an ETA."""

    sequence: int
    status: MatrixStudyProgressStatus
    message: str
    completed_conditions: int
    total_conditions: int
    condition: MatrixStudyProgressCondition | None = None

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
        validate_matrix_study_progress_event(self.as_dict())

    @property
    def progress_version(self) -> str:
        return MATRIX_PROGRESS_VERSION

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


MatrixStudyProgressCallback = Callable[[MatrixStudyProgressEvent], None]
