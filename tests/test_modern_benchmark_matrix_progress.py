from __future__ import annotations

from dataclasses import FrozenInstanceError

import jsonschema
import pytest

from diffeoforge.modern_benchmark_matrix_progress import (
    MatrixStudyProgressCondition,
    MatrixStudyProgressEvent,
    validate_matrix_study_progress_event,
)


def _condition(sequence: int = 1) -> MatrixStudyProgressCondition:
    return MatrixStudyProgressCondition(
        sequence=sequence,
        condition_id=(
            f"condition-{sequence:04d}-subjects-000001-"
            "tiles-q000003-s000005-standard"
        ),
        cell_id="subjects-000001-tiles-q000003-s000005",
        subject_count=1,
        query_tile_size=3,
        source_tile_size=5,
        tile_autograd_strategy="standard",
    )


def test_progress_events_are_immutable_strict_and_exact_count_based() -> None:
    started = MatrixStudyProgressEvent(
        sequence=0,
        status="study_started",
        message="Study started",
        completed_conditions=0,
        total_conditions=2,
    )
    condition_started = MatrixStudyProgressEvent(
        sequence=1,
        status="condition_started",
        message="Condition started",
        completed_conditions=0,
        total_conditions=2,
        condition=_condition(1),
    )
    condition_completed = MatrixStudyProgressEvent(
        sequence=2,
        status="condition_completed",
        message="Condition completed",
        completed_conditions=1,
        total_conditions=2,
        condition=_condition(1),
    )

    assert started.progress_version == "0.2"
    assert started.as_dict()["condition"] is None
    assert condition_started.as_dict()["condition"]["subject_count"] == 1
    assert condition_started.as_dict()["condition"]["effective_pairwise_evaluation"] == {
        "mode": "blockwise",
        "query_tile_size": 3,
        "source_tile_size": 5,
    }
    assert condition_completed.completed_conditions == 1
    with pytest.raises(FrozenInstanceError):
        started.status = "study_completed"  # type: ignore[misc]

    invalid = started.as_dict()
    invalid["percent_complete"] = 50
    with pytest.raises(jsonschema.ValidationError):
        validate_matrix_study_progress_event(invalid)


@pytest.mark.parametrize(
    ("status", "completed", "condition"),
    [
        ("study_started", 1, None),
        ("study_completed", 1, None),
        ("condition_started", 1, _condition(1)),
        ("condition_completed", 0, _condition(1)),
        ("condition_reconciled", 0, _condition(1)),
        ("study_interrupted", 1, _condition(1)),
    ],
)
def test_inconsistent_lifecycle_counts_are_rejected(
    status: str,
    completed: int,
    condition: MatrixStudyProgressCondition | None,
) -> None:
    with pytest.raises(ValueError):
        MatrixStudyProgressEvent(
            sequence=0,
            status=status,  # type: ignore[arg-type]
            message="invalid",
            completed_conditions=completed,
            total_conditions=2,
            condition=condition,
        )
