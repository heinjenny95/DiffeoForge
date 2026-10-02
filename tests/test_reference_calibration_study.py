from __future__ import annotations

import os
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
    record_reference_calibration_stage_review,
)
from diffeoforge.reference_recommendation import recommend_reference_parameters

ROOT = Path(__file__).parents[1]
MESH_DIRECTORY = ROOT / "examples" / "synthetic" / "meshes"


@pytest.fixture(autouse=True)
def _synthetic_learned_seed(monkeypatch):
    _stub_learned_seed(monkeypatch)


def _stub_learned_seed(monkeypatch):
    from test_reference_adaptive_calibration import seed_stub

    # These controllers produce synthetic receipts, not optimizer tensors.
    monkeypatch.setattr("diffeoforge.reference_adaptive_calibration.bind_learned_seed", seed_stub)


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
    study_root = next(parent for parent in atlas_path.parents if (parent / "study.json").is_file())
    subjects = sorted((study_root / "inputs" / "subjects").glob("*.vtk"))
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
        subject_residual_p95=tuple((p.name, 0.2 + offset) for p in subjects),
    )


class _CompletedController:
    def __init__(self, request) -> None:
        self.request = request

    def request_cancel(self) -> bool:
        return True

    def run(self, *, event_callback=None):
        self.request.destination.mkdir(parents=True)
        for name in ("manifest.json", "result.json", "output-inventory.json"):
            (self.request.destination / name).write_text("{}", encoding="utf-8")
        return SimpleNamespace(completed=True)


class _FailedController(_CompletedController):
    def run(self, *, event_callback=None):
        raise RuntimeError("synthetic transient failure")


def _afk_runner(tmp_path, monkeypatch, *, invalid=False, controller=_CompletedController):
    _stub_learned_seed(monkeypatch)
    snapshot = create_reference_calibration_study(
        _project(tmp_path),
        tmp_path / "afk-study",
        pilot_max_iterations=50,
    )

    def collect(run):
        atlas = run / "atlas.vtk"
        atlas.write_text("placeholder", encoding="utf-8")
        return replace(_metrics(atlas), invalid_face_count=1 if invalid else 0)

    monkeypatch.setattr(study_module, "collect_reference_calibration_run_metrics", collect)
    monkeypatch.setattr(study_module, "atlas_rms_distance", lambda *_args: 0.001)
    return ReferenceCalibrationStudyRunner(snapshot.study_directory, controller_factory=controller)


def _review_ready_stage(tmp_path, monkeypatch):
    runner = _afk_runner(tmp_path, monkeypatch)
    snapshot = runner.run_current_stage()
    # Synthetic run receipts, separate from the metrics stub used by this fixture.
    for candidate in snapshot.candidates:
        for name in ("manifest.json", "result.json", "output-inventory.json"):
            (candidate.run_directory / name).write_text("{}", encoding="utf-8")
    return runner, snapshot


def test_visual_decisions_survive_reopen_override_stale_afk_and_bind_evidence(
    tmp_path,
    monkeypatch,
):
    runner, snapshot = _review_ready_stage(tmp_path, monkeypatch)
    subjects = tuple(s.filename for s in snapshot.plan.selected_pilot_subjects)
    rejected, accepted = snapshot.candidates[:2]
    for candidate, approval in ((rejected, False), (accepted, True)):
        study_module.record_reference_calibration_candidate_review(
            runner.study_directory,
            candidate_id=candidate.candidate_id,
            approved=approval,
            reviewed_subjects=subjects,
            anatomical_notes="Synthetic tip and branch review.",
            subject_decisions={name: ("pass" if approval else "fail") for name in subjects},
        )
    reopened = load_reference_calibration_study(runner.study_directory)
    assert reopened.visual_reviews == {
        rejected.candidate_id: False,
        accepted.candidate_id: True,
    }
    assert reopened.visual_review_notes[accepted.candidate_id] == "Synthetic tip and branch review."
    assessment = assess_reference_calibration_snapshot(
        reopened,
        visual_approvals={rejected.candidate_id: True},
    )
    assert assessment.balanced_candidate_id == accepted.candidate_id
    assert not assessment.candidates[0].eligible
    events = study_module._load_events(runner.study_directory)
    assert events[-1]["anatomical_notes"] == "Synthetic tip and branch review."
    # A changed receipt cannot silently reuse an anatomical decision.
    (accepted.run_directory / "result.json").write_text('{"changed":true}', encoding="utf-8")
    with pytest.raises(ReferenceCalibrationStudyError, match="source evidence changed"):
        load_reference_calibration_study(runner.study_directory)


