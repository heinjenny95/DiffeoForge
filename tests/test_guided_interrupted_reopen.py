"""Replay interrupted method comparisons through the normal saved-pilot window."""

from types import SimpleNamespace

import pytest
from pilot_view_helpers import wait_pilot_view
from test_guided_pilot import run_batch
from test_pilot_dead_end_journeys import dialog_for
from test_pilot_shared_first import new_pilot
from test_reference_calibration_study import _CompletedController

from diffeoforge import pilot_form_progress
from diffeoforge import reference_calibration_study as study
from diffeoforge import reference_guided_pilot as guided


class InterruptVarifold(_CompletedController):
    def run(self, *, event_callback=None):
        if "guided-varifold" in self.request.config_path.parts:
            self.request.destination.mkdir(parents=True)
            return SimpleNamespace(completed=False)
        return super().run(event_callback=event_callback)


def stopped_comparison(tmp_path, monkeypatch):
    first = run_batch(new_pilot(tmp_path), monkeypatch, controller=InterruptVarifold)
    assert [(c.candidate_id, c.status) for c in first.candidates] == [
        ("guided-current", "completed"), ("guided-varifold", "interrupted")
    ]
    return first


def test_reopened_stopped_comparison_can_advance_with_approved_method(tmp_path, monkeypatch):
    first = stopped_comparison(tmp_path, monkeypatch)
    target = guided.record(first)["target"]
    first = study.record_reference_calibration_candidate_review(
        first.study_directory, candidate_id="guided-current", approved=True,
        reviewed_subjects=(target,), subject_decisions={target: "pass"},
        display_scopes={target: "preview"},
    )
    app, dialog = dialog_for(first, monkeypatch)
    try:
        assert "failed" not in dialog.status.text().lower()
        assert dialog.next_step_button.isVisible() and dialog.next_step_button.isEnabled()
        assert dialog.next_step_button.objectName() == "primary"
        assert dialog.start_button.objectName() != "primary"
        monkeypatch.setattr(study.ReferenceCalibrationStudyRunner, "run_current_stage",
                            lambda *a, **kw: pytest.fail("Next started a numerical run"))
        queued = []
        monkeypatch.setattr(dialog._thread_pool, "start", queued.append)
        dialog.next_step_button.click()
        assert len(queued) == 1
        queued[0].run()
        wait_pilot_view(dialog, timeout=40)
        child = dialog.snapshot
        assert child.study_directory != first.study_directory
        assert guided.record(child)["target"] != guided.record(first)["target"]
        source = guided._approved_record(first, "guided-current")
        assert pilot_form_progress.marker(child)["reviews"] == [source]
        assert not child.visual_reviews and not any(c.attempts for c in child.candidates)
        saved = study.load_reference_calibration_study(first.study_directory)
        assert saved.visual_reviews == {"guided-current": True}
        assert [c.attempts for c in saved.candidates] == [1, 1]
    finally:
        dialog._worker = None
        dialog.close()
        app.processEvents()


def test_reopen_unfinished_retry_uses_latest_attempt_and_refreshes_without_dispatch(
        tmp_path, monkeypatch):
    from PySide6.QtWidgets import QLabel, QPushButton

    first = stopped_comparison(tmp_path, monkeypatch)
    completed, stopped = first.candidates
    # Reproduce a second attempt whose owning window has not yet written its
    # terminal event. A missing event cannot distinguish a live run from a crash.
    root = first.study_directory
    second = stopped.run_directory.parent / "pilot-attempt-02"
    second.mkdir()
    latest = dict(stage_id=first.current_stage.stage_id, candidate_id=stopped.candidate_id,
                  attempt=2, run_directory=second.relative_to(root).as_posix())
    study._append_event(root, "candidate_started", dict(latest, request_id="test-attempt-two"))
    lock = root / "method-comparison-active.lock"
    lock.mkdir()
    reopened = study.load_reference_calibration_study(root)
    current = reopened.candidates[1]
    assert reopened.status == "running" and current.status == "orphaned"
    assert current.attempts == 2 and current.run_directory == second
    assert not current.failure and "cancel" not in current.error.lower()
    app, dialog = dialog_for(reopened, monkeypatch)
    try:
        assert "locked" in dialog.status.text().lower()
        path = dialog.content.findChild(QLabel, "unresolvedAttemptPath")
        assert path and path.isVisible() and str(second) in path.text()
        refresh = dialog.content.findChild(QPushButton, "refreshPilotStatus")
        assert refresh and refresh.isVisible() and refresh.isEnabled()
        assert not dialog.start_button.isVisible() and not dialog.next_step_button.isVisible()
        before = (root / "events.jsonl").read_bytes()
        with pytest.raises(study.ReferenceCalibrationStudyError, match="execution lock"):
            run_batch(reopened, monkeypatch)
        assert (root / "events.jsonl").read_bytes() == before
        assert lock.is_dir()
        # The owning worker records a verified stop and releases its own lock.
        study._append_event(root, "candidate_interrupted", dict(latest, error="Stopped by user"))
        lock.rmdir()
        refresh.click()
        wait_pilot_view(dialog, timeout=40)
        latest_state = dialog.snapshot
        current = latest_state.candidates[1]
        assert (current.status, current.run_directory, current.error) == (
            "interrupted", second, "Stopped by user")
        assert dialog.start_button.isVisible() and dialog.start_button.isEnabled()
        assert "retry" in dialog.start_button.text().lower()
        assert "failed" not in dialog.status.text().lower()
        retried = run_batch(latest_state, monkeypatch)
        assert retried.candidates[0].run_directory == completed.run_directory
        assert [c.attempts for c in retried.candidates] == [1, 3]
        assert retried.candidates[1].status == "completed"
        assert stopped.run_directory.is_dir() and second.is_dir()
    finally:
        dialog.close()
        app.processEvents()


def test_past_stage_review_banner_cannot_mask_new_unfinished_attempt(tmp_path, monkeypatch):
    class FailVarifold(_CompletedController):
        def run(self, *, event_callback=None):
            if "guided-varifold" in self.request.config_path.parts:
                raise RuntimeError("Earlier synthetic failure")
            return super().run(event_callback=event_callback)

    first = run_batch(new_pilot(tmp_path), monkeypatch, controller=FailVarifold)
    assert first.status == "awaiting_review" and first.candidates[1].status == "failed"
    subject = first.plan.selected_pilot_subjects[0].filename
    first = study.record_reference_calibration_candidate_review(
        first.study_directory, candidate_id="guided-current", approved=True,
        reviewed_subjects=(subject,), subject_decisions={subject: "pass"},
        display_scopes={subject: "preview"},
    )
    candidate = first.candidates[1]
    root = first.study_directory
    second = candidate.config_path.parent / "runs" / "pilot-attempt-02"
    study._append_event(root, "candidate_started", dict(
        stage_id=first.current_stage.stage_id, candidate_id=candidate.candidate_id,
        attempt=2, run_directory=second.relative_to(root).as_posix(), request_id="retry",
    ))
    reopened = study.load_reference_calibration_study(root)
    assert reopened.status == "running" and reopened.candidates[1].status == "orphaned"
    assert reopened.candidates[1].run_directory == second
    assert reopened.visual_reviews == {"guided-current": True}
    with pytest.raises(ValueError, match="resolve the current batch"):
        guided.next_action(root, "adaptive_next_form", "guided-current")
