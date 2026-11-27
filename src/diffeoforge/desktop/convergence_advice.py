"""Asynchronous diagnosis for the selected completed run."""

from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QObject, Qt, QTimer
from PySide6.QtWidgets import QHBoxLayout, QLabel

from diffeoforge.convergence_advice import run_advice
from diffeoforge.reference_atlas_stop import MORPHOSPACE_STABILITY
from diffeoforge.reference_morphospace_stopping import read_morphospace_stability
from diffeoforge.runs import ToleranceContinuation, run_status, tolerance_extension_preview

_POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix="convergence-advice")


def _comparison_text(row, iteration, required):
    previous = row["previous_iteration"]
    span = row["window_iterations"]
    window = (
        f"Accepted iterations {previous} → {iteration} · {span}/{required} joint iterations"
        if previous is not None else
        f"Accepted iteration {iteration} · collecting {required}-iteration window"
    )
    if span < required and previous is not None:
        window += " (partial)"
    if row["status"] == "measured":
        cohort = row["cohort_percent"]
        specimen = row["max_subject_percent"]
        names = ", ".join(row["worst_subjects"])
        cohort_result = "within threshold" if cohort < 1.0 else "above or at threshold"
        specimen_result = "within threshold" if specimen < 2.0 else "above or at threshold"
        metrics = (
            f"Cohort {cohort:.4g}% (requires <1%; {cohort_result}) · "
            f"Highest specimen {specimen:.4g}% (requires <2%; {specimen_result}) · {names}"
        )
    else:
        metrics = "Morphospace stability cannot yet be assessed from the saved fields."
    return f"{window}\n{metrics}"


def morphospace_text(row):
    iteration = row["iteration"]
    long_window = row["long_window"]
    short = _comparison_text(row, iteration, 200)
    long = (
        "400-iteration window is still collecting accepted joint steps."
        if long_window["window_iterations"] < 400
        and long_window["previous_iteration"] == row["previous_iteration"]
        else _comparison_text(long_window, iteration, 400)
    )
    value = row["weighted_fit_error"]
    attachment = "" if value is None else f"\nWeighted fit error {value:.6g}"
    return f"{short}\n{long}{attachment}"


def _review_advice(source):
    maximum, advice = None, ""
    try:
        maximum, advice = run_advice(source)
    except (OSError, RuntimeError, TypeError, ValueError, KeyError):
        pass
    try:
        evidence = read_morphospace_stability(source)
    except (OSError, RuntimeError, TypeError, ValueError, KeyError):
        return None, "The saved atlas stopping evidence could not be verified."
    if evidence is not None:
        terminal = evidence["terminal"]
        if terminal is None or terminal["reason"] != "iteration_limit":
            maximum = None
        if terminal is None:
            lifecycle = run_status(source)["status"]
            reason = {
                "interrupted": "Run interrupted before a terminal optimizer assessment",
                "failed": "Backend failed before a terminal optimizer assessment",
            }.get(lifecycle, "No terminal optimizer assessment was saved")
        else:
            reason = {
                "morphospace_stable": "Morphospace stability criterion met",
                "native_tolerance": "Native objective-change tolerance reached",
                "iteration_limit": "Iteration limit reached",
                "line_search_exhausted": "Line search exhausted",
                "optimizer_callback": "Optimizer stopped by its callback",
                "numerical_failure": "Numerical failure",
                "backend_failure": "Backend failure",
                "cancelled": "Cancelled",
            }[terminal["reason"]]
        rows = evidence["observations"]
        stability_stop = evidence["policy"]["mode"] == MORPHOSPACE_STABILITY
        mode = (
            "Run until morphospace stabilizes" if stability_stop else
            "Stop at optimizer convergence and review"
        )
        if evidence["policy"].get("unlimited_iterations"):
            mode += " (no iteration limit)"
        lines = [f"{mode} · {reason}"]
        if stability_stop:
            lines.append(
                morphospace_text(rows[-1]) if rows else "No accepted state could be assessed."
            )
            if rows and rows[-1]["previous_iteration"] is not None:
                previous = rows[-1]["previous_iteration"]
                old = next(row for row in rows if row["iteration"] == previous)
                lines.append(
                    f"Weighted fit error over the short comparison window "
                    f"{old['weighted_fit_error']:.6g} → {rows[-1]['weighted_fit_error']:.6g}"
                )
            if (terminal is not None and terminal["reason"] == "iteration_limit"
                    and (not rows or rows[-1]["window_iterations"] < 200)):
                lines.append("The full 200-iteration window was unavailable at the limit.")
        if len(rows) > 1:
            lines.append(
                f"Weighted fit error, first to last checkpoint "
                f"{rows[0]['weighted_fit_error']:.6g} → {rows[-1]['weighted_fit_error']:.6g}"
            )
        advice = "\n".join(lines)
        if terminal is not None and terminal["export"] == "complete":
            advice += "\nReview the saved reconstructions in Visual QC for anatomical plausibility."
        elif terminal is not None:
            advice += "\nFinal reconstruction export " + {
                "failed": "failed or was interrupted.",
                "not_started": "did not start.",
                "pending": "has no recorded completion.",
            }[terminal["export"]]
    try:
        continuation = tolerance_extension_preview(source)
    except (OSError, RuntimeError, TypeError, ValueError, KeyError):
        continuation = None
    return (continuation if continuation is not None else maximum), advice


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
        self.window._iteration_extension_after_tolerance = False
        for widget in (*self.buttons, *self.labels):
            widget.hide()
        if self.future is not None:
            self.future.cancel()
        self.future = None if source is None else _POOL.submit(_review_advice, source)
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
        if not advice:
            return
        tolerance = isinstance(maximum, ToleranceContinuation)
        for button, label in zip(self.buttons, self.labels, strict=True):
            label.setText(advice)
            label.show()
            if tolerance:
                button.setText("Continue +300 iterations with tighter tolerance…")
                button.setToolTip(
                    f"Accepted checkpoint {maximum.checkpoint_iteration}, "
                    f"new cap {maximum.maximum_iterations}. "
                    f"Tolerance {maximum.source_tolerance:g} → {maximum.tolerance:g}."
                )
                button.show()
            elif maximum is not None:
                button.setText(f"Continue +300 iterations ({maximum} → {maximum + 300})")
                button.setToolTip(
                    "Continue from the saved state in a new run; previous results are retained."
                )
                button.show()
        self.window._iteration_extension_source = self.source if maximum is not None else None
        self.window._iteration_extension_after_tolerance = tolerance
