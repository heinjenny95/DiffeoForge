"""The pilot chat stays responsive and only dispatches selected pilot actions."""

from threading import Event, get_ident
from time import monotonic, sleep

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
        return {"message": "Der bessere Fit ist weiterhin gespeichert.", "actions": []}

    dialog = show(window, {}, reply=reply, invoke=lambda _: pytest.fail("Unexpected action"))
    try:
        dialog.question.setPlainText("x" * 1201)
        assert not dialog.send.isEnabled()
        assert "1200" in dialog.status.text()
        dialog.question.setPlainText("Wie komme ich zurück?")
        dialog.send.click()
        _wait(app, dialog.question.isEnabled)
        assert dialog.send.isEnabled()
        assert dialog.question.toPlainText() == "Wie komme ich zurück?"
        assert "erneut senden" in dialog.status.text()
        assert "private model diagnostic" not in dialog.transcript.toPlainText()
        dialog.send.click()
        _wait(app, dialog.question.isEnabled)
        assert "weiterhin gespeichert" in dialog.transcript.toPlainText()
        assert not dialog._action_buttons and dialog.status.isHidden()
        assert attempts == ["Wie komme ich zurück?"] * 2
    finally:
        if isValid(dialog):
            dialog.close()
        app.processEvents()


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
