"""The real pilot presentation must keep the event loop live through slow reads."""

import threading
import time
from dataclasses import replace
from types import SimpleNamespace

import pytest

pytest.importorskip("PySide6")
from pilot_view_helpers import wait_pilot_view
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication


def _wait(app, predicate):
    deadline = time.monotonic() + 10
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.002)
    assert predicate()


def test_slow_presentation_never_blocks_constructor_or_event_loop(monkeypatch, tmp_path):
    from test_reference_calibration_study import _review_ready_stage

    import diffeoforge.desktop.reference_calibration_dialog as module

    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    _, snapshot = _review_ready_stage(tmp_path, monkeypatch)
    prepare = module.prepare_pilot_view
    entered, release = threading.Event(), threading.Event()
    threads, ticks = [], []

    def slow(*args):
        threads.append(threading.get_ident())
        entered.set()
        assert release.wait(5)
        return prepare(*args)

    monkeypatch.setattr(module, "prepare_pilot_view", slow)
    timer = QTimer()
    timer.timeout.connect(lambda: ticks.append(1))
    timer.start(2)
    dialog = module.ReferenceCalibrationDialog(snapshot.study_directory,
                                               verified_snapshot=snapshot)
    try:
        _wait(app, entered.is_set)
        assert dialog._view_loading and not dialog.next_step_button.isEnabled()
        for _ in range(20):
            app.processEvents()
            time.sleep(0.003)
        assert len(ticks) >= 5
        assert threads == [threads[0]] and threading.get_ident() not in threads
    finally:
        release.set()
        timer.stop()
    wait_pilot_view(dialog)
    assert dialog.snapshot is snapshot
    before = len(threads)
    for _ in range(10):
        dialog._render(snapshot)
    assert len(threads) == before  # Display-only redraw reuses the prepared view.
    dialog.close()


def test_latest_view_and_closed_view_discard_stale_delivery(monkeypatch, tmp_path):
    from test_reference_calibration_study import _review_ready_stage

    import diffeoforge.desktop.reference_calibration_dialog as module
    from diffeoforge.desktop.pilot_view_preparation import prepare_pilot_view

    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    _, snapshot = _review_ready_stage(tmp_path, monkeypatch)
    dialog = module.ReferenceCalibrationDialog(snapshot.study_directory,
                                               verified_snapshot=snapshot)
    wait_pilot_view(dialog)
    prepared = prepare_pilot_view(snapshot.study_directory, snapshot)
    old = dialog.snapshot
    dialog.study_directory = tmp_path / "other"
    dialog._view_loaded(snapshot.study_directory, prepared)
    assert dialog.snapshot is old
    dialog.study_directory = snapshot.study_directory
    dialog.close()
    dialog._view_loaded(snapshot.study_directory, replace(prepared, fits={"stale": {}}))
    assert "stale" not in dialog._prepared_view.fits
    app.processEvents()


def test_success_reuses_worker_snapshot_and_comparison_callback_does_no_read(
    monkeypatch, tmp_path,
):
    from test_reference_calibration_study import _review_ready_stage

    import diffeoforge.desktop.reference_calibration_dialog as module

    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    _, snapshot = _review_ready_stage(tmp_path, monkeypatch)
    dialog = module.ReferenceCalibrationDialog(snapshot.study_directory,
                                               verified_snapshot=snapshot)
    wait_pilot_view(dialog)

    def forbidden(*args, **kwargs):
        pytest.fail("A GUI completion callback tried to reload the entire history")

    monkeypatch.setattr(module, "load_reference_calibration_study", forbidden)
    dialog._succeeded(snapshot)
    wait_pilot_view(dialog)
    assert dialog.snapshot is snapshot
    # A delivery for a window that was closed must not read or open any viewer.
    dialog.close()
    monkeypatch.setattr(module, "CalibrationCandidateViewerDialog", forbidden)
    dialog._candidate_prepared(
        (snapshot.study_directory, snapshot.candidates[0]), (snapshot, (), {}),
    )
    app.processEvents()


