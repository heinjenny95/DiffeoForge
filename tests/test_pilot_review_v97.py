import json
import time
from dataclasses import replace

import pytest
from test_reference_adaptive_calibration import setup_search
from test_reference_calibration_dialog import _model
from test_reference_calibration_study import _review_ready_stage

import diffeoforge.reference_calibration_study as study
from diffeoforge.config import load_config, validate_input_paths


def test_preview_review_during_stage_is_persistent_without_mutating_engine_ledger(
    tmp_path, monkeypatch
):
    runner, snapshot = _review_ready_stage(tmp_path, monkeypatch)
    # Keep only the first completion; the remaining candidates are still pending.
    # The event chain is rewritten only in this isolated synthetic fixture.
    events_path = runner.study_directory / study.STUDY_EVENTS
    candidate = snapshot.candidates[0]
    rows = [json.loads(line) for line in events_path.read_text().splitlines()]
    rows = [
        row
        for row in rows
        if row["event"] != "stage_awaiting_review"
        and (not row.get("candidate_id") or row["candidate_id"] == candidate.candidate_id)
    ]
    previous = None
    for sequence, row in enumerate(rows):
        row.pop("event_hash")
        row["sequence"] = sequence
        row["previous_hash"] = previous
        row["event_hash"] = study._canonical_hash(row)
        previous = row["event_hash"]
    events_path.write_text("\n".join(study._canonical_json(row) for row in rows) + "\n")
    pending = study.load_reference_calibration_study(runner.study_directory)
    assert any(c.status == "pending" for c in pending.candidates)
    before = events_path.read_bytes()
    subjects = tuple(s.filename for s in snapshot.plan.selected_pilot_subjects)
    saved = study.record_reference_calibration_candidate_review(
        runner.study_directory,
        candidate_id=candidate.candidate_id,
        approved=True,
        reviewed_subjects=subjects,
        subject_decisions=dict.fromkeys(subjects, "pass"),
        display_scopes=dict.fromkeys(subjects, "preview"),
    )
    assert saved.visual_reviews[candidate.candidate_id] is True
    assert events_path.read_bytes() == before
    assert (
        study.load_reference_calibration_study(runner.study_directory).visual_reviews
        == saved.visual_reviews
    )
    journal = runner.study_directory / "visual-reviews.json"
    data = json.loads(journal.read_text())
    data["records"][0]["approved"] = False
    journal.write_text(json.dumps(data))
    with pytest.raises(study.ReferenceCalibrationStudyError, match="journal chain"):
        study.load_reference_calibration_study(runner.study_directory)


def test_selected_capped_fit_continues_alone_with_same_state_and_settings(tmp_path, monkeypatch):
    import diffeoforge.reference_adaptive_calibration as adaptive

    runner, source = setup_search(tmp_path, monkeypatch)
    events = runner.study_directory / study.STUDY_EVENTS
    rows = [json.loads(line) for line in events.read_text().splitlines()]
    cid = source.candidates[-1].candidate_id
    previous = None
    for row in rows:
        if row["event"] == "candidate_completed" and row["candidate_id"] == cid:
            row["metrics"].update(converged=False, optimizer_stop_signal="maximum_iterations")
        row.pop("event_hash")
        row["previous_hash"] = previous
        row["event_hash"] = study._canonical_hash(row)
        previous = row["event_hash"]
    events.write_text("\n".join(study._canonical_json(r) for r in rows) + "\n")
    source = study.load_reference_calibration_study(runner.study_directory)
    before = events.read_bytes()
    child = adaptive.create_selected_continuation(
        runner.study_directory,
        tmp_path / "continued",
        candidate_id=cid,
        iterations=777,
    )
    pending = [c for c in child.candidates if c.status == "pending"]
    assert len(pending) == 1
    assert len(child.candidates) == len(source.candidates) + 1
    config = load_config(pending[0].config_path)
    original = load_config(next(c.config_path for c in source.candidates if c.candidate_id == cid))
    assert config["optimization"] == {**original["optimization"], "max_iterations": 777}
    for name in ("attachment", "noise_std"):
        assert config["model"][name] == original["model"][name]
    inputs = validate_input_paths(config, pending[0].config_path)
    assert inputs.initial_momenta and inputs.initial_control_points
    assert events.read_bytes() == before
    assert not child.visual_reviews  # A warm continuation needs its own review.
    reopened = study.load_reference_calibration_study(child.study_directory)
    assert len([c for c in reopened.candidates if c.status == "pending"]) == 1