def test_review_requires_all_subjects_and_selection_records_saved_decisions(tmp_path, monkeypatch):
    runner, snapshot = _review_ready_stage(tmp_path, monkeypatch)
    subjects = tuple(s.filename for s in snapshot.plan.selected_pilot_subjects)
    candidate = snapshot.candidates[0]
    before = study_module._load_events(runner.study_directory)
    for invalid in (subjects[:-1], (*subjects, subjects[0])):
        with pytest.raises(ReferenceCalibrationStudyError, match="every pilot subject"):
            study_module.record_reference_calibration_candidate_review(
                runner.study_directory,
                candidate_id=candidate.candidate_id,
                approved=True,
                reviewed_subjects=invalid,
                subject_decisions={name: ("pass" if True else "fail") for name in invalid},
            )
    assert study_module._load_events(runner.study_directory) == before
    study_module.record_reference_calibration_candidate_review(
        runner.study_directory,
        candidate_id=candidate.candidate_id,
        approved=True,
        reviewed_subjects=subjects,
        subject_decisions={name: ("pass" if True else "fail") for name in subjects},
    )
    selected, _ = study_module.record_reference_calibration_provisional_override(
        runner.study_directory,
        visual_approvals={},
        selected_candidate_id=candidate.candidate_id,
    )
    assert selected.selected_candidate_ids["attachment"] == candidate.candidate_id
    assert selected.visual_reviews == {"deformation-retained": True}
    event = next(
        e
        for e in reversed(study_module._load_events(runner.study_directory))
        if e["event"] == "stage_selected"
    )
    assert event["visual_approvals"] == {candidate.candidate_id: True}


def test_dataset_feature_conflicts_cannot_be_approved(tmp_path, monkeypatch):
    runner, snapshot = _review_ready_stage(tmp_path, monkeypatch)
    subjects = tuple(s.filename for s in snapshot.plan.selected_pilot_subjects)
    cid = snapshot.candidates[0].candidate_id
    for original, reconstruction in ((3, 2), (3, None), (True, 2), (-1, 2)):
        with pytest.raises(ReferenceCalibrationStudyError, match="[Ff]eature"):
            study_module.record_reference_calibration_candidate_review(
                runner.study_directory,
                candidate_id=cid,
                approved=True,
                reviewed_subjects=subjects,
                feature_observations={
                    subjects[0]: {
                        "original": original,
                        "reconstruction": reconstruction,
                        "criterion": "Study A: distal prongs",
                        "judgement": "preserved",
                    }
                },
                subject_decisions={name: ("pass" if True else "fail") for name in subjects},
            )
    counts = {
        subjects[0]: {
            "original": 3,
            "reconstruction": 2,
            "criterion": "Study A: distal prongs",
            "judgement": "not_preserved",
        }
    }
    saved = study_module.record_reference_calibration_candidate_review(
        runner.study_directory,
        candidate_id=cid,
        approved=False,
        reviewed_subjects=subjects,
        feature_observations=counts,
        subject_decisions={name: ("pass" if False else "fail") for name in subjects},
    )
    assert saved.feature_observations[cid] == counts
    assert saved.visual_reviews[cid] is False
    assert not assess_reference_calibration_snapshot(saved).candidates[0].eligible
    qualitative = {
        subjects[0]: {
            "original": None,
            "reconstruction": None,
            "criterion": "Study B: joint outline",
            "judgement": "uncertain",
        }
    }
    with pytest.raises(ReferenceCalibrationStudyError, match="unresolved feature"):
        study_module.record_reference_calibration_candidate_review(
            runner.study_directory,
            candidate_id=cid,
            approved=True,
            reviewed_subjects=subjects,
            feature_observations=qualitative,
            subject_decisions={name: ("pass" if True else "fail") for name in subjects},
        )
    qualitative[subjects[0]]["judgement"] = "preserved"
    accepted = study_module.record_reference_calibration_candidate_review(
        runner.study_directory,
        candidate_id=cid,
        approved=True,
        reviewed_subjects=subjects,
        feature_observations=qualitative,
        subject_decisions={name: ("pass" if True else "fail") for name in subjects},
    )
    assert accepted.feature_observations[cid] == qualitative
    assert accepted.visual_reviews[cid] is True


