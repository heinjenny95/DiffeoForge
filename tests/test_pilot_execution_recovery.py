"""A released pilot can reclaim only its own normally completed native fit."""

import json
import shutil
from types import SimpleNamespace

import pytest
from pilot_view_helpers import wait_pilot_view
from test_pilot_dead_end_journeys import dialog_for
from test_pilot_shared_first import new_pilot
from test_qualification_resume import cancelled_fixture
from test_reference_attachment_comparison import _detail
from test_reference_calibration_study import _metrics

from diffeoforge import pilot_execution_recovery as recovery
from diffeoforge import reference_calibration_study as study
from diffeoforge import reference_guided_pilot as guided
from diffeoforge.mesh import sha256_file
from diffeoforge.reference_qualification_resume import FILES, pending


def interrupted_after_native(tmp_path, monkeypatch):
    source = tmp_path / "native"
    source.mkdir()
    _, original, _ = cancelled_fixture(source, monkeypatch)
    project = tmp_path / "guided"
    project.mkdir()
    pilot = new_pilot(project)
    candidate = pilot.candidates[0]
    root = pilot.study_directory
    run = candidate.config_path.parent / "runs" / "pilot-attempt-01"
    with pytest.raises(RuntimeError, match="lost worker"), recovery.writer(root):
        study._append_event(root, "candidate_started", dict(
            stage_id=pilot.current_stage.stage_id, candidate_id=candidate.candidate_id,
            attempt=1, run_directory=run.relative_to(root).as_posix(), request_id="native-a",
        ))
        shutil.copytree(original.run_directory, run)
        manifest = json.loads((run / "manifest.json").read_text())
        manifest["source_config"]["sha256"] = sha256_file(candidate.config_path)
        (run / "manifest.json").write_text(json.dumps(manifest))
        (run / "manifest.sha256").write_text(sha256_file(run / "manifest.json"))
        live = study.load_reference_calibration_study(root)
        assert recovery.inspect(live) is None
        with pytest.raises(ValueError, match="execution lock"):
            recovery.recover(root, {})
        raise RuntimeError("lost worker")
    saved = study.load_reference_calibration_study(root)
    offer = recovery.inspect(saved)
    assert offer and offer["candidate"] == candidate.candidate_id
    return saved, run, offer


def test_explicit_saved_fit_recovery_uses_no_controller_and_is_replayable(tmp_path, monkeypatch):
    saved, run, offer = interrupted_after_native(tmp_path, monkeypatch)
    root = saved.study_directory
    native_before = {name: sha256_file(run / name) for name in FILES}
    before = (root / "events.jsonl").read_bytes()
    app, dialog = dialog_for(saved, monkeypatch)
    try:
        assert dialog.next_step_button.isVisible()
        assert dialog.next_step_button.text() == "Recover saved fit for surface checks"
        assert not dialog.start_button.isVisible()
        assert before == (root / "events.jsonl").read_bytes()
        with monkeypatch.context() as guarded:
            guarded.setattr(study.ReferenceCalibrationStudyRunner, "run_current_stage",
                            lambda *a, **kw: pytest.fail("Recovery started a fit"))
            queued = []
            guarded.setattr(dialog._thread_pool, "start", queued.append)
            dialog.next_step_button.click()
            assert len(queued) == 1
            queued[0].run()
            wait_pilot_view(dialog, timeout=40)
        after = dialog.snapshot
        assert after.candidates[0].status == "interrupted" and not after.visual_reviews
        assert offer["candidate"] in pending(after)
        assert not (root / recovery.LOCK).exists()
        assert after.event_count == saved.event_count + 1
        assert dialog.next_step_button.text() == "Resume surface checks on recovered fit"
        assert not dialog.start_button.isVisible()
        again = guided.next_action(root, "recover_saved_native_fit", offer["candidate"], goal=offer)
        assert again.event_count == after.event_count
        assert (root / "events.jsonl").read_bytes().startswith(before)
        assert [c.attempts for c in again.candidates] == [1, 0]
        from diffeoforge import reference_attachment_comparison as methods
        from diffeoforge import result_report

        monkeypatch.setattr(result_report, "collect_run_report", lambda *_: SimpleNamespace(
            result=dict(status="completed", return_code=0),
            checks=[SimpleNamespace(status="pass")]))
        monkeypatch.setattr(study, "collect_reference_calibration_run_metrics",
                            lambda _: _metrics(run / "atlas.vtk"))
        subjects = [s.filename for s in again.plan.selected_pilot_subjects]
        monkeypatch.setattr(methods, "measure", lambda *a, **kw: dict(
            attachment_comparison=_detail(subjects), fit_scope="full_targets",
            original_surface_fit={s: dict(p95=.01, p99=.02, mean=.005, diagonal=1)
                                  for s in subjects}))
        runner = study.ReferenceCalibrationStudyRunner(root, controller_factory=lambda *a:
            pytest.fail("Checking a recovered fit started a native controller"))
        _, identifier, goal = (*dialog._guided_footer_action[1:], dialog._guided_footer_goal)
        checked = recovery.resume_checks(runner, identifier, goal)
        assert checked.candidates[0].status == "completed"
        assert checked.candidates[0].metrics["qualification_resumed_without_fitting"]
        assert checked.candidates[1].attempts == 0 and not checked.visual_reviews
        assert {name: sha256_file(run / name) for name in FILES} == native_before
    finally:
        dialog._worker = None
        dialog.close()
        app.processEvents()


