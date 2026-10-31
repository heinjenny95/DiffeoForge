"""Actual Qt controls for feedback-only inspection and returning to earlier fits."""

from test_fit_preference_dialog import wait
from test_guided_feedback import attempted, decision
from test_reference_calibration_dialog import _model

from diffeoforge import guided_feedback as feedback
from diffeoforge import guided_strategy as strategy
from diffeoforge import reference_guided_pilot as guided


def test_feedback_widget_never_enables_a_decision_before_geometry(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from diffeoforge.desktop.guided_feedback import GuidedFeedbackControls

    app = QApplication.instance() or QApplication([])
    base, trial = attempted(tmp_path, monkeypatch)
    panel = GuidedFeedbackControls(feedback.presentation(trial, "guided-varifold"))
    panel.show()
    saved = []
    panel.saveRequested.connect(saved.append)
    assert all(not b.isEnabled() for b in panel.outcomes.values())
    panel.set_ready(False)
    panel.outcomes["worse"].click()
    assert panel.decision is None and not panel.save.isEnabled()
    panel.set_ready(True)
    panel.outcomes["worse"].click()
    panel.note.setText("The end is now farther from the original")
    panel.save.click()
    assert saved[0]["outcome"] == "worse" and saved[0]["comparison"] == feedback.reference(
        base, "guided-varifold"
    )
    panel.close()
    app.processEvents()


def test_ready_compact_viewer_can_save_feedback_without_approving_or_rejecting(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from diffeoforge.desktop.preview_mesh_loader import PreviewMeshLoader
    from diffeoforge.desktop.reference_calibration_dialog import (
        CalibrationCandidateViewerDialog,
        CalibrationQcPair,
    )

    app = QApplication.instance() or QApplication([])
    base, trial = attempted(tmp_path, monkeypatch)
    monkeypatch.setattr(PreviewMeshLoader, "request_paths", lambda *_a, **_k: None)
    target = guided.record(trial)["target"]
    original, fitted = tmp_path / target, tmp_path / "current.vtk"
    pair = CalibrationQcPair(
        pair_id="current",
        label=target,
        original_path=original,
        reconstruction_path=fitted,
        required=True,
        original_sha256="0" * 64,
        reconstruction_sha256="0" * 64,
    )
    viewer = CalibrationCandidateViewerDialog(
        trial.study_directory,
        trial.candidates[0],
        pairs=(pair,),
        compact_review=True,
        guided_feedback_context=feedback.presentation(trial, "guided-varifold"),
    )
    viewer.show()
    assert viewer.decision_panel.isHidden()
    assert not viewer.guided_feedback.outcomes["worse"].isEnabled()
    viewer._pair_loaded(0, (_model(original), _model(fitted)))
    wait(app, lambda: viewer.canvas.comparison_ready and viewer.decision_panel.isVisible())
    viewer.problem_regions[target] = []  # A prior unmarked recovery carries no patch selection.
    viewer.guided_feedback.outcomes["worse"].click()
    viewer.guided_feedback.note.setText("Surface matching became worse")
    viewer.guided_feedback.save.click()
    assert viewer._guided_feedback_only and not viewer.review_recorded
    report = viewer.guided_feedback_decision
    assert report["problem_regions"] == {}
    assert report["outcome"] == "worse" and report["comparison"] == feedback.reference(
        base, "guided-varifold"
    )
    saved = feedback.save_feedback(trial.study_directory, "guided-varifold", report)
    assert not saved.visual_reviews and feedback.inspected(saved, "guided-varifold")
    viewer.close()
    app.processEvents()


def test_earlier_start_is_visible_and_works_before_rating_latest_attempt(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from pilot_view_helpers import wait_pilot_view
    from PySide6.QtWidgets import QApplication, QLabel, QPushButton

    from diffeoforge.desktop.reference_calibration_dialog import ReferenceCalibrationDialog

    app = QApplication.instance() or QApplication([])
    base, trial = attempted(tmp_path, monkeypatch)
    trial = feedback.save_feedback(trial.study_directory, "guided-varifold",
                                   decision(base, trial, "better"))
    dialog = ReferenceCalibrationDialog(trial.study_directory)
    dialog.show()
    try:
        wait_pilot_view(dialog)
        toggle = next(
            b
            for b in dialog.content.findChildren(QPushButton)
            if b.text() == "Choose / inspect an earlier fit…"
        )
        assert toggle.isVisible()
        toggle.click()
        choose = next(
            b
            for b in dialog.content.findChildren(QPushButton)
            if b.text() == "Work from this fit…" and b.isVisible()
        )
        queued = []
        # This test retains the transition/repeated-click guard. The annotation
        # viewer's settled geometry/save contract is exercised separately.
        monkeypatch.setattr(dialog, "_open_guided_working_fit", lambda identifier, ref:
            dialog._start_pilot(adaptive=False,
                               guided_action=("adaptive_select_start", identifier, ref)))
        monkeypatch.setattr(dialog._thread_pool, "start", queued.append)
        for _ in range(10):
            choose.click()
        assert len(queued) == 1
        queued.pop().run()
        wait_pilot_view(dialog)
        assert not dialog._snapshot.visual_reviews
        selected = feedback.selection(dialog._snapshot, "guided-varifold")
        assert selected["directory"] == str(base.study_directory)
        assert dialog.content.findChild(QLabel, "guidedStartingFit").isVisible()
        prepare = next(
            b
            for b in dialog.content.findChildren(QPushButton)
            if "prepare 1 trial on 1 specimen" in b.text()
        )
        assert prepare.isEnabled()
        proposed = strategy.trial_proposal(dialog._snapshot, "guided-varifold", "goal:weight")
        assert (
            proposed["values"]["attachment_kernel_width"]
            == base.plan.effective_values["attachment_kernel_width"]
        )
    finally:
        dialog._worker = None
        dialog.close()
        app.processEvents()


def test_actual_review_callback_saves_feedback_only_and_keeps_current_pilot(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from pilot_view_helpers import wait_pilot_view
    from PySide6.QtWidgets import QApplication

    import diffeoforge.desktop.reference_calibration_dialog as ui
    from diffeoforge.desktop.preview_mesh_loader import PreviewMeshLoader
    from diffeoforge.reference_calibration_study import load_reference_calibration_study

    app = QApplication.instance() or QApplication([])
    _base, trial = attempted(tmp_path, monkeypatch)
    monkeypatch.setattr(PreviewMeshLoader, "request_paths", lambda *_a, **_k: None)
    target = guided.record(trial)["target"]
    original, fitted = tmp_path / target, tmp_path / "current.vtk"
    pair = ui.CalibrationQcPair(
        pair_id="current",
        label=target,
        original_path=original,
        reconstruction_path=fitted,
        required=True,
        original_sha256="0" * 64,
        reconstruction_sha256="0" * 64,
    )
    parent = ui.ReferenceCalibrationDialog(trial.study_directory)
    parent.show()
    wait_pilot_view(parent)

    def inspect(viewer):
        viewer.show()
        viewer._pair_loaded(0, (_model(original), _model(fitted)))
        wait(app, lambda: viewer.canvas.comparison_ready)
        viewer.guided_feedback.outcomes["worse"].click()
        viewer.guided_feedback.note.setText("This change did not help")
        viewer.guided_feedback.save.click()
        return 1

    monkeypatch.setattr(ui.CalibrationCandidateViewerDialog, "exec", inspect)
    prepared = (trial, (pair,), {}, (), feedback.presentation(trial, "guided-varifold"))
    try:
        parent._candidate_prepared((trial.study_directory, trial.candidates[0]), prepared)
        wait(app, lambda: not parent._review_saving)
        wait_pilot_view(parent)
        current = load_reference_calibration_study(trial.study_directory)
        assert current.study_directory == parent.study_directory
        assert not current.visual_reviews and parent._worker is None
        assert feedback.presentation(current, "guided-varifold")["feedback"]["outcome"] == "worse"
        assert not (current.study_directory / "fit-search-latest.json").exists()
    finally:
        parent.close()
        app.processEvents()
