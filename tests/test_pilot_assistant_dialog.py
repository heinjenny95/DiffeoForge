"""The pilot chat stays responsive and only dispatches selected pilot actions."""

from threading import Event, get_ident
from time import monotonic, sleep
from types import SimpleNamespace

import pytest


def _wait(app, condition, *, timeout=5):
    deadline = monotonic() + timeout
    while not condition() and monotonic() < deadline:
        app.processEvents()
        sleep(.002)
    assert condition()


@pytest.fixture
def desktop(monkeypatch):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QWidget

    app = QApplication.instance() or QApplication([])
    window = QWidget()
    window.show()
    yield app, window
    window.close()
    app.processEvents()


def test_chat_reuses_context_and_turns_and_opens_only_an_explicit_action(desktop):
    from shiboken6 import isValid

    from diffeoforge.desktop.pilot_assistant import show

    app, window = desktop
    main_thread = get_ident()
    entered, release = Event(), Event()
    turns, dispatched = [], []
    context = {
        "assistant_actions": {"retained": "Open saved fit", "review": "Review current fit",
                              "about": "Read about pilot checks"},
        "assistant_language": "en",
        "remaining_areas": 1,
    }

    def reply(current, question, history):
        assert get_ident() != main_thread
        assert current is context
        turns.append((question, history))
        if not history:
            entered.set()
            assert release.wait(4)
            return {"message": "Start from the saved fit.",
                    "actions": ["unavailable", "retained", "retained", "review", "about"]}
        return {"message": "<b>Protect the first two areas</b>",
                "actions": ["retained"], "status": "Local evidence"}

    def invoke(action):
        assert get_ident() == main_thread
        assert not (isValid(dialog) and dialog.isVisible())
        dispatched.append(action)

    dialog = show(window, context, reply=reply, invoke=invoke)
    try:
        app.processEvents()
        assert dialog.isVisible()
        assert not dialog.send.isEnabled()
        question = "The first two areas look good. The third still misses."
        dialog.question.setPlainText(question)
        dialog.send.click()
        _wait(app, entered.is_set)
        assert not dialog.send.isEnabled()
        assert not dialog.question.isEnabled()
        assert dialog.status.text() == "Checking the pilot stage …"
        assert not dispatched
        release.set()
        _wait(app, dialog.question.isEnabled)
        assert [b.text() for b in dialog._action_buttons] == [
            "Open saved fit", "Review current fit"]
        old_action = dialog._action_buttons[1]
        dialog.question.setPlainText("How do I protect them?")
        dialog.send.click()
        old_action.click()
        assert not dispatched
        _wait(app, dialog.question.isEnabled)
        assert turns == [
            (question, ()),
            ("How do I protect them?", ((question, "Start from the saved fit."),)),
        ]
        assert "<b>Protect the first two areas</b>" in dialog.transcript.toPlainText()
        assert dialog.status.text() == "Local evidence"
        assert [b.text() for b in dialog._action_buttons] == ["Open saved fit"]
        assert not dispatched
        selected = dialog._action_buttons[0]
        selected.click()
        selected.click()
        assert dispatched == ["retained"]
    finally:
        release.set()
        if isValid(dialog):
            dialog.close()
        app.processEvents()


def test_chat_hides_backend_errors_and_can_retry(desktop):
    from shiboken6 import isValid

    from diffeoforge.desktop.pilot_assistant import show

    app, window = desktop
    attempts = []

    def reply(_context, message, history):
        attempts.append(message)
        assert not history
        if len(attempts) == 1:
            raise RuntimeError("private model diagnostic")
        return {"message": "The previous fit is still saved.", "actions": []}

    dialog = show(window, {"assistant_language": "de"}, reply=reply,
                  invoke=lambda _: pytest.fail("Unexpected action"))
    try:
        assert dialog.windowTitle() == "Pilot chat"
        assert dialog.send.text() == "Send"
        assert dialog.question.accessibleName() == "Your question"
        dialog.question.setPlainText("x" * 1201)
        assert not dialog.send.isEnabled()
        assert "1200" in dialog.status.text()
        dialog.question.setPlainText("Wie komme ich zurück?")
        dialog.send.click()
        _wait(app, dialog.question.isEnabled)
        assert dialog.send.isEnabled()
        assert dialog.question.toPlainText() == "Wie komme ich zurück?"
        assert "You can send the question again." in dialog.status.text()
        assert "private model diagnostic" not in dialog.transcript.toPlainText()
        dialog.send.click()
        _wait(app, dialog.question.isEnabled)
        assert "You\nWie komme ich zurück?" in dialog.transcript.toPlainText()
        assert "The previous fit is still saved." in dialog.transcript.toPlainText()
        assert not dialog._action_buttons and dialog.status.isHidden()
        assert attempts == ["Wie komme ich zurück?"] * 2
    finally:
        if isValid(dialog):
            dialog.close()
        app.processEvents()


def test_pilot_chat_context_offers_english_actions(desktop, monkeypatch):
    from PySide6.QtWidgets import QInputDialog

    from diffeoforge.desktop.pilot_assistant_context import context_for_view

    dispatched = []
    fit = {"directory": "earlier-fit", "candidate_id": "kept"}
    window = SimpleNamespace(
        _worker=None,
        _restoring_search=False,
        _guided_review_target=None,
        _guided_footer_action=None,
        review_next_button=SimpleNamespace(isHidden=lambda: True),
        next_step_button=SimpleNamespace(isHidden=lambda: True),
        start_button=SimpleNamespace(isHidden=lambda: True),
        _open_guided_working_fit=lambda *args: dispatched.append(args),
    )
    view = SimpleNamespace(
        snapshot=SimpleNamespace(attachment_comparison={}, candidates=[]),
        guidance={"checked": 1, "total": 2,
                  "feedback": {"candidate": {"choices": [
                      {"reference": fit, "label": "Test 1", "trial_index": 1},
                  ]}}},
    )
    options_seen = []

    def pick(_window, title, label, items, *, editable):
        options_seen.append((title, label, items, editable))
        return items[0], True

    monkeypatch.setattr(QInputDialog, "getItem", pick)
    context, callbacks = context_for_view(window, view)
    assert context["assistant_actions"] == {
        "work:0": "Open starting fit · Test 1", "history": "Saved fits"}
    callbacks["history"]()
    assert options_seen == [("Saved fits", "Choose a starting fit",
                             ["Open starting fit · Test 1"], False)]
    assert dispatched == [("candidate", fit)]


def test_chat_can_close_while_waiting_for_a_reply(desktop):
    from PySide6.QtCore import QThreadPool
    from shiboken6 import isValid

    from diffeoforge.desktop.pilot_assistant import show

    app, window = desktop
    entered, release = Event(), Event()
    dispatched = []

    def reply(_context, _message, _history):
        entered.set()
        assert release.wait(4)
        return {"message": "A fit is available.", "actions": ["late"]}

    dialog = show(window, {"assistant_actions": {"late": "Open saved fit"}},
                  reply=reply, invoke=dispatched.append)
    try:
        dialog.question.setPlainText("Was ist der nächste Schritt?")
        dialog.send.click()
        _wait(app, entered.is_set)
        assert dialog.close()
        assert not (isValid(dialog) and dialog.isVisible())
    finally:
        release.set()
        assert QThreadPool.globalInstance().waitForDone(4000)
        app.processEvents()
    assert not dispatched
