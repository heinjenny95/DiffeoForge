from copy import deepcopy
from pathlib import Path

import pytest

from diffeoforge.config import ConfigurationError
from diffeoforge.reference_calibration import (
    CalibrationCandidateEvidence,
    assess_calibration_stage,
    build_reference_calibration_plan,
    calibration_plan_json,
    select_representative_pilot_subjects,
    verify_reference_calibration_plan_provenance,
)
from diffeoforge.reference_recommendation import recommend_reference_parameters

ROOT = Path(__file__).parents[1]
MESH_DIRECTORY = ROOT / "examples" / "synthetic" / "meshes"


def _cohort() -> tuple[Path, ...]:
    return (
        MESH_DIRECTORY / "template.vtk",
        *sorted(MESH_DIRECTORY.glob("subject-*.vtk")),
    )


def _recommendation():
    return recommend_reference_parameters(
        _cohort(),
        alignment_basis="declared_gpa",
        surface_detail_intent="balanced",
        deformation_scale_intent="balanced",
    )


def test_pilot_selection_is_deterministic_unique_and_excludes_template() -> None:
    recommendation = _recommendation()

    first = select_representative_pilot_subjects(recommendation, requested_count=4)
    second = select_representative_pilot_subjects(recommendation, requested_count=4)

    assert first == second
    assert len(first) == 4
    assert len({subject.filename for subject in first}) == 4
    assert recommendation.template_filename not in {
        subject.filename for subject in first
    }
    assert first[0].selection_role == "geometry-descriptor medoid"
    assert all(
        subject.selection_role == "farthest-first geometry-descriptor extreme"
        for subject in first[1:]
    )
    assert [subject.selection_order for subject in first] == [1, 2, 3, 4]
    assert all(subject.sha256 for subject in first)


def test_pilot_selection_caps_at_the_available_subject_count() -> None:
    recommendation = _recommendation()

    selected = select_representative_pilot_subjects(
        recommendation,
        requested_count=100,
    )

    assert len(selected) == recommendation.subject_count


def test_calibration_plan_is_deterministic_staged_and_hash_bound() -> None:
    recommendation = _recommendation()

    first = build_reference_calibration_plan(
        recommendation,
        coordinate_unit="millimeter",
        requested_pilot_subject_count=4,
        smallest_relevant_feature=0.2,
    )
    second = build_reference_calibration_plan(
        recommendation,
        coordinate_unit="millimeter",
        requested_pilot_subject_count=4,
        smallest_relevant_feature=0.2,
    )

    assert first == second
    assert len(first.fingerprint) == 64
    assert first.recommendation_fingerprint == recommendation.fingerprint
    assert first.pilot_subject_count == 4
    assert first.smallest_relevant_feature == pytest.approx(0.2)
    assert first.attachment_center_source == (
        "researcher_measured_feature_with_mesh_sampling_floor"
    )
    assert [stage.stage_id for stage in first.stages] == [
        "attachment",
        "deformation",
        "noise",
        "timepoints",
    ]
    assert 2 <= len(first.stages[0].candidates) <= 3
    assert all(len(stage.candidates) == 3 for stage in first.stages[1:])
    assert first.stages[1].candidates[1].values[
        "initial_control_point_spacing"
    ] == pytest.approx(
        first.stages[1].candidates[1].values["deformation_kernel_width"]
    )
    assert first.provenance["status"] == "planned_not_executed"
    assert first.provenance["fingerprint"] == first.fingerprint
    assert "not executed" in first.summary_text().lower()

    serialized = calibration_plan_json(first)
    assert serialized.endswith("\n")
    assert f'"fingerprint": "{first.fingerprint}"' in serialized
    assert '"status": "planned_not_executed"' in serialized


def test_feature_measurement_changes_attachment_candidates_not_deformation_center() -> None:
    recommendation = _recommendation()
    unmeasured = build_reference_calibration_plan(
        recommendation,
        coordinate_unit="unitless",
        requested_pilot_subject_count=3,
    )
    measured = build_reference_calibration_plan(
        recommendation,
        coordinate_unit="unitless",
        requested_pilot_subject_count=3,
        smallest_relevant_feature=(
            2.0 * recommendation.effective_values["attachment_kernel_width"]
        ),
    )

    assert unmeasured.fingerprint != measured.fingerprint
    assert unmeasured.stages[0].candidates != measured.stages[0].candidates
    assert unmeasured.stages[1].candidates == measured.stages[1].candidates
    assert measured.effective_values["attachment_kernel_width"] >= (
        2.0 * recommendation.effective_values["attachment_kernel_width"]
    )
    assert measured.parameter_ratios["attachment_kernel_width"] == pytest.approx(
        measured.effective_values["attachment_kernel_width"]
        / recommendation.template_diagonal
    )


