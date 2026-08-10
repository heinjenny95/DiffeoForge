"""Concise desktop front end for the resumable Validation Lab study."""

from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, QUrl, Signal, Slot
from PySide6.QtGui import QCloseEvent, QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from diffeoforge.desktop.info_disclosure import InfoDisclosure
from diffeoforge.reference_validation_study import (
    ReferenceValidationStudyRunner,
    ReferenceValidationStudySnapshot,
    load_reference_validation_study,
)


def _emphasize(button: QPushButton, enabled: bool) -> None:
    button.setObjectName("primary" if enabled else "secondary")
    style = button.style()
    style.unpolish(button)
    style.polish(button)
    button.update()


class _Signals(QObject):
    event = Signal(object)
    succeeded = Signal(object)
    failed = Signal(str)


class _ValidationWorker(QRunnable):
    def __init__(self, runner: ReferenceValidationStudyRunner) -> None:
        super().__init__()
        self.runner = runner
        self.signals = _Signals()
        self._lock = threading.Lock()
        self._finished = False

    def request_cancel(self) -> bool:
        with self._lock:
            if self._finished:
                return False
        return self.runner.request_cancel()

    @Slot()
    def run(self) -> None:
        try:
            snapshot = self.runner.run_all(event_callback=self.signals.event.emit)
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            self.signals.failed.emit(str(error))
        else:
            self.signals.succeeded.emit(snapshot)
        finally:
            with self._lock:
                self._finished = True


