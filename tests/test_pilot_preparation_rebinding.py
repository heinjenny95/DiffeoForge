"""A deliberate pilot preparation must prepare the current form, never stale state."""

from types import SimpleNamespace

import pytest
from test_desktop_calibration import _prepared_window

from diffeoforge.desktop.project_review import review_project
from diffeoforge.desktop.project_setup import create_project
from diffeoforge.desktop.widgets import _ProjectWorker


def _existing(monkeypatch, tmp_path):
    app, window, queued = _prepared_window(monkeypatch, tmp_path)
    window.reference_attachment_type_combo.setCurrentIndex(
        window.reference_attachment_type_combo.findData("current")
    )
    window.analyze_reference_parameters_button.click()
    queued.pop().run()
    app.processEvents()
    window.build_reference_calibration_button.click()
    result = create_project(window._request())
    window._project_succeeded(result)
    window._review = review_project(result.config_path, result.engine)
    window._reference_readiness = SimpleNamespace(ready=True)
    assert window._bound_project_matches_form()
    return app, window, queued, result


@pytest.mark.parametrize("action", ["primary", "pilot_card"])
@pytest.mark.parametrize("changed", ["project", "method"])
def test_changed_form_prepares_current_project_once(monkeypatch, tmp_path, action, changed):
    app, window, queued, previous = _existing(monkeypatch, tmp_path)
    original = previous.config_path.read_bytes()
    monkeypatch.setattr(window, "_confirm_configuration_overwrite", lambda _path: True)
    monkeypatch.setattr(
        window, "_open_reference_calibration", lambda: pytest.fail("Stale pilot opened")
    )
    try:
        if changed == "project":
            window.project_edit.setText(str(tmp_path / "new-project"))
        else:
            window.reference_attachment_type_combo.setCurrentIndex(
                window.reference_attachment_type_combo.findData("auto")
            )
        assert not window._bound_project_matches_form()
        assert window._reference_calibration_plan_matches_current_inputs()
        button = (
            window.create_button
            if action == "primary"
            else window.open_reference_calibration_button
        )
        for _ in range(20):
            button.click()
        assert len(queued) == 1
        worker = queued[0]
        assert isinstance(worker, _ProjectWorker)
        assert worker.request.project_directory == window._request().project_directory
        assert worker.request.reference_attachment_type == (
            "auto" if changed == "method" else "current"
        )
        assert window._guided_reference_calibration_requested
        assert window._reference_readiness is None
        assert previous.config_path.read_bytes() == original
    finally:
        window._worker = None
        window.close()
        app.processEvents()


def test_changed_method_honors_cancelled_configuration_overwrite(monkeypatch, tmp_path):
    app, window, queued, previous = _existing(monkeypatch, tmp_path)
    original = previous.config_path.read_bytes()
    confirmations = []
    monkeypatch.setattr(
        window,
        "_confirm_configuration_overwrite",
        lambda path: confirmations.append(path) or False,
    )
    try:
        window.reference_attachment_type_combo.setCurrentIndex(
            window.reference_attachment_type_combo.findData("auto")
        )
        window.open_reference_calibration_button.click()
        assert confirmations == [previous.config_path]
        assert not queued and window._worker is None
        assert window._result is previous
        assert not window._guided_reference_calibration_requested
        assert previous.config_path.read_bytes() == original
    finally:
        window.close()
        app.processEvents()


def test_stale_plan_cannot_prepare_a_changed_project(monkeypatch, tmp_path):
    app, window, queued, previous = _existing(monkeypatch, tmp_path)
    original = previous.config_path.read_bytes()
    try:
        window.project_edit.setText(str(tmp_path / "new-project"))
        window.reference_pilot_subject_count_spin.setValue(2)
        window._prepare_or_open_reference_calibration()
        assert not queued and window._worker is None
        assert window._result is previous
        assert previous.config_path.read_bytes() == original
    finally:
        window.close()
        app.processEvents()


def test_old_completed_selection_is_not_current_after_method_edit(monkeypatch, tmp_path):
    app, window, _queued, previous = _existing(monkeypatch, tmp_path)
    try:
        window._reference_calibrated_config_path = previous.config_path
        assert window._reference_calibration_completed()
        window.reference_attachment_type_combo.setCurrentIndex(
            window.reference_attachment_type_combo.findData("auto")
        )
        assert not window._reference_calibration_completed()
    finally:
        window.close()
        app.processEvents()
