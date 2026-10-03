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
    assert "Run kept options with all" in dialog.start_button.text()
    assert "Joint fits still need" in dialog.screen_notice.text()
    dialog.adaptive_fit_search.setChecked(True)
    monkeypatch.setattr(dialog, "_start_pilot", lambda **kwargs: calls.append(kwargs))
    dialog._start()
    assert calls[-1] == dict(adaptive=False)
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
    assert dialog.integration_controls.isVisible()
    assert all(field.isEnabled() for field in dialog.integration_fields.values())
    assert dialog.integration_fields["atlas_rms_relative"].value() == 0.5
    dialog.close()
    app.processEvents()
