from copy import deepcopy
from pathlib import Path

import pytest

from diffeoforge.config import ConfigurationError
from diffeoforge.mesh import sha256_file
from diffeoforge.reference_calibration import (
    CalibrationCandidateEvidence,
    assess_calibration_stage,
    bind_reference_calibration_plan_to_inputs,
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


def test_calibration_plan_can_bind_published_effective_input_bytes(
    tmp_path: Path,
) -> None:
    recommendation = _recommendation()
    plan = build_reference_calibration_plan(
        recommendation,
        coordinate_unit="unitless",
        requested_pilot_subject_count=3,
    )
    cohort = _cohort()
    effective = tmp_path / "effective"
    effective.mkdir()
    published = []
    for source in cohort:
        destination = effective / source.name
        destination.write_bytes(source.read_bytes() + b"\n")
        published.append(destination)

    rebound = bind_reference_calibration_plan_to_inputs(
        plan,
        template=published[0],
        subjects=published[1:],
    )

    assert rebound.fingerprint != plan.fingerprint
    assert rebound.template_sha256 == sha256_file(published[0])
    by_name = {path.name: path for path in published[1:]}
    assert all(
        selected.sha256 == sha256_file(by_name[selected.filename])
        for selected in rebound.selected_pilot_subjects
    )
    assert (
        verify_reference_calibration_plan_provenance(rebound.provenance)
        == rebound.fingerprint
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
    assert first.attachment_center_source == "researcher_measured_feature"
    assert [stage.stage_id for stage in first.stages] == [
        "attachment",
        "deformation",
        "noise",
        "timepoints",
    ]
    assert len(first.stages[0].candidates) == 18
    assert [len(stage.candidates) for stage in first.stages[1:]] == [5, 5, 3]
    assert all(
        {
            "attachment_kernel_width",
            "deformation_kernel_width",
            "initial_control_point_spacing",
        }
        == set(candidate.values)
        for candidate in first.stages[0].candidates
    )
    assert first.stages[1].candidates[2].values[
        "initial_control_point_spacing"
    ] == pytest.approx(
        first.stages[1].candidates[2].values["deformation_kernel_width"]
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


def test_extreme_expected_disparity_widens_search_and_does_not_penalize_amplitude() -> None:
    moderate = build_reference_calibration_plan(
        _recommendation(),
        coordinate_unit="unitless",
        requested_pilot_subject_count=3,
    )
    extreme_recommendation = recommend_reference_parameters(
        _cohort(),
        alignment_basis="declared_gpa",
        surface_detail_intent="balanced",
        deformation_scale_intent="balanced",
        expected_shape_disparity="extreme",
    )
    extreme = build_reference_calibration_plan(
        extreme_recommendation,
        coordinate_unit="unitless",
        requested_pilot_subject_count=3,
    )
    moderate_widths = [
        candidate.values["deformation_kernel_width"]
        for candidate in moderate.stages[1].candidates
    ]
    extreme_widths = [
        candidate.values["deformation_kernel_width"]
        for candidate in extreme.stages[1].candidates
    ]
    assert min(extreme_widths) < min(moderate_widths)
    assert max(extreme_widths) > max(moderate_widths)

    noise_stage = extreme.stages[2]
    evidence = tuple(
        CalibrationCandidateEvidence(
            candidate_id=candidate.candidate_id,
            completed=True,
            converged=True,
            invalid_face_count=0,
            residual_p95=0.1 + index,
            deformation_energy=1000.0 if index == 0 else 0.01,
            distortion_p95=1000.0 if index == 0 else 0.01,
            runtime_seconds=10.0 + index,
            review_approved=None,
        )
        for index, candidate in enumerate(noise_stage.candidates)
    )
    assessment = assess_calibration_stage(
        extreme,
        stage_id="noise",
        evidence=evidence,
    )

    assert assessment.balanced_candidate_id == noise_stage.candidates[0].candidate_id
    assert set(assessment.weights) == {"residual_p95", "runtime_seconds"}
    assert "extreme" in " ".join(assessment.cautions)


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
    assert len(stage.candidates) == 5
    evidence = _stage_evidence(
        plan,
        "noise",
        (
            (0.08, 1.10, 0.65, 14.0),
            (0.10, 0.90, 0.50, 10.0),
            (0.15, 0.45, 0.20, 12.0),
            (0.30, 0.30, 0.15, 9.0),
            (0.42, 0.25, 0.12, 8.0),
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
    assert first.status == "selection_required"
    assert first.balanced_candidate_id in first.pareto_candidate_ids
    assert set(first.weights) == {
        "residual_p95",
        "deformation_energy",
        "distortion_p95",
        "runtime_seconds",
    }
    assert sum(first.weights.values()) == pytest.approx(1.0)
    assert all(candidate.eligible for candidate in first.candidates)
    cautions = " ".join(first.cautions)
    assert "robust recommendation" in cautions
    assert first.weight_scenario_count > 1
    assert first.recommendation_confidence == "ambiguous"
    assert first.automatic_selection_allowed is False
    assert first.sensitivity_flags
    assert len(first.fingerprint) == 64


def test_stage_assessment_requires_stable_evidence_before_automatic_selection() -> None:
    plan = build_reference_calibration_plan(
        _recommendation(),
        coordinate_unit="unitless",
        requested_pilot_subject_count=3,
    )
    stage = next(stage for stage in plan.stages if stage.stage_id == "noise")
    evidence = tuple(
        CalibrationCandidateEvidence(
            candidate_id=candidate.candidate_id,
            completed=True,
            converged=True,
            invalid_face_count=0,
            residual_p95=0.1 + index,
            deformation_energy=0.2 + index,
            distortion_p95=0.3 + index,
            runtime_seconds=10.0 + index,
            review_approved=None,
            subject_residual_p95=(
                ("subject-a.vtk", 0.10 + index),
                ("subject-b.vtk", 0.11 + index),
                ("subject-c.vtk", 0.09 + index),
            ),
        )
        for index, candidate in enumerate(stage.candidates)
    )

    assessment = assess_calibration_stage(
        plan,
        stage_id="noise",
        evidence=evidence,
    )

    assert assessment.recommendation_confidence == "robust"
    assert assessment.automatic_selection_allowed is True
    assert assessment.weight_stability == pytest.approx(1.0)
    assert assessment.subject_bootstrap_stability == pytest.approx(1.0)
    assert assessment.subject_bootstrap_iterations == 256
    selected = next(
        candidate
        for candidate in assessment.candidates
        if candidate.candidate_id == assessment.balanced_candidate_id
    )
    assert selected.weight_win_fraction == pytest.approx(1.0)
    assert selected.subject_bootstrap_win_fraction == pytest.approx(1.0)


def test_stage_assessment_fails_closed_on_missing_metrics_without_requiring_review() -> None:
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
            review_approved=None,
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
        all(
            "visual registration review" not in reason
            for reason in candidate.rejection_reasons
        )
        for candidate in assessment.candidates
    )
    assert all(
        any("resampling_sensitivity" in reason for reason in candidate.rejection_reasons)
        for candidate in assessment.candidates
    )


def test_stage_assessment_rejects_an_explicit_visual_qc_failure() -> None:
    plan = build_reference_calibration_plan(
        _recommendation(),
        coordinate_unit="unitless",
        requested_pilot_subject_count=3,
    )
    stage = next(stage for stage in plan.stages if stage.stage_id == "noise")
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
            review_approved=False,
        )
        for candidate in stage.candidates
    )

    assessment = assess_calibration_stage(
        plan,
        stage_id="noise",
        evidence=evidence,
    )

    assert assessment.status == "no_eligible_candidate"
    assert all(not candidate.eligible for candidate in assessment.candidates)
    assert all(
        candidate.rejection_reasons
        == ("optional visual registration review explicitly failed",)
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
