import pytest
from test_reference_stage_retention import _second_stage
from test_reference_stage_screening import _review_screen

from diffeoforge import reference_stage_screening as screening
from diffeoforge.reference_stage_retention import keep_previous_fit


def _dialog(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from diffeoforge.desktop.reference_calibration_dialog import ReferenceCalibrationDialog

    app = QApplication.instance() or QApplication([])
    runner, _, _, second = _second_stage(tmp_path, monkeypatch)
    dialog = ReferenceCalibrationDialog(second.study_directory)
    dialog.show()
    app.processEvents()
    return app, runner, dialog


def test_stage_two_default_filter_and_optional_full_comparison(tmp_path, monkeypatch):
    app, _, dialog = _dialog(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(dialog, "_start_pilot", lambda **kwargs: calls.append(kwargs))
    assert dialog.screen_controls.isVisible()
    assert dialog.screen_enabled.isChecked()
    dialog.start_button.click()
    assert calls[-1] == dict(adaptive=False, early_screen=True,
                            screen_subjects=(dialog.screen_subject.currentData(),))
    dialog.screen_enabled.setChecked(False)
    assert not dialog.screen_subject.isEnabled()
    dialog._start()
    assert calls[-1] == {}
    dialog.close()
    app.processEvents()


def test_saved_screen_waits_for_review_and_kept_options_use_joint_dispatch(tmp_path, monkeypatch):
    app, runner, dialog = _dialog(tmp_path, monkeypatch)
    result = screening.run_next_screen(runner, subjects=(dialog.screen_subject.currentData(),))
    dialog._render()
    assert dialog.start_button.text() == "Review this specimen"
    assert dialog.advance_button.isHidden()
    calls = []
    monkeypatch.setattr(dialog, "_review_early_screen", lambda: calls.append("review"))
    dialog._start()
    assert calls == ["review"]
    while True:
        result = _review_screen(result, True)
        if result.early_screening["complete"]:
            break
        result = screening.run_next_screen(runner)
    dialog._render()
    assert dialog.screen_comparison.isVisible()
    assert not dialog.start_button.isEnabled()
    assert dialog.screen_comparison.table.rowCount() == len(result.early_screening["kept"])
    assert "Joint fits still need" in dialog.screen_notice.text()
    dialog.adaptive_fit_search.setChecked(True)
    monkeypatch.setattr(dialog, "_start_pilot", lambda **kwargs: calls.append(kwargs))
    dialog._start()
    assert calls == ["review"]  # No default winner and no batch dispatch.
    chosen = result.early_screening["kept"][1]
    dialog.screen_comparison.choice.setCurrentIndex(
        dialog.screen_comparison.choice.findData(chosen)
    )
    dialog._start()
    assert calls[-1] == dict(adaptive=False, screen_joint_choice=chosen)
    dialog.close()
    app.processEvents()


def test_stage_three_filter_and_stage_four_full_cohort_controls(tmp_path, monkeypatch):
    app, _, dialog = _dialog(tmp_path, monkeypatch)
    keep_previous_fit(dialog.study_directory)
    dialog._render()
    assert dialog.screen_controls.isVisible()
    assert dialog.snapshot.current_stage.order == 3
    keep_previous_fit(dialog.study_directory)
    dialog._render()
    assert dialog.snapshot.current_stage.order == 4
    assert dialog.screen_controls.isHidden()
    # Current stage 4 uses fixed-state qualification; legacy refit criteria stay hidden.
    assert dialog.integration_controls.isHidden()
    assert dialog.qualification_button.isVisible()
    assert all(field.isEnabled() for field in dialog.integration_fields.values())
    assert dialog.integration_fields["atlas_rms_relative"].value() == 0.5
    dialog.close()
    app.processEvents()


def test_technical_failures_show_retry_with_separate_counts_and_worker_dispatch(
    tmp_path, monkeypatch
):
    from test_reference_calibration_study import _FailedController

    app, runner, dialog = _dialog(tmp_path, monkeypatch)
    runner._controller_factory = _FailedController
    result = screening.run_next_screen(runner, subjects=(dialog.screen_subject.currentData(),))
    while not result.early_screening["complete"]:
        result = screening.run_next_screen(runner)
    dialog._render()
    assert dialog.retry_screens_button.isVisible()
    assert "0 discarded" in dialog.screen_notice.text()
    assert "technical failures" in dialog.screen_notice.text()
    assert dialog.start_button.isHidden()
    calls = []
    monkeypatch.setattr(dialog, "_start_pilot", lambda **kwargs: calls.append(kwargs))
    dialog.retry_screens_button.click()
    assert calls == [dict(adaptive=False, retry_screens=True)]
    from diffeoforge.desktop.reference_calibration_dialog import _CalibrationStageWorker

    monkeypatch.setattr(runner, "run_current_stage", lambda **kwargs: pytest.fail("Optimizer"))
    worker = _CalibrationStageWorker(runner, retry_screens=True)
    outcomes = []
    worker.signals.succeeded.connect(outcomes.append)
    worker.run()
    app.processEvents()
    assert len(outcomes) == 1 and not worker.error_message
    assert not outcomes[0].early_screening["technical_failures"]
    dialog._render()
    assert dialog.retry_screens_button.isHidden()
    assert dialog.start_button.text() == "Test next option"
    dialog.close()
    app.processEvents()


def test_comparison_sorts_saved_distances_keeps_missing_values_and_requires_a_choice(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from diffeoforge.desktop.screening_choice import ScreeningChoicePanel

    app = QApplication.instance() or QApplication([])
    ids = ["option-a", "option-b", "option-c"]
    rows = [dict(candidate_id=cid, p95=p95, median=p95, deformation_energy=0.5,
                 distortion_p95=0.1, resampling_sensitivity=0.02,
                 stop_signals=["maximum_iterations"],
                 converged=False, completed=True, review="kept")
            for cid, p95 in zip(ids, (0.2, 0.1, None), strict=True)]
    state = dict(stage_id="deformation", comparison=rows, candidate_ids=ids, kept=ids,
                 joint_selection=None)
    snapshot = SimpleNamespace(study_directory="synthetic-study", early_screening=state,
                               current_stage=SimpleNamespace(candidates=[
                                   SimpleNamespace(candidate_id=cid) for cid in ids]))
    panel = ScreeningChoicePanel()
    panel.present(snapshot)
    assert [panel.table.item(i, 0).text() for i in range(3)] == ["B", "A", "C"]
    assert panel.table.item(2, 2).text() == "—"
    assert panel.table.item(0, 7).text() == "maximum_iterations"
    assert panel.selected_candidate_id is None
    panel.choice.setCurrentIndex(panel.choice.findData(ids[0]))
    panel.present(snapshot)
    assert panel.selected_candidate_id == ids[0]
    state["joint_selection"] = ids[0]
    panel.present(snapshot)
    assert not panel.choice.isEnabled()
    panel.close()
    app.processEvents()
