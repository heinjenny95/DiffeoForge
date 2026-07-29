from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

import diffeoforge.reference_calibration_study as study_module
from diffeoforge.cli import main
from diffeoforge.desktop.project_setup import (
    DesktopEngine,
    ProjectSetupRequest,
    create_project,
)
from diffeoforge.reference_calibration import build_reference_calibration_plan
from diffeoforge.reference_calibration_metrics import (
    ReferenceCalibrationRunMetrics,
)
from diffeoforge.reference_calibration_study import (
    ReferenceCalibrationStudyError,
    ReferenceCalibrationStudyRunner,
    create_reference_calibration_study,
    load_reference_calibration_study,
    record_reference_calibration_stage_review,
)
from diffeoforge.reference_recommendation import recommend_reference_parameters

ROOT = Path(__file__).parents[1]
MESH_DIRECTORY = ROOT / "examples" / "synthetic" / "meshes"


def _project(tmp_path: Path) -> Path:
    cohort = (
        MESH_DIRECTORY / "template.vtk",
        *sorted(MESH_DIRECTORY.glob("subject-*.vtk")),
    )
    recommendation = recommend_reference_parameters(
        cohort,
        alignment_basis="declared_gpa",
        surface_detail_intent="balanced",
        deformation_scale_intent="balanced",
    )
    plan = build_reference_calibration_plan(
        recommendation,
        coordinate_unit="unitless",
        requested_pilot_subject_count=3,
    )
    provenance = recommendation.provenance
    provenance["calibration_plan"] = plan.provenance
    result = create_project(
        ProjectSetupRequest(
            mesh_directory=MESH_DIRECTORY,
            project_directory=tmp_path / "project",
            units="unitless",
            engine=DesktopEngine.DEFORMETRICA_REFERENCE,
            reference_parameter_profile="data_assisted",
            reference_parameter_ratios=recommendation.parameter_ratios,
            reference_parameter_recommendation=provenance,
        )
    )
    return result.config_path


def _metrics(atlas_path: Path, offset: float = 0.0) -> ReferenceCalibrationRunMetrics:
    return ReferenceCalibrationRunMetrics(
        metric_version="0.1",
        completed=True,
        converged=True,
        optimizer_stop_signal="tolerance_threshold",
        stop_interpretation="completed before cap",
        final_iteration=12,
        maximum_iterations=50,
        residual_p95=0.2 + offset,
        residual_median=0.1 + offset,
        resampling_sensitivity=0.02 + offset,
        deformation_energy=0.4 + offset,
        attachment_objective_magnitude=0.5 + offset,
        distortion_p95=0.1 + offset,
        invalid_face_count=0,
        runtime_seconds=10.0 + offset,
        subject_reconstruction_count=3,
        atlas_path=str(atlas_path),
        notes=(),
    )


class _CompletedController:
    def __init__(self, request) -> None:
        self.request = request

    def request_cancel(self) -> bool:
        return True

    def run(self, *, event_callback=None):
        self.request.destination.mkdir(parents=True)
        return SimpleNamespace(completed=True)


class _FailedController(_CompletedController):
    def run(self, *, event_callback=None):
        raise RuntimeError("synthetic transient failure")


def test_study_creation_binds_inputs_and_prepares_only_first_stage(
    tmp_path: Path,
) -> None:
    config = _project(tmp_path)

    snapshot = create_reference_calibration_study(
        config,
        tmp_path / "study",
        pilot_max_iterations=50,
    )

    assert snapshot.status == "ready"
    assert snapshot.current_stage is not None
    assert snapshot.current_stage.stage_id == "attachment"
    assert 2 <= len(snapshot.candidates) <= 3
    assert {candidate.status for candidate in snapshot.candidates} == {"pending"}
    assert not (snapshot.study_directory / "stages" / "02-deformation").exists()
    for candidate in snapshot.candidates:
        loaded = yaml.safe_load(candidate.config_path.read_text(encoding="utf-8"))
        assert loaded["optimization"]["max_iterations"] == 50
        assert loaded["input"]["subject_pattern"] == "*.vtk"
        assert loaded["output"]["directory"] == "./runs"


