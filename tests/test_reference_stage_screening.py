from pathlib import Path

import pytest
from test_reference_calibration_study import _approve_for_test
from test_reference_stage_retention import _second_stage

from diffeoforge import reference_calibration_study as study
from diffeoforge import reference_stage_screening as screening
from diffeoforge.config import load_config, validate_input_paths
from diffeoforge.reference_pca import read_deformetrica_momenta
from diffeoforge.reference_stage_retention import keep_previous_fit


def _review_screen(snapshot, approved):
    child = snapshot.study_directory / snapshot.early_screening["current_child"]
    probe = study.load_reference_calibration_study(child)
    cid = probe.candidates[0].candidate_id
    if approved:
        _approve_for_test(child, cid)
    else:
        names = tuple(s.filename for s in probe.plan.selected_pilot_subjects)
        study.record_reference_calibration_candidate_review(
            child, candidate_id=cid, approved=False, reviewed_subjects=names,
            subject_decisions={n: "fail" for n in names},
            display_scopes={n: "preview" for n in names},
        )
    return screening.record_screen_review(snapshot.study_directory, child)


def test_one_screen_waits_for_review_without_joint_approval_or_rerun(tmp_path, monkeypatch):
    runner, _, _, second = _second_stage(tmp_path, monkeypatch)
    name = second.plan.selected_pilot_subjects[-1].filename
    result = screening.run_next_screen(runner, subjects=(name,))
    assert all(c.attempts == 0 for c in result.candidates)
    child = study.load_reference_calibration_study(
        result.study_directory / result.early_screening["current_child"]
    )
    assert child.plan.pilot_subject_count == 1
    config = load_config(child.candidates[0].config_path)
    assert config["optimization"]["freeze_template"] is True
    assert config["optimization"]["freeze_control_points"] is True
    inputs = validate_input_paths(config, child.candidates[0].config_path)
    assert [p.name for p in inputs.subjects] == [name]
    if inputs.initial_momenta:
        assert read_deformetrica_momenta(inputs.initial_momenta, allow_singleton=True).shape[0] == 1
        assert config["model"]["deformation"]["initial_momenta_subjects"] == [name]
    again = screening.run_next_screen(runner)
    assert again.early_screening["current_child"] == result.early_screening["current_child"]
    assert study.load_reference_calibration_study(child.study_directory).candidates[0].attempts == 1
    with pytest.raises(ValueError, match="Review the early screens"):
        runner.run_current_stage()
    passed = _review_screen(result, True)
    assert passed.early_screening["kept"] == [second.candidates[0].candidate_id]
    assert passed.visual_reviews == {"deformation-retained": True}


def test_rejected_options_are_not_run_jointly_and_kept_fit_requires_fresh_qc(tmp_path, monkeypatch):
    runner, _, accepted, second = _second_stage(tmp_path, monkeypatch)
    name = second.plan.selected_pilot_subjects[0].filename
    result = screening.run_next_screen(runner, subjects=(name,))
    first = result.early_screening["next_candidate"]
    result = _review_screen(result, True)
    while not result.early_screening["complete"]:
        result = screening.run_next_screen(runner)
        result = _review_screen(result, False)
    reopened = study.load_reference_calibration_study(second.study_directory)
    assert reopened.early_screening == result.early_screening
    assert len(reopened.early_screening["rejected"]) == len(second.candidates) - 2
    joint = runner.run_current_stage()
    assert joint.status == "awaiting_review"
    kept = next(c for c in joint.candidates if c.candidate_id == first)
    assert kept.attempts == 1
    assert first not in joint.visual_reviews
    assert all(c.attempts == 0 for c in joint.candidates if c.status == "screened_out")
    baseline = next(c for c in joint.candidates if c.candidate_id.endswith("-retained"))
    assert study.calibration_candidate_run_directory(baseline) == accepted.run_directory
    with pytest.raises(study.ReferenceCalibrationStudyError, match="Every pilot specimen"):
        study.record_reference_calibration_stage_review(
            joint.study_directory, visual_approvals={}, selected_candidate_id=first,
        )


