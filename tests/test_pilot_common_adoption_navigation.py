"""A reviewed model revision has one visible, explicit next action."""
from copy import deepcopy

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
    _, rejected, _ = rejected_capacity(tmp_path, monkeypatch)
    app, dialog = dialog_for(rejected, monkeypatch)
    try:
        assert rejected.visual_reviews["guided-varifold"] is False
        action = dialog._guided_footer_action
        assert not action or action[1] != "adaptive_adopt_common_model"
    finally:
        dialog.close()
        app.processEvents()
