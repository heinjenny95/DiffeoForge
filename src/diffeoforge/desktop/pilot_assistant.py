"""A local chat view with explicit actions supplied by the current pilot."""

from collections.abc import Mapping, Sequence

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from diffeoforge.desktop.preview_mesh_loader import PreviewMeshLoader

_MAX_QUESTION = 1200
_TEXT = {
    "de": {
        "title": "Pilot-Chat",
        "scope": "Lokal · Empfehlungen zum aktuellen Pilotstand",
        "welcome": "Beschreibe kurz, was am Fit passt und was noch fehlt.",
        "history": "Chatverlauf",
        "you": "Du",
        "assistant": "Pilot",
        "question": "Deine Frage",
        "placeholder": "Zwei Stellen passen. Wie bessere ich die dritte nach?",
        "send": "Senden",
        "close": "Schließen",
        "busy": "Ich prüfe den Pilotstand …",
        "error": "Die Antwort konnte nicht erstellt werden. Du kannst die Frage erneut senden.",
        "length": "Bitte kürze deine Frage auf höchstens 1200 Zeichen.",
    },
    "en": {
        "title": "Pilot chat",
        "scope": "Local · Recommendations for this pilot stage",
        "welcome": "Describe what fits well and what still needs work.",
        "history": "Chat history",
        "you": "You",
        "assistant": "Pilot",
        "question": "Your question",
        "placeholder": "Two areas look good. How do I improve the third?",
        "send": "Send",
        "close": "Close",
        "busy": "Checking the pilot stage …",
        "error": "The reply could not be generated. You can send the question again.",
        "length": "Please shorten your question to 1200 characters or fewer.",
    },
}


class PilotAssistantDialog(QDialog):
    def __init__(self, window, context, *, reply, invoke):
        super().__init__(window)
        self._context = context
        self._reply = reply
        self._invoke = invoke
        self._labels = dict(context.get("assistant_actions", {}))
        self._text = _TEXT.get(context.get("assistant_language", "de"), _TEXT["en"])
        self._history = []
        self._pending = None
        self._action_buttons = []
        self._loader = PreviewMeshLoader(self)
        self._loader.loaded.connect(self._show_reply)
        self._loader.failed.connect(self._show_error)
        self.finished.connect(self._loader.cancel)
        self.setWindowTitle(self._text["title"])
        self.resize(570, 455)

        layout = QVBoxLayout(self)
        caption = QLabel(self._text["scope"])
        caption.setObjectName("sectionTitle")
        caption.setWordWrap(True)
        layout.addWidget(caption)
        self.transcript = QPlainTextEdit()
        self.transcript.setReadOnly(True)
        self.transcript.setAccessibleName(self._text["history"])
        layout.addWidget(self.transcript, 1)
        self._append(self._text["assistant"], self._text["welcome"])

        self._actions = QWidget()
        self._actions_layout = QVBoxLayout(self._actions)
        self._actions_layout.setContentsMargins(0, 0, 0, 0)
        self._actions.hide()
        layout.addWidget(self._actions)
        self.status = QLabel()
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        self.status.hide()
        layout.addWidget(self.status)

        self.question = QPlainTextEdit()
        self.question.setAccessibleName(self._text["question"])
        self.question.setPlaceholderText(self._text["placeholder"])
        self.question.setMaximumHeight(self.question.fontMetrics().lineSpacing() * 3 + 20)
        self.question.textChanged.connect(self._update_controls)
        layout.addWidget(self.question)

        row = QHBoxLayout()
        row.addStretch()
        self.send = QPushButton(self._text["send"])
        self.send.setObjectName("primary")
        self.send.setAutoDefault(False)
        self.send.clicked.connect(self._send)
        row.addWidget(self.send)
        close = QPushButton(self._text["close"])
        close.setAutoDefault(False)
        close.clicked.connect(self.reject)
        row.addWidget(close)
        layout.addLayout(row)
        for key in ("Ctrl+Return", "Ctrl+Enter"):
            shortcut = QShortcut(QKeySequence(key), self.question)
            shortcut.activated.connect(self._send)
        self._update_controls()
        self.question.setFocus()

    def _append(self, speaker, message):
        self.transcript.appendPlainText(f"{speaker}\n{message}\n")
        self.transcript.verticalScrollBar().setValue(self.transcript.verticalScrollBar().maximum())

    def _set_status(self, text):
        self.status.setText(text)
        self.status.setVisible(bool(text))

    def _update_controls(self):
        length = len(self.question.toPlainText().strip())
        self.send.setEnabled(self._pending is None and 0 < length <= _MAX_QUESTION)
        if length > _MAX_QUESTION:
            self._set_status(self._text["length"])
        elif self.status.text() == self._text["length"]:
            self._set_status("")

    def _send(self):
        if not self.send.isEnabled():
            return
        message = self.question.toPlainText().strip()
        self._pending = message
        self._show_actions(())
        self._set_status(self._text["busy"])
        self.question.clear()
        self.question.setEnabled(False)
        self._update_controls()
        self._append(self._text["you"], message)
        reply, context, history = self._reply, self._context, tuple(self._history)
        self._loader.request_operation(message, lambda: reply(context, message, history))

    def _show_reply(self, question, result):
        if (not isinstance(result, Mapping) or not isinstance(result.get("message"), str)
                or not result["message"].strip()):
            self._show_error(question, "")
            return
        self._history.append((question, result["message"]))
        self._append(self._text["assistant"], result["message"])
        status = result.get("status", "")
        self._set_status(status if isinstance(status, str) else "")
        self._show_actions(result.get("actions", ()))
        self._finish_request()

    def _show_error(self, question, _detail):
        self._set_status(self._text["error"])
        self.question.setPlainText(question)
        self._finish_request()

    def _finish_request(self):
        self._pending = None
        self.question.setEnabled(True)
        self._update_controls()
        self.question.setFocus()

    def _show_actions(self, suggestions):
        for button in self._action_buttons:
            self._actions_layout.removeWidget(button)
            button.setEnabled(False)
            button.hide()
            button.deleteLater()
        self._action_buttons.clear()
        seen = set()
        if isinstance(suggestions, Sequence) and not isinstance(suggestions, str):
            for action in suggestions:
                if not isinstance(action, str) or action not in self._labels or action in seen:
                    continue
                seen.add(action)
                button = QPushButton(self._labels[action])
                button.setAutoDefault(False)
                button.clicked.connect(
                    lambda _checked=False, key=action, source=button: self._choose(key, source)
                )
                self._actions_layout.addWidget(button)
                self._action_buttons.append(button)
                if len(seen) == 2:
                    break
        self._actions.setVisible(bool(seen))

    def _choose(self, action, source):
        if self._pending is not None or source not in self._action_buttons:
            return
        invoke = self._invoke
        self._show_actions(())
        self.accept()
        invoke(action)


def show(window, context, *, reply, invoke):
    """Use an evidence snapshot and only dispatch an explicit verified action ID.

    reply(context, question, history) runs off the UI thread. Its result has a
    plain-text message and optional status and action IDs. The caller rechecks
    the selected action against the current pilot when invoking it.
    """
    dialog = PilotAssistantDialog(window, context, reply=reply, invoke=invoke)
    dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    dialog.open()
    return dialog
