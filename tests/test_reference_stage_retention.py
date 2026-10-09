import pytest
from test_reference_calibration_study import _afk_runner, _approve_for_test, _review_ready_stage

from diffeoforge import reference_calibration_study as study
from diffeoforge.config import load_config, validate_input_paths
from diffeoforge.reference_stage_retention import keep_previous_fit


@pytest.mark.parametrize("other_approved", [False, True])
@pytest.mark.parametrize("provisional", [False, True])
def test_other_candidate_reviews_do_not_block_exact_retention(
    tmp_path, monkeypatch, other_approved, provisional,
):
    from dataclasses import replace

    runner = _afk_runner(tmp_path, monkeypatch)
    if provisional:
        collect = study.collect_reference_calibration_run_metrics
        monkeypatch.setattr(study, "collect_reference_calibration_run_metrics", lambda run: replace(
            collect(run), converged=False, optimizer_stop_signal="maximum_iterations",
            final_iteration=50,
        ))
    first = runner.run_current_stage()
    other, selected = first.candidates[:2]
    subjects = tuple(s.filename for s in first.plan.selected_pilot_subjects)
    study.record_reference_calibration_candidate_review(
        first.study_directory, candidate_id=other.candidate_id, approved=other_approved,
        reviewed_subjects=subjects,
        subject_decisions={name: "pass" if other_approved else "fail" for name in subjects},
    )
    _approve_for_test(first.study_directory, selected.candidate_id)
    original = {p: p.read_bytes() for p in (first.study_directory / "stages").rglob("*")
                if p.is_file()}
    choose = (study.record_reference_calibration_iteration_limit_selection if provisional
              else study.record_reference_calibration_stage_review)
    second, _ = choose(first.study_directory, selected_candidate_id=selected.candidate_id,
                       **({} if provisional else {"visual_approvals": {}}))
    baseline = second.candidates[-1]
    assert baseline.candidate_id == "deformation-retained"
    assert study.calibration_candidate_run_directory(baseline) == selected.run_directory
    assert second.visual_reviews[baseline.candidate_id] is True
    third = keep_previous_fit(second.study_directory)
    assert third.current_stage.order == 3
    assert all(p.read_bytes() == contents for p, contents in original.items())
    assert third.candidates[-1].metrics == selected.metrics
    retained_selection = next(e for e in reversed(study._load_events(third.study_directory))
                              if e["event"] == "stage_selected")
    assert bool(retained_selection.get("iteration_limit_provisional")) == provisional
    study._append_event(first.study_directory, "candidate_visual_review", dict(
        stage_id="attachment", candidate_id=selected.candidate_id, approved=False,
        reviewed_subjects=list(subjects), source=study._candidate_review_binding(selected),
    ))
    with pytest.raises(study.ReferenceCalibrationStudyError, match="withdrawn"):
        keep_previous_fit(third.study_directory)


def _second_stage(tmp_path, monkeypatch):
    runner, first = _review_ready_stage(tmp_path, monkeypatch)
    candidate = first.candidates[0]
    _approve_for_test(first.study_directory, candidate.candidate_id)
    second, _ = study.record_reference_calibration_stage_review(
        first.study_directory, selected_candidate_id=candidate.candidate_id, visual_approvals={}
    )
    return runner, first, candidate, second


def test_retained_fit_reuses_exact_output_and_real_previous_approval(tmp_path, monkeypatch):
    _, first, accepted, second = _second_stage(tmp_path, monkeypatch)
    baseline = second.candidates[-1]
    assert baseline.candidate_id == "deformation-retained"
    assert baseline.attempts == 0
    assert second.visual_reviews[baseline.candidate_id] is True
    assert study.calibration_candidate_run_directory(baseline) == accepted.run_directory
    assert baseline.metrics == accepted.metrics
    assert not any(
        e["event"] == "candidate_visual_review" and e.get("stage_id") == "deformation"
        for e in study._load_events(first.study_directory)
    )
    before = load_config(accepted.config_path)
    retained = load_config(baseline.config_path)
    assert retained["model"] == before["model"]
    assert second.plan.fingerprint != first.plan.fingerprint
    assert study.load_reference_calibration_study(second.study_directory).plan == second.plan