def test_calibration_plan_rejects_invalid_inputs() -> None:
    recommendation = _recommendation()

    with pytest.raises(ValueError, match="at least 2"):
        select_representative_pilot_subjects(recommendation, requested_count=1)
    with pytest.raises(ValueError, match="finite and positive"):
        build_reference_calibration_plan(
            recommendation,
            coordinate_unit="millimeter",
            smallest_relevant_feature=0,
        )
    with pytest.raises(ValueError, match="coordinate_unit"):
        build_reference_calibration_plan(
            recommendation,
            coordinate_unit=" ",
        )


def test_calibration_plan_provenance_verification_detects_any_changed_decision() -> None:
    plan = build_reference_calibration_plan(
        _recommendation(),
        coordinate_unit="millimeter",
        requested_pilot_subject_count=4,
        smallest_relevant_feature=0.2,
    )
    provenance = deepcopy(plan.provenance)

    assert verify_reference_calibration_plan_provenance(provenance) == plan.fingerprint

    provenance["stages"][0]["candidates"][0]["parameter_values"][
        "attachment_kernel_width"
    ] *= 2
    with pytest.raises(ConfigurationError, match="fingerprint"):
        verify_reference_calibration_plan_provenance(provenance)


def _stage_evidence(
    plan,
    stage_id: str,
    rows: tuple[tuple[float, float, float, float], ...],
) -> tuple[CalibrationCandidateEvidence, ...]:
    stage = next(stage for stage in plan.stages if stage.stage_id == stage_id)
    return tuple(
        CalibrationCandidateEvidence(
            candidate_id=candidate.candidate_id,
            completed=True,
            converged=True,
            invalid_face_count=0,
            residual_p95=row[0],
            deformation_energy=row[1],
            distortion_p95=row[2],
            runtime_seconds=row[3],
            resampling_sensitivity=(0.2 + index * 0.1),
            review_approved=True,
        )
        for index, (candidate, row) in enumerate(
            zip(stage.candidates, rows, strict=True)
        )
    )


def test_stage_assessment_retains_pareto_candidates_and_exposes_weights() -> None:
    plan = build_reference_calibration_plan(
        _recommendation(),
        coordinate_unit="unitless",
        requested_pilot_subject_count=3,
    )
    stage = next(stage for stage in plan.stages if stage.stage_id == "noise")
    assert len(stage.candidates) == 3
    evidence = _stage_evidence(
        plan,
        "noise",
        (
            (0.10, 0.90, 0.50, 10.0),
            (0.15, 0.45, 0.20, 12.0),
            (0.30, 0.30, 0.15, 9.0),
        ),
    )

    first = assess_calibration_stage(
        plan,
        stage_id="noise",
        evidence=evidence,
    )
    second = assess_calibration_stage(
        plan,
        stage_id="noise",
        evidence=evidence,
    )

    assert first == second
    assert first.status == "review_required"
    assert first.balanced_candidate_id in first.pareto_candidate_ids
    assert set(first.weights) == {
        "residual_p95",
        "deformation_energy",
        "distortion_p95",
        "runtime_seconds",
    }
    assert sum(first.weights.values()) == pytest.approx(1.0)
    assert all(candidate.eligible for candidate in first.candidates)
    assert "not an automatic approval" in " ".join(first.cautions)
    assert len(first.fingerprint) == 64


def test_stage_assessment_fails_closed_on_missing_review_or_metrics() -> None:
    plan = build_reference_calibration_plan(
        _recommendation(),
        coordinate_unit="unitless",
        requested_pilot_subject_count=3,
    )
    stage = next(stage for stage in plan.stages if stage.stage_id == "attachment")
    evidence = tuple(
        CalibrationCandidateEvidence(
            candidate_id=candidate.candidate_id,
            completed=True,
            converged=True,
            invalid_face_count=0,
            residual_p95=0.1,
            deformation_energy=0.2,
            distortion_p95=0.3,
            runtime_seconds=10.0,
            resampling_sensitivity=None,
            review_approved=False,
        )
        for candidate in stage.candidates
    )

    assessment = assess_calibration_stage(
        plan,
        stage_id="attachment",
        evidence=evidence,
    )

    assert assessment.status == "no_eligible_candidate"
    assert assessment.balanced_candidate_id is None
    assert assessment.pareto_candidate_ids == ()
    assert all(not candidate.eligible for candidate in assessment.candidates)
    assert all(
        any(
            "visual registration review" in reason
            for reason in candidate.rejection_reasons
        )
        for candidate in assessment.candidates
    )
    assert all(
        any("resampling_sensitivity" in reason for reason in candidate.rejection_reasons)
        for candidate in assessment.candidates
    )


def test_stage_assessment_requires_exact_candidate_evidence() -> None:
    plan = build_reference_calibration_plan(
        _recommendation(),
        coordinate_unit="unitless",
        requested_pilot_subject_count=3,
    )

    with pytest.raises(ValueError, match="must match"):
        assess_calibration_stage(
            plan,
            stage_id="noise",
            evidence=(),
        )
