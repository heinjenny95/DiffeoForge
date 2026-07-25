"""Desktop review and execution dialog for staged Deformetrica calibration."""

from __future__ import annotations

import threading
from collections.abc import Mapping
from pathlib import Path, PurePosixPath

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, QUrl, Signal, Slot
from PySide6.QtGui import QCloseEvent, QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
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

from diffeoforge.desktop.landmark_3d_widget import InteractiveMeshCanvas3D
from diffeoforge.desktop.mesh_preview import load_mesh_preview
from diffeoforge.reference_calibration_study import (
    CalibrationStudyCandidateState,
    ReferenceCalibrationStudyRunner,
    ReferenceCalibrationStudySnapshot,
    load_reference_calibration_study,
    record_reference_calibration_stage_review,
)
from diffeoforge.result_report import collect_run_report


class _CalibrationSignals(QObject):
    event = Signal(object)
    succeeded = Signal(object)
    failed = Signal(str)


class _CalibrationStageWorker(QRunnable):
    def __init__(self, runner: ReferenceCalibrationStudyRunner) -> None:
        super().__init__()
        self.runner = runner
        self.signals = _CalibrationSignals()
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
            result = self.runner.run_current_stage(
                event_callback=self.signals.event.emit
            )
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            self.signals.failed.emit(str(error))
        else:
            self.signals.succeeded.emit(result)
        finally:
            with self._lock:
                self._finished = True


