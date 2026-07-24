from __future__ import annotations

import jsonschema
import pytest

from diffeoforge.modern_optimizer_benchmark_progress import (
    OptimizerStudyProgressCondition,
    OptimizerStudyProgressEvent,
    validate_optimizer_study_progress_event,
)


def test_optimizer_progress_events_are_strict_exact_counts() -> None:
    condition = OptimizerStudyProgressCondition(
        sequence=2,
        condition_id="condition-0002-subjects-0005-cycles-003",
        subject_count=5,
        cycle_cap=3,
    )
    event = OptimizerStudyProgressEvent(
        sequence=4,
        status="condition_completed",
        message="A frozen condition completed.",
        completed_conditions=2,
        total_conditions=4,
        condition=condition,
    )

    assert event.progress_version == "0.1"
    assert event.as_dict()["condition"]["cycle_cap"] == 3
    validate_optimizer_study_progress_event(event.as_dict())


def test_optimizer_progress_rejects_percentages_and_inconsistent_counts() -> None:
    event = OptimizerStudyProgressEvent(
        sequence=0,
        status="study_started",
        message="The frozen study started.",
        completed_conditions=0,
        total_conditions=2,
    ).as_dict()
    event["percentage"] = 0.0
    with pytest.raises(jsonschema.ValidationError):
        validate_optimizer_study_progress_event(event)

    condition = OptimizerStudyProgressCondition(
        sequence=2,
        condition_id="condition-0002-subjects-0005-cycles-003",
        subject_count=5,
        cycle_cap=3,
    )
    with pytest.raises(ValueError, match="inconsistent"):
        OptimizerStudyProgressEvent(
            sequence=1,
            status="condition_started",
            message="Starting.",
            completed_conditions=2,
            total_conditions=2,
            condition=condition,
        )