def test_verification_scope_reuses_within_read_but_next_action_checks_tampering(
    monkeypatch, tmp_path,
):
    from test_reference_calibration_study import _review_ready_stage

    import diffeoforge.reference_calibration_study as study

    runner, _ = _review_ready_stage(tmp_path, monkeypatch)
    read = study._load_verified_calibration_study
    calls = []

    def counted(*args, **kwargs):
        calls.append(args[0])
        return read(*args, **kwargs)

    monkeypatch.setattr(study, "_load_verified_calibration_study", counted)
    with study.calibration_verification_scope():
        first = study.load_reference_calibration_study(runner.study_directory)
        assert study.load_reference_calibration_study(runner.study_directory) is first
    assert calls.count(runner.study_directory) == 1
    manifest = runner.study_directory / "study.json"
    manifest.write_text("{}", encoding="utf-8")
    with pytest.raises(study.ReferenceCalibrationStudyError):
        study.load_reference_calibration_study(runner.study_directory)
    assert calls.count(runner.study_directory) == 2


@pytest.mark.parametrize("fail_save", [False, True])
def test_slow_review_save_keeps_event_loop_live_and_never_fakes_qc(
    monkeypatch, tmp_path, fail_save,
):
    from test_reference_calibration_study import _review_ready_stage

    import diffeoforge.desktop.reference_calibration_dialog as module
    import diffeoforge.reference_calibration_study as study

    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    _, snapshot = _review_ready_stage(tmp_path, monkeypatch)
    candidate = snapshot.candidates[0]
    name = snapshot.plan.selected_pilot_subjects[0].filename
    pair = SimpleNamespace(original_path=tmp_path / name, required=True, pair_id="fixture")
    dialog = module.ReferenceCalibrationDialog(snapshot.study_directory,
                                               verified_snapshot=snapshot)
    wait_pilot_view(dialog)
    before = (snapshot.study_directory / study.STUDY_EVENTS).read_bytes()
    notes = SimpleNamespace(setText=lambda s: None, text=lambda: "Fixture review")

    class Inspection:
        def __init__(self, *args, **kwargs):
            self.anatomical_notes = notes
            self.feature_observations = {}
            self.subject_decisions = {}
            self._pairs = (pair,)
            self._reviewed_pair_ids = set()
            self.display_scopes = {name: "preview"}
            self.mesh_combo = SimpleNamespace(currentData=lambda: None)
            self.review_recorded, self.review_passed = True, False
            self.fit_preferences, self.keep_as_plan_b = None, False

        def _update_review_progress(self):
            pass

        def exec(self):
            self.subject_decisions = {name: "fail"}
            self._reviewed_pair_ids.add("fixture")

    entered, release = threading.Event(), threading.Event()
    threads, warnings = [], []
    real_save = module.record_reference_calibration_candidate_review

    def slow_save(*args, **kwargs):
        threads.append(threading.get_ident())
        entered.set()
        assert release.wait(5)
        if fail_save:
            raise ValueError("Fixture changed evidence")
        return real_save(*args, **kwargs)

    monkeypatch.setattr(module, "CalibrationCandidateViewerDialog", Inspection)
    monkeypatch.setattr(module, "record_reference_calibration_candidate_review", slow_save)
    monkeypatch.setattr(module.QMessageBox, "warning", lambda *a: warnings.append(a[2]))
    monkeypatch.setattr(module.QMessageBox, "information", lambda *a: None)
    dialog._candidate_prepared((snapshot.study_directory, candidate), (snapshot, (pair,), {}))
    try:
        _wait(app, entered.is_set)
        assert dialog._review_saving and not dialog.content.isEnabled()
        dialog.reject()
        assert not dialog._view_closed
        assert candidate.candidate_id not in dialog.snapshot.visual_reviews
        ticks = []
        QTimer.singleShot(0, lambda: ticks.append(1))
        _wait(app, lambda: bool(ticks))
        assert threading.get_ident() not in threads
    finally:
        release.set()
    _wait(app, lambda: not dialog._review_saving)
    wait_pilot_view(dialog)
    assert (snapshot.study_directory / study.STUDY_EVENTS).read_bytes() == before
    if fail_save:
        assert warnings == ["Fixture changed evidence"]
        assert candidate.candidate_id not in dialog.snapshot.visual_reviews
    else:
        assert not warnings
        assert dialog.snapshot.visual_reviews[candidate.candidate_id] is False
    dialog.close()
