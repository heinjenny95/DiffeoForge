from pathlib import Path

import pytest
from test_reference_calibration_study import _approve_for_test, _review_ready_stage
from test_reference_sequential_fit import _measured, _reject

from diffeoforge import reference_calibration_study as study
from diffeoforge import reference_fit_search as search
from diffeoforge import reference_sequential_fit as sequence


def test_plan_b_survives_later_rejection_restore_and_requires_new_approval(tmp_path, monkeypatch):
    runner, _ = _review_ready_stage(tmp_path, monkeypatch)
    monkeypatch.setattr(search, "measure_original_fit", _measured)
    first = sequence.run_specimen_sequence(runner)
    cid = first.candidates[0].candidate_id
    _approve_for_test(first.study_directory, cid)
    current = sequence.run_specimen_sequence(runner, action=("advance", cid, 0))
    root = Path(sequence.sequence_info(current.study_directory)["root"])
    prior_approvals = sequence._read(root)["approved"]
    # Even an already recorded pass is not automatically reusable after restoration.
    _approve_for_test(current.study_directory, cid)
    later = sequence.run_specimen_sequence(runner, action=("maybe", cid, 0))
    assert later.study_directory != current.study_directory
    assert sequence._read(root)["approved"] == prior_approvals
    assert sequence.sequence_progress(later.study_directory)["approved"] == 1
    assert sequence.sequence_progress(later.study_directory)["remaining"] == 2
    _reject(later)
    latest = sequence.run_specimen_sequence(runner, action=("reject", cid, 0))
    retained = sequence._read(root)
    monkeypatch.setattr(search, "run_fit_search", lambda *a, **k: pytest.fail("Restore ran a fit"))
    restored = sequence.run_specimen_sequence(runner, action=("restore", "", 0))
    assert restored.study_directory == current.study_directory
    state = sequence._read(root)
    assert state["trials"] == retained["trials"]
    assert state["creation_count"] == retained["creation_count"]
    assert latest.study_directory.exists()
    assert sequence.sequence_progress(restored.study_directory)["fresh_review_required"]
    study._append_event(restored.study_directory, "unrelated_progress", {"message": "No QC"})
    assert sequence.sequence_progress(restored.study_directory)["fresh_review_required"]
    with pytest.raises(ValueError, match="explicitly approve"):
        sequence.run_specimen_sequence(runner, action=("advance", cid, 0))
    _approve_for_test(restored.study_directory, cid)
    assert not sequence.sequence_progress(restored.study_directory)["fresh_review_required"]


def test_maybe_does_not_record_qc_and_fallback_survives_failed_preparation(tmp_path, monkeypatch):
    runner, _ = _review_ready_stage(tmp_path, monkeypatch)
    monkeypatch.setattr(search, "measure_original_fit", _measured)
    first = sequence.run_specimen_sequence(runner)
    root = Path(sequence.sequence_info(first.study_directory)["root"])
    monkeypatch.setattr(
        sequence,
        "_make_child",
        lambda *a, **k: (_ for _ in ()).throw(ValueError("Preparation failed")),
    )
    with pytest.raises(ValueError, match="Preparation failed"):
        sequence.run_specimen_sequence(
            runner, action=("maybe", first.candidates[0].candidate_id, 0)
        )
    state = sequence._read(root)
    assert state["fallbacks"]["0"]["study"] == first.study_directory.name
    assert not state["approved"]
    assert not study.load_reference_calibration_study(first.study_directory).visual_reviews
    assert not (root / "specimen-sequence-active.lock").exists()
    state["fallbacks"]["0"]["basis"]["deformation_kernel_width"] *= 2
    sequence._save(root, state)
    with pytest.raises(ValueError, match="Plan B identity"):
        sequence._read(root)


