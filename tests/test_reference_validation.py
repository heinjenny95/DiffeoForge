from __future__ import annotations

import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

import diffeoforge.reference_validation_study as validation_study_module
from diffeoforge.cli import main
from diffeoforge.desktop.project_setup import (
    DesktopEngine,
    ProjectSetupRequest,
    create_project,
)
from diffeoforge.reference_calibration import build_reference_calibration_plan
from diffeoforge.reference_recommendation import recommend_reference_parameters
from diffeoforge.reference_validation import (
    ReferenceValidationError,
    ValidationRunEvidence,
    assess_reference_validation,
    build_reference_validation_plan,
    validation_plan_json,
)
from diffeoforge.reference_validation_study import (
    ReferenceValidationStudyError,
    ReferenceValidationStudyRunner,
    create_reference_validation_study,
    load_reference_validation_study,
)

ROOT = Path(__file__).parents[1]
MESH_DIRECTORY = ROOT / "examples" / "synthetic" / "meshes"


def _calibrated_project(tmp_path: Path, *, smallest_feature: float | None = 0.1) -> Path:
    mesh_directory = tmp_path / "meshes"
    mesh_directory.mkdir()
    shutil.copy2(MESH_DIRECTORY / "template.vtk", mesh_directory / "template.vtk")
    sources = sorted(MESH_DIRECTORY.glob("subject-*.vtk"))
    for index in range(10):
        shutil.copy2(sources[index % len(sources)], mesh_directory / f"subject-{index:02d}.vtk")
    cohort = (mesh_directory / "template.vtk", *sorted(mesh_directory.glob("subject-*.vtk")))
    recommendation = recommend_reference_parameters(
        cohort,
        alignment_basis="declared_gpa",
        surface_detail_intent="balanced",
        deformation_scale_intent="balanced",
    )
    calibration = build_reference_calibration_plan(
        recommendation,
        coordinate_unit="unitless",
        requested_pilot_subject_count=4,
        smallest_relevant_feature=smallest_feature,
    )
    provenance = recommendation.provenance
    provenance["calibration_plan"] = calibration.provenance
    result = create_project(
        ProjectSetupRequest(
            mesh_directory=mesh_directory,
            project_directory=tmp_path / "project",
            units="unitless",
            engine=DesktopEngine.DEFORMETRICA_REFERENCE,
            reference_parameter_profile="data_assisted",
            reference_parameter_ratios=recommendation.parameter_ratios,
            reference_parameter_recommendation=provenance,
        )
    )
    config = yaml.safe_load(result.config_path.read_text(encoding="utf-8"))
    config["project"]["parameter_provenance"]["recommendation"][
        "calibration_result"
    ] = {
        "version": "0.1",
        "status": "completed",
        "study_id": "reference-calibration-test",
        "plan_fingerprint": calibration.fingerprint,
        "study_manifest_sha256": "a" * 64,
        "decision_event_hash": "b" * 64,
        "selected_candidate_ids": {
            "attachment": calibration.stages[0].candidates[0].candidate_id,
            "deformation": calibration.stages[1].candidates[0].candidate_id,
            "noise": calibration.stages[2].candidates[0].candidate_id,
            "timepoints": calibration.stages[3].candidates[0].candidate_id,
        },
        "selected_values": {
            "attachment_kernel_width": config["model"]["attachment"]["kernel_width"],
            "deformation_kernel_width": config["model"]["deformation"]["kernel_width"],
            "initial_control_point_spacing": config["model"]["deformation"][
                "initial_control_point_spacing"
            ],
            "noise_std": config["model"]["noise_std"],
            "timepoints": config["model"]["deformation"]["timepoints"],
        },
        "full_cohort_confirmation_required": True,
    }
    result.config_path.write_text(
        yaml.safe_dump(config, sort_keys=False), encoding="utf-8"
    )
    return result.config_path


