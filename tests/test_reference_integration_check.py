from dataclasses import replace

import pytest
from test_reference_stage_retention import _second_stage

from diffeoforge import reference_calibration_study as study
from diffeoforge import reference_integration_check as integration
from diffeoforge.reference_stage_retention import keep_previous_fit


def _fourth(tmp_path, monkeypatch):
    from test_reference_adaptive_calibration import seed_stub

    from diffeoforge.mesh import sha256_file

    runner, _, _, second = _second_stage(tmp_path, monkeypatch)
    keep_previous_fit(second.study_directory)
    fourth = keep_previous_fit(second.study_directory)

    def bound_seed(snapshot, center_id, destination):
        seed = seed_stub(snapshot, center_id, destination)
        candidate = next(c for c in snapshot.candidates if c.candidate_id == center_id)
        seed["source_manifest_sha256"] = sha256_file(
            study.calibration_candidate_run_directory(candidate) / "manifest.json")
        return seed

    monkeypatch.setattr("diffeoforge.reference_adaptive_calibration.bind_learned_seed", bound_seed)
    return runner, fourth


def test_predeclared_criteria_bind_full_cohort_and_choose_smallest_adequate_count(
    tmp_path, monkeypatch
):
    runner, fourth = _fourth(tmp_path, monkeypatch)
    done = runner.run_current_stage()
    assert done.integration_tolerances
    events = study._load_events(done.study_directory)
    declaration = next(e for e in events if e["event"] == "integration_tolerances_declared")
    assert len(declaration["subjects"]) == done.plan.pilot_subject_count
    assert declaration["sequence"] < min(
        e["sequence"] for e in events
        if e["event"] == "candidate_started" and e["stage_id"] == "timepoints"
    )
    assessment = study.assess_reference_calibration_snapshot(done)
    assert assessment.balanced_candidate_id == fourth.candidates[0].candidate_id
    assert assessment.metric_weights == (("timepoints", 1.0),)
    assert not assessment.candidates[-1].eligible  # No finer reference for the largest.
    assert not done.visual_reviews  # Numerical stability never supplies anatomical QC.
    with pytest.raises(study.ReferenceCalibrationStudyError, match="Every pilot specimen"):
        study.record_reference_calibration_stage_review(
            done.study_directory, selected_candidate_id=assessment.balanced_candidate_id,
            visual_approvals={},
        )
    with pytest.raises(ValueError, match="already bound"):
        integration.declare_tolerances(done, {k: 0.2 for k in integration.DEFAULT_TOLERANCES})


def test_worst_specimen_failure_cannot_be_hidden_by_cohort_average(tmp_path, monkeypatch):
    runner, _ = _fourth(tmp_path, monkeypatch)
    done = runner.run_current_stage()
    first = done.candidates[0]
    metrics = dict(first.metrics)
    metrics["subject_residual_p95"] = dict(metrics["subject_residual_p95"])
    name = next(iter(metrics["subject_residual_p95"]))
    metrics["subject_residual_p95"][name] *= 3
    # Cohort residual and runtime stay identical; only one measured specimen differs.
    changed = replace(done, candidates=(replace(first, metrics=metrics), *done.candidates[1:]))
    assessment = study.assess_reference_calibration_snapshot(changed)
    assert not assessment.candidates[0].eligible
    assert any("residual_relative_difference exceeds" in r
               for r in assessment.candidates[0].rejection_reasons)
    missing = dict(metrics)
    missing["subject_residual_p95"] = {}
    changed = replace(done, candidates=(replace(first, metrics=missing), *done.candidates[1:]))
    assert not study.assess_reference_calibration_snapshot(changed).candidates[0].eligible


def test_nonconverged_finer_reference_cannot_certify_a_coarser_run(tmp_path, monkeypatch):
    runner, _ = _fourth(tmp_path, monkeypatch)
    done = runner.run_current_stage()
    reference = done.candidates[1]
    changed = replace(done, candidates=(done.candidates[0], replace(
        reference, metrics=dict(reference.metrics, converged=False)), *done.candidates[2:]))
    assessment = study.assess_reference_calibration_snapshot(changed)
    assert not assessment.candidates[0].eligible
    assert not assessment.candidates[1].eligible


def test_invalid_criteria_refused_before_any_execution(tmp_path, monkeypatch):
    _, fourth = _fourth(tmp_path, monkeypatch)
    for value in (0, -1, float("nan"), True, 2):
        values = dict(integration.DEFAULT_TOLERANCES, residual_relative=value)
        with pytest.raises(ValueError, match="finite positive"):
            integration.declare_tolerances(fourth, values)
    assert not study.load_reference_calibration_study(fourth.study_directory).integration_tolerances


def test_legacy_started_comparison_keeps_its_original_meaning(tmp_path, monkeypatch):
    runner, fourth = _fourth(tmp_path, monkeypatch)
    monkeypatch.setattr(integration, "declare_tolerances", lambda snapshot, _values: snapshot)
    done = runner.run_current_stage()
    assert not done.integration_tolerances
    monkeypatch.undo()
    assert integration.declare_tolerances(done) == done
    with pytest.raises(ValueError, match="before running"):
        integration.declare_tolerances(done, integration.DEFAULT_TOLERANCES)