@pytest.fixture(scope="session")
def afk_qt_application():
    """Match the desktop's process-long application lifetime across later GUI tests."""
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    previous = os.environ.get("QT_QPA_PLATFORM")
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    application = QApplication.instance() or QApplication([])
    yield application
    application.closeAllWindows()
    application.processEvents()
    if previous is None:
        os.environ.pop("QT_QPA_PLATFORM", None)
    else:
        os.environ["QT_QPA_PLATFORM"] = previous


@pytest.mark.parametrize("failure_point", ["runner", "dispatch"])
def test_afk_start_errors_are_visible_and_retryable(
    tmp_path, monkeypatch, afk_qt_application, failure_point
):
    from unittest.mock import Mock

    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QMessageBox

    import diffeoforge.desktop.reference_calibration_dialog as dialog_module

    runner = _afk_runner(tmp_path, monkeypatch)
    events_path = runner.study_directory / "events.jsonl"
    events_before = events_path.read_bytes()
    dialog = dialog_module.ReferenceCalibrationDialog(runner.study_directory)
    dialog.afk_mode.setChecked(True)
    dialog.outward_mode.setChecked(True)
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Yes)
    messages = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *a: messages.append(a[1:]))
    worker = Mock()
    monkeypatch.setattr(dialog_module, "_CalibrationStageWorker", lambda *a, **kw: worker)
    queued = []
    dialog._thread_pool = SimpleNamespace(start=queued.append)

    def fail(*args, **kwargs):
        raise AttributeError("synthetic startup error")

    if failure_point == "limits":
        monkeypatch.setattr(dialog_module, "default_outward_safety_limits", fail)
    elif failure_point == "runner":
        monkeypatch.setattr(dialog_module, "ReferenceCalibrationStudyRunner", fail)
    else:
        dialog._thread_pool = SimpleNamespace(start=fail)
    dialog.start_button.click()
    assert len(messages) == 1
    assert messages[0][0] == "Pilot could not start"
    assert "AttributeError: synthetic startup error" in messages[0][1]
    assert "Pilot start failed" in dialog.status.text()
    assert not queued and dialog._worker is None
    assert dialog.start_button.isEnabled()
    assert dialog.afk_mode.isEnabled() and dialog.outward_mode.isEnabled()
    assert not dialog.cancel_button.isEnabled() and dialog.cancel_button.isHidden()
    assert events_path.read_bytes() == events_before
    dialog.close()
    dialog.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    afk_qt_application.processEvents()


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
    ).run_current_stage(event_callback=lambda event: observed.append(str(event["event"])))

    assert calls == len(initial.candidates)
    assert result.status == "awaiting_review"
    assert {candidate.status for candidate in result.candidates} == {"completed"}
    assert observed.count("candidate_started") == len(initial.candidates)
    assert observed.count("candidate_completed") == len(initial.candidates)
    assert observed[-1] == "stage_awaiting_review"

    selected = result.candidates[1].candidate_id
    _approve_for_test(result.study_directory, selected)
    advanced, assessment = record_reference_calibration_stage_review(
        result.study_directory,
        visual_approvals={candidate.candidate_id: True for candidate in result.candidates},
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
        assert config["model"]["attachment"]["kernel_width"] == pytest.approx(selected_value)


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
    assert (
        dict(successor.plan.search_extension_lineage)["parent_plan_fingerprint"]
        == source.plan.fingerprint
    )
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
        candidate.values["attachment_kernel_width"] for candidate in stage.candidates
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
        _approve_for_test(source.study_directory, source.candidates[0].candidate_id)
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
    # Keep the legacy boundary scenario: the unchanged baseline was inspected
    # and rejected here, so the new trials determine the outward proposal.
    name = source.plan.selected_pilot_subjects[0].filename
    source = study_module.record_reference_calibration_candidate_review(
        source.study_directory,
        candidate_id="noise-retained", approved=False, reviewed_subjects=(name,),
        subject_decisions={name: "fail"}, display_scopes={name: "preview"},
    )
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
        candidate for candidate in first.candidates if candidate.candidate_id == failed_id
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
        candidate for candidate in second.candidates if candidate.candidate_id == failed_id
    )
    assert retried.attempts == 2
    assert retried.error is None
    assert {
        candidate.candidate_id: candidate.attempts
        for candidate in second.candidates
        if candidate.candidate_id in completed_attempts
    } == completed_attempts


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
        _approve_for_test(snapshot.study_directory, selected)
        snapshot, _assessment = record_reference_calibration_stage_review(
            snapshot.study_directory,
            visual_approvals={candidate.candidate_id: True for candidate in snapshot.candidates},
            selected_candidate_id=selected,
        )

    assert snapshot.status == "completed"
    assert snapshot.final_config_path is not None
    final = yaml.safe_load(snapshot.final_config_path.read_text(encoding="utf-8"))
    calibration = final["project"]["parameter_provenance"]["recommendation"]["calibration_result"]
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
    assert final["optimization"]["max_iterations"] == source["optimization"]["max_iterations"]
    load_reference_calibration_study(snapshot.study_directory)