@pytest.mark.parametrize("error", [StopIteration(), KeyError("missing"), IndexError("index")])
def test_unexpected_worker_failure_always_releases_controller_and_close(monkeypatch, error):
    from types import SimpleNamespace

    from diffeoforge import reference_sequential_fit
    from diffeoforge.desktop.reference_calibration_dialog import _CalibrationStageWorker

    runner = SimpleNamespace(study_directory=Path("synthetic"))

    def fail(*a, **k):
        raise error

    monkeypatch.setattr(reference_sequential_fit, "run_specimen_sequence", fail)
    worker = _CalibrationStageWorker(runner, specimen_fit=True)
    failures, finished = [], []
    worker.signals.failed.connect(failures.append)
    worker.signals.finished.connect(finished.append)
    worker.run()
    assert failures and type(error).__name__ in failures[0]
    assert finished == [worker]
    assert worker.is_finished and not worker.request_cancel()


def test_blank_improve_choice_uses_single_completed_fit_and_finished_worker_can_close(
    tmp_path, monkeypatch
):
    from PySide6.QtWidgets import QApplication, QLabel

    from diffeoforge.desktop.reference_calibration_dialog import (
        ReferenceCalibrationDialog,
        _CalibrationStageWorker,
    )

    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    runner, _ = _review_ready_stage(tmp_path, monkeypatch)
    monkeypatch.setattr(search, "measure_original_fit", _measured)
    first = sequence.run_specimen_sequence(runner)
    dialog = ReferenceCalibrationDialog(first.study_directory)
    calls = []
    monkeypatch.setattr(dialog, "_start_pilot", lambda **kw: calls.append(kw))
    dialog.selection_combo.setCurrentIndex(0)
    dialog._find_fit()
    assert calls[-1]["specimen_action"] == ("improve", "fit-specimen", 0)
    assert any("0 of 3 approved" in label.text() for label in dialog.findChildren(QLabel))
    assert not any("Stage 1 of 4" in label.text() for label in dialog.findChildren(QLabel))
    worker = _CalibrationStageWorker(runner)
    worker._finished = True
    dialog._worker = worker
    # A delayed completion from another worker must not release an active worker.
    active = _CalibrationStageWorker(runner)
    dialog._worker = active
    dialog._worker_finished(worker)
    assert dialog._worker is active
    dialog._worker = worker
    dialog.show()
    assert dialog.close()
    assert dialog._worker is None
    app.processEvents()


def test_plan_b_and_read_only_comparison_never_record_approval(tmp_path, monkeypatch):
    import time
    from dataclasses import replace

    from PySide6.QtWidgets import QApplication, QDialog
    from test_reference_calibration_dialog import _model

    from diffeoforge.desktop.reference_calibration_dialog import (
        CalibrationCandidateViewerDialog,
        CalibrationQcPair,
    )

    app = QApplication.instance() or QApplication([])
    candidate = study.CalibrationStudyCandidateState(
        "test", "test", "completed", tmp_path / "c", tmp_path / "run", {}, None, 1
    )
    monkeypatch.setattr(
        "diffeoforge.desktop.pilot_preview.load_pilot_preview",
        lambda p, **kw: replace(_model(p), geometry_is_proxy=True, source_triangle_count=9000),
    )
    for read_only in (False, True):
        pair = CalibrationQcPair("1", "1", tmp_path / "a.vtk", tmp_path / "b.vtk", not read_only)
        dialog = CalibrationCandidateViewerDialog(
            tmp_path, candidate, pairs=(pair,), allow_plan_b=True, read_only=read_only
        )
        dialog.show()
        deadline = time.monotonic() + 10
        while not dialog.canvas.comparison_ready and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.005)
        assert dialog.canvas.comparison_ready
        if read_only:
            assert not dialog.decision_panel.isVisible()
            assert not dialog.maybe_button.isVisible()
            dialog.close_button.click()
        else:
            assert dialog.maybe_button.isEnabled()
            dialog.maybe_button.click()
            assert dialog.result() == QDialog.DialogCode.Accepted
            assert dialog.keep_as_plan_b
        assert not dialog.review_recorded and not dialog.review_passed
        assert not dialog.subject_decisions
        dialog.close()
