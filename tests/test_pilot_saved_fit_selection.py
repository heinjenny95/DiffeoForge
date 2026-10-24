import pytest
from pilot_view_helpers import wait_pilot_view
from test_reference_integration_check import _fourth

from diffeoforge.reference_stage_retention import register_previous_fit


@pytest.mark.parametrize("action", ["primary", "qualification"])
def test_ready_stage_four_replaces_previous_stage_choice_and_preserves_reviews(
    tmp_path, monkeypatch, action,
):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QLabel

    from diffeoforge.desktop.reference_calibration_dialog import ReferenceCalibrationDialog

    app = QApplication.instance() or QApplication([])
    _, fourth = _fourth(tmp_path, monkeypatch)
    fourth = register_previous_fit(fourth, for_qualification=True)
    retained = fourth.candidates[-1]
    assert fourth.status == "ready"
    assert retained.candidate_id == "timepoints-retained"
    assert fourth.visual_reviews[retained.candidate_id] is True
    protected = {
        p: p.read_bytes() for p in fourth.study_directory.rglob("*")
        if p.is_file() and p.name in {"events.jsonl", "visual-reviews.json", "evidence.json"}
    }
    dialog = ReferenceCalibrationDialog(fourth.study_directory)
    wait_pilot_view(dialog)
    assert dialog.selection_combo.currentData() == retained.candidate_id
    # The same window previously selected a stage-three option. A ready stage
    # must rebuild its chooser even before any time-grid check has run.
    dialog.selection_combo.addItem("Previous stage B", "noise-02")
    dialog.selection_combo.setCurrentIndex(dialog.selection_combo.count() - 1)
    dialog._render(fourth)
    wait_pilot_view(dialog)
    assert dialog.selection_combo.findData("noise-02") == -1
    assert dialog.selection_combo.currentData() == retained.candidate_id
    assert "Saved fit from stage 3" in dialog.selection_combo.currentText()
    captions = [w.text() for w in dialog.findChildren(QLabel)]
    assert "Saved fit from stage 3" in captions
    assert not any(t.startswith("Option D") for t in captions)
    workers = []
    monkeypatch.setattr(dialog._thread_pool, "start", workers.append)
    with pytest.raises(ValueError, match="current stage"):
        dialog._dispatch_pilot(qualification=True, qualification_source="noise-02")
    assert not workers and dialog._worker is None
    if action == "primary":
        dialog._start()
    else:
        dialog.qualification_button.click()
    assert len(workers) == 1
    assert workers[0].qualification is True
    assert workers[0].qualification_source == retained.candidate_id
    assert workers[0].strict_optimizer is False
    assert all(p.read_bytes() == contents for p, contents in protected.items())
    # The captured worker is deliberately not run: dispatch cannot fit, shoot,
    # overwrite a review or declare successful numerical qualification itself.
    dialog._worker = None
    dialog.close()
    app.processEvents()


def test_ready_stage_four_with_multiple_saved_fits_keeps_current_stage_choice(
    tmp_path, monkeypatch,
):
    from dataclasses import replace

    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from diffeoforge.desktop.reference_calibration_dialog import ReferenceCalibrationDialog

    app = QApplication.instance() or QApplication([])
    runner, fourth = _fourth(tmp_path, monkeypatch)
    completed = runner.run_current_stage()
    dialog = ReferenceCalibrationDialog(completed.study_directory)
    wait_pilot_view(dialog)
    chosen = completed.candidates[0].candidate_id
    dialog.selection_combo.setCurrentIndex(dialog.selection_combo.findData(chosen))
    dialog._render(replace(completed, status="ready"))
    wait_pilot_view(dialog)
    assert dialog.selection_combo.currentData() == chosen
    dialog._render(replace(completed, status="ready"))
    wait_pilot_view(dialog)
    assert dialog.selection_combo.currentData() == chosen
    dialog.close()
    app.processEvents()