def test_validation_plan_is_deterministic_hash_bound_and_separates_holdout(
    tmp_path: Path,
) -> None:
    config = _calibrated_project(tmp_path)

    first = build_reference_validation_plan(config, resample_count=3)
    second = build_reference_validation_plan(config, resample_count=3)

    assert first == second
    assert len(first.fingerprint) == 64
    assert first.subject_count == 10
    assert len(first.heldout_subjects) == 2
    assert not set(first.training_subjects) & set(first.heldout_subjects)
    assert set(first.training_subjects) | set(first.heldout_subjects) == {
        subject.filename for subject in first.subjects
    }
    assert all(
        name not in set(first.heldout_subjects)
        for cohort in first.cohorts
        for name in cohort.subject_filenames
    )
    assert len(first.cohorts) == 4
    assert len(first.run_specs) == len(first.finalists) * len(first.cohorts)
    assert len(first.finalists) >= 2
    assert first.run_specs[0].phase == "training_confirmation"
    assert "planned_not_executed" in validation_plan_json(first)
    assert "Fixed-template registration" in validation_plan_json(first)


def test_validation_plan_requires_completed_calibration(tmp_path: Path) -> None:
    config = _calibrated_project(tmp_path)
    loaded = yaml.safe_load(config.read_text(encoding="utf-8"))
    del loaded["project"]["parameter_provenance"]["recommendation"][
        "calibration_result"
    ]
    config.write_text(yaml.safe_dump(loaded, sort_keys=False), encoding="utf-8")

    with pytest.raises(ReferenceValidationError, match="completed"):
        build_reference_validation_plan(config)


def _evidence(plan, winner: str) -> tuple[ValidationRunEvidence, ...]:
    values = []
    for spec in plan.run_specs:
        index = next(
            index
            for index, finalist in enumerate(plan.finalists)
            if finalist.finalist_id == spec.finalist_id
        )
        residual = 0.2 + index * 0.04
        distortion = 0.15 + index * 0.03
        if spec.finalist_id == winner:
            residual = 0.1
            distortion = 0.05
        values.append(
            ValidationRunEvidence(
                run_id=spec.run_id,
                finalist_id=spec.finalist_id,
                cohort_id=spec.cohort_id,
                completed=True,
                converged=True,
                invalid_face_count=0,
                external_residual_p95=residual,
                distortion_p95=distortion,
                runtime_seconds=10.0 + index,
            )
        )
    return tuple(values)


def test_validation_assessment_reports_robust_winner_and_remaining_gates(
    tmp_path: Path,
) -> None:
    plan = build_reference_validation_plan(
        _calibrated_project(tmp_path), resample_count=4
    )
    winner = plan.finalists[0].finalist_id

    result = assess_reference_validation(plan, _evidence(plan, winner))

    assert result.status == "robust_within_search_space"
    assert result.recommended_finalist_id == winner
    assert result.winner_support == pytest.approx(1.0)
    assert result.practical_error_margin == pytest.approx(0.005)
    assert "heldout" in " ".join(result.next_gates).lower()
    assert result.missing_run_ids == ()


def test_validation_assessment_is_incomplete_when_one_predeclared_run_is_missing(
    tmp_path: Path,
) -> None:
    plan = build_reference_validation_plan(
        _calibrated_project(tmp_path), resample_count=2
    )
    evidence = _evidence(plan, plan.finalists[0].finalist_id)[:-1]

    result = assess_reference_validation(plan, evidence)

    assert result.status == "incomplete"
    assert result.confidence == "not assessed"
    assert result.missing_run_ids == (plan.run_specs[-1].run_id,)


def test_validation_assessment_refuses_robustness_if_one_finalist_is_invalid(
    tmp_path: Path,
) -> None:
    plan = build_reference_validation_plan(
        _calibrated_project(tmp_path), resample_count=1
    )
    evidence = list(_evidence(plan, plan.finalists[0].finalist_id))
    evidence[-1] = ValidationRunEvidence(
        **{
            **evidence[-1].__dict__,
            "converged": False,
        }
    )

    result = assess_reference_validation(plan, evidence)

    assert result.status == "failed_validity_gate"
    assert "not robust" in result.confidence
    assert result.warnings


def test_numerical_equivalence_fallback_is_explicitly_not_biological(
    tmp_path: Path,
) -> None:
    plan = build_reference_validation_plan(
        _calibrated_project(tmp_path, smallest_feature=None), resample_count=1
    )

    result = assess_reference_validation(
        plan, _evidence(plan, plan.finalists[0].finalist_id)
    )

    assert "not a biological" in result.practical_error_margin_basis
    assert result.warnings


