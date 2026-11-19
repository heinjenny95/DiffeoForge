"""Asynchronous diagnosis for the selected completed run."""

from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QObject, Qt, QTimer
from PySide6.QtWidgets import QHBoxLayout, QLabel

from diffeoforge.convergence_advice import run_advice

_POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix="convergence-advice")


class ConvergenceAdviceController(QObject):
    def __init__(self, window, buttons):
        super().__init__(window)
        self.window, self.buttons = window, buttons
        self.source = None
        self.future = None
        self.labels = []
        self.timer = QTimer(self)
        self.timer.setInterval(40)
        self.timer.timeout.connect(self._poll)
        for button in buttons:
            label = QLabel(button.parentWidget())
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setWordWrap(True)
            label.hide()
            container = button.parentWidget()
            layout = container.layout()
            if isinstance(layout, QHBoxLayout):
                # A wrapped paragraph must not become another column of the footer.
                outer = container.parentWidget().layout()
                outer.insertWidget(outer.indexOf(container), label)
                label.setContentsMargins(24, 8, 24, 8)
            else:
                layout.addWidget(label)
            self.labels.append(label)

    def load(self, source):
        if source is not None and source == self.source and self.future is not None:
            return
        self.timer.stop()
        self.source = source
        self.window._iteration_extension_source = None
        for widget in (*self.buttons, *self.labels):
            widget.hide()
        if self.future is not None:
            self.future.cancel()
        self.future = None if source is None else _POOL.submit(run_advice, source)
        if self.future is not None:
            self.timer.start()

    def _poll(self):
        if self.future is None or not self.future.done():
            return
        self.timer.stop()
        try:
            maximum, advice = self.future.result()
        except (OSError, RuntimeError, TypeError, ValueError, KeyError):
            self.future = None
            return
        for button, label in zip(self.buttons, self.labels, strict=True):
            label.setText(advice)
            label.show()
            if maximum is not None:
                button.setText(f"Continue +300 iterations ({maximum} → {maximum + 300})")
                button.setToolTip(
                    "Continue from the saved state in a new run; previous results are retained."
                )
                button.show()
        self.window._iteration_extension_source = self.source if maximum is not None else None
