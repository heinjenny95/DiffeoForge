from __future__ import annotations

import jsonschema
import pytest

from diffeoforge.modern_progress import (
    ModernOptimizerProgress,
    ModernProgressEvent,
    _schema,
    validate_modern_progress_event,
)


def test_stage_event_has_strict_versioned_serialization() -> None:
    event = ModernProgressEvent(
        sequence=0,
        phase="workflow",
        status="started",
        message="Modern workflow started",
        completed_stages=0,
    )

    assert event.as_dict() == {
        "progress_version": "0.1",
        "sequence": 0,
        "phase": "workflow",
        "status": "started",
        "message": "Modern workflow started",
        "completed_stages": 0,
        "total_stages": 7,
        "optimizer": None,
    }
    assert _schema()["title"] == "DiffeoForge modern workflow progress event"


def test_optimizer_decision_is_schema_validated_without_eta_claims() -> None:
    event = ModernProgressEvent(
        sequence=6,
        phase="optimization",
        status="decision",
        message="Optimizer momenta: accepted",
        completed_stages=4,
        optimizer=ModernOptimizerProgress(
            completed_decisions=1,
            maximum_decisions=3,
            cycle=1,
            max_cycles=1,
            block="momenta",
            status="accepted",
            objective=-1.25,
            attachment=-1.0,
            regularity=-0.25,
            gradient_norm=0.5,
            accepted_step_size=0.01,
            line_search_evaluations=2,
        ),
    )

    serialized = event.as_dict()
    validate_modern_progress_event(serialized)
    assert not ({"elapsed_seconds", "eta_seconds", "percent"} & serialized.keys())


def test_progress_schema_rejects_undeclared_fields_and_mismatched_decisions() -> None:
    event = ModernProgressEvent(
        sequence=0,
        phase="inputs",
        status="completed",
        message="done",
        completed_stages=1,
    ).as_dict()
    event["eta_seconds"] = 10

    with pytest.raises(jsonschema.ValidationError):
        validate_modern_progress_event(event)
    mismatched = ModernProgressEvent(
        sequence=0,
        phase="inputs",
        status="completed",
        message="done",
        completed_stages=1,
    ).as_dict()
    mismatched["status"] = "decision"
    with pytest.raises(jsonschema.ValidationError):
        validate_modern_progress_event(mismatched)
    with pytest.raises(ValueError, match="inconsistent"):
        ModernProgressEvent(
            sequence=0,
            phase="quality",
            status="completed",
            message="too early",
            completed_stages=2,
        )


def test_optimizer_progress_rejects_nonfinite_values() -> None:
    with pytest.raises(ValueError, match="objective"):
        ModernOptimizerProgress(
            completed_decisions=0,
            maximum_decisions=0,
            cycle=0,
            max_cycles=0,
            block=None,
            status="initial",
            objective=float("nan"),
            attachment=0.0,
            regularity=0.0,
            gradient_norm=None,
            accepted_step_size=None,
            line_search_evaluations=0,
        )