def test_one_bulk_approval_from_previews_without_individual_dropdown_actions(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from diffeoforge.desktop.reference_calibration_dialog import (
        CalibrationCandidateViewerDialog,
        CalibrationQcPair,
    )

    application = QApplication.instance() or QApplication([])
    pairs = tuple(
        CalibrationQcPair(
            str(i),
            str(i),
            tmp_path / f"{i}.vtk",
            tmp_path / f"{i}-reco.vtk",
            True,
        )
        for i in range(2)
    )
    candidate = study.CalibrationStudyCandidateState(
        "test", "test", "completed", tmp_path / "c", tmp_path / "run", {}, None, 1
    )
    monkeypatch.setattr(
        "diffeoforge.desktop.pilot_preview.load_pilot_preview",
        lambda p, **kw: replace(_model(p), geometry_is_proxy=True, source_triangle_count=9000),
    )
    dialog = CalibrationCandidateViewerDialog(tmp_path, candidate, pairs=pairs)
    dialog.show()

    def wait():
        deadline = time.monotonic() + 10
        while not dialog.canvas.comparison_ready and time.monotonic() < deadline:
            application.processEvents()
            time.sleep(0.005)
        assert dialog.canvas.comparison_ready and not dialog.canvas.full_resolution_ready

    wait()
    assert dialog.fail_button.isEnabled() and not dialog.complete_button.isEnabled()
    assert not dialog.subject_decisions
    dialog.next_specimen_button.click()
    wait()
    assert dialog.complete_button.isEnabled() and not dialog.subject_decisions
    dialog.complete_button.click()
    assert dialog.review_passed
    assert set(dialog.subject_decisions.values()) == {"pass"}
    assert set(dialog.display_scopes.values()) == {"preview"}
    dialog.close()


def test_finished_candidate_can_be_prepared_without_blocking_gui_during_pilot(
    tmp_path, monkeypatch
):
    import threading

    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    import diffeoforge.desktop.reference_calibration_dialog as dialogs

    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    application = QApplication.instance() or QApplication([])
    runner, snapshot = _review_ready_stage(tmp_path, monkeypatch)
    dialog = dialogs.ReferenceCalibrationDialog(runner.study_directory)
    assert not dialog.adaptive_fit_search.isChecked()
    dialog._worker = object()
    dialog._render(snapshot)
    candidate = snapshot.candidates[0]
    assert dialog._review_buttons[candidate.candidate_id].isEnabled()
    release = threading.Event()
    prepared = []

    def collect(*args):
        assert release.wait(5)
        return ()

    monkeypatch.setattr(dialogs, "collect_calibration_qc_pairs", collect)
    dialog._viewer_preparation.loaded.disconnect()
    dialog._viewer_preparation.loaded.connect(lambda *args: prepared.append(args))
    QTimer.singleShot(40, release.set)
    dialog._open_candidate(candidate)
    deadline = time.monotonic() + 5
    while not prepared and time.monotonic() < deadline:
        application.processEvents()
        time.sleep(0.005)
    assert prepared and release.is_set()
    dialog._worker = None
    dialog.close()


def test_review_journal_survives_successor_and_retains_display_scope(tmp_path, monkeypatch):
    import diffeoforge.reference_adaptive_calibration as adaptive

    runner, source = setup_search(tmp_path, monkeypatch)
    candidate = source.candidates[0]
    name = source.plan.selected_pilot_subjects[0].filename
    saved = study.record_reference_calibration_candidate_review(
        runner.study_directory,
        candidate_id=candidate.candidate_id,
        approved=False,
        reviewed_subjects=(name,),
        subject_decisions={name: "fail"},
        display_scopes={name: "preview"},
    )
    before = (runner.study_directory / study.STUDY_EVENTS).read_bytes()
    child = adaptive.create_selected_continuation(
        runner.study_directory,
        tmp_path / "successor",
        candidate_id=candidate.candidate_id,
        iterations=123,
    )
    assert child.visual_reviews == saved.visual_reviews
    assert child.visual_display_scopes[candidate.candidate_id] == {name: "preview"}
    assert (runner.study_directory / study.STUDY_EVENTS).read_bytes() == before
    assert (
        study.load_reference_calibration_study(child.study_directory).visual_reviews
        == child.visual_reviews
    )
