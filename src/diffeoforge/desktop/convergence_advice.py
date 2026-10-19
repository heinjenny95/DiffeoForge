"""Asynchronous cap assessment; stale results cannot update a different run."""

from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QLabel

from diffeoforge.convergence_advice import capped_run_advice

_POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix="cap-advice")


class CapAdviceController(QObject):
    def __init__(self, window, buttons):
        super().__init__(window)
        self.window, self.buttons = window, buttons
        self.future = None
        self.labels = []
        self.timer = QTimer(self)
        self.timer.setInterval(40)
        self.timer.timeout.connect(self._poll)
        for button in buttons:
            label = QLabel(button.parentWidget())
            label.setWordWrap(True)
            label.hide()
            button.parentWidget().layout().addWidget(label)
            self.labels.append(label)

    def load(self, source):
        self.timer.stop()
        self.source = source
        self.window._iteration_extension_source = None
        for widget in (*self.buttons, *self.labels):
            widget.hide()
        if self.future is not None:
            self.future.cancel()
        self.future = None if source is None else _POOL.submit(capped_run_advice, source)
        if self.future is not None:
            self.timer.start()

    def _poll(self):
        if self.future is None or not self.future.done():
            return
        self.timer.stop()
        try:
            maximum, advice = self.future.result()
        except (OSError, RuntimeError, TypeError, ValueError, KeyError):
            return
        self.window._iteration_extension_source = self.source
        for button, label in zip(self.buttons, self.labels, strict=True):
            button.setText(f"Continue +300 iterations ({maximum} → {maximum + 300})")
            button.setToolTip(
                "Continue from the saved state in a new run; previous results are retained."
            )
            button.show()
            label.setText(advice)
            label.show()
