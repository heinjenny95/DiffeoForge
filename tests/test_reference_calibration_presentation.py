from pathlib import Path

from diffeoforge.desktop.reference_calibration_presentation import (
    automatic_check_summary,
    candidate_parameter_summary,
    candidate_tradeoff_assessments,
    candidate_tradeoff_labels,
    stage_guidance,
    technical_metric_text,
)
from diffeoforge.reference_calibration import CalibrationCandidate, CalibrationStage
from diffeoforge.reference_calibration_study import CalibrationStudyCandidateState


def _stage() -> CalibrationStage:
    return CalibrationStage(
        stage_id="attachment",
        order=1,
        kind="attachment_width",
        title="Surface-matching detail",
        candidates=(
            CalibrationCandidate(
                candidate_id="attachment-01",
                label="center",
                parameter_values=(("attachment_kernel_width", 0.22),),
                rationale="Tests the declared detail scale.",
            ),
        ),
        locked_from_previous_stages=(),
        evidence_required=(),
        reject_when=(),
        decision_rule="Technical decision rule.",
    )


def _state(
    candidate_id: str,
    *,
    residual: float,
    distortion: float,
    energy: float,
    runtime: float,
) -> CalibrationStudyCandidateState:
    return CalibrationStudyCandidateState(
        candidate_id=candidate_id,
        label=candidate_id,
        status="completed",
        config_path=Path(f"{candidate_id}.yaml"),
        run_directory=Path(candidate_id),
        metrics={
            "residual_p95": residual,
            "residual_median": residual / 2.0,
            "distortion_p95": distortion,
            "deformation_energy": energy,
            "resampling_sensitivity": 0.01,
            "runtime_seconds": runtime,
            "converged": True,
            "invalid_face_count": 0,
            "final_iteration": 12,
            "maximum_iterations": 150,
        },
        error=None,
        attempts=1,
    )


def test_attachment_guidance_explains_the_decision_without_jargon() -> None:
    guidance = stage_guidance(_stage())
    parameter, direction = candidate_parameter_summary(
        _stage(),
        {"attachment_kernel_width": 0.219907},
        coordinate_unit="mm",
    )

    assert "matching-detail and deformation-scale" in guidance.question
    assert "stable across metric priorities" in guidance.action
    assert "collect more evidence" in guidance.action
    assert "overfitting" in guidance.caution
    assert parameter == "Surface-detail width: 0.219907 mm"
    assert direction == "Smaller follows finer detail; larger emphasizes broader shape."


def test_tradeoff_labels_state_both_sides_without_declaring_a_winner() -> None:
    close_but_costly = _state(
        "attachment-01",
        residual=0.065,
        distortion=0.191,
        energy=0.558,
        runtime=35.2,
    )
    smooth_and_fast = _state(
        "attachment-02",
        residual=0.074,
        distortion=0.119,
        energy=0.392,
        runtime=8.1,
    )

    labels = candidate_tradeoff_labels((close_but_costly, smooth_and_fast))

    assert labels["attachment-01"] == (
        "Closest automatic surface match",
        "Most atlas/reconstruction area change",
        "Highest deformation cost",
        "Slowest pilot run",
    )
    assert labels["attachment-02"] == (
        "Largest measured mismatch",
        "Least atlas/reconstruction area change",
        "Lowest deformation cost",
        "Fastest pilot run",
    )
    assert all(
        "recommended" not in label.casefold()
        for values in labels.values()
        for label in values
    )

    assessments = candidate_tradeoff_assessments(
        (close_but_costly, smooth_and_fast)
    )
    assert tuple(item.tone for item in assessments["attachment-01"]) == (
        "favorable",
        "unfavorable",
        "caution",
        "unfavorable",
    )
    assert tuple(item.tone for item in assessments["attachment-02"]) == (
        "unfavorable",
        "favorable",
        "favorable",
        "favorable",
    )
    fastest = assessments["attachment-02"][-1]
    assert fastest.label == "Fastest pilot run"
    assert "efficiency" in fastest.interpretation
    assert "does not establish registration quality" in fastest.interpretation


def test_machine_checks_and_technical_details_keep_interpretation_limits() -> None:
    metrics = _state(
        "attachment-01",
        residual=0.065,
        distortion=0.191,
        energy=0.558,
        runtime=35.2,
    ).metrics
    assert metrics is not None

    passed, summary = automatic_check_summary(metrics)
    technical = technical_metric_text(metrics)

    assert passed is True
    assert "no invalid faces" in summary
    assert "not Deformetrica's configured attachment objective" in technical
    assert "do not prove anatomically correct registration" in technical
