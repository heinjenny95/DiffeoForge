"""One explicit joint confirmation after multiple preserved screening approvals."""

import pytest
from test_reference_calibration_study import _approve_for_test
from test_reference_stage_retention import _second_stage
from test_reference_stage_screening import _review_screen

from diffeoforge import reference_calibration_study as study
from diffeoforge import reference_stage_screening as screening


def _screen_all(tmp_path, monkeypatch, rejected=()):
    runner, _, accepted, second = _second_stage(tmp_path, monkeypatch)
    name = second.plan.selected_pilot_subjects[0].filename
    result = screening.run_next_screen(runner, subjects=(name,))
    while True:
        result = _review_screen(result, result.early_screening["next_candidate"] not in rejected)
        if result.early_screening["complete"]:
            break
        result = screening.run_next_screen(runner)
    return runner, accepted, result


def test_one_joint_fit_preserves_all_screen_approvals_and_can_advance(tmp_path, monkeypatch):
    runner, baseline, snapshot = _screen_all(tmp_path, monkeypatch)
    before = (snapshot.study_directory / "events.jsonl").read_bytes()
    preserved = {p: p.read_bytes() for p in
                 (snapshot.study_directory / "early-screening").rglob("*") if p.is_file()}
    kept = snapshot.early_screening["kept"]
    chosen = kept[1]
    selected = screening.select_joint_option(snapshot.study_directory, chosen)
    assert selected.early_screening["kept"] == kept
    assert selected.early_screening["rejected"] == []
    assert selected.early_screening["joint_selection"] == chosen
    assert set(selected.early_screening["deferred"]) == set(kept) - {chosen}
    assert study.load_reference_calibration_study(snapshot.study_directory) == selected
    joint = runner.run_current_stage()  # Persistent guard protects even an unfiltered caller.
    assert joint.status == "awaiting_review"
    assert next(c for c in joint.candidates if c.candidate_id == chosen).attempts == 1
    assert all(c.attempts == 0 and c.status == "screen_deferred"
               for c in joint.candidates if c.candidate_id in set(kept) - {chosen})
    assert chosen not in joint.visual_reviews
    assert study.calibration_candidate_run_directory(joint.candidates[-1]) == baseline.run_directory
    with pytest.raises(study.ReferenceCalibrationStudyError, match="Every pilot specimen"):
        study.record_reference_calibration_stage_review(
            joint.study_directory, selected_candidate_id=chosen, visual_approvals={},
        )
    _approve_for_test(joint.study_directory, chosen)
    third, _ = study.record_reference_calibration_stage_review(
        joint.study_directory, selected_candidate_id=chosen, visual_approvals={},
    )
    assert third.current_stage.stage_id == "noise"
    assert (snapshot.study_directory / "events.jsonl").read_bytes().startswith(before)
    assert all(p.read_bytes() == value for p, value in preserved.items())


def test_choice_is_explicit_validated_idempotent_and_locked(tmp_path, monkeypatch):
    runner, _, _, second = _second_stage(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="Review the early screens"):
        screening.select_joint_option(second.study_directory, second.candidates[0].candidate_id)
    snapshot = screening.run_next_screen(
        runner, subjects=(second.plan.selected_pilot_subjects[0].filename,)
    )
    rejected = snapshot.early_screening["next_candidate"]
    snapshot = _review_screen(snapshot, False)
    while not snapshot.early_screening["complete"]:
        snapshot = _review_screen(screening.run_next_screen(runner), True)
    for cid in (rejected, "unknown", "deformation-retained"):
        with pytest.raises(ValueError, match="visually kept"):
            screening.select_joint_option(snapshot.study_directory, cid)
    chosen = snapshot.early_screening["kept"][0]
    selected = screening.select_joint_option(snapshot.study_directory, chosen)
    assert screening.select_joint_option(snapshot.study_directory, chosen).event_count == (
        selected.event_count
    )
    with pytest.raises(ValueError, match="locked"):
        screening.select_joint_option(snapshot.study_directory, snapshot.early_screening["kept"][1])
    joint = runner.run_current_stage()
    assert screening.select_joint_option(snapshot.study_directory, chosen).event_count == (
        joint.event_count
    )


def test_existing_joint_batch_cannot_be_relabelled_as_single_choice(tmp_path, monkeypatch):
    runner, _, snapshot = _screen_all(tmp_path, monkeypatch)
    joint = runner.run_current_stage()
    with pytest.raises(ValueError, match="existing joint attempt"):
        screening.select_joint_option(joint.study_directory, snapshot.early_screening["kept"][0])


def test_choice_rejects_valid_chain_with_stale_review_binding(tmp_path, monkeypatch):
    _, _, snapshot = _screen_all(tmp_path, monkeypatch)
    screening.select_joint_option(snapshot.study_directory, snapshot.early_screening["kept"][0])
    choice = study._load_events(snapshot.study_directory)[-1]
    study._append_event(snapshot.study_directory, choice["event"], dict(
        stage_id=choice["stage_id"], candidate_id=choice["candidate_id"],
        screening_event_hash=choice["screening_event_hash"], review_event_hashes=[],
    ))
    with pytest.raises(ValueError, match="verified screening decisions"):
        study.load_reference_calibration_study(snapshot.study_directory)


def test_worker_ignores_adaptive_mode_and_confirms_only_the_explicit_option(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from diffeoforge.desktop.reference_calibration_dialog import _CalibrationStageWorker

    app = QApplication.instance() or QApplication([])
    runner, _, snapshot = _screen_all(tmp_path, monkeypatch)
    chosen = snapshot.early_screening["kept"][-1]
    worker = _CalibrationStageWorker(runner, screen_joint_choice=chosen, adaptive_fit_search=True)
    outcomes = []
    worker.signals.succeeded.connect(outcomes.append)
    worker.run()
    app.processEvents()
    assert not worker.error_message and len(outcomes) == 1
    assert {c.candidate_id for c in outcomes[0].candidates if c.attempts} == {chosen}
    assert outcomes[0].plan.pilot_subject_count == snapshot.plan.pilot_subject_count


def test_cancel_and_retry_cannot_start_another_kept_option(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from test_reference_calibration_study import _CompletedController

    runner, _, snapshot = _screen_all(tmp_path, monkeypatch)
    chosen = snapshot.early_screening["kept"][0]
    screening.select_joint_option(snapshot.study_directory, chosen)

    class Cancelled:
        def __init__(self, request):
            pass

        def request_cancel(self):
            pass

        def run(self, **kwargs):
            assert runner.request_cancel()
            return SimpleNamespace(completed=False)

    runner._controller_factory = Cancelled
    cancelled = runner.run_current_stage()
    assert {c.candidate_id for c in cancelled.candidates if c.attempts} == {chosen}
    retry = study.ReferenceCalibrationStudyRunner(snapshot.study_directory,
                                                 controller_factory=_CompletedController)
    completed = retry.run_current_stage()
    assert {c.candidate_id for c in completed.candidates if c.attempts} == {chosen}
    assert next(c for c in completed.candidates if c.candidate_id == chosen).attempts == 2