def test_keep_skips_bad_or_unexecuted_trials_without_new_run_or_repeat_qc(tmp_path, monkeypatch):
    _, first, accepted, second = _second_stage(tmp_path, monkeypatch)
    receipts = {p: p.read_bytes() for p in accepted.run_directory.iterdir() if p.is_file()}
    run_directories = set(first.study_directory.rglob("pilot-attempt-*"))
    third = keep_previous_fit(second.study_directory)
    assert third.current_stage.stage_id == "noise"
    assert third.selected_candidate_ids["deformation"] == "deformation-retained"
    assert set(first.study_directory.rglob("pilot-attempt-*")) == run_directories
    assert all(p.read_bytes() == content for p, content in receipts.items())
    assert (
        third.selected_values["initial_control_point_spacing"]
        == load_config(accepted.config_path)["model"]["deformation"][
            "initial_control_point_spacing"
        ]
    )
    for candidate in third.candidates[:-1]:
        inputs = validate_input_paths(load_config(candidate.config_path), candidate.config_path)
        assert "stage-seeds" in str(inputs.template)
        assert inputs.initial_control_points is not None
        assert inputs.initial_momenta is not None
    # A second explicit keep advances to integration, but cannot skip numerical QC.
    fourth = keep_previous_fit(third.study_directory)
    assert fourth.current_stage.stage_id == "timepoints"
    with pytest.raises(study.ReferenceCalibrationStudyError, match="stages 2 and 3"):
        keep_previous_fit(fourth.study_directory)


def test_changed_grid_uses_learned_template_without_incompatible_momenta(tmp_path, monkeypatch):
    _, _, _, second = _second_stage(tmp_path, monkeypatch)
    for candidate in second.candidates[:-1]:
        config = load_config(candidate.config_path)
        inputs = validate_input_paths(config, candidate.config_path)
        assert "stage-seeds" in str(inputs.template)
        # The ordinary grid-changing candidates must not reuse the old field.
        if inputs.initial_control_points is None:
            assert inputs.initial_momenta is None


def test_modified_source_output_cannot_be_kept(tmp_path, monkeypatch):
    _, _, accepted, second = _second_stage(tmp_path, monkeypatch)
    (accepted.run_directory / "result.json").write_text("changed", encoding="utf-8")
    with pytest.raises(study.ReferenceCalibrationStudyError, match="evidence|source"):
        keep_previous_fit(second.study_directory)


def test_modified_reference_cannot_be_reopened(tmp_path, monkeypatch):
    _, _, _, second = _second_stage(tmp_path, monkeypatch)
    reference = second.candidates[-1].run_directory / "evidence.json"
    reference.write_text("{}", encoding="utf-8")
    with pytest.raises(study.ReferenceCalibrationStudyError, match="reference changed"):
        study.load_reference_calibration_study(second.study_directory)


def test_retained_selection_uses_no_controller(tmp_path, monkeypatch):
    runner, _, _, second = _second_stage(tmp_path, monkeypatch)

    def forbidden(*args, **kwargs):
        pytest.fail("Keeping an approved fit must not launch an optimizer")

    monkeypatch.setattr(runner, "run_current_stage", forbidden)
    result = keep_previous_fit(second.study_directory)
    assert result.current_stage.order == 3


def test_legacy_completed_bad_stage_can_keep_source_without_changing_trials(tmp_path, monkeypatch):
    import diffeoforge.reference_stage_retention as retention

    register = retention.register_previous_fit
    monkeypatch.setattr(retention, "register_previous_fit", lambda snapshot: snapshot)
    runner, _, accepted, second = _second_stage(tmp_path, monkeypatch)
    assert not any(c.candidate_id.endswith("-retained") for c in second.candidates)
    second = runner.run_current_stage()
    assert second.status == "awaiting_review"
    original = {
        p: p.read_bytes() for p in (second.study_directory / "stages").rglob("*") if p.is_file()
    }
    monkeypatch.setattr(retention, "register_previous_fit", register)
    third = keep_previous_fit(second.study_directory)
    assert third.current_stage.order == 3
    assert all(p.read_bytes() == data for p, data in original.items())
    prior, _ = retention._candidate(second.study_directory, "deformation", "deformation-retained")
    assert study.calibration_candidate_run_directory(prior) == accepted.run_directory


