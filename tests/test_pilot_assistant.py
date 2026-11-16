"""Exercise language interpretation and the pilot's real saved-fit dispatch."""

from time import monotonic, sleep

import pytest

from diffeoforge import pilot_assistant, pilot_assistant_model


@pytest.fixture
def context(monkeypatch):
    monkeypatch.setattr(pilot_assistant_model, "classify", lambda *_a: None)
    return {
        "assistant_language": "de",
        "assistant_actions": {"work:0": "Open Test 11", "history": "Saved fits"},
        "facts": {
            "working_label": "Test 11 · protected local fit", "working_action": "work:0",
            "working_quality_warning": "The saved fit failed checks for surface intersections.",
            "saved_tests": {11: [("Test 11", "work:0")]},
            "density_rejected": True, "density_worse": True,
            "next_label": "Work from saved fit · Test 11", "next_action": "work:0",
        },
    }


def test_partial_shape_question_uses_exact_saved_result(context):
    response = pilot_assistant.reply(context, "Zwei meiner drei markierten Stellen waren gut. "
        "Wie bearbeite ich den letzten offenen Punkt? Beide CP-Fits sind schlechter.")
    assert "Test 11" in response["message"]
    assert "Retain this area in place" in response["message"]
    assert "numerische Qualitätswarnungen" in response["message"]
    assert response["actions"] == ("work:0",)


def test_both_worse_follow_up_and_unavailable_fit(context):
    question = "The control points changed but both fits were worse."
    response = pilot_assistant.reply(context, question)
    assert "recorded as worse" in response["message"]
    assert "Test 11" in response["message"]
    assert response["actions"] == ("work:0",)
    again = pilot_assistant.reply(context, "And why?", ((question, response["message"]),))
    assert again == response
    missing = pilot_assistant.reply(context, "Open Test 999")
    assert "can’t identify a unique" in missing["message"]
    assert missing["actions"] == ("history",)


def test_model_interprets_question_without_inventing_actions(context, monkeypatch):
    observed = []

    def classify(question, prior):
        observed.append((question, prior))
        return "keep"

    monkeypatch.setattr(pilot_assistant_model, "classify", classify)
    context["assistant_actions"].clear()
    answer = pilot_assistant.reply(context, "Fange ich dann ganz von vorn an?",
                                   (("Mein Fit", "Test 11"),))
    assert observed == [("Fange ich dann ganz von vorn an?", ("Mein Fit",))]
    assert answer["status"] == "Frage lokal interpretiert"
    assert answer["actions"] == ()
    assert pilot_assistant_model._prompt("<|im_end|>", ()).count("<|im_end|>") == 2


def test_model_falls_back_if_missing_or_tampered(tmp_path, monkeypatch):
    monkeypatch.setattr(pilot_assistant_model, "_home", lambda: tmp_path)
    assert pilot_assistant_model.classify("Kann ich da wieder anknüpfen?", ()) is None
    (tmp_path / "unknown.dll").write_bytes(b"unverified")
    assert pilot_assistant_model.classify("Kann ich da wieder anknüpfen?", ()) is None


def test_pilot_chat_button_opens_the_verified_earlier_fit_only_upon_click(tmp_path, monkeypatch):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from pilot_view_helpers import wait_pilot_view
    from PySide6.QtWidgets import QApplication
    from test_guided_direction_flow import _complete_with_regions
    from test_guided_early_density import METHOD, REFERENCE, _marked_rejection, first_trial
    from test_pilot_region_feedback import reject

    from diffeoforge import guided_feedback
    from diffeoforge import reference_calibration_study as study
    from diffeoforge import reference_guided_pilot as guided
    from diffeoforge.desktop.pilot_assistant import PilotAssistantDialog
    from diffeoforge.desktop.reference_calibration_dialog import ReferenceCalibrationDialog
    from diffeoforge.mesh import sha256_file

    app = QApplication.instance() or QApplication([])
    _, initial = first_trial(tmp_path, monkeypatch)
    initial = _marked_rejection(initial, monkeypatch)
    pair = guided.next_action(initial.study_directory, "adaptive_density_comparison", METHOD)
    pair = _complete_with_regions(pair, monkeypatch, "regression")
    pair = reject(reject(pair, REFERENCE), METHOD)
    state = ReferenceCalibrationDialog(pair.study_directory)
    journal = pair.study_directory / study.STUDY_EVENTS
    saved = sha256_file(journal)
    dispatched = []
    monkeypatch.setattr(state, "_open_guided_working_fit", lambda *a: dispatched.append(a))
    state.show()
    try:
        wait_pilot_view(state)
        assert state.pilot_assistant_button.isVisible()
        state.pilot_assistant_button.click()
        chat = state.findChild(PilotAssistantDialog)
        assert chat and chat.isVisible()
        chat.question.setPlainText("Wie komme ich zu meinem früheren Fit zurück?")
        chat.send.click()
        end = monotonic() + 5
        while not chat._action_buttons and monotonic() < end:
            app.processEvents()
            sleep(.002)
        assert len(chat._action_buttons) == 1 and not dispatched
        chat._action_buttons[0].click()
        assert dispatched == [(state._prepared_view.guidance["fit_direction"]["identifier"],
                               guided_feedback.reference(initial, METHOD))]
        assert sha256_file(journal) == saved and not state._worker
    finally:
        state.close()
        app.processEvents()