class _CompletedController:
    def __init__(self, request) -> None:
        self.request = request

    def request_cancel(self) -> bool:
        return True

    def run(self, *, event_callback=None):
        self.request.destination.mkdir(parents=True)
        return SimpleNamespace(completed=True)


def test_validation_study_freezes_every_run_without_starting_execution(
    tmp_path: Path,
) -> None:
    snapshot = create_reference_validation_study(
        _calibrated_project(tmp_path),
        tmp_path / "validation-study",
        resample_count=2,
        maximum_iterations=44,
    )

    assert snapshot.status == "ready"
    assert snapshot.completed_run_count == 0
    assert len(snapshot.runs) == len(snapshot.plan.run_specs)
    assert {run.status for run in snapshot.runs} == {"pending"}
    for run in snapshot.runs:
        config = yaml.safe_load(run.config_path.read_text(encoding="utf-8"))
        assert config["optimization"]["max_iterations"] == 44
        cohort_files = {
            path.name
            for path in (run.config_path.parent / config["input"]["directory"]).resolve().glob(
                "*.vtk"
            )
        }
        assert not cohort_files & set(snapshot.plan.heldout_subjects)


def test_validation_lab_cli_initializes_and_reports_json_status(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    destination = tmp_path / "cli-validation"

    assert (
        main(
            [
                "reference-validation-study-init",
                str(_calibrated_project(tmp_path)),
                "--output",
                str(destination),
                "--resamples",
                "2",
            ]
        )
        == 0
    )
    creation = capsys.readouterr().out
    assert "Validation Lab study created" in creation
    assert "No process was started" in creation

    assert (
        main(
            [
                "reference-validation-study-status",
                str(destination),
                "--json",
            ]
        )
        == 0
    )
    status = capsys.readouterr().out
    assert '"status": "ready"' in status
    assert '"completed_run_count": 0' in status


def test_validation_study_rejects_changed_frozen_configuration(tmp_path: Path) -> None:
    snapshot = create_reference_validation_study(
        _calibrated_project(tmp_path),
        tmp_path / "validation-study",
        resample_count=1,
    )
    snapshot.runs[0].config_path.write_text(
        snapshot.runs[0].config_path.read_text(encoding="utf-8") + "\n# changed\n",
        encoding="utf-8",
    )

    with pytest.raises(ReferenceValidationStudyError, match="changed"):
        load_reference_validation_study(snapshot.study_directory)


def test_validation_runner_resumes_runs_and_publishes_scoped_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = create_reference_validation_study(
        _calibrated_project(tmp_path),
        tmp_path / "validation-study",
        resample_count=2,
    )
    winner = snapshot.plan.finalists[0].finalist_id

    def collect(run_directory: Path, *, run_id: str, finalist_id: str, cohort_id: str):
        winning = finalist_id == winner
        return ValidationRunEvidence(
            run_id=run_id,
            finalist_id=finalist_id,
            cohort_id=cohort_id,
            completed=True,
            converged=True,
            invalid_face_count=0,
            external_residual_p95=0.05 if winning else 0.25,
            distortion_p95=0.04 if winning else 0.15,
            runtime_seconds=10.0,
            atlas_path=str(run_directory / "atlas.vtk"),
        )

    monkeypatch.setattr(
        validation_study_module,
        "collect_reference_validation_run_evidence",
        collect,
    )
    events: list[dict[str, object]] = []

    completed = ReferenceValidationStudyRunner(
        snapshot.study_directory,
        controller_factory=_CompletedController,
    ).run_all(event_callback=events.append)

    assert completed.status == "completed"
    assert completed.completed_run_count == len(snapshot.runs)
    assert completed.assessment is not None
    assert completed.assessment.status == "robust_within_search_space"
    assert completed.assessment.recommended_finalist_id == winner
    assert completed.report_json_path is not None
    assert completed.report_html_path is not None
    report = completed.report_json_path.read_text(encoding="utf-8")
    assert "not a universal" in report
    assert "Fixed-template registration" in report
    assert events[-1]["event"] == "validation_completed"
    reloaded = load_reference_validation_study(completed.study_directory)
    assert reloaded == completed
