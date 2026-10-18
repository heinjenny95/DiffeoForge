from dataclasses import replace
from types import SimpleNamespace

import pytest

from diffeoforge.desktop.reference_calibration_presentation import stage_options_rejected


@pytest.mark.parametrize("order", [1, 4])
def test_recovery_does_not_skip_first_fit_or_final_qualification(order):
    snapshot = SimpleNamespace(current_stage=SimpleNamespace(order=order))
    assert not stage_options_rejected(snapshot)


@pytest.mark.parametrize("status,review,expected", [
    ("screened_out", None, True),
    ("completed", False, True),
    ("completed", True, False),
    ("completed", None, False),
    ("screen_failed", None, False),
    ("screen_deferred", None, False),
    ("failed", False, False),
    ("interrupted", False, False),
    ("orphaned", False, False),
    ("pending", False, False),
])
def test_recovery_requires_rejection_of_every_new_option(status, review, expected):
    snapshot = SimpleNamespace(
        current_stage=SimpleNamespace(order=2, stage_id="deformation"),
        candidates=[
            SimpleNamespace(candidate_id="deformation-retained", status="completed"),
            SimpleNamespace(candidate_id="option-a", status="screened_out"),
            SimpleNamespace(candidate_id="option-b", status=status),
        ],
        visual_reviews={"deformation-retained": True, "option-b": review},
    )
    assert stage_options_rejected(snapshot) is expected
    snapshot.candidates = snapshot.candidates[:1]
    assert not stage_options_rejected(snapshot)


def _visible_in_dialog(dialog, widget):
    from PySide6.QtCore import QPoint

    assert widget.isVisible()
    assert dialog.rect().contains(widget.mapTo(dialog, QPoint(0, 0)))
    assert dialog.rect().contains(widget.mapTo(dialog, widget.rect().bottomRight()))


def test_rejected_screens_and_joint_fits_offer_visible_exact_retention(tmp_path, monkeypatch):
    from test_reference_screening_dialog import _dialog
    from test_reference_stage_screening import _review_screen

    from diffeoforge import reference_calibration_study as study
    from diffeoforge import reference_stage_screening as screening
    from diffeoforge.desktop.reference_calibration_dialog import _CalibrationStageWorker
    from diffeoforge.desktop.widgets import _STYLE

    app, runner, dialog = _dialog(tmp_path, monkeypatch)
    old_style = app.styleSheet()
    app.setStyleSheet(_STYLE)
    dialog.resize(850, 650)
    assert not dialog.pilot_tools.toggle_button.isChecked()
    original = study.calibration_candidate_run_directory(dialog.snapshot.candidates[-1])
    original_bytes = {p: p.read_bytes() for p in original.rglob("*") if p.is_file()}
    events_path = dialog.study_directory / "events.jsonl"

    result = screening.run_next_screen(
        runner, subjects=(dialog.screen_subject.currentData(),),
    )
    result = _review_screen(result, False)
    dialog._render()
    assert "All stage" not in dialog.retained_fit_notice.text()
    assert dialog.start_button.text() == "Test next option"
    while not result.early_screening["complete"]:
        result = screening.run_next_screen(runner)
        result = _review_screen(result, False)
    before = events_path.read_bytes()
    dialog._render()
    app.processEvents()
    assert events_path.read_bytes() == before  # Display never selects or launches anything.
    assert "All stage 2 options were rejected" in dialog.retained_fit_notice.text()
    assert dialog.keep_previous_button.text() == "Keep approved stage 1 fit → stage 3"
    assert dialog.keep_previous_button.objectName() == "primary"
    assert dialog.start_button.isHidden() and dialog.advance_button.isHidden()
    assert dialog.minimumSizeHint().height() <= 650
    for position in (0, dialog.scroll.verticalScrollBar().maximum()):
        dialog.scroll.verticalScrollBar().setValue(position)
        app.processEvents()
        _visible_in_dialog(dialog, dialog.retained_fit_notice)
        _visible_in_dialog(dialog, dialog.keep_previous_button)
    starts = []
    monkeypatch.setattr(dialog, "_start_pilot", lambda **kw: starts.append(kw))
    dialog.keep_previous_button.click()
    assert starts == [dict(adaptive=False, retain_previous=True)]
    with monkeypatch.context() as guarded:
        guarded.setattr(runner, "run_current_stage", lambda **kw: pytest.fail("Optimizer"))
        worker = _CalibrationStageWorker(runner, retain_previous=True)
        worker.run()
        assert worker.error_message is None
    third = runner.run_current_stage()
    names = tuple(s.filename for s in third.plan.selected_pilot_subjects)
    for candidate in third.candidates[:-1]:
        study.record_reference_calibration_candidate_review(
            third.study_directory, candidate_id=candidate.candidate_id, approved=False,
            reviewed_subjects=names, subject_decisions={n: "fail" for n in names},
            display_scopes={n: "preview" for n in names},
        )
    dialog._render()
    app.processEvents()
    assert "All stage 3 options were rejected" in dialog.retained_fit_notice.text()
    assert "Time resolution still needs checking" in dialog.retained_fit_notice.text()
    assert dialog.keep_previous_button.text() == "Keep approved stage 2 fit → stage 4"
    assert study.calibration_candidate_run_directory(dialog.snapshot.candidates[-1]) == original
    _visible_in_dialog(dialog, dialog.keep_previous_button)
    # Combo changes must not restore the misleading generic "review this option" next step.
    dialog.selection_combo.setCurrentIndex(1)
    assert "All stage 3 options were rejected" in dialog.status.text()
    with monkeypatch.context() as guarded:
        guarded.setattr(runner, "run_current_stage", lambda **kw: pytest.fail("Optimizer"))
        worker = _CalibrationStageWorker(runner, retain_previous=True)
        worker.run()
        assert worker.error_message is None
    before = events_path.read_bytes()
    dialog._render()
    app.processEvents()
    assert events_path.read_bytes() == before
    assert dialog.snapshot.current_stage.order == 4
    assert dialog.retained_fit_panel.isHidden() and dialog.keep_previous_button.isHidden()
    from PySide6.QtWidgets import QLabel

    guide = dialog.findChild(QLabel, "stageNextSteps")
    assert guide and "2 Check time resolution" in guide.text()
    assert all(p.read_bytes() == data for p, data in original_bytes.items())
    dialog.close()
    app.setStyleSheet(old_style)
    app.processEvents()