def test_calibration_study_cli_initializes_and_reports_verified_status(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    destination = tmp_path / "cli-study"

    assert (
        main(
            [
                "reference-calibration-study-init",
                str(_project(tmp_path)),
                "--output",
                str(destination),
                "--pilot-max-iterations",
                "42",
            ]
        )
        == 0
    )
    creation = capsys.readouterr().out
    assert "Calibration study created" in creation
    assert "no atlas run started" in creation

    assert (
        main(
            [
                "reference-calibration-study-status",
                str(destination),
                "--json",
            ]
        )
        == 0
    )
    status = capsys.readouterr().out
    assert '"status": "ready"' in status
    assert '"stage_id": "attachment"' in status


def test_runner_executes_every_candidate_then_pauses_for_review(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    initial = create_reference_calibration_study(
        _project(tmp_path),
        tmp_path / "study",
        pilot_max_iterations=50,
    )
    calls = 0

    def collect(run: Path):
        nonlocal calls
        calls += 1
        atlas = run / "atlas.vtk"
        atlas.write_text("placeholder", encoding="utf-8")
        return _metrics(atlas, calls / 100)

    monkeypatch.setattr(
        study_module,
        "collect_reference_calibration_run_metrics",
        collect,
    )
    observed: list[str] = []
    result = ReferenceCalibrationStudyRunner(
        initial.study_directory,
        controller_factory=_CompletedController,
    ).run_current_stage(
        event_callback=lambda event: observed.append(str(event["event"]))
    )

    assert calls == len(initial.candidates)
    assert result.status == "awaiting_review"
    assert {candidate.status for candidate in result.candidates} == {"completed"}
    assert observed.count("candidate_started") == len(initial.candidates)
    assert observed.count("candidate_completed") == len(initial.candidates)
    assert observed[-1] == "stage_awaiting_review"

    selected = result.candidates[1].candidate_id
    advanced, assessment = record_reference_calibration_stage_review(
        result.study_directory,
        visual_approvals={
            candidate.candidate_id: True for candidate in result.candidates
        },
        selected_candidate_id=selected,
    )

    assert assessment.balanced_candidate_id is not None
    assert advanced.current_stage is not None
    assert advanced.current_stage.stage_id == "deformation"
    assert advanced.selected_candidate_ids["attachment"] == selected
    selected_value = next(
        candidate.values["attachment_kernel_width"]
        for candidate in result.current_stage.candidates
        if candidate.candidate_id == selected
    )
    for candidate in advanced.candidates:
        config = yaml.safe_load(candidate.config_path.read_text(encoding="utf-8"))
        assert config["model"]["attachment"]["kernel_width"] == pytest.approx(
            selected_value
        )


def test_study_verification_rejects_changed_candidate_configuration(
    tmp_path: Path,
) -> None:
    snapshot = create_reference_calibration_study(
        _project(tmp_path),
        tmp_path / "study",
    )
    candidate = snapshot.candidates[0]
    candidate.config_path.write_text(
        candidate.config_path.read_text(encoding="utf-8") + "\n# changed\n",
        encoding="utf-8",
    )

    with pytest.raises(ReferenceCalibrationStudyError, match="changed"):
        load_reference_calibration_study(snapshot.study_directory)


def test_failed_candidate_can_be_retried_without_rerunning_completed_candidates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = create_reference_calibration_study(
        _project(tmp_path),
        tmp_path / "study",
        pilot_max_iterations=50,
    )
    failed_id = snapshot.candidates[0].candidate_id
    failed_once = False

    def factory(request):
        nonlocal failed_once
        if failed_id in str(request.config_path) and not failed_once:
            failed_once = True
            return _FailedController(request)
        return _CompletedController(request)

    def collect(run: Path):
        atlas = run / "atlas.vtk"
        atlas.write_text("placeholder", encoding="utf-8")
        return _metrics(atlas)

    monkeypatch.setattr(
        study_module,
        "collect_reference_calibration_run_metrics",
        collect,
    )
    runner = ReferenceCalibrationStudyRunner(
        snapshot.study_directory,
        controller_factory=factory,
    )
    first = runner.run_current_stage()

    assert first.status == "awaiting_review"
    failed = next(
        candidate
        for candidate in first.candidates
        if candidate.candidate_id == failed_id
    )
    assert failed.status == "failed"
    completed_attempts = {
        candidate.candidate_id: candidate.attempts
        for candidate in first.candidates
        if candidate.status == "completed"
    }

    second = ReferenceCalibrationStudyRunner(
        snapshot.study_directory,
        controller_factory=factory,
    ).run_current_stage()

    assert {candidate.status for candidate in second.candidates} == {"completed"}
    retried = next(
        candidate
        for candidate in second.candidates
        if candidate.candidate_id == failed_id
    )
    assert retried.attempts == 2
    assert retried.error is None
    assert {
        candidate.candidate_id: candidate.attempts
        for candidate in second.candidates
        if candidate.candidate_id in completed_attempts
    } == completed_attempts


def test_stage_selection_allows_candidate_without_optional_visual_qc(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = create_reference_calibration_study(
        _project(tmp_path),
        tmp_path / "study",
        pilot_max_iterations=50,
    )

    def collect(run: Path):
        atlas = run / "atlas.vtk"
        atlas.parent.mkdir(parents=True, exist_ok=True)
        atlas.write_text("placeholder", encoding="utf-8")
        return _metrics(atlas)

    monkeypatch.setattr(
        study_module,
        "collect_reference_calibration_run_metrics",
        collect,
    )
    completed = ReferenceCalibrationStudyRunner(
        snapshot.study_directory,
        controller_factory=_CompletedController,
    ).run_current_stage()
    selected = completed.candidates[0].candidate_id

    advanced, assessment = record_reference_calibration_stage_review(
        completed.study_directory,
        visual_approvals={},
        selected_candidate_id=selected,
    )

    assert assessment.status == "selection_required"
    assert advanced.current_stage is not None
    assert advanced.current_stage.stage_id == "deformation"
    selection_event = [
        event
        for event in study_module._load_events(completed.study_directory)
        if event["event"] == "stage_selected"
    ][-1]
    assert selection_event["visual_review_policy"] == "optional"
    assert selection_event["visual_review_status"][selected] == (
        "not_performed"
    )


def test_stage_selection_rejects_candidate_that_failed_optional_visual_qc(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = create_reference_calibration_study(
        _project(tmp_path),
        tmp_path / "study",
        pilot_max_iterations=50,
    )

    def collect(run: Path):
        atlas = run / "atlas.vtk"
        atlas.parent.mkdir(parents=True, exist_ok=True)
        atlas.write_text("placeholder", encoding="utf-8")
        return _metrics(atlas)

    monkeypatch.setattr(
        study_module,
        "collect_reference_calibration_run_metrics",
        collect,
    )
    completed = ReferenceCalibrationStudyRunner(
        snapshot.study_directory,
        controller_factory=_CompletedController,
    ).run_current_stage()
    selected = completed.candidates[0].candidate_id

    with pytest.raises(ReferenceCalibrationStudyError, match="not eligible"):
        record_reference_calibration_stage_review(
            completed.study_directory,
            visual_approvals={selected: False},
            selected_candidate_id=selected,
        )


def test_all_four_stages_publish_selected_full_cohort_configuration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = _project(tmp_path)
    source = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    snapshot = create_reference_calibration_study(
        config_path,
        tmp_path / "study",
        pilot_max_iterations=50,
    )
    call = 0

    def collect(run: Path):
        nonlocal call
        call += 1
        atlas = run / "atlas.vtk"
        atlas.parent.mkdir(parents=True, exist_ok=True)
        atlas.write_text("placeholder", encoding="utf-8")
        return _metrics(atlas, call / 1000)

    monkeypatch.setattr(
        study_module,
        "collect_reference_calibration_run_metrics",
        collect,
    )
    monkeypatch.setattr(study_module, "atlas_rms_distance", lambda *_args: 0.001)

    for _stage in range(4):
        snapshot = ReferenceCalibrationStudyRunner(
            snapshot.study_directory,
            controller_factory=_CompletedController,
        ).run_current_stage()
        assert snapshot.status == "awaiting_review"
        selected = snapshot.candidates[0].candidate_id
        snapshot, _assessment = record_reference_calibration_stage_review(
            snapshot.study_directory,
            visual_approvals={
                candidate.candidate_id: True for candidate in snapshot.candidates
            },
            selected_candidate_id=selected,
        )

    assert snapshot.status == "completed"
    assert snapshot.final_config_path is not None
    final = yaml.safe_load(snapshot.final_config_path.read_text(encoding="utf-8"))
    calibration = final["project"]["parameter_provenance"]["recommendation"][
        "calibration_result"
    ]
    assert calibration["status"] == "completed"
    assert calibration["plan_fingerprint"] == snapshot.plan.fingerprint
    assert set(calibration["selected_candidate_ids"]) == {
        "attachment",
        "deformation",
        "noise",
        "timepoints",
    }
    assert calibration["full_cohort_confirmation_required"] is True
    assert final["input"]["directory"] == str(MESH_DIRECTORY.resolve())
    assert final["optimization"]["max_iterations"] == source["optimization"][
        "max_iterations"
    ]
    load_reference_calibration_study(snapshot.study_directory)