class ReferenceValidationDialog(QDialog):
    """Run or resume all predeclared validation comparisons with compact guidance."""

    def __init__(self, study_directory: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.study_directory = study_directory.expanduser().resolve()
        self._snapshot = load_reference_validation_study(self.study_directory)
        self._worker: _ValidationWorker | None = None
        self._thread_pool = QThreadPool.globalInstance()
        self.setWindowTitle("DiffeoForge Validation Lab")
        self.resize(940, 760)
        self.setMinimumSize(760, 600)

        root = QVBoxLayout(self)
        title = QLabel("Validation Lab")
        title.setObjectName("title")
        root.addWidget(title)
        subtitle = QLabel(
            "Test whether the pilot-selected parameters remain preferred when the "
            "training cohort changes. DiffeoForge runs the complete frozen comparison "
            "and produces one uncertainty-aware report."
        )
        subtitle.setWordWrap(True)
        root.addWidget(subtitle)
        root.addWidget(
            InfoDisclosure(
                "What this can and cannot prove",
                (
                    "A robust result means the same finalist is preferred across the "
                    "predeclared training and resampling comparisons, using external "
                    "surface error and deformation distortion. It supports robustness "
                    "within this tested parameter neighborhood. It does not prove a "
                    "universal optimum, and the reserved subjects remain untouched until "
                    "fixed-template registration is implemented. Independent biological "
                    "landmarks remain a later validation gate."
                ),
                parent=self,
            )
        )

        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)
        self.progress = QProgressBar()
        self.progress.setRange(0, len(self._snapshot.runs))
        root.addWidget(self.progress)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        body_layout = QVBoxLayout(body)
        self.design_label = QLabel()
        self.design_label.setWordWrap(True)
        self.design_label.setObjectName("card")
        body_layout.addWidget(self.design_label)
        body_layout.addWidget(
            InfoDisclosure(
                "See frozen finalists and decision rule",
                self._design_details(),
                parent=body,
            )
        )
        self.result_label = QLabel()
        self.result_label.setWordWrap(True)
        self.result_label.setObjectName("status")
        body_layout.addWidget(self.result_label)
        body_layout.addStretch()
        scroll.setWidget(body)
        root.addWidget(scroll, 1)

        actions = QHBoxLayout()
        self.cancel_button = QPushButton("Cancel safely")
        self.cancel_button.setObjectName("danger")
        self.cancel_button.clicked.connect(self._cancel)
        self.report_button = QPushButton("Open validation report")
        self.report_button.clicked.connect(self._open_report)
        self.run_button = QPushButton("Run complete validation comparison")
        self.run_button.clicked.connect(self._run)
        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.close)
        actions.addWidget(self.cancel_button)
        actions.addStretch()
        actions.addWidget(self.report_button)
        actions.addWidget(self.close_button)
        actions.addWidget(self.run_button)
        root.addLayout(actions)
        self._render()

    def _design_details(self) -> str:
        lines = ["Frozen finalists:"]
        for finalist in self._snapshot.plan.finalists:
            values = finalist.values
            lines.append(
                f"• {finalist.label}: attachment {values['attachment_kernel_width']:.6g}; "
                f"deformation {values['deformation_kernel_width']:.6g}; control spacing "
                f"{values['initial_control_point_spacing']:.6g}; noise "
                f"{values['noise_std']:.6g}; time points {int(values['timepoints'])}."
            )
        lines.extend(("", "Decision rule:", *self._snapshot.plan.selection_rule))
        return "\n".join(lines)

    def _render(self) -> None:
        snapshot = self._snapshot
        completed = snapshot.completed_run_count
        total = len(snapshot.runs)
        self.progress.setValue(completed)
        self.design_label.setText(
            f"{len(snapshot.plan.finalists)} frozen finalists • "
            f"{len(snapshot.plan.training_subjects)} training subjects • "
            f"{len(snapshot.plan.heldout_subjects)} untouched heldout subjects • "
            f"{snapshot.plan.resample_count} resamples • {total} total atlas runs"
        )
        running = self._worker is not None
        if running:
            self.status_label.setObjectName("status")
            self.status_label.setText(
                f"Validation is running: {completed} of {total} immutable runs complete. "
                "Completed runs are retained if you cancel."
            )
        elif snapshot.status == "completed" and snapshot.assessment is not None:
            assessment = snapshot.assessment
            self.status_label.setObjectName(
                "statusSuccess"
                if assessment.status == "robust_within_search_space"
                else "statusWarning"
            )
            winner = assessment.recommended_finalist_id or "no unique finalist"
            support = (
                "not available"
                if assessment.winner_support is None
                else f"{assessment.winner_support:.0%}"
            )
            self.status_label.setText(
                f"Comparison complete. Evidence: {assessment.confidence}. "
                f"Preferred finalist: {winner}; cohort support: {support}."
            )
            self.result_label.setText(
                "Next scientific gates: fixed-template registration of the untouched "
                "holdout and an independent anatomy-specific validation criterion."
            )
        elif snapshot.status in {"ready_to_retry", "interrupted"}:
            self.status_label.setObjectName("statusWarning")
            self.status_label.setText(
                f"{completed} of {total} runs are complete. Continue to retry only the "
                "missing or interrupted runs; completed evidence will not be repeated."
            )
            self.result_label.setText("No final comparison is reported until every run completes.")
        else:
            self.status_label.setObjectName("status")
            self.status_label.setText(
                "Ready. No process has started. The design and every input are already "
                "hash-bound."
            )
            self.result_label.setText(
                "Next: run the green complete validation comparison. You do not need to "
                "select between candidates during execution."
            )
        self.status_label.setStyleSheet("")
        self.result_label.setStyleSheet("")
        self.cancel_button.setVisible(running)
        self.cancel_button.setEnabled(running)
        self.report_button.setVisible(snapshot.report_html_path is not None)
        self.report_button.setEnabled(snapshot.report_html_path is not None and not running)
        self.run_button.setVisible(snapshot.status != "completed")
        self.run_button.setEnabled(not running and snapshot.status != "completed")
        self.run_button.setText(
            "Continue validation comparison"
            if completed
            else "Run complete validation comparison"
        )
        _emphasize(self.run_button, self.run_button.isEnabled())
        self.close_button.setEnabled(not running)

    @Slot()
    def _run(self) -> None:
        if self._worker is not None:
            return
        runner = ReferenceValidationStudyRunner(self.study_directory)
        worker = _ValidationWorker(runner)
        worker.signals.event.connect(self._event)
        worker.signals.succeeded.connect(self._succeeded)
        worker.signals.failed.connect(self._failed)
        self._worker = worker
        self._render()
        self._thread_pool.start(worker)

    @Slot(object)
    def _event(self, event: object) -> None:
        if isinstance(event, dict) and event.get("event") in {
            "run_completed",
            "run_failed",
            "run_interrupted",
        }:
            try:
                self._snapshot = load_reference_validation_study(self.study_directory)
            except (OSError, RuntimeError, TypeError, ValueError):
                return
            self._render()

    @Slot(object)
    def _succeeded(self, snapshot: ReferenceValidationStudySnapshot) -> None:
        self._worker = None
        self._snapshot = snapshot
        self._render()

    @Slot(str)
    def _failed(self, message: str) -> None:
        self._worker = None
        try:
            self._snapshot = load_reference_validation_study(self.study_directory)
        except (OSError, RuntimeError, TypeError, ValueError):
            pass
        self._render()
        QMessageBox.critical(self, "Validation Lab paused", message)

    @Slot()
    def _cancel(self) -> None:
        if self._worker is not None:
            self._worker.request_cancel()
            self.cancel_button.setEnabled(False)
            self.status_label.setText(
                "Cancellation requested. DiffeoForge is stopping the active run safely."
            )

    @Slot()
    def _open_report(self) -> None:
        path = self._snapshot.report_html_path
        if path is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._worker is not None:
            QMessageBox.information(
                self,
                "Validation is still running",
                "Cancel the active validation safely before closing this window.",
            )
            event.ignore()
            return
        event.accept()
