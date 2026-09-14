"""Concise desktop front end for the resumable Validation Lab study."""

from __future__ import annotations

import shutil
import statistics
import threading
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, QTimer, QUrl, Signal, Slot
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

from diffeoforge.config import load_config, validate_input_paths
from diffeoforge.desktop.info_disclosure import InfoDisclosure
from diffeoforge.desktop.reference_runtime_estimate import estimate_reference_runtime
from diffeoforge.desktop.validation_preparation import check_cancelled
from diffeoforge.reference_holdout_study import (
    HOLDOUT_DIRECTORY_NAME,
    ReferenceHoldoutStudyRunner,
    ReferenceHoldoutStudySnapshot,
    create_reference_holdout_study,
    load_reference_holdout_study,
)
from diffeoforge.reference_validation_study import (
    ReferenceValidationStudyRunner,
    ReferenceValidationStudySnapshot,
    load_reference_validation_study,
)
from diffeoforge.report import collect_preflight
from diffeoforge.validation_progress import validation_progress, wall_seconds


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


class _PreparationWorker(QRunnable):
    """Single-flight, cooperatively cancelled preparation without engine launch."""

    def __init__(self, operation: Callable) -> None:
        super().__init__()
        self.operation = operation
        self.signals = _Signals()
        self.cancelled = threading.Event()

    def request_cancel(self) -> bool:
        self.cancelled.set()
        return True

    @Slot()
    def run(self) -> None:
        try:
            value = self.operation(self.cancelled, self.signals.event.emit)
            check_cancelled(self.cancelled)
        except Exception as error:
            self.signals.failed.emit(str(error))
        else:
            self.signals.succeeded.emit(value)


class _ValidationWorker(QRunnable):
    def __init__(self, runner: object) -> None:
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
        def forward(event: object) -> None:
            self.signals.event.emit(event)
            if isinstance(event, dict) and event.get("event") in {
                "run_completed",
                "run_failed",
                "run_interrupted",
                "evidence_recovery_required",
            }:
                # Hashing and geometry verification must never run on the GUI thread.
                loader = (
                    load_reference_holdout_study
                    if isinstance(self.runner, ReferenceHoldoutStudyRunner)
                    else load_reference_validation_study
                )
                snapshot = loader(self.runner.study_directory)
                self.signals.event.emit({"event": "snapshot", "snapshot": snapshot})

        try:
            snapshot = self.runner.run_all(event_callback=forward)
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            self.signals.failed.emit(str(error))
        else:
            self.signals.succeeded.emit(snapshot)
        finally:
            with self._lock:
                self._finished = True


