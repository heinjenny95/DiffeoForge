from __future__ import annotations

import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

import diffeoforge.reference_holdout_study as holdout_study_module
import diffeoforge.reference_validation_study as validation_study_module
from diffeoforge.cli import main
from diffeoforge.desktop.project_setup import (
    DesktopEngine,
    ProjectSetupRequest,
    create_project,
)
from diffeoforge.mesh import sha256_file
from diffeoforge.reference_calibration import build_reference_calibration_plan
from diffeoforge.reference_holdout_study import (
    ReferenceHoldoutStudyRunner,
    create_reference_holdout_study,
    load_reference_holdout_study,
)
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
from diffeoforge.runs import prepare_run, verify_prepared_run

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
    config["project"]["parameter_provenance"]["recommendation"]["calibration_result"] = {
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
    result.config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
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
    del loaded["project"]["parameter_provenance"]["recommendation"]["calibration_result"]
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
    plan = build_reference_validation_plan(_calibrated_project(tmp_path), resample_count=4)
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
    plan = build_reference_validation_plan(_calibrated_project(tmp_path), resample_count=2)
    evidence = _evidence(plan, plan.finalists[0].finalist_id)[:-1]

    result = assess_reference_validation(plan, evidence)

    assert result.status == "incomplete"
    assert result.confidence == "not assessed"
    assert result.missing_run_ids == (plan.run_specs[-1].run_id,)


def test_validation_assessment_refuses_robustness_if_one_finalist_is_invalid(
    tmp_path: Path,
) -> None:
    plan = build_reference_validation_plan(_calibrated_project(tmp_path), resample_count=1)
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

    result = assess_reference_validation(plan, _evidence(plan, plan.finalists[0].finalist_id))

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
            for path in (run.config_path.parent / config["input"]["directory"])
            .resolve()
            .glob("*.vtk")
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


def _completed_parent_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    snapshot = create_reference_validation_study(
        _calibrated_project(tmp_path),
        tmp_path / "validation-study",
        resample_count=1,
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
    completed = ReferenceValidationStudyRunner(
        snapshot.study_directory,
        controller_factory=_CompletedController,
    ).run_all()
    for run in completed.runs:
        if run.cohort_id != "training-confirmation" or run.run_directory is None:
            continue
        (run.run_directory / "result.json").write_text("{}\n", encoding="utf-8")
        (run.run_directory / "output-inventory.json").write_text("{}\n", encoding="utf-8")
        model_directory = run.run_directory / "trained-model"
        model_directory.mkdir()
        shutil.copy2(
            MESH_DIRECTORY / "template.vtk",
            model_directory / "estimated-template.vtk",
        )
        (model_directory / "estimated-control-points.txt").write_text(
            "0 0 0\n1 1 1\n", encoding="ascii"
        )
    return completed


def test_holdout_study_freezes_trained_models_and_exact_reserved_subjects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent = _completed_parent_validation(tmp_path, monkeypatch)

    def trained_artifacts(run_directory: Path):
        template = run_directory / "trained-model" / "estimated-template.vtk"
        points = run_directory / "trained-model" / "estimated-control-points.txt"
        return (
            template,
            sha256_file(template),
            points,
            sha256_file(points),
            "estimated-template.vtk",
            "estimated-control-points.txt",
        )

    monkeypatch.setattr(
        holdout_study_module,
        "_trained_model_artifacts",
        trained_artifacts,
    )
    snapshot = create_reference_holdout_study(parent.study_directory)

    assert snapshot.status == "ready"
    assert snapshot.heldout_subjects == parent.plan.heldout_subjects
    assert len(snapshot.runs) == len(parent.plan.finalists)
    manifest = json.loads(
        (snapshot.study_directory / "holdout-study.json").read_text(encoding="utf-8")
    )
    assert manifest["parent"]["study_id"] == parent.study_id
    assert manifest["parent"]["manifest_sha256"] == sha256_file(
        parent.study_directory / "validation-study.json"
    )
    for run in snapshot.runs:
        config = yaml.safe_load(run.config_path.read_text(encoding="utf-8"))
        assert config["optimization"]["freeze_template"] is True
        assert config["optimization"]["freeze_control_points"] is True
        assert "initial_control_points" in config["model"]["deformation"]
        selected = {
            path.name
            for path in (run.config_path.parent / config["input"]["directory"])
            .resolve()
            .glob("*.vtk")
        }
        assert selected == set(parent.plan.heldout_subjects)

    prepared = prepare_run(snapshot.runs[0].config_path, run_id="holdout-test")
    prepared_manifest = verify_prepared_run(prepared)
    model_xml = (prepared / "engine" / "model.xml").read_text(encoding="utf-8")
    assert "<initial-control-points>../input/control-points/" in model_xml
    assert any(
        item["path"].startswith("input/control-points/")
        for item in prepared_manifest["protected_artifacts"]
    )


def test_holdout_runner_reports_paired_subject_support(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent = _completed_parent_validation(tmp_path, monkeypatch)

    def trained_artifacts(run_directory: Path):
        template = run_directory / "trained-model" / "estimated-template.vtk"
        points = run_directory / "trained-model" / "estimated-control-points.txt"
        return (
            template,
            sha256_file(template),
            points,
            sha256_file(points),
            "estimated-template.vtk",
            "estimated-control-points.txt",
        )

    monkeypatch.setattr(
        holdout_study_module,
        "_trained_model_artifacts",
        trained_artifacts,
    )
    snapshot = create_reference_holdout_study(parent.study_directory)
    winner = parent.plan.finalists[0].finalist_id

    def collect(run_directory: Path, *, run_id: str, finalist_id: str, cohort_id: str):
        winning = finalist_id == winner
        value = 0.01 if winning else 0.25
        return ValidationRunEvidence(
            run_id=run_id,
            finalist_id=finalist_id,
            cohort_id=cohort_id,
            completed=True,
            converged=True,
            invalid_face_count=0,
            external_residual_p95=value,
            distortion_p95=0.02 if winning else 0.2,
            runtime_seconds=5.0,
            subject_residual_p95=tuple((name, value) for name in snapshot.heldout_subjects),
        )

    monkeypatch.setattr(
        holdout_study_module,
        "collect_reference_validation_run_evidence",
        collect,
    )
    completed = ReferenceHoldoutStudyRunner(
        snapshot.study_directory,
        controller_factory=_CompletedController,
    ).run_all()

    assert completed.status == "completed"
    assert completed.assessment is not None
    assert completed.assessment.status == "confirmed_on_holdout"
    assert completed.assessment.preferred_finalist_id == winner
    assert completed.assessment.subject_support == pytest.approx(1.0)
    assert completed.report_json_path is not None
    report = json.loads(completed.report_json_path.read_text(encoding="utf-8"))
    assert report["design"]["registration_mode"] == ("fixed template and fixed control points")
    assert "not proof of biological" in report["claim_scope"]
    assert load_reference_holdout_study(completed.study_directory) == completed


def test_validation_dialog_shows_first_iteration_activity_and_live_eta(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from diffeoforge.desktop.reference_validation_dialog import (
        ReferenceValidationDialog,
    )

    snapshot = create_reference_validation_study(
        _calibrated_project(tmp_path),
        tmp_path / "validation-dialog-study",
        resample_count=1,
    )
    application = QApplication.instance() or QApplication(
        ["diffeoforge-validation-dialog-test"]
    )
    dialog = ReferenceValidationDialog(snapshot.study_directory)
    dialog._worker = object()
    dialog._active_mode = "training"

    run_id = snapshot.runs[0].run_id
    dialog._event({"event": "run_started", "run_id": run_id})
    assert dialog.progress.minimum() == 0
    assert dialog.progress.maximum() == 0
    assert "first complete optimizer iteration" in dialog.status_label.text()

    dialog._event(
        {
            "event": "worker_event",
            "run_id": run_id,
            "worker_event": {
                "kind": "activity",
                "payload": {
                    "elapsed_seconds": 90.0,
                    "last_iteration": None,
                    "maximum_iterations": 150,
                },
            },
        }
    )
    assert "Elapsed 1 min 30 s" in dialog.status_label.text()
    assert dialog.progress.maximum() == 0

    dialog._event(
        {
            "event": "worker_event",
            "run_id": run_id,
            "worker_event": {
                "kind": "progress",
                "payload": {
                    "iteration": 12,
                    "maximum_iterations": 150,
                    "elapsed_seconds": 180.0,
                    "eta_to_iteration_cap_seconds": 2070.0,
                    "seconds_per_iteration": 15.0,
                    "resource_contention_detected": False,
                },
            },
        }
    )
    assert dialog.progress.maximum() == len(snapshot.runs) * 1000
    assert "iteration 12 of maximum 150" in dialog.status_label.text()
    assert "current-run upper-bound ETA 34 min 30 s" in dialog.status_label.text()

    dialog._worker = None
    dialog.close()
    application.processEvents()