class CalibrationCandidateViewerDialog(QDialog):
    """Review the atlas and all subject reconstructions from one immutable run."""

    def __init__(
        self,
        candidate: CalibrationStudyCandidateState,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        if candidate.run_directory is None:
            raise ValueError("Candidate has no completed run directory")
        self.setWindowTitle(f"Calibration QC — {candidate.candidate_id}")
        self.resize(1040, 820)
        layout = QVBoxLayout(self)
        intro = QLabel(
            "Rotate and inspect the final atlas and every pilot-subject reconstruction. "
            "This visual check is required before DiffeoForge will accept a stage choice."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        report = collect_run_report(candidate.run_directory)
        output = candidate.run_directory / "output"
        paths: list[tuple[str, Path]] = []
        for record in report.inventory:
            relative = PurePosixPath(str(record["path"]))
            name = relative.name
            if (
                "__EstimatedParameters__Template_" not in name
                and "__Reconstruction__" not in name
            ):
                continue
            path = output.joinpath(*relative.parts).resolve()
            if not path.is_file() or not path.is_relative_to(output.resolve()):
                continue
            label = (
                "Final atlas template"
                if "__EstimatedParameters__Template_" in name
                else name.split("__subject_", 1)[-1].removesuffix(".vtk")
            )
            paths.append((label, path))
        if not paths:
            raise ValueError("Candidate run contains no atlas or reconstruction VTK")
        self.mesh_combo = QComboBox()
        for label, path in paths:
            self.mesh_combo.addItem(label, str(path))
        self.mesh_combo.currentIndexChanged.connect(self._load_selected)
        layout.addWidget(self.mesh_combo)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.canvas = InteractiveMeshCanvas3D()
        self.canvas.set_picking_enabled(False)
        self.canvas.setMinimumHeight(620)
        layout.addWidget(self.canvas, 1)
        controls = QHBoxLayout()
        reset = QPushButton("Reset view")
        reset.clicked.connect(self.canvas.reset_view)
        close = QPushButton("Close visual review")
        close.clicked.connect(self.accept)
        controls.addWidget(reset)
        controls.addStretch()
        controls.addWidget(close)
        layout.addLayout(controls)
        self._load_selected(0)

    @Slot(int)
    def _load_selected(self, _index: int) -> None:
        path = Path(str(self.mesh_combo.currentData())).resolve()
        try:
            model = load_mesh_preview(path)
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            self.canvas.set_model(None)
            self.status.setText(f"Mesh could not be displayed: {error}")
            return
        self.canvas.set_model(model)
        self.canvas.reset_view()
        self.status.setText(
            f"{path.name} · {model.point_count} points · "
            f"{model.triangle_count} triangles · read-only"
        )


class ReferenceCalibrationDialog(QDialog):
    """Execute one stage at a time and require explicit candidate review."""

    def __init__(
        self,
        study_directory: Path,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.study_directory = study_directory.resolve()
        self._snapshot = load_reference_calibration_study(self.study_directory)
        self._worker: _CalibrationStageWorker | None = None
        self._thread_pool = QThreadPool.globalInstance()
        self._approval_checks: dict[str, QCheckBox] = {}
        self.setWindowTitle("Automatic Deformetrica pilot calibration")
        self.resize(1040, 820)
        self.setMinimumSize(850, 650)

        root = QVBoxLayout(self)
        title = QLabel("Automatic staged pilot calibration")
        title.setObjectName("title")
        root.addWidget(title)
        boundary = QLabel(
            "DiffeoForge runs every predeclared candidate automatically. It never "
            "chooses anatomical correctness automatically: each stage pauses for your "
            "visual QC and explicit selection."
        )
        boundary.setWordWrap(True)
        root.addWidget(boundary)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.progress.setFormat("Ready")
        root.addWidget(self.progress)
        self.status = QLabel()
        self.status.setWordWrap(True)
        root.addWidget(self.status)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.content = QWidget()
        self.content_layout = QVBoxLayout(self.content)
        self.scroll.setWidget(self.content)
        root.addWidget(self.scroll, 1)

        footer = QHBoxLayout()
        self.cancel_button = QPushButton("Cancel safely")
        self.cancel_button.clicked.connect(self._cancel)
        self.start_button = QPushButton("Run all candidates in this stage")
        self.start_button.clicked.connect(self._start)
        self.advance_button = QPushButton("Approve selection & prepare next stage")
        self.advance_button.clicked.connect(self._advance)
        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        footer.addWidget(self.cancel_button)
        footer.addStretch()
        footer.addWidget(self.start_button)
        footer.addWidget(self.advance_button)
        footer.addWidget(close)
        root.addLayout(footer)
        self._render()

    @property
    def snapshot(self) -> ReferenceCalibrationStudySnapshot:
        return self._snapshot

    def _clear_content(self) -> None:
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._approval_checks = {}

    def _render(self) -> None:
        self._snapshot = load_reference_calibration_study(self.study_directory)
        self._clear_content()
        running = self._worker is not None
        if self._snapshot.status == "completed":
            self.status.setText(
                "All four stages are complete. The selected configuration is ready "
                "for a separate full-cohort confirmation run."
            )
            path = self._snapshot.final_config_path
            label = QLabel(
                "Selected configuration:\n"
                + (str(path) if path is not None else "unavailable")
            )
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            label.setWordWrap(True)
            self.content_layout.addWidget(label)
            if path is not None:
                open_button = QPushButton("Open selected configuration")
                open_button.clicked.connect(
                    lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
                )
                self.content_layout.addWidget(open_button)
            self.progress.setRange(0, 1)
            self.progress.setValue(1)
            self.progress.setFormat("Calibration complete")
            self.start_button.hide()
            self.advance_button.hide()
            self.cancel_button.setEnabled(False)
            self.content_layout.addStretch()
            return
        stage = self._snapshot.current_stage
        assert stage is not None
        heading = QLabel(
            f"Stage {stage.order} of {len(self._snapshot.plan.stages)} — {stage.title}"
        )
        heading.setObjectName("sectionTitle")
        self.content_layout.addWidget(heading)
        rule = QLabel(stage.decision_rule)
        rule.setWordWrap(True)
        self.content_layout.addWidget(rule)
        completed = sum(
            candidate.status == "completed"
            for candidate in self._snapshot.candidates
        )
        self.progress.setRange(0, len(self._snapshot.candidates))
        self.progress.setValue(completed)
        self.progress.setFormat(
            f"{completed} of {len(self._snapshot.candidates)} candidates completed"
        )
        for candidate in self._snapshot.candidates:
            self.content_layout.addWidget(self._candidate_card(candidate))
        self.content_layout.addStretch()
        awaiting = self._snapshot.status == "awaiting_review"
        retryable = any(
            candidate.status in {"failed", "interrupted", "orphaned"}
            for candidate in self._snapshot.candidates
        )
        self.start_button.setText(
            "Retry failed candidates"
            if awaiting and retryable
            else "Run all candidates in this stage"
        )
        self.start_button.setVisible(not awaiting or retryable)
        self.start_button.setEnabled(not running)
        self.cancel_button.setEnabled(running)
        self.advance_button.setVisible(awaiting)
        self.advance_button.setEnabled(awaiting and not running)
        self.status.setText(
            "Candidate execution is ready. Already completed candidates are "
            "retained when you continue."
            if not awaiting
            else (
                "Execution has paused. Open every completed candidate, inspect "
                "atlas and reconstructions, approve the acceptable candidates, "
                "then select one."
            )
        )
        if awaiting:
            self.selection_combo = QComboBox()
            self.selection_combo.addItem("Select one approved candidate…", None)
            for candidate in self._snapshot.candidates:
                if candidate.status == "completed":
                    self.selection_combo.addItem(
                        f"{candidate.candidate_id} — {candidate.label}",
                        candidate.candidate_id,
                    )
            self.content_layout.insertWidget(
                max(0, self.content_layout.count() - 1),
                self.selection_combo,
            )

    def _candidate_card(
        self,
        candidate: CalibrationStudyCandidateState,
    ) -> QWidget:
        card = QFrame()
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        title = QLabel(
            f"{candidate.candidate_id} — {candidate.label} — {candidate.status}"
        )
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        if candidate.metrics is not None:
            metrics = candidate.metrics
            detail = QLabel(
                "Geometric surface-distance QC p95: "
                f"{float(metrics['residual_p95']):.6g}\n"
                "Atlas area-distortion p95: "
                f"{float(metrics['distortion_p95']):.6g}\n"
                "Final regularity magnitude: "
                f"{float(metrics['deformation_energy']):.6g}\n"
                f"Runtime: {float(metrics['runtime_seconds']):.1f} s\n"
                f"Optimizer convergence evidence: "
                f"{'yes' if metrics['converged'] else 'no'}"
            )
            detail.setWordWrap(True)
            detail.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
            )
            layout.addWidget(detail)
            row = QHBoxLayout()
            viewer = QPushButton("Open atlas & all reconstructions…")
            viewer.clicked.connect(
                lambda _checked=False, value=candidate: self._open_candidate(value)
            )
            approval = QCheckBox(
                "I inspected this candidate and approve its anatomical registration QC"
            )
            self._approval_checks[candidate.candidate_id] = approval
            row.addWidget(viewer)
            row.addWidget(approval, 1)
            layout.addLayout(row)
        elif candidate.error:
            error = QLabel(candidate.error)
            error.setWordWrap(True)
            layout.addWidget(error)
        else:
            detail = QLabel(
                "No process has started for this candidate."
                if candidate.status == "pending"
                else "A new immutable attempt will be created when the stage continues."
            )
            detail.setWordWrap(True)
            layout.addWidget(detail)
        return card

    @Slot()
    def _start(self) -> None:
        if self._worker is not None:
            return
        runner = ReferenceCalibrationStudyRunner(self.study_directory)
        worker = _CalibrationStageWorker(runner)
        worker.signals.event.connect(self._event)
        worker.signals.succeeded.connect(self._succeeded)
        worker.signals.failed.connect(self._failed)
        self._worker = worker
        self.start_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.status.setText(
            "DiffeoForge is running the stage candidates sequentially. Closing is "
            "disabled until the current candidate reaches a terminal state."
        )
        self._thread_pool.start(worker)

    @Slot(object)
    def _event(self, event: Mapping[str, object]) -> None:
        kind = str(event["event"])
        candidate_id = str(event.get("candidate_id", ""))
        if kind == "candidate_started":
            self.status.setText(f"{candidate_id}: immutable pilot run started.")
        elif kind == "candidate_worker_event":
            worker = event["worker_event"]
            payload = worker["payload"]
            if worker["kind"] == "progress":
                self.status.setText(
                    f"{candidate_id}: Deformetrica iteration "
                    f"{payload['iteration']} of {payload['maximum_iterations']}."
                )
            elif worker["kind"] == "phase":
                self.status.setText(f"{candidate_id}: {payload['message']}")
            elif worker["kind"] == "activity":
                self.status.setText(
                    f"{candidate_id}: engine active for "
                    f"{float(payload['elapsed_seconds']):.0f} seconds."
                )
        elif kind == "candidate_completed":
            self.status.setText(
                f"{candidate_id} completed; automatic QC metrics were verified."
            )
        elif kind in {"candidate_failed", "candidate_interrupted"}:
            self.status.setText(f"{candidate_id}: {event['error']}")

    @Slot(object)
    def _succeeded(self, _snapshot: ReferenceCalibrationStudySnapshot) -> None:
        self._worker = None
        self._render()

    @Slot(str)
    def _failed(self, message: str) -> None:
        self._worker = None
        self._render()
        self.status.setText(f"Calibration stage could not continue: {message}")

    @Slot()
    def _cancel(self) -> None:
        if self._worker is None:
            return
        if self._worker.request_cancel():
            self.cancel_button.setEnabled(False)
            self.status.setText(
                "Cancellation requested. The current candidate is being stopped "
                "safely; completed candidates remain available."
            )

    @Slot()
    def _advance(self) -> None:
        selected = self.selection_combo.currentData()
        if selected is None:
            QMessageBox.warning(
                self,
                "Select a candidate",
                "Choose one visually approved candidate before continuing.",
            )
            return
        approvals = {
            candidate_id: check.isChecked()
            for candidate_id, check in self._approval_checks.items()
        }
        try:
            _snapshot, assessment = record_reference_calibration_stage_review(
                self.study_directory,
                visual_approvals=approvals,
                selected_candidate_id=str(selected),
            )
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            QMessageBox.warning(self, "Stage selection rejected", str(error))
            return
        self._render()
        balanced = assessment.balanced_candidate_id
        self.status.setText(
            f"Researcher selection recorded: {selected}. "
            f"Transparent balanced-score suggestion was: {balanced or 'none'}. "
            "The suggestion did not make the decision."
        )

    def _open_candidate(self, candidate: CalibrationStudyCandidateState) -> None:
        try:
            dialog = CalibrationCandidateViewerDialog(candidate, self)
            dialog.exec()
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            QMessageBox.warning(self, "Candidate viewer unavailable", str(error))

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._worker is None:
            event.accept()
            return
        QMessageBox.information(
            self,
            "Calibration still running",
            "Cancel safely first and wait until the current candidate reaches a "
            "terminal state before closing this window.",
        )
        event.ignore()