@pytest.mark.parametrize(
    "limits",
    [
        {},
        {"x": (1.0,)},
        {"x": (-1.0, 2.0)},
        {"x": (2.0, 1.0)},
        {"x": (0.0, 1.0)},
        {"": (1.0, 2.0)},
    ],
)
def test_outward_safety_limits_are_validated_strictly(limits) -> None:
    with pytest.raises(ValueError):
        study_module._validated_outward_safety_limits(limits)


def test_default_outward_limits_come_from_the_tested_grid() -> None:
    from diffeoforge.reference_calibration import CalibrationCandidate

    def candidate(name, value):
        return CalibrationCandidate(name, name, ((name, value),), "Test real plan storage")

    plan = SimpleNamespace(
        stages=(
            SimpleNamespace(
                candidates=(
                    candidate("noise_std", 0.02),
                    candidate("noise_std", 0.08),
                    candidate("fixed", 1.0),
                )
            ),
        )
    )

    limits = study_module.default_outward_safety_limits(plan, factor=4.0)

    assert limits == {"noise_std": (0.005, 0.32)}
    # A parameter that never varies gets no interval to widen.
    assert "fixed" not in limits


def _approve_for_test(root, candidate_id):
    snapshot = load_reference_calibration_study(root)
    subjects = tuple(s.filename for s in snapshot.plan.selected_pilot_subjects)
    study_module.record_reference_calibration_candidate_review(
        root,
        candidate_id=candidate_id,
        approved=True,
        reviewed_subjects=subjects,
        subject_decisions={name: "pass" for name in subjects},
    )