def test_retained_fit_cannot_override_an_explicit_new_rejection(tmp_path, monkeypatch):
    _, _, _, second = _second_stage(tmp_path, monkeypatch)
    name = second.plan.selected_pilot_subjects[0].filename
    study.record_reference_calibration_candidate_review(
        second.study_directory,
        candidate_id="deformation-retained",
        approved=False,
        reviewed_subjects=(name,),
        subject_decisions={name: "fail"},
        display_scopes={name: "preview"},
    )
    with pytest.raises(study.ReferenceCalibrationStudyError, match="recorded visual QC"):
        keep_previous_fit(second.study_directory)


def test_source_approval_withdrawal_and_false_parameter_labels_block_reuse(tmp_path, monkeypatch):
    import copy

    from diffeoforge.reference_stage_retention import verify_reference

    _, _, accepted, second = _second_stage(tmp_path, monkeypatch)
    event = next(
        e for e in study._load_events(second.study_directory) if e["event"] == "stage_retained"
    )
    changed = copy.deepcopy(event)
    changed["candidate"]["parameter_values"]["noise_std"] *= 2
    with pytest.raises(study.ReferenceCalibrationStudyError, match="approved evidence"):
        verify_reference(second.study_directory, changed)
    study._append_event(
        second.study_directory,
        "candidate_visual_review",
        dict(
            stage_id="attachment",
            candidate_id=accepted.candidate_id,
            approved=False,
            reviewed_subjects=[second.plan.selected_pilot_subjects[0].filename],
            source=study._candidate_review_binding(accepted),
        ),
    )
    with pytest.raises(study.ReferenceCalibrationStudyError, match="withdrawn"):
        keep_previous_fit(second.study_directory)


def test_retained_stages_complete_with_real_numerical_review_and_no_exported_pilot_field(
    tmp_path, monkeypatch
):
    runner, _, _, second = _second_stage(tmp_path, monkeypatch)
    third = keep_previous_fit(second.study_directory)
    fourth = keep_previous_fit(third.study_directory)
    fourth = runner.run_current_stage()
    assert fourth.current_stage.order == 4
    cid = fourth.candidates[0].candidate_id
    _approve_for_test(fourth.study_directory, cid)
    final, _ = study.record_reference_calibration_stage_review(
        fourth.study_directory, selected_candidate_id=cid, visual_approvals={}
    )
    assert final.status == "completed"
    config = load_config(final.final_config_path)
    inputs = validate_input_paths(config, final.final_config_path)
    assert inputs.initial_control_points is not None and inputs.initial_momenta is None
    assert "selected-seed" in str(inputs.template)
    assert final.selected_candidate_ids["noise"] == "noise-retained"
    assert study.load_reference_calibration_study(final.study_directory).plan == final.plan


def test_keep_button_dispatches_only_retention_worker_and_hides_for_numerical_stage(
    tmp_path, monkeypatch
):
    from PySide6.QtWidgets import QApplication

    from diffeoforge.desktop.reference_calibration_dialog import (
        ReferenceCalibrationDialog,
        _CalibrationStageWorker,
    )

    application = QApplication.instance() or QApplication([])
    runner, _, _, second = _second_stage(tmp_path, monkeypatch)
    dialog = ReferenceCalibrationDialog(second.study_directory)
    assert not dialog.keep_previous_button.isHidden()
    assert dialog.keep_previous_button.text() == "Keep approved stage 1 fit → stage 3"
    starts = []
    monkeypatch.setattr(dialog, "_start_pilot", lambda **kwargs: starts.append(kwargs))
    dialog.keep_previous_button.click()
    assert starts == [dict(adaptive=False, retain_previous=True)]

    def forbidden(*args, **kwargs):
        pytest.fail("Retention worker must not run an optimizer")

    monkeypatch.setattr(runner, "run_current_stage", forbidden)
    worker = _CalibrationStageWorker(runner, retain_previous=True)
    worker.run()
    assert worker.error_message is None and worker.is_finished
    third = study.load_reference_calibration_study(second.study_directory)
    fourth = keep_previous_fit(third.study_directory)
    dialog._render()
    assert dialog.keep_previous_button.isHidden()
    assert fourth.current_stage.order == 4
    dialog.close()
    application.processEvents()
