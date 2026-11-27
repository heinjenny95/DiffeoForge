"""Select the stopping rule and budget for a successor to a completed atlas."""

from math import isfinite

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
)

from diffeoforge.desktop.convergence_advice import TERMINAL_REASONS
from diffeoforge.reference_atlas_stop import (
    ITERATION_TARGET,
    MORPHOSPACE_STABILITY,
    MORPHOSPACE_STABILITY_UNLIMITED,
    OPTIMIZER_CONVERGENCE,
)


class AtlasContinuationDialog(QDialog):
    def __init__(self, source, parent=None):
        super().__init__(parent)
        self.source = source
        self.setWindowTitle("Continue from this atlas checkpoint")
        self.setMinimumWidth(470)
        layout = QVBoxLayout(self)
        reason = TERMINAL_REASONS[source.source_reason]
        previous_limit = source.source_maximum_iterations
        summary = QLabel(
            f"{reason} at accepted iteration {source.checkpoint_iteration}."
            + (f" Previous iteration limit {previous_limit}." if previous_limit else "")
        )
        summary.setWordWrap(True)
        layout.addWidget(summary)

        form = QFormLayout()
        self.rule = QComboBox()
        self.rule.addItem("Optimizer convergence", OPTIMIZER_CONVERGENCE)
        self.rule.addItem("Run to iteration number", ITERATION_TARGET)
        self.rule.addItem("Morphospace stability (recommended)", MORPHOSPACE_STABILITY)
        self.rule.setCurrentIndex(self.rule.findData(source.source_mode))
        form.addRow("Stopping rule", self.rule)
        self.tolerance = QComboBox()
        self.tolerance.setEditable(True)
        self.tolerance.addItems(["1e-6", "1e-4"])
        self.tolerance.setCurrentText(str(source.source_tolerance))
        self.tolerance_label = QLabel("Objective-change tolerance")
        form.addRow(self.tolerance_label, self.tolerance)
        default_limit = previous_limit
        if default_limit is None or default_limit <= source.checkpoint_iteration:
            default_limit = source.checkpoint_iteration + 300
        self.limit = QLineEdit(str(default_limit))
        self.limit_label = QLabel("New total iteration limit")
        form.addRow(self.limit_label, self.limit)
        self.unlimited = QCheckBox("No joint iteration limit")
        self.unlimited.setChecked(
            source.source_mode == MORPHOSPACE_STABILITY and previous_limit is None
        )
        form.addRow(self.unlimited)
        layout.addLayout(form)

        self.detail = QLabel()
        self.detail.setWordWrap(True)
        layout.addWidget(self.detail)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.review = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.review.setText("Review continuation")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.rule.currentIndexChanged.connect(self._update)
        self.tolerance.currentTextChanged.connect(self._update)
        self.limit.textChanged.connect(self._update)
        self.unlimited.toggled.connect(self._update)
        self._update()

    def options(self):
        mode = self.rule.currentData()
        if mode == MORPHOSPACE_STABILITY and self.unlimited.isChecked():
            return {"quality_stop": MORPHOSPACE_STABILITY_UNLIMITED}
        limit = int(self.limit.text())
        extra = limit - self.source.checkpoint_iteration
        if extra <= 0:
            raise ValueError("Enter a total iteration limit above the saved checkpoint.")
        if mode == ITERATION_TARGET:
            return {"iteration_limit": limit}
        if mode == MORPHOSPACE_STABILITY:
            return {"quality_stop": MORPHOSPACE_STABILITY, "quality_iterations": extra}
        tolerance = float(self.tolerance.currentText())
        if not isfinite(tolerance) or tolerance <= 0:
            raise ValueError("Enter a positive, finite optimizer tolerance.")
        return {"optimizer_tolerance": tolerance, "iteration_limit": limit}

    def _update(self):
        native = self.rule.currentData() == OPTIMIZER_CONVERGENCE
        quality = self.rule.currentData() == MORPHOSPACE_STABILITY
        self.tolerance.setVisible(native)
        self.tolerance_label.setVisible(native)
        self.unlimited.setVisible(quality)
        capped = not quality or not self.unlimited.isChecked()
        self.limit.setEnabled(capped)
        self.limit_label.setEnabled(capped)
        try:
            options = self.options()
        except (ValueError, OverflowError):
            self.review.setEnabled(False)
            self.detail.setText(
                f"Enter a whole-number limit above {self.source.checkpoint_iteration}"
                + (" and a positive, finite tolerance." if native else ".")
            )
            return
        self.review.setEnabled(True)
        budget = (f"Up to {int(self.limit.text()) - self.source.checkpoint_iteration} more "
                  "joint iterations. " if capped else "")
        if native:
            detail = (
                f"Source tolerance {self.source.source_tolerance:g}. The optimizer can stop "
                "as soon as the selected tolerance is met, even with a higher iteration limit."
            )
        elif quality:
            first = self.source.checkpoint_iteration + 200
            detail = (
                f"The first full comparison is at iteration {first}. "
                "Stop when distance changes are below 1% for the cohort and 2% for every "
                "specimen. A 400-iteration comparison also applies once available."
            )
            if capped and options["quality_iterations"] < 200:
                detail += " This budget ends before the first full comparison."
        else:
            detail = (
                "Continue to the chosen iteration even if an objective or morphospace "
                "threshold is met earlier. Cancellation or a technical stop can end the run."
            )
        self.detail.setText(budget + detail)