def test_finer_resolution_preserves_history_and_only_runs_the_added_full_cohort(
    tmp_path, monkeypatch,
):
    from diffeoforge.config import load_config, validate_input_paths

    runner, _ = _fourth(tmp_path, monkeypatch)
    done = runner.run_current_stage()
    old = {p: p.read_bytes() for p in done.study_directory.rglob("*") if p.is_file()}
    prepared = integration.add_finer_resolution(done.study_directory)
    assert len(prepared.candidates) == 4
    added = prepared.candidates[-1]
    assert prepared.current_stage.candidates[-1].values == {"timepoints": 40.0}
    assert prepared.integration_tolerances == done.integration_tolerances
    assert prepared.selected_candidate_ids == done.selected_candidate_ids
    assert prepared.visual_reviews == done.visual_reviews
    config = load_config(added.config_path)
    assert config["model"]["deformation"]["timepoints"] == 40
    inputs = validate_input_paths(config, added.config_path)
    assert inputs.initial_momenta is not None and inputs.initial_control_points is not None
    assert len(inputs.subjects) == prepared.plan.pilot_subject_count
    for path, content in old.items():
        assert (path.read_bytes().startswith(content) if path.name == study.STUDY_EVENTS
                else path.read_bytes() == content)
    assert integration.next_resolution(prepared) is None
    with pytest.raises(ValueError, match="Finish the complete"):
        integration.add_finer_resolution(done.study_directory)
    before = study._load_events(done.study_directory)[-1]["sequence"]
    finished = runner.run_current_stage()
    starts = [e for e in study._load_events(done.study_directory)
              if e["sequence"] > before and e["event"] == "candidate_started"]
    assert [e["candidate_id"] for e in starts] == [added.candidate_id]
    assert (finished.candidates[-1].metrics["subject_reconstruction_count"]
            == done.plan.pilot_subject_count)
    assessment = study.assess_reference_calibration_snapshot(finished)
    assert assessment.candidates[-2].eligible  # Former highest count has a finer reference.
    assert not assessment.candidates[-1].eligible
    assert added.candidate_id not in finished.visual_reviews
    reopened = study.load_reference_calibration_study(done.study_directory)
    assert reopened.plan == finished.plan
    assert integration.next_resolution(reopened) == 50
    second = integration.add_finer_resolution(reopened.study_directory)
    assert second.current_stage.candidates[-1].values == {"timepoints": 50.0}
    assert len(second.candidates) == 5
    with pytest.raises(ValueError, match="already bound"):
        integration.declare_tolerances(second, {k: 0.2 for k in integration.DEFAULT_TOLERANCES})


@pytest.mark.parametrize("problem", ["not_converged", "invalid", "rejected", "screening"])
def test_finer_resolution_requires_valid_finest_complete_cohort(problem, tmp_path, monkeypatch):
    runner, _ = _fourth(tmp_path, monkeypatch)
    done = runner.run_current_stage()
    last = done.candidates[-1]
    metrics = dict(last.metrics)
    reviews = dict(done.visual_reviews)
    if problem == "not_converged":
        metrics["converged"] = False
    elif problem == "invalid":
        metrics["invalid_face_count"] = 1
    elif problem == "screening":
        metrics["fit_scope"] = "screening"
    else:
        reviews[last.candidate_id] = False
    modified = replace(done, candidates=(*done.candidates[:-1], replace(last, metrics=metrics)),
                       visual_reviews=reviews)
    assert integration.next_resolution(modified) is None


def test_modified_extension_seed_or_config_is_rejected_on_reopen(tmp_path, monkeypatch):
    runner, _ = _fourth(tmp_path, monkeypatch)
    done = runner.run_current_stage()
    integration.add_finer_resolution(done.study_directory)
    event = study._load_events(done.study_directory)[-1]
    seed = done.study_directory / event["continuation_seed"]["files"]["momenta"]["copy"]
    old = seed.read_bytes()
    seed.write_bytes(old + b"\nchanged\n")
    with pytest.raises(ValueError, match="initialization changed"):
        study.load_reference_calibration_study(done.study_directory)
    seed.write_bytes(old)
    config = done.study_directory / event["config"]
    config.write_bytes(config.read_bytes() + b"\n# changed\n")
    with pytest.raises(study.ReferenceCalibrationStudyError, match="configuration changed"):
        study.load_reference_calibration_study(done.study_directory)


def test_finer_resolution_button_dispatches_one_background_comparison(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from diffeoforge.desktop.reference_calibration_dialog import ReferenceCalibrationDialog

    app = QApplication.instance() or QApplication([])
    runner, _ = _fourth(tmp_path, monkeypatch)
    runner.run_current_stage()
    dialog = ReferenceCalibrationDialog(runner.study_directory)
    dialog.show()
    app.processEvents()
    assert dialog.finer_resolution_button.isVisible()
    assert "40 time points" in dialog.finer_resolution_button.text()
    calls = []
    monkeypatch.setattr(dialog, "_start_pilot", lambda **kwargs: calls.append(kwargs))
    dialog.finer_resolution_button.click()
    assert calls == [{"adaptive": False, "finer_resolution": True}]
    dialog._worker = object()
    dialog._render()
    assert not dialog.finer_resolution_button.isEnabled()
    dialog._worker = None
    dialog.close()
    app.processEvents()


def test_worker_prepares_and_executes_only_the_new_resolution(tmp_path, monkeypatch):
    from diffeoforge.desktop.reference_calibration_dialog import _CalibrationStageWorker

    runner, _ = _fourth(tmp_path, monkeypatch)
    done = runner.run_current_stage()
    before = study._load_events(done.study_directory)[-1]["sequence"]
    worker = _CalibrationStageWorker(runner, finer_resolution=True)
    events, success, failures = [], [], []
    worker.signals.event.connect(events.append)
    worker.signals.succeeded.connect(success.append)
    worker.signals.failed.connect(failures.append)
    worker.run()
    assert not failures and len(success) == 1
    assert events[0]["event"] == "integration_resolution_prepared"
    starts = [e for e in study._load_events(done.study_directory)
              if e["sequence"] > before and e["event"] == "candidate_started"]
    assert [e["candidate_id"] for e in starts] == ["timepoints-04"]
    assert success[0].status == "awaiting_review"