class ReferenceValidationDialog(QDialog):
    """Run or resume all predeclared validation comparisons with compact guidance."""

    def __init__(
        self,
        study_directory: Path,
        parent: QWidget | None = None,
        *,
        prepare: Callable | None = None,
    ) -> None:
        super().__init__(parent)
        self.study_directory = study_directory.expanduser().resolve()
        self._snapshot: ReferenceValidationStudySnapshot | None = None
        self._holdout_snapshot: ReferenceHoldoutStudySnapshot | None = None
        self._worker: _ValidationWorker | _PreparationWorker | None = None
        self._preparing = False
        self._cancel_requested = False
        self._evidence_run_id: str | None = None
        self._active_mode: str | None = None
        self._active_run_id: str | None = None
        self._live_status: str | None = None
        self._live_progress_fraction = 0.0
        self._indeterminate_progress = False
        self._thread_pool = QThreadPool.globalInstance()
        self.setWindowTitle("DiffeoForge Validation Lab")
        self.resize(940, 760)
        self.setMinimumSize(760, 600)

        root = QVBoxLayout(self)
        title = QLabel("Validation Lab")
        title.setObjectName("title")
        root.addWidget(title)
        subtitle = QLabel(
            "Test parameter stability, then confirm it on untouched holdout subjects."
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
                    "universal optimum. The fixed-template holdout adds out-of-sample "
                    "geometric evidence without re-estimating the atlas. Independent "
                    "biological landmarks remain a separate later validation gate."
                ),
                parent=self,
            )
        )

        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        root.addWidget(self.progress)
        self.accounting_label = QLabel()
        self.accounting_label.setWordWrap(True)
        root.addWidget(self.accounting_label)
        self.elapsed_label = QLabel()
        self.elapsed_label.setWordWrap(True)
        root.addWidget(self.elapsed_label)

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
        self.design_disclosure = InfoDisclosure(
            "See frozen finalists and decision rule",
            "Loading frozen design…",
            parent=body,
        )
        body_layout.addWidget(self.design_disclosure)
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
        self._clock_timer = QTimer(self)
        self._clock_timer.setInterval(1000)
        self._clock_timer.timeout.connect(self._render_elapsed)
        self._clock_timer.start()

        def initial(cancelled: threading.Event, phase: Callable) -> object:
            if prepare is not None:
                directory = prepare(cancelled, phase)
            else:
                directory = self.study_directory
            phase("Verifying frozen inputs and existing evidence…")
            check_cancelled(cancelled)
            training = load_reference_validation_study(directory)
            check_cancelled(cancelled)
            holdout = directory / HOLDOUT_DIRECTORY_NAME
            held = load_reference_holdout_study(holdout) if holdout.is_dir() else None
            return training, held, None

        self._start_preparation(initial)

    def _design_details(self) -> str:
        if self._snapshot is None:
            return "Loading frozen design…"
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
        if self._preparing or self._snapshot is None:
            self.status_label.setText(self._live_status or "Preparing Validation Lab…")
            self.progress.setRange(0, 0 if self._preparing else 1)
            self.run_button.setEnabled(False)
            self.cancel_button.setVisible(self._preparing)
            self.cancel_button.setEnabled(self._preparing and not self._cancel_requested)
            self.close_button.setEnabled(not self._preparing)
            self.report_button.setVisible(False)
            return
        snapshot = self._display_snapshot()
        plan = self._snapshot.plan
        completed = snapshot.completed_run_count
        total = len(snapshot.runs)
        progress = validation_progress(
            self._snapshot,
            self._holdout_snapshot,
            active_mode=self._active_mode,
            active_run_id=self._active_run_id,
            evidence_run_id=self._evidence_run_id,
        )
        self.progress.setRange(0, max(1, progress.total))
        self.progress.setValue(progress.verified)
        self.progress.setFormat(
            f"{progress.verified} of {progress.total} run results verified · %p% of frozen runs"
            + (" · reports complete" if progress.reports_complete else " · validation not complete")
        )
        self.accounting_label.setText(
            f"Training {progress.training_verified}/{progress.training_total} · "
            f"Holdout {progress.holdout_verified}/{progress.holdout_total}\n"
            f"Backend finished {progress.backend_finished} · evidence pending "
            f"{progress.evidence_pending}, failed {progress.evidence_failed} · "
            f"execution failed {progress.execution_failed} · interrupted {progress.interrupted} · "
            f"active {progress.active} · pending {progress.pending}"
        )
        self._render_elapsed()
        self.design_label.setText(
            f"{len(plan.finalists)} frozen finalists • "
            f"{len(plan.training_subjects)} training subjects • "
            f"{len(plan.heldout_subjects)} untouched heldout subjects • "
            f"{plan.resample_count} resamples • "
            f"{len(self._snapshot.runs)} training/resample runs • "
            f"{len(plan.finalists)} fixed-template holdout runs"
        )
        running = self._worker is not None
        if running:
            self.status_label.setObjectName("status")
            self.status_label.setText(
                self._live_status
                or (
                    f"Validation is running: {completed} of {total} immutable runs "
                    "complete. Completed runs are retained if you cancel."
                )
            )
        elif self._snapshot.status == "completed" and self._holdout_snapshot is None:
            assessment = self._snapshot.assessment
            assert assessment is not None
            winner = assessment.recommended_finalist_id or "no unique finalist"
            support = (
                "not available"
                if assessment.winner_support is None
                else f"{assessment.winner_support:.0%}"
            )
            self.status_label.setObjectName("statusWarning")
            self.status_label.setText(
                f"Training/resampling comparison complete: {assessment.confidence}. "
                f"Preferred finalist: {winner}; cohort support: {support}."
            )
            heldout_count = len(self._snapshot.plan.heldout_subjects)
            self.result_label.setText(
                f"Ready for the scientific holdout gate: {heldout_count} "
                "untouched subjects × "
                f"{len(self._snapshot.plan.finalists)} frozen trained models = "
                f"{len(self._snapshot.plan.finalists)} additional Deformetrica runs."
            )
        elif isinstance(snapshot, ReferenceHoldoutStudySnapshot) and snapshot.status == "completed":
            assessment = snapshot.assessment
            assert assessment is not None
            support = (
                "not available"
                if assessment.subject_support is None
                else f"{assessment.subject_support:.0%}"
            )
            self.status_label.setObjectName(
                "statusSuccess" if assessment.status == "confirmed_on_holdout" else "statusWarning"
            )
            self.status_label.setText(
                f"Fixed-template holdout complete. Evidence: {assessment.status}. "
                f"Heldout preference: {assessment.preferred_finalist_id or 'none'}; "
                f"paired subject support: {support}."
            )
            self.result_label.setText(
                "The reserved subjects have now been evaluated without updating any "
                "trained template or control point. Independent anatomy-specific "
                "validation remains a separate scientific gate."
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
            self.result_label.setText("The frozen comparison is complete.")
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
                "Ready. No process has started. The design and every input are already hash-bound."
            )
            self.result_label.setText(
                "Next: run the green complete validation comparison. You do not need to "
                "select between candidates during execution."
            )
        self.status_label.setStyleSheet("")
        self.result_label.setStyleSheet("")
        self.cancel_button.setVisible(running)
        self.cancel_button.setEnabled(running and not self._cancel_requested)
        report_path = self._report_path()
        self.report_button.setVisible(report_path is not None)
        self.report_button.setEnabled(report_path is not None and not running)
        all_complete = (
            self._holdout_snapshot is not None and self._holdout_snapshot.status == "completed"
        )
        self.run_button.setVisible(not all_complete)
        self.run_button.setEnabled(not running and not all_complete)
        if self._snapshot.status != "completed":
            self.run_button.setText(
                "Continue training/resampling comparison"
                if self._snapshot.completed_run_count
                else "Run training/resampling comparison"
            )
        elif self._holdout_snapshot is None:
            self.run_button.setText("Prepare and run fixed-template holdout")
        else:
            self.run_button.setText(
                "Continue fixed-template holdout"
                if self._holdout_snapshot.completed_run_count
                else "Run fixed-template holdout"
            )
        _emphasize(self.run_button, self.run_button.isEnabled())
        self.close_button.setEnabled(not running)

    @Slot()
    def _run(self) -> None:
        if self._worker is not None or self._snapshot is None:
            return
        directory = self.study_directory

        def prepare(cancelled: threading.Event, phase: Callable) -> object:
            phase("Verifying the frozen study and retained evidence…")
            training = load_reference_validation_study(directory)
            check_cancelled(cancelled)
            held_dir = directory / HOLDOUT_DIRECTORY_NAME
            held = load_reference_holdout_study(held_dir) if held_dir.is_dir() else None
            if training.status != "completed":
                mode = "training"
                execution_snapshot = training
                runner = ReferenceValidationStudyRunner(directory)
            else:
                mode = "holdout"
                if held is None:
                    phase("Preparing fixed-template holdout inputs; no engine has started…")
                    check_cancelled(cancelled)
                    held = create_reference_holdout_study(directory)
                execution_snapshot = held
                runner = ReferenceHoldoutStudyRunner(held.study_directory)
            check_cancelled(cancelled)
            phase("Checking mesh geometry, storage and workload…")
            text = self._preflight_text(execution_snapshot, mode=mode, cancelled=cancelled)
            return training, held, (runner, mode, text)

        self._start_preparation(prepare)

    def _start_preparation(self, operation: Callable) -> None:
        if self._worker is not None:
            return
        worker = _PreparationWorker(operation)
        worker.signals.event.connect(self._preparation_phase)
        worker.signals.succeeded.connect(self._prepared)
        worker.signals.failed.connect(self._preparation_failed)
        self._worker = worker
        self._preparing = True
        self._cancel_requested = False
        self._live_status = "Preparing — no engine has started. You can cancel safely."
        self._render()
        self._thread_pool.start(worker)

    @Slot(object)
    def _preparation_phase(self, text: object) -> None:
        if not self._cancel_requested:
            self._live_status = str(text)
            self._render()

    @Slot(object)
    def _prepared(self, value: object) -> None:
        cancelled = self._cancel_requested
        self._worker = None
        self._preparing = False
        if cancelled:
            self._preparation_failed("Preparation cancelled. No engine was started.")
            return
        self._snapshot, self._holdout_snapshot, execution = value
        self.study_directory = self._snapshot.study_directory
        self.design_disclosure.content_widget.setText(self._design_details())
        self._live_status = None
        self._render()
        if execution is None:
            return
        runner, mode, text = execution
        # This is the only launch boundary: GUI confirmation after background verification.
        if (
            text
            and QMessageBox.question(
                self,
                "Validation workload preflight",
                text,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        if self._cancel_requested:
            return
        worker = _ValidationWorker(runner)
        worker.signals.event.connect(self._event)
        worker.signals.succeeded.connect(self._succeeded)
        worker.signals.failed.connect(self._failed)
        self._worker = worker
        self._active_mode = mode
        self._active_run_id = None
        self._evidence_run_id = None
        self._live_status = None
        self._live_progress_fraction = 0.0
        self._indeterminate_progress = False
        self._render()
        self._thread_pool.start(worker)

    @Slot(str)
    def _preparation_failed(self, message: str) -> None:
        self._worker = None
        self._preparing = False
        self._live_status = message
        self._render()
        self.status_label.setText(message)
        if not self._cancel_requested:
            QMessageBox.critical(self, "Validation Lab preparation paused", message)

    def _render_elapsed(self) -> None:
        if self._snapshot is None:
            return
        if (
            self._holdout_snapshot is not None
            and self._holdout_snapshot.status == "completed"
            and self._holdout_snapshot.completed_at is None
        ):
            self.elapsed_label.setText(
                "Study finished; completion time unavailable in legacy ledger."
            )
            return
        elapsed = wall_seconds(
            self._snapshot.first_started_at,
            end=self._holdout_snapshot.completed_at if self._holdout_snapshot else None,
            now=datetime.now(UTC),
        )
        self.elapsed_label.setText(
            "Original start time unavailable (not started or legacy untimed ledger)."
            if elapsed is None
            else f"Since original start: {self._format_duration(elapsed)} "
            "(wall time, including pauses/offline time; not compute time)."
        )

    @Slot(object)
    def _event(self, event: object) -> None:
        if not isinstance(event, dict):
            return
        if event.get("event") == "snapshot":
            snapshot = event["snapshot"]
            if isinstance(snapshot, ReferenceHoldoutStudySnapshot):
                self._holdout_snapshot = snapshot
            else:
                self._snapshot = snapshot
            self._render()
            return
        if event.get("event") == "run_started":
            self._active_run_id = str(event.get("run_id", "current run"))
            self._evidence_run_id = None
            if (
                self._snapshot is not None
                and not any(r.attempts for r in self._snapshot.runs)
                and self._snapshot.first_started_at is None
            ):
                self._snapshot = replace(self._snapshot, first_started_at=event.get("recorded_at"))
            self._live_progress_fraction = 0.001
            self._indeterminate_progress = True
            self._live_status = (
                f"Starting {self._active_run_id}. The first complete optimizer "
                "iteration can take much longer than later iterations."
            )
            self._render()
            return
        if event.get("event") == "worker_event":
            self._render_worker_event(event)
            return
        if event.get("event") == "backend_completed":
            self._evidence_run_id = str(event["run_id"])
            self._live_status = f"{self._evidence_run_id}: backend finished; verifying evidence…"
            self._render()
            return
        if event.get("event") in {
            "run_completed",
            "run_failed",
            "run_interrupted",
            "evidence_recovery_required",
        }:
            self._live_progress_fraction = 0.0
            self._indeterminate_progress = False
            self._active_run_id = None
            self._evidence_run_id = None
            self._live_status = None
            self._render()

    @Slot(object)
    def _succeeded(self, snapshot: object) -> None:
        self._worker = None
        if isinstance(snapshot, ReferenceHoldoutStudySnapshot):
            self._holdout_snapshot = snapshot
        elif isinstance(snapshot, ReferenceValidationStudySnapshot):
            self._snapshot = snapshot
        self._active_mode = None
        self._active_run_id = None
        self._evidence_run_id = None
        self._live_status = None
        self._live_progress_fraction = 0.0
        self._indeterminate_progress = False
        self._render()

    @Slot(str)
    def _failed(self, message: str) -> None:
        self._worker = None
        self._active_mode = None
        self._active_run_id = None
        self._evidence_run_id = None
        self._live_status = None
        self._live_progress_fraction = 0.0
        self._indeterminate_progress = False
        self._render()
        QMessageBox.critical(self, "Validation Lab paused", message)

    @Slot()
    def _cancel(self) -> None:
        if self._worker is not None:
            self._cancel_requested = True
            self._worker.request_cancel()
            self.cancel_button.setEnabled(False)
            self.status_label.setText(
                "Cancelling preparation at the next safe boundary; no engine will start."
                if self._preparing
                else "Cancellation requested. DiffeoForge is stopping the active run safely."
            )

    @Slot()
    def _open_report(self) -> None:
        path = self._report_path()
        if path is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _display_snapshot(
        self,
    ) -> ReferenceValidationStudySnapshot | ReferenceHoldoutStudySnapshot:
        if self._active_mode == "training":
            return self._snapshot
        if self._holdout_snapshot is not None:
            return self._holdout_snapshot
        return self._snapshot

    def _report_path(self) -> Path | None:
        if (
            self._holdout_snapshot is not None
            and self._holdout_snapshot.report_html_path is not None
        ):
            return self._holdout_snapshot.report_html_path
        return self._snapshot.report_html_path

    @staticmethod
    def _format_duration(seconds: float) -> str:
        total = max(0, int(round(seconds)))
        hours, remainder = divmod(total, 3600)
        minutes, remaining = divmod(remainder, 60)
        if hours:
            return f"{hours} h {minutes:02d} min"
        if minutes:
            return f"{minutes} min {remaining:02d} s"
        return f"{remaining} s"

    @staticmethod
    def _format_bytes(value: float) -> str:
        if value >= 1024**3:
            return f"{value / 1024**3:.1f} GiB"
        if value >= 1024**2:
            return f"{value / 1024**2:.0f} MiB"
        return f"{value / 1024:.0f} KiB"

    def _preflight_text(
        self,
        snapshot: ReferenceValidationStudySnapshot | ReferenceHoldoutStudySnapshot,
        *,
        mode: str,
        cancelled: threading.Event,
    ) -> str:
        pending = [run for run in snapshot.runs if run.status != "completed"]
        if not pending:
            return ""
        first_preflight = collect_preflight(pending[0].config_path)
        estimate = estimate_reference_runtime(first_preflight)
        completed_durations = [
            float(run.evidence.runtime_seconds)
            for run in snapshot.runs
            if run.evidence is not None and run.evidence.runtime_seconds is not None
        ]
        if completed_durations:
            per_run = statistics.median(completed_durations)
            typical = per_run * len(pending)
            lower = typical * 0.65
            upper = typical * 1.8
            estimate_basis = "measured completed runs from this validation"
        else:
            typical = estimate.typical_seconds * len(pending)
            lower = estimate.lower_seconds * len(pending)
            upper = estimate.upper_seconds * len(pending)
            estimate_basis = (
                "same-project pilot observations"
                if estimate.confidence == "pilot_calibrated"
                else "a deliberately broad engineering estimate"
            )
        protected_input_bytes = 0
        subject_registrations = 0
        maximum_iterations = 0
        for run in pending:
            check_cancelled(cancelled)
            config = load_config(run.config_path)
            inputs = validate_input_paths(config, run.config_path)
            subject_registrations += inputs.subject_count
            maximum_iterations = max(
                maximum_iterations, int(config["optimization"]["max_iterations"])
            )
            protected_input_bytes += inputs.template.stat().st_size + sum(
                path.stat().st_size for path in inputs.subjects
            )
            if inputs.initial_control_points is not None:
                protected_input_bytes += inputs.initial_control_points.stat().st_size
        disk_typical = protected_input_bytes * 5.0
        disk_upper = protected_input_bytes * 10.0
        free = shutil.disk_usage(snapshot.study_directory).free
        label = (
            "training/resampling atlas estimation"
            if mode == "training"
            else "fixed-template heldout registration"
        )
        text = (
            f"DiffeoForge is about to start {len(pending)} immutable Deformetrica "
            f"runs for {label}.\n\n"
            f"Workload: {subject_registrations} total subject registrations; each run "
            f"may use up to {maximum_iterations} optimizer iterations.\n"
            f"Planning time: typically about {self._format_duration(typical)}, with a "
            f"broad range of {self._format_duration(lower)} to "
            f"{self._format_duration(upper)} ({estimate_basis}).\n"
            f"Disk planning: roughly {self._format_bytes(disk_typical)}, with an upper "
            f"planning allowance near {self._format_bytes(disk_upper)}; "
            f"{self._format_bytes(free)} is currently free.\n\n"
            "The first iteration can remain visually quiet for several minutes. Once "
            "Deformetrica logs iterations, this window will show the active run, exact "
            "iteration and separate run/study elapsed time. Iteration-cap projections "
            "are not predicted completion times. The computer must remain awake. "
            "Safe cancellation retains every completed run for later continuation.\n\n"
            "Start now?"
        )
        check_cancelled(cancelled)
        return text

    def _render_worker_event(self, envelope: dict[str, object]) -> None:
        raw = envelope.get("worker_event")
        if not isinstance(raw, dict):
            return
        kind = raw.get("kind")
        payload = raw.get("payload")
        if not isinstance(payload, dict):
            return
        snapshot = self._display_snapshot()
        total = len(snapshot.runs)
        run_id = str(envelope.get("run_id", self._active_run_id or "current run"))
        run_number = next(
            (i + 1 for i, run in enumerate(snapshot.runs) if run.run_id == run_id), "?"
        )
        self._active_run_id = run_id
        if kind == "activity":
            elapsed = float(payload.get("elapsed_seconds", 0.0))
            last = payload.get("last_iteration")
            if last is None:
                self._indeterminate_progress = True
                detail = "computing the first complete optimizer iteration"
            else:
                self._indeterminate_progress = False
                maximum = int(payload.get("maximum_iterations", 1))
                self._live_progress_fraction = min(0.999, int(last) / max(1, maximum))
                detail = (
                    f"active between iterations; last logged iteration {last} of "
                    f"{payload.get('maximum_iterations')}"
                )
            self._live_status = (
                f"Run {run_number} of {total}: {run_id} — {detail}. "
                f"This run elapsed {self._format_duration(elapsed)}."
            )
        elif kind == "progress":
            self._indeterminate_progress = False
            iteration = int(payload["iteration"])
            maximum = int(payload["maximum_iterations"])
            elapsed = float(payload["elapsed_seconds"])
            self._live_progress_fraction = min(0.999, iteration / max(1, maximum))
            eta = payload.get("eta_to_iteration_cap_seconds")
            eta_text = (
                "iteration-cap projection warming up"
                if eta is None
                else f"iteration-cap scenario {self._format_duration(float(eta))} "
                "(not a completion estimate or upper bound)"
            )
            contention = (
                " Resource contention detected; the estimate has widened."
                if payload.get("resource_contention_detected")
                else ""
            )
            self._live_status = (
                f"Run {run_number} of {total}: {run_id} — iteration {iteration} of "
                f"maximum {maximum}; elapsed {self._format_duration(elapsed)}; "
                f"{eta_text}.{contention}"
            )
        self._render()

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
