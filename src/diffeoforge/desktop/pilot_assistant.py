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
_LENGTH_WARNING = f"Please shorten your question to {_MAX_QUESTION} characters or fewer."


class PilotAssistantDialog(QDialog):
    def __init__(self, window, context, *, reply, invoke):
        super().__init__(window)
        self._context = context
        self._reply = reply
        self._invoke = invoke
        self._labels = dict(context.get("assistant_actions", {}))
        self._history = []
        self._pending = None
        self._action_buttons = []
        self._loader = PreviewMeshLoader(self)
        self._loader.loaded.connect(self._show_reply)
        self._loader.failed.connect(self._show_error)
        self.finished.connect(self._loader.cancel)
        self.setWindowTitle("Pilot chat")
        self.resize(570, 455)

        layout = QVBoxLayout(self)
        caption = QLabel("Local · Recommendations for this pilot stage")
        caption.setObjectName("sectionTitle")
        caption.setWordWrap(True)
        layout.addWidget(caption)
        self.transcript = QPlainTextEdit()
        self.transcript.setReadOnly(True)
        self.transcript.setAccessibleName("Chat history")
        layout.addWidget(self.transcript, 1)
        self._append("Pilot", "Describe what fits well and what still needs work.")

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
        self.question.setAccessibleName("Your question")
        self.question.setPlaceholderText("The fit bridges an opening. How should I mark it?")
        self.question.setMaximumHeight(self.question.fontMetrics().lineSpacing() * 3 + 20)
        self.question.textChanged.connect(self._update_controls)
        layout.addWidget(self.question)

        row = QHBoxLayout()
        row.addStretch()
        self.send = QPushButton("Send")
        self.send.setObjectName("primary")
        self.send.setAutoDefault(False)
        self.send.clicked.connect(self._send)
        row.addWidget(self.send)
        close = QPushButton("Close")
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
            self._set_status(_LENGTH_WARNING)
        elif self.status.text() == _LENGTH_WARNING:
            self._set_status("")

    def _send(self):
        if not self.send.isEnabled():
            return
        message = self.question.toPlainText().strip()
        self._pending = message
        self._show_actions(())
        self._set_status("Checking the pilot stage …")
        self.question.clear()
        self.question.setEnabled(False)
        self._update_controls()
        self._append("You", message)
        reply, context, history = self._reply, self._context, tuple(self._history)
        self._loader.request_operation(message, lambda: reply(context, message, history))

    def _show_reply(self, question, result):
        if (not isinstance(result, Mapping) or not isinstance(result.get("message"), str)
                or not result["message"].strip()):
            self._show_error(question, "")
            return
        self._history.append((question, result["message"]))
        self._append("Pilot", result["message"])
        status = result.get("status", "")
        self._set_status(status if isinstance(status, str) else "")
        self._show_actions(result.get("actions", ()))
        self._finish_request()

    def _show_error(self, question, _detail):
        self._set_status("The reply could not be generated. You can send the question again.")
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