def test_provisional_baseline_and_busy_or_withdrawn_review_are_not_silenced(tmp_path, monkeypatch):
    from test_reference_screening_dialog import _dialog

    import diffeoforge.desktop.reference_calibration_dialog as module

    app, _, dialog = _dialog(tmp_path, monkeypatch)
    real = module.iteration_limit_selection_available
    monkeypatch.setattr(module, "iteration_limit_selection_available", lambda snapshot, cid: (
        True if cid == "deformation-retained" else real(snapshot, cid)
    ))
    dialog._render()
    assert dialog.keep_previous_button.text() == "Keep provisional stage 1 fit → stage 3"
    assert "Convergence remains unconfirmed" in dialog.retained_fit_notice.text()
    dialog._restoring_search = True
    dialog._render()
    assert not dialog.keep_previous_button.isEnabled()
    dialog._restoring_search = False
    withdrawn = replace(dialog.snapshot, visual_reviews={"deformation-retained": False})
    dialog._render(withdrawn)
    assert dialog.retained_fit_panel.isHidden()
    assert not dialog.keep_previous_button.isEnabled()
    dialog.close()
    app.processEvents()


@pytest.mark.parametrize("changes,action", [
    ({"selected": False}, "choose"),
    ({"approved": False}, "review"),
    ({"reasons": ("Check time resolution of this saved fit (no optimization)",)}, "check"),
    ({"reasons": ("integration check differs for specimen (10->19): inspect/refine",)}, "finer"),
    ({"reasons": ("roundtrip check differs for specimen (source): inspect/refine",)}, "details"),
    ({"reasons": ("Geometry or complete-cohort evidence is invalid",)}, "details"),
    ({"reasons": ("A complete, valid joint fit is required",)}, "details"),
    ({"reasons": ("Optimizer convergence is not established",)}, "details"),
    ({"reasons": ("Unrecognized blocker",)}, "details"),
    ({"eligible": True}, "finish"),
    ({"provisional": True}, "finish"),
    ({"pending": True}, "check"),
])
def test_final_step_explains_check_results_without_overriding_gates(changes, action):
    from diffeoforge.desktop.reference_calibration_presentation import final_stage_next_step

    values = dict(selected=True, approved=True, reasons=())
    values.update(changes)
    result = final_stage_next_step(**values)
    assert result.action == action
    assert len(result.message) < 200
    if values.get("provisional"):
        assert "provisionally" in result.label and "iteration limit" in result.message
    if action == "finer":
        assert result.warning and "then review and check again" in result.message


