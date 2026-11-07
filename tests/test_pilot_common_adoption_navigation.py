"""A reviewed model revision has one visible, explicit next action."""
from copy import deepcopy

import pytest
from test_guided_pilot import approve
from test_pilot_common_candidate import rejected_capacity
from test_pilot_dead_end_journeys import dialog_for

from diffeoforge import guided_strategy as strategy
from diffeoforge import pilot_form_progress as progress
from diffeoforge import reference_guided_pilot as guided


def test_approved_candidate_pins_adoption_and_preserves_individual_reviews(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QLabel

    local, root, _ = rejected_capacity(tmp_path, monkeypatch)
    approved = approve(root, "guided-varifold")
    guidance = strategy.state(approved)
    assert guidance["common_recovery"]["mode"] == "adopt"
    assert "guided-varifold" in guidance["common_revision"]
    old = deepcopy(progress.marker(approved))
    app, dialog = dialog_for(approved, monkeypatch)
    try:
        assert dialog.next_step_button.isVisible() and dialog.next_step_button.isEnabled()
        assert dialog.next_step_button.text() == "Use approved common settings → check next form"
        assert dialog._guided_footer_action == (
            approved.study_directory, "adaptive_adopt_common_model", "guided-varifold")
        labels = dialog.content.findChildren(QLabel)
        assert any(label.text() == "Use the approved common settings" for label in labels)
        assert not any(label.text() == "Improve the fit" for label in labels)
        assert not any(label.text().startswith("Test additional control points.")
                       for label in labels)
        assert not any(label.text().startswith("Next form could not be prepared:")
                       for label in dialog.content.findChildren(QLabel))
        calls = []
        monkeypatch.setattr(dialog, "_start_pilot", lambda **kwargs: calls.append(kwargs))
        dialog.next_step_button.click()
        assert calls == [dict(
            adaptive=False, guided_action=("adaptive_adopt_common_model", "guided-varifold", None))]
        successor = guided.next_action(approved.study_directory, "adaptive_adopt_common_model",
                                      "guided-varifold")
        assert progress.marker(successor)["reviews"] == old["reviews"]
        assert progress.marker(successor)["protocol"] != old["protocol"]
        assert not successor.visual_reviews and successor.candidates[0].attempts == 0
        assert local.visual_reviews["guided-varifold"] is True
    finally:
        dialog.close()
        app.processEvents()


def test_rejected_candidate_cannot_offer_model_adoption(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QLabel

    _, rejected, _ = rejected_capacity(tmp_path, monkeypatch)
    app, dialog = dialog_for(rejected, monkeypatch)
    try:
        assert rejected.visual_reviews["guided-varifold"] is False
        action = dialog._guided_footer_action
        assert not action or action[1] != "adaptive_adopt_common_model"
        assert not any(label.text() == "Use the approved common settings"
                       for label in dialog.content.findChildren(QLabel))
    finally:
        dialog.close()
        app.processEvents()


def test_exhausted_family_keeps_review_and_saved_fit_choice_without_repeat(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QLabel, QPushButton
    from test_guided_pilot import run_batch
    from test_pilot_common_candidate import compared
    from test_pilot_region_feedback import reject

    _, current, _ = rejected_capacity(tmp_path, monkeypatch, outcome="same")
    ledger = deepcopy(progress.marker(current))
    for kind in ("detail", "weight"):
        choice = strategy.state(current)["common_recovery"]
        assert choice["kind"] == kind
        current = guided.next_action(current.study_directory, "adaptive_common_continue",
                                     "guided-varifold")
        current = compared(reject(run_batch(current, monkeypatch, capped=True),
                                  "guided-varifold"), "same")
    choice = strategy.state(current)["common_recovery"]
    assert choice["mode"] == "stalled" and not choice["available"]
    folders = set(current.study_directory.parent.iterdir())
    with pytest.raises(ValueError):
        guided.next_action(current.study_directory, "adaptive_common_continue", "guided-varifold")
    assert set(current.study_directory.parent.iterdir()) == folders
    assert progress.marker(current) == ledger and not current.visual_reviews["guided-varifold"]
    app, dialog = dialog_for(current, monkeypatch)
    try:
        assert dialog.review_next_button.isVisible() and dialog.review_next_button.isEnabled()
        assert "bounded iteration" in " ".join(
            label.text() for label in dialog.content.findChildren(QLabel))
        toggle = next(button for button in dialog.content.findChildren(QPushButton)
                      if button.text() == "Choose / inspect an earlier fit…")
        assert toggle.isVisible() and toggle.isEnabled()
        toggle.click()
        app.processEvents()
        choose = next(button for button in dialog.content.findChildren(QPushButton)
                      if button.text() == "Work from this fit…" and button.isVisible())
        calls = []
        monkeypatch.setattr(dialog, "_open_guided_working_fit", lambda *args: calls.append(args))
        choose.click()
        assert calls and calls[0][0] == "guided-varifold"
        assert (not dialog._guided_footer_action
                or dialog._guided_footer_action[1] != "adaptive_adopt_common_model")
        assert dialog._worker is None
    finally:
        dialog.close()
        app.processEvents()
