"""The primary setup action opens unfinished pilots using verified study status."""

from dataclasses import replace

import pytest
from test_desktop_pilot_responsiveness import _wait
from test_desktop_pilot_responsiveness import pilot_window as _pilot_window

from diffeoforge.desktop.project_setup import DesktopEngine

pilot_window = _pilot_window


@pytest.mark.parametrize("status", ["ready", "running", "awaiting_review", "orphaned",
                                    "interrupted", "failed"])
def test_unfinished_saved_pilot_is_the_primary_open_action(pilot_window, monkeypatch, status):
    _, window, source = pilot_window
    snapshot = replace(source, status=status)
    window.engine_combo.setCurrentIndex(
        window.engine_combo.findData(DesktopEngine.DEFORMETRICA_REFERENCE))
    monkeypatch.setattr(window, "_saved_pilot_status", lambda *_: snapshot)
    monkeypatch.setattr(window, "_reference_calibration_plan_matches_current_inputs", lambda: True)
    monkeypatch.setattr(window, "_bound_project_matches_form", lambda: True)
    opened = []
    monkeypatch.setattr(window, "_open_reference_calibration", lambda: opened.append(snapshot))
    monkeypatch.setattr(window, "_navigate_to_step", lambda *_: pytest.fail(
        "An unfinished saved pilot skipped to parameter review"))
    window._sync_setup_primary_action(form_ready=True)
    assert window.create_button.objectName() == "primary"
    assert window.create_button.text() == "Open saved pilot…"
    assert window.create_button.isEnabled()
    window._refresh_reference_calibration_execution_card()
    assert window.open_reference_calibration_button.text() == "Open saved pilot…"
    assert "finished running" not in window.reference_calibration_execution_status.text()
    window.create_button.click()
    assert opened == [snapshot]


@pytest.mark.parametrize("has_final_config", [False, True])
def test_completed_status_needs_verified_final_configuration_before_apply(
    pilot_window, monkeypatch, has_final_config,
):
    _, window, source = pilot_window
    snapshot = replace(source, status="completed",
                       final_config_path=source.study_directory / "final.yaml"
                       if has_final_config else None)
    monkeypatch.setattr(window, "_saved_pilot_status", lambda *_: snapshot)
    assert window._reference_calibration_action_text() == (
        "Apply completed pilot calibration" if has_final_config else "Open saved pilot…")


def test_study_file_existence_is_not_a_completion_or_review_signal(pilot_window):
    app, window, source = pilot_window
    assert (source.study_directory / "study.json").is_file()
    assert window._reference_calibration_action_text() == "Checking saved pilot…"
    _wait(app, lambda: not window._pilot_status_loading)
    # This is the actual freshly verified prepared study, not a completion guess.
    assert window._pilot_status_snapshot.status == "ready"
    assert window._reference_calibration_action_text() == "Open saved pilot…"
    assert window._pilot_status_snapshot.final_config_path is None