def test_unstable_time_grid_has_one_visible_selected_fit_action_and_folded_details(
    tmp_path, monkeypatch,
):
    from PySide6.QtWidgets import QApplication, QLabel
    from test_pilot_completion import _approve_preview, _checked

    from diffeoforge import reference_pilot_completion as completion
    from diffeoforge.desktop.reference_calibration_dialog import ReferenceCalibrationDialog
    from diffeoforge.desktop.widgets import _STYLE

    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    zero = dict(rms=0.0, p95=0.0, maximum=0.0)
    monkeypatch.setattr(completion, "movement", lambda a, b, scale: (
        dict(rms=0.1, p95=0.1, maximum=0.1)
        if a.parent.name.isdecimal() and b.parent.name.isdecimal() else dict(zero)
    ))
    _, done, _, identifier = _checked(tmp_path, monkeypatch, capped=True)
    _approve_preview(done, identifier)
    before = {p: p.read_bytes() for p in done.study_directory.rglob("*") if p.is_file()}
    app = QApplication.instance() or QApplication([])
    old_style = app.styleSheet()
    app.setStyleSheet(_STYLE)
    dialog = ReferenceCalibrationDialog(done.study_directory)
    dialog.selection_combo.setCurrentIndex(dialog.selection_combo.findData(identifier))
    dialog.resize(850, 650)
    dialog.show()
    app.processEvents()
    assert "good-looking reconstruction can still change" in dialog.status.text()
    assert dialog.status.objectName() == "statusWarning"
    planned = next(c for c in dialog.snapshot.current_stage.candidates
                   if c.candidate_id == identifier)
    count = int(planned.values["timepoints"])
    assert dialog.next_step_button.text() == f"Recalculate with {2 * count - 1} time steps…"
    assert dialog.final_check_summary.text().splitlines()[0] == "Shape review: approved"
    assert f"needs more time steps ({count} → {2 * count - 1})" in dialog.final_check_summary.text()
    assert ("limit reached (50 iterations); convergence unconfirmed"
            in dialog.final_check_summary.text())
    assert dialog.next_step_button.isEnabled()
    assert dialog.start_button.isHidden() and dialog.advance_button.isHidden()
    assert dialog.review_next_button.isHidden() and dialog.qualification_button.isHidden()
    assert dialog.minimumSizeHint().height() <= 650
    _visible_in_dialog(dialog, dialog.next_step_button)
    _visible_in_dialog(dialog, dialog.final_check_summary)
    dialog.scroll.verticalScrollBar().setValue(dialog.scroll.verticalScrollBar().maximum())
    app.processEvents()
    _visible_in_dialog(dialog, dialog.final_check_summary)
    visible_labels = [w.text() for w in dialog.findChildren(QLabel) if w.isVisible()]
    assert not any("integration check differs" in t or "No option qualifies" in t
                   for t in visible_labels)
    starts = []
    monkeypatch.setattr(dialog, "_start_pilot", lambda **kw: starts.append(kw))
    dialog.next_step_button.click()
    assert starts == [dict(adaptive=False, qualification=True, qualification_source=identifier,
                           finer_model=True, qualification_iterations=300)]
    unreviewed = done.candidates[-1].candidate_id
    dialog.selection_combo.setCurrentIndex(dialog.selection_combo.findData(unreviewed))
    assert dialog.next_step_button.text() == "Review saved fit…"
    assert dialog.final_check_summary.text().startswith("Shape review: review needed")
    dialog.selection_combo.setCurrentIndex(0)
    assert not dialog.next_step_button.isEnabled()
    assert dialog.final_check_summary.isHidden()
    dialog.selection_combo.setCurrentIndex(dialog.selection_combo.findData(identifier))
    dialog._restoring_search = True
    dialog._render()
    assert not dialog.next_step_button.isEnabled()
    assert dialog.final_check_summary.isHidden()
    dialog._restoring_search = False
    dialog._render()
    assert all(p.read_bytes() == data for p, data in before.items())
    dialog.close()
    app.setStyleSheet(old_style)
    app.processEvents()


@pytest.mark.parametrize("reasons,approved,metrics,extra,expected", [
    (("integration check differs for a (19->37): inspect/refine",) * 6, True,
     {"converged": False, "optimizer_stop_signal": "maximum_iterations", "maximum_iterations": 300},
     {}, ("approved", "needs more time steps (19 → 37)",
          "limit reached (300 iterations); convergence unconfirmed")),
    (("Check time resolution of this saved fit (no optimization)",), True,
     {"converged": True}, {}, ("approved", "not checked yet", "convergence confirmed")),
    (("Optimizer convergence is not established",), True,
     {"converged": False}, {}, ("approved", "passed", "convergence unconfirmed")),
    (("roundtrip check differs for a (source): inspect/refine",), True,
     {"converged": True}, {},
     ("approved", "could not verify the saved fit", "convergence confirmed")),
    ((), None, {}, {}, ("review needed", "check needed", "convergence unconfirmed")),
    ((), True, {"converged": True}, {"eligible": True},
     ("approved", "passed", "convergence confirmed")),
    (("Anatomical review rejected",), False, {"converged": True}, {},
     ("rejected", "passed", "convergence confirmed")),
    (("Unknown evidence failure",), True, {}, {},
     ("approved", "check needed", "convergence unconfirmed")),
])
def test_final_check_summary_separates_anatomy_resolution_and_optimizer(
    reasons, approved, metrics, extra, expected,
):
    from diffeoforge.desktop.reference_calibration_presentation import final_stage_check_summary

    text = final_stage_check_summary(approved=approved, reasons=reasons, metrics=metrics,
                                    timepoints=19, **extra)
    lines = text.splitlines()
    assert len(lines) == 3
    assert lines == [f"Shape review: {expected[0]}", f"Time resolution: {expected[1]}",
                     f"Optimization: {expected[2]}"]


def test_next_time_grid_is_selected_count_and_never_promises_a_pass():
    from diffeoforge.desktop.reference_calibration_presentation import final_stage_next_step

    for count in (10, 19, 37):
        step = final_stage_next_step(selected=True, approved=True, timepoints=count, reasons=(
            "integration check differs for a (37->73): inspect/refine",
            "Optimizer convergence is not established",
        ))
        assert step.label == f"Recalculate with {2 * count - 1} time steps…"
        assert step.action == "finer" and "then review and check again" in step.message
        assert "good-looking reconstruction" in step.message
