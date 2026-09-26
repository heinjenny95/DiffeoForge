from __future__ import annotations

import jsonschema
import pytest

from diffeoforge.modern_optimizer_benchmark_progress import (
    OptimizerStudyProgressCondition,
    OptimizerStudyProgressEvent,
    OptimizerStudyProgressObservation,
    validate_optimizer_study_progress_event,
)
from diffeoforge.modern_progress import ModernOptimizerProgress


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

    assert event.progress_version == "0.2"
    assert event.as_dict()["condition"]["cycle_cap"] == 3
    validate_optimizer_study_progress_event(event.as_dict())

    legacy = {
        "progress_version": "0.1",
        "sequence": 0,
        "status": "study_started",
        "message": "A legacy study started.",
        "completed_conditions": 0,
        "total_conditions": 1,
        "condition": None,
    }
    validate_optimizer_study_progress_event(legacy)


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


def test_optimizer_progress_serializes_one_committed_decision_observation() -> None:
    condition = OptimizerStudyProgressCondition(
        sequence=1,
        condition_id="condition-0001-subjects-0236-cycles-003",
        subject_count=236,
        cycle_cap=3,
    )
    observation = OptimizerStudyProgressObservation(
        repeat=1,
        total_repeats=1,
        optimizer_elapsed_ns=90_000_000_000,
        optimizer=ModernOptimizerProgress(
            completed_decisions=4,
            maximum_decisions=9,
            cycle=2,
            max_cycles=3,
            block="momenta",
            status="accepted",
            objective=-12.0,
            attachment=-10.0,
            regularity=-2.0,
            gradient_norm=0.25,
            accepted_step_size=0.01,
            line_search_evaluations=2,
        ),
    )
    event = OptimizerStudyProgressEvent(
        sequence=2,
        status="condition_progress",
        message="A committed optimizer decision was observed.",
        completed_conditions=0,
        total_conditions=1,
        condition=condition,
        observation=observation,
    )

    serialized = event.as_dict()
    assert serialized["observation"]["optimizer"]["completed_decisions"] == 4
    validate_optimizer_study_progress_event(serialized)
