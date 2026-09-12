from __future__ import annotations

from dataclasses import replace
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
    assess_reference_calibration_snapshot,
    create_reference_calibration_search_extension_study,
    create_reference_calibration_study,
    latest_reference_calibration_search_extension_directory,
    load_reference_calibration_study,
    record_reference_calibration_provisional_override,
    record_reference_calibration_stage_review,
)
from diffeoforge.reference_recommendation import recommend_reference_parameters

ROOT = Path(__file__).parents[1]
MESH_DIRECTORY = ROOT / "examples" / "synthetic" / "meshes"


def test_latest_search_extension_directory_follows_deterministic_rounds(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "reference-pilot-abc123"
    root.mkdir()
    monkeypatch.setattr(
        study_module,
        "_search_extension_series",
        lambda candidate: (candidate.resolve(), 0),
    )
    assert latest_reference_calibration_search_extension_directory(root) == root

    first = tmp_path / "reference-pilot-abc123-extension-01"
    first.mkdir()
    assert latest_reference_calibration_search_extension_directory(root) == first

    third = tmp_path / "reference-pilot-abc123-extension-03"
    third.mkdir()
    with pytest.raises(ReferenceCalibrationStudyError, match="missing round"):
        latest_reference_calibration_search_extension_directory(root)


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
    assert len(snapshot.candidates) == 18
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


def test_unbounded_stage_can_create_and_run_hash_bound_outward_successor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = create_reference_calibration_study(
        _project(tmp_path),
        tmp_path / "source-study",
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
    source = ReferenceCalibrationStudyRunner(
        source.study_directory,
        controller_factory=_CompletedController,
    ).run_current_stage()
    source_assessment = assess_reference_calibration_snapshot(source)
    assert source_assessment.search_range_status == "not_bounded"
    assert source_assessment.search_boundary_parameters == (
        "attachment_kernel_width:minimum",
        "deformation_kernel_width:minimum",
        "initial_control_point_spacing:minimum",
    )

    successor = create_reference_calibration_search_extension_study(
        source.study_directory,
        tmp_path / "successor-study",
        safety_limits={
            "attachment_kernel_width": (1e-8, 100.0),
            "deformation_kernel_width": (1e-8, 100.0),
            "initial_control_point_spacing": (1e-8, 100.0),
        },
    )

    assert successor.status == "ready"
    assert successor.current_stage is not None
    assert successor.current_stage.stage_id == "attachment"
    assert successor.plan.version == "0.4"
    assert dict(successor.plan.search_extension_lineage)[
        "parent_plan_fingerprint"
    ] == source.plan.fingerprint
    assert len(successor.candidates) == len(source.candidates) + 6
    assert sum(candidate.status == "completed" for candidate in successor.candidates) == len(
        source.candidates
    )
    assert sum(candidate.status == "pending" for candidate in successor.candidates) == 6

    new_calls_before = call
    successor = ReferenceCalibrationStudyRunner(
        successor.study_directory,
        controller_factory=_CompletedController,
    ).run_current_stage()
    assert call - new_calls_before == 6
    assert successor.status == "awaiting_review"
    assert {candidate.status for candidate in successor.candidates} == {"completed"}
    combined = assess_reference_calibration_snapshot(successor)
    assert combined.plan_fingerprint == successor.plan.fingerprint
    assert combined.search_range_status == "bounded"
    assert combined.search_boundary_parameters == ()

    cli_successor = tmp_path / "cli-successor-study"
    assert (
        main(
            [
                "reference-calibration-study-extend",
                str(source.study_directory),
                "--output",
                str(cli_successor),
                "--limit",
                "attachment_kernel_width=1e-8:100",
                "--limit",
                "deformation_kernel_width=1e-8:100",
                "--limit",
                "initial_control_point_spacing=1e-8:100",
            ]
        )
        == 0
    )
    output = capsys.readouterr().out
    assert "Calibration search successor created" in output
    assert "new outward candidates: 6" in output
    assert load_reference_calibration_study(cli_successor).status == "ready"

    source_events = source.study_directory / study_module.STUDY_EVENTS
    source_events.write_text(
        source_events.read_text(encoding="utf-8") + "{}\n",
        encoding="utf-8",
    )
    with pytest.raises(ReferenceCalibrationStudyError):
        load_reference_calibration_study(cli_successor)


def test_search_extension_refuses_candidates_past_declared_safety_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = create_reference_calibration_study(
        _project(tmp_path),
        tmp_path / "source-study",
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
    source = ReferenceCalibrationStudyRunner(
        source.study_directory,
        controller_factory=_CompletedController,
    ).run_current_stage()
    stage = source.current_stage
    assert stage is not None
    minimum_attachment = min(
        candidate.values["attachment_kernel_width"]
        for candidate in stage.candidates
    )

    with pytest.raises(ReferenceCalibrationStudyError, match="Safety limit reached"):
        create_reference_calibration_search_extension_study(
            source.study_directory,
            tmp_path / "rejected-successor",
            safety_limits={
                "attachment_kernel_width": (minimum_attachment, 100.0),
                "deformation_kernel_width": (1e-8, 100.0),
                "initial_control_point_spacing": (1e-8, 100.0),
            },
        )
    assert not (tmp_path / "rejected-successor").exists()


def test_automatic_pilot_reuses_declared_limits_until_boundary_is_interior(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_directory = tmp_path / "pilot-extension-01"
    source_directory.mkdir()
    destination = tmp_path / "pilot-extension-02"
    stage = SimpleNamespace(stage_id="attachment")
    completed_candidate = SimpleNamespace(
        candidate_id="attachment-01",
        status="completed",
    )
    pending_candidate = SimpleNamespace(
        candidate_id="attachment-outward-r02-01",
        status="pending",
    )
    inherited_limits = {
        "attachment_kernel_width": (0.01, 1.0),
        "deformation_kernel_width": (0.01, 2.0),
    }
    source = SimpleNamespace(
        study_directory=source_directory,
        status="awaiting_review",
        current_stage=stage,
        candidates=(completed_candidate,),
        search_extension_safety_limits=inherited_limits,
    )
    successor_ready = SimpleNamespace(
        study_directory=destination,
        status="ready",
        current_stage=stage,
        candidates=(completed_candidate, pending_candidate),
        search_extension_safety_limits=inherited_limits,
        search_extension_round=2,
    )
    successor_awaiting = SimpleNamespace(
        **{
            **successor_ready.__dict__,
            "status": "awaiting_review",
            "candidates": (completed_candidate,),
        }
    )
    completed = SimpleNamespace(
        study_directory=destination,
        status="completed",
        current_stage=None,
        candidates=(),
        selected_candidate_ids={"attachment": "attachment-02"},
        plan=SimpleNamespace(stages=(stage,)),
    )
    boundary_assessment = SimpleNamespace(
        automatic_selection_allowed=False,
        search_range_status="not_bounded",
        search_boundary_parameters=("attachment_kernel_width:maximum",),
        stage_id="attachment",
        balanced_candidate_id="attachment-01",
    )
    bounded_assessment = SimpleNamespace(
        automatic_selection_allowed=True,
        search_range_status="bounded",
        search_boundary_parameters=(),
        stage_id="attachment",
        balanced_candidate_id="attachment-02",
    )

    monkeypatch.setattr(
        study_module,
        "load_reference_calibration_study",
        lambda directory: source
        if Path(directory).resolve() == source_directory
        else successor_ready,
    )
    monkeypatch.setattr(
        study_module,
        "assess_reference_calibration_snapshot",
        lambda snapshot: boundary_assessment
        if snapshot is source
        else bounded_assessment,
    )
    monkeypatch.setattr(
        study_module,
        "next_reference_calibration_search_extension_destination",
        lambda _directory: destination,
    )
    created: list[tuple[Path, Path, dict[str, tuple[float, float]]]] = []

    def create_successor(source_path, destination_path, *, safety_limits):
        created.append((Path(source_path), Path(destination_path), dict(safety_limits)))
        return successor_ready

    monkeypatch.setattr(
        study_module,
        "create_reference_calibration_search_extension_study",
        create_successor,
    )
    monkeypatch.setattr(
        study_module,
        "select_reference_calibration_stage_automatically",
        lambda _directory: (completed, bounded_assessment),
    )
    runner = ReferenceCalibrationStudyRunner(source_directory)
    monkeypatch.setattr(
        runner,
        "run_current_stage",
        lambda *, event_callback=None: successor_awaiting,
    )
    observed: list[dict[str, object]] = []

    result = runner.run_complete_automatic_pilot(event_callback=observed.append)

    assert result is completed
    assert runner.study_directory == destination
    assert created == [
        (
            source_directory,
            destination,
            {"attachment_kernel_width": inherited_limits["attachment_kernel_width"]},
        )
    ]
    extension_event = next(
        event for event in observed if event["event"] == "automatic_search_extended"
    )
    assert extension_event["extension_round"] == 2
    assert extension_event["pending_candidate_ids"] == [
        "attachment-outward-r02-01"
    ]


def test_noise_extension_preserves_prior_stage_selections(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = create_reference_calibration_study(
        _project(tmp_path),
        tmp_path / "source-study",
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
    for expected_stage in ("attachment", "deformation"):
        source = ReferenceCalibrationStudyRunner(
            source.study_directory,
            controller_factory=_CompletedController,
        ).run_current_stage()
        assert source.current_stage is not None
        assert source.current_stage.stage_id == expected_stage
        source, _assessment = record_reference_calibration_stage_review(
            source.study_directory,
            visual_approvals={},
            selected_candidate_id=source.candidates[0].candidate_id,
        )
    source = ReferenceCalibrationStudyRunner(
        source.study_directory,
        controller_factory=_CompletedController,
    ).run_current_stage()
    assert source.current_stage is not None
    assert source.current_stage.stage_id == "noise"
    assessment = assess_reference_calibration_snapshot(source)
    assert assessment.search_boundary_parameters == ("noise_std:minimum",)

    successor = create_reference_calibration_search_extension_study(
        source.study_directory,
        tmp_path / "noise-successor",
        safety_limits={"noise_std": (1e-10, 100.0)},
    )

    assert successor.current_stage is not None
    assert successor.current_stage.stage_id == "noise"
    assert successor.selected_candidate_ids == source.selected_candidate_ids
    assert successor.selected_values == source.selected_values
    assert len(successor.candidates) == len(source.candidates) + 2
    assert sum(candidate.status == "pending" for candidate in successor.candidates) == 2


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


def test_automatic_pilot_reports_a_shared_candidate_failure_reason(tmp_path: Path) -> None:
    snapshot = create_reference_calibration_study(
        _project(tmp_path),
        tmp_path / "automatic-failure-study",
        pilot_max_iterations=50,
    )

    with pytest.raises(
        ReferenceCalibrationStudyError,
        match=(
            r"All 18 incomplete candidates reported the same error: "
            r"synthetic transient failure"
        ),
    ):
        ReferenceCalibrationStudyRunner(
            snapshot.study_directory,
            controller_factory=_FailedController,
        ).run_complete_automatic_pilot()


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


def test_provisional_override_is_recorded_as_researcher_authorized(
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
    assessment = study_module.assess_reference_calibration_snapshot(completed)
    selected = assessment.balanced_candidate_id
    assert selected is not None

    advanced, _assessment = record_reference_calibration_provisional_override(
        completed.study_directory,
        visual_approvals={},
        selected_candidate_id=selected,
    )

    assert advanced.current_stage is not None
    event = [
        item
        for item in study_module._load_events(completed.study_directory)
        if item["event"] == "stage_selected"
    ][-1]
    assert event["selection_mode"] == "researcher_provisional_balanced_override"
    assert event["researcher_decision"] is True


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


def test_complete_automatic_pilot_runs_all_stages_and_writes_explainable_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = create_reference_calibration_study(
        _project(tmp_path),
        tmp_path / "automatic-study",
        pilot_max_iterations=50,
    )
    call = 0
    preferred_indices = {
        "attachment": 8,
        "deformation": 3,
        "noise": 3,
        "timepoints": 1,
    }

    def collect(run: Path):
        nonlocal call
        call += 1
        atlas = run / "atlas.vtk"
        atlas.parent.mkdir(parents=True, exist_ok=True)
        atlas.write_text("placeholder", encoding="utf-8")
        stage_id, index_text = run.parents[1].name.rsplit("-", maxsplit=1)
        offset = abs(int(index_text) - preferred_indices[stage_id]) / 1000
        return _metrics(atlas, offset)

    monkeypatch.setattr(
        study_module,
        "collect_reference_calibration_run_metrics",
        collect,
    )
    monkeypatch.setattr(study_module, "atlas_rms_distance", lambda *_args: 0.001)
    observed: list[dict[str, object]] = []

    completed = ReferenceCalibrationStudyRunner(
        snapshot.study_directory,
        controller_factory=_CompletedController,
    ).run_complete_automatic_pilot(event_callback=observed.append)

    assert completed.status == "completed"
    assert set(completed.selected_candidate_ids) == {
        "attachment",
        "deformation",
        "noise",
        "timepoints",
    }
    assert completed.report_json_path is not None
    assert completed.report_html_path is not None
    final_config = yaml.safe_load(
        completed.final_config_path.read_text(encoding="utf-8")
    )
    calibration_result = final_config["project"]["parameter_provenance"][
        "recommendation"
    ]["calibration_result"]
    assert set(calibration_result["selection_modes"].values()) == {
        "automatic_provisional_balanced_score"
    }
    runtime_calibration = calibration_result["runtime_calibration"]
    assert runtime_calibration["pilot_subject_count"] == 3
    assert len(runtime_calibration["observations"]) == 31
    report = study_module.load_reference_calibration_report(
        completed.study_directory
    )
    assert report["status"] == "provisional_pilot_recommendation"
    assert len(report["stage_decisions"]) == 4
    assert [
        decision["search_range_status"] for decision in report["stage_decisions"]
    ] == ["bounded", "bounded", "bounded", "not_applicable"]
    assert len(report["recommended_parameters"]) == 5
    assert report["full_cohort_confirmation_required"] is True
    assert {
        decision["selection_mode"] for decision in report["stage_decisions"]
    } == {"automatic_provisional_balanced_score"}
    selection_events = [
        event
        for event in study_module._load_events(completed.study_directory)
        if event["event"] == "stage_selected"
    ]
    assert len(selection_events) == 4
    assert all(event["researcher_decision"] is False for event in selection_events)
    assert sum(
        event["event"] == "automatic_stage_selected" for event in observed
    ) == 4
    assert "What it changes" in completed.report_html_path.read_text(
        encoding="utf-8"
    )


def test_automatic_pilot_pauses_on_subject_tail_ambiguity_then_continues(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = create_reference_calibration_study(
        _project(tmp_path),
        tmp_path / "mixed-automatic-study",
        pilot_max_iterations=50,
    )
    preferred_indices = {
        "attachment": 8,
        "deformation": 3,
        "timepoints": 1,
    }

    def collect(run: Path) -> ReferenceCalibrationRunMetrics:
        atlas = run / "atlas.vtk"
        atlas.parent.mkdir(parents=True, exist_ok=True)
        atlas.write_text("placeholder", encoding="utf-8")
        stage_id, index_text = run.parents[1].name.rsplit("-", maxsplit=1)
        candidate_index = int(index_text)
        if stage_id == "noise":
            subject_residuals = {
                1: (("a.vtk", 0.1), ("b.vtk", 0.5), ("c.vtk", 0.5)),
                2: (("a.vtk", 0.5), ("b.vtk", 0.1), ("c.vtk", 0.5)),
                3: (("a.vtk", 0.5), ("b.vtk", 0.5), ("c.vtk", 0.1)),
            }.get(
                candidate_index,
                (("a.vtk", 0.4), ("b.vtk", 0.4), ("c.vtk", 0.4)),
            )
            return replace(
                _metrics(atlas),
                subject_residual_p95=subject_residuals,
            )
        offset = abs(candidate_index - preferred_indices[stage_id]) / 1000
        return replace(
            _metrics(atlas, offset),
            subject_residual_p95=(
                ("a.vtk", 0.10 + offset),
                ("b.vtk", 0.11 + offset),
                ("c.vtk", 0.09 + offset),
            ),
        )

    monkeypatch.setattr(
        study_module,
        "collect_reference_calibration_run_metrics",
        collect,
    )
    monkeypatch.setattr(study_module, "atlas_rms_distance", lambda *_args: 0.001)
    observed: list[dict[str, object]] = []
    runner = ReferenceCalibrationStudyRunner(
        snapshot.study_directory,
        controller_factory=_CompletedController,
    )

    with pytest.raises(
        ReferenceCalibrationStudyError,
        match="refused to invent a unique winner",
    ):
        runner.run_complete_automatic_pilot(event_callback=observed.append)

    paused = load_reference_calibration_study(snapshot.study_directory)
    assert paused.status == "awaiting_review"
    assert paused.current_stage is not None
    assert paused.current_stage.stage_id == "noise"
    assert set(paused.selected_candidate_ids) == {"attachment", "deformation"}
    assessment = assess_reference_calibration_snapshot(paused)
    assert assessment.recommendation_confidence == "ambiguous"
    assert assessment.automatic_selection_allowed is False
    assert assessment.subject_bootstrap_iterations == 256
    assert assessment.subject_bootstrap_stability is not None
    assert assessment.subject_bootstrap_stability < 0.70
    assert any(
        "pilot subjects are resampled" in flag
        for flag in assessment.sensitivity_flags
    )
    assert assessment.balanced_candidate_id is not None

    continued, recorded = record_reference_calibration_provisional_override(
        paused.study_directory,
        visual_approvals={},
        selected_candidate_id=assessment.balanced_candidate_id,
    )
    assert recorded.fingerprint == assessment.fingerprint
    assert continued.status == "ready"
    assert continued.current_stage is not None
    assert continued.current_stage.stage_id == "timepoints"

    completed = runner.run_complete_automatic_pilot(event_callback=observed.append)
    assert completed.status == "completed"
    assert set(completed.selected_candidate_ids) == {
        "attachment",
        "deformation",
        "noise",
        "timepoints",
    }
    report = study_module.load_reference_calibration_report(
        completed.study_directory
    )
    selection_modes = {
        decision["stage_id"]: decision["selection_mode"]
        for decision in report["stage_decisions"]
    }
    assert selection_modes == {
        "attachment": "automatic_provisional_balanced_score",
        "deformation": "automatic_provisional_balanced_score",
        "noise": "researcher_provisional_balanced_override",
        "timepoints": "automatic_provisional_balanced_score",
    }
    selection_events = [
        event
        for event in study_module._load_events(completed.study_directory)
        if event["event"] == "stage_selected"
    ]
    assert [event["researcher_decision"] for event in selection_events] == [
        False,
        False,
        True,
        False,
    ]