@pytest.mark.parametrize("change", ["native", "missing_shutdown", "owner", "legacy", "newer_start"])
def test_recovery_refuses_changed_binding_and_preserves_lock(tmp_path, monkeypatch, change):
    saved, run, offer = interrupted_after_native(tmp_path, monkeypatch)
    root = saved.study_directory
    marker = root / recovery.LOCK / "owner.json"
    if change == "native":
        with (run / "result.json").open("a") as stream:
            stream.write(" ")
    elif change == "missing_shutdown":
        (run / "logs/backend-control.json").unlink()
    elif change == "owner":
        data = json.loads(marker.read_text())
        data["host"] += "-unverified"
        marker.write_text(json.dumps(data))
    elif change == "legacy":
        marker.unlink()
    else:
        study._append_event(root, "candidate_started", dict(
            stage_id=saved.current_stage.stage_id, candidate_id=offer["candidate"],
            attempt=2, run_directory="other-attempt", request_id="different",
        ))
    journal = (root / "events.jsonl").read_bytes()
    with pytest.raises((OSError, ValueError)):
        recovery.recover(root, offer)
    assert (root / recovery.LOCK).is_dir()
    assert (root / "events.jsonl").read_bytes() == journal


def test_partial_recovery_finishes_once_and_leaves_racing_legacy_lock_in_place(
        tmp_path, monkeypatch):
    saved, _, offer = interrupted_after_native(tmp_path, monkeypatch)
    root = saved.study_directory
    with monkeypatch.context() as interrupted:
        def crash_after_journal(*args):
            raise OSError("lost reply")

        interrupted.setattr(recovery, "_release_marker", crash_after_journal)
        with pytest.raises(OSError, match="lost reply"):
            recovery.recover(root, offer)
    partial = study.load_reference_calibration_study(root)
    assert partial.event_count == saved.event_count + 1
    assert recovery.inspect(partial) == offer
    from pathlib import Path

    rename = Path.rename
    def racing_legacy_writer(path, target):
        moved = rename(path, target)
        if path == root / recovery.LOCK:
            path.mkdir()
        return moved

    monkeypatch.setattr(Path, "rename", racing_legacy_writer)
    finished = recovery.recover(root, offer)
    assert finished.event_count == partial.event_count
    assert (root / recovery.LOCK).is_dir() and not any((root / recovery.LOCK).iterdir())
    with pytest.raises(ValueError, match="no verified pilot writer"):
        recovery.recover(root, offer)


@pytest.mark.parametrize("had_terminal", [False, True])
def test_ordinary_exception_releases_writer_outside_an_unfinished_attempt(tmp_path, had_terminal):
    pilot = new_pilot(tmp_path)
    root = pilot.study_directory
    with pytest.raises(RuntimeError, match="synthetic"), recovery.writer(root):
        if had_terminal:
            attempt = dict(stage_id=pilot.current_stage.stage_id,
                           candidate_id=pilot.candidates[0].candidate_id, attempt=1,
                           run_directory=None)
            study._append_event(root, "candidate_started", dict(attempt, request_id="failed"))
            study._append_event(root, "candidate_failed", dict(attempt, error="checked"))
        raise RuntimeError("synthetic")
    assert not (root / recovery.LOCK).exists()
    with recovery.writer(root):
        assert (root / recovery.LOCK / "owner.json").is_file()