def test_all_rejected_can_keep_baseline_and_stage_four_is_never_screened(tmp_path, monkeypatch):
    runner, _, _, second = _second_stage(tmp_path, monkeypatch)
    name = second.plan.selected_pilot_subjects[0].filename
    result = screening.run_next_screen(runner, subjects=(name,))
    while True:
        result = _review_screen(result, False)
        if result.early_screening["complete"]:
            break
        result = screening.run_next_screen(runner)
    third = keep_previous_fit(second.study_directory)
    assert third.current_stage.order == 3 and not third.early_screening
    fourth = keep_previous_fit(second.study_directory)
    assert fourth.current_stage.order == 4 and not fourth.early_screening
    with pytest.raises(ValueError, match="stages 2 and 3"):
        screening.start_screening(fourth, (name,))
    completed = runner.run_current_stage()
    assert all(c.attempts == 1 for c in completed.candidates)
    assert all(load_config(c.config_path)["input"]["directory"] for c in completed.candidates)
    assert completed.plan.pilot_subject_count == second.plan.pilot_subject_count


def test_second_specimen_rejection_discards_whole_option(tmp_path, monkeypatch):
    runner, _, _, second = _second_stage(tmp_path, monkeypatch)
    names = tuple(s.filename for s in second.plan.selected_pilot_subjects[:2])
    result = screening.run_next_screen(runner, subjects=names)
    cid = result.early_screening["next_candidate"]
    result = _review_screen(result, True)
    assert result.early_screening["next_candidate"] == cid
    assert result.early_screening["next_subject"] == names[1]
    result = screening.run_next_screen(runner)
    result = _review_screen(result, False)
    assert cid in result.early_screening["rejected"]
    assert result.early_screening["next_candidate"] != cid


def test_modified_probe_receipt_or_reference_blocks_saved_decision(tmp_path, monkeypatch):
    runner, _, _, second = _second_stage(tmp_path, monkeypatch)
    result = screening.run_next_screen(
        runner, subjects=(second.plan.selected_pilot_subjects[0].filename,)
    )
    child = result.study_directory / result.early_screening["current_child"]
    result = _review_screen(result, True)
    probe = study.load_reference_calibration_study(child)
    (probe.candidates[0].run_directory / "result.json").write_text("changed", encoding="utf-8")
    with pytest.raises((ValueError, study.ReferenceCalibrationStudyError), match="evidence|review"):
        study.load_reference_calibration_study(second.study_directory)


def test_invalid_selector_and_stale_review_are_rejected(tmp_path, monkeypatch):
    runner, _, _, second = _second_stage(tmp_path, monkeypatch)
    name = second.plan.selected_pilot_subjects[0].filename
    for names in ((), (name, name), ("not-in-cohort.vtk",)):
        with pytest.raises(ValueError, match="specimens"):
            screening.start_screening(second, names)
    result = screening.run_next_screen(runner, subjects=(name,))
    with pytest.raises(ValueError, match="stale"):
        screening.record_screen_review(result.study_directory, Path(tmp_path))


def test_technical_failure_excludes_option_without_inventing_visual_review(tmp_path, monkeypatch):
    runner, _, _, second = _second_stage(tmp_path, monkeypatch)

    class Failed:
        def __init__(self, request):
            pass

        def run(self, **kwargs):
            raise RuntimeError("synthetic engine failure")

    runner._controller_factory = Failed
    result = screening.run_next_screen(
        runner, subjects=(second.plan.selected_pilot_subjects[0].filename,)
    )
    cid = second.candidates[0].candidate_id
    assert result.early_screening["technical_failures"] == [cid]
    assert cid in result.early_screening["rejected"]
    assert cid not in result.visual_reviews
    assert result.early_screening["next_candidate"] != cid


def test_cancel_preserves_queue_and_targets_active_child(tmp_path, monkeypatch):
    from types import SimpleNamespace

    runner, _, _, second = _second_stage(tmp_path, monkeypatch)
    calls = []

    class Cancelled:
        def __init__(self, request):
            pass

        def request_cancel(self):
            calls.append("cancelled")

        def run(self, **kwargs):
            assert runner.request_cancel()
            return SimpleNamespace(completed=False)

    runner._controller_factory = Cancelled
    result = screening.run_next_screen(
        runner, subjects=(second.plan.selected_pilot_subjects[0].filename,)
    )
    assert calls == ["cancelled"]
    assert result.early_screening["current_status"] == "interrupted"
    assert not result.early_screening["rejected"]
    assert not result.early_screening["kept"]
    assert runner._active_controller is None
