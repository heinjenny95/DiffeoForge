"""Desktop review and execution dialog for staged Deformetrica calibration."""

from __future__ import annotations

import threading
from collections.abc import Mapping
from dataclasses import dataclass
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

from diffeoforge.desktop.calibration_comparison_widget import (
    CalibrationComparisonCanvas3D,
)
from diffeoforge.desktop.mesh_preview import load_mesh_preview
from diffeoforge.desktop.reference_calibration_presentation import (
    automatic_check_summary,
    candidate_parameter_summary,
    candidate_tradeoff_labels,
    stage_guidance,
    technical_metric_text,
)
from diffeoforge.reference_calibration import CalibrationCandidate
from diffeoforge.reference_calibration_study import (
    CalibrationStudyCandidateState,
    ReferenceCalibrationStudyRunner,
    ReferenceCalibrationStudySnapshot,
    load_reference_calibration_study,
    record_reference_calibration_stage_review,
)
from diffeoforge.result_report import collect_run_report


@dataclass(frozen=True)
class CalibrationQcPair:
    """One bound original/reconstruction pair for visual calibration QC."""

    pair_id: str
    label: str
    original_path: Path
    reconstruction_path: Path
    required: bool


def collect_calibration_qc_pairs(
    study_directory: Path,
    candidate: CalibrationStudyCandidateState,
) -> tuple[CalibrationQcPair, ...]:
    """Collect the initial-template/atlas and subject/reconstruction comparisons."""

    if candidate.run_directory is None:
        raise ValueError("Candidate has no completed run directory")
    root = study_directory.resolve()
    subjects_directory = (root / "inputs" / "subjects").resolve()
    template_directory = (root / "inputs" / "template").resolve()
    if not subjects_directory.is_dir() or not template_directory.is_dir():
        raise ValueError("Calibration study inputs are incomplete")
    subject_paths = {
        path.name: path.resolve() for path in subjects_directory.iterdir() if path.is_file()
    }
    template_paths = tuple(
        sorted(
            (path.resolve() for path in template_directory.iterdir() if path.is_file()),
            key=lambda path: path.name.casefold(),
        )
    )
    if len(template_paths) != 1:
        raise ValueError("Calibration study must contain exactly one bound template")

    report = collect_run_report(candidate.run_directory)
    output = (candidate.run_directory / "output").resolve()
    atlas_path: Path | None = None
    reconstructions: dict[str, Path] = {}
    for record in report.inventory:
        relative = PurePosixPath(str(record["path"]))
        name = relative.name
        path = output.joinpath(*relative.parts).resolve()
        if not path.is_file() or not path.is_relative_to(output):
            continue
        if "__EstimatedParameters__Template_" in name:
            atlas_path = path
            continue
        if "__Reconstruction__" not in name or "__subject_" not in name:
            continue
        encoded_source_name = name.split("__subject_", 1)[1]
        source_name = encoded_source_name.removesuffix(".vtk")
        reconstructions[source_name] = path
    if atlas_path is None:
        raise ValueError("Candidate run contains no final atlas VTK")
    missing = sorted(set(subject_paths) - set(reconstructions))
    unexpected = sorted(set(reconstructions) - set(subject_paths))
    if missing or unexpected:
        raise ValueError(
            "Original/reconstruction identity could not be matched exactly. "
            f"Missing reconstructions: {missing or 'none'}; "
            f"unexpected reconstructions: {unexpected or 'none'}"
        )

    pairs = [
        CalibrationQcPair(
            pair_id="atlas",
            label="Atlas overview — initial template vs final atlas",
            original_path=template_paths[0],
            reconstruction_path=atlas_path,
            required=False,
        )
    ]
    pairs.extend(
        CalibrationQcPair(
            pair_id=f"subject:{name}",
            label=f"Pilot specimen — {name}",
            original_path=path,
            reconstruction_path=reconstructions[name],
            required=True,
        )
        for name, path in sorted(
            subject_paths.items(),
            key=lambda item: item[0].casefold(),
        )
    )
    return tuple(pairs)


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
            result = self.runner.run_current_stage(event_callback=self.signals.event.emit)
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
        study_directory: Path,
        candidate: CalibrationStudyCandidateState,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        if candidate.run_directory is None:
            raise ValueError("Candidate has no completed run directory")
        self._pairs = collect_calibration_qc_pairs(study_directory, candidate)
        self._reviewed_pair_ids: set[str] = set()
        self._required_pair_ids = {pair.pair_id for pair in self._pairs if pair.required}
        self._required_pair_indexes = tuple(
            index for index, pair in enumerate(self._pairs) if pair.required
        )
        self.setWindowTitle(f"Visual registration check — {candidate.candidate_id}")
        self.resize(1080, 900)
        layout = QVBoxLayout(self)
        title = QLabel("Does the reconstruction preserve the original anatomy?")
        title.setObjectName("title")
        layout.addWidget(title)
        intro = QLabel(
            "Blue lines are the original pilot mesh. The orange surface is what "
            "Deformetrica reconstructed from the atlas. Where they overlap closely, "
            "the blue lines should sit on the orange surface."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        instructions = QLabel(
            "What to check\n"
            "1. Open every pilot specimen in the list.\n"
            "2. Rotate it and inspect the anatomical features important to your study.\n"
            "3. Pass this option only if those features are preserved and you see no "
            "implausible local stretching, collapse, or warping."
        )
        instructions.setWordWrap(True)
        instructions.setObjectName("card")
        layout.addWidget(instructions)
        self.mesh_combo = QComboBox()
        for index, pair in enumerate(self._pairs):
            if pair.required:
                specimen_number = self._required_pair_indexes.index(index) + 1
                label = (
                    f"Specimen {specimen_number} of {len(self._required_pair_indexes)} "
                    f"— {pair.label}"
                )
            else:
                label = f"Optional overview — {pair.label}"
            self.mesh_combo.addItem(label, index)
        self.mesh_combo.currentIndexChanged.connect(self._load_selected)
        specimen_navigation = QHBoxLayout()
        self.previous_specimen_button = QPushButton("← Previous specimen")
        self.previous_specimen_button.clicked.connect(lambda: self._navigate_required_specimen(-1))
        self.next_specimen_button = QPushButton("Next specimen →")
        self.next_specimen_button.clicked.connect(lambda: self._navigate_required_specimen(1))
        specimen_navigation.addWidget(self.previous_specimen_button)
        specimen_navigation.addWidget(self.mesh_combo, 1)
        specimen_navigation.addWidget(self.next_specimen_button)
        layout.addLayout(specimen_navigation)
        toggles = QHBoxLayout()
        self.show_original = QCheckBox("Show original (blue lines)")
        self.show_original.setChecked(True)
        self.show_reconstruction = QCheckBox("Show reconstruction (orange surface)")
        self.show_reconstruction.setChecked(True)
        toggles.addWidget(self.show_original)
        toggles.addWidget(self.show_reconstruction)
        toggles.addStretch()
        layout.addLayout(toggles)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.canvas = CalibrationComparisonCanvas3D()
        self.show_original.toggled.connect(self.canvas.set_show_original)
        self.show_reconstruction.toggled.connect(self.canvas.set_show_reconstruction)
        layout.addWidget(self.canvas, 1)
        self.review_progress = QLabel()
        self.review_progress.setWordWrap(True)
        layout.addWidget(self.review_progress)
        self.review_gate = QLabel()
        self.review_gate.setObjectName("status")
        self.review_gate.setWordWrap(True)
        layout.addWidget(self.review_gate)
        self.pass_check = QCheckBox(
            "Visual QC passed: I checked every pilot specimen, the important anatomy "
            "is preserved, and I see no implausible warping."
        )
        self.pass_check.hide()
        self.pass_check.toggled.connect(self._update_complete_button)
        layout.addWidget(self.pass_check)
        controls = QHBoxLayout()
        reset = QPushButton("Reset view")
        reset.clicked.connect(self.canvas.reset_view)
        close = QPushButton("Close without passing")
        close.clicked.connect(self.reject)
        self.complete_button = QPushButton("Record visual QC pass")
        self.complete_button.setEnabled(False)
        self.complete_button.clicked.connect(self.accept)
        controls.addWidget(reset)
        controls.addStretch()
        controls.addWidget(close)
        controls.addWidget(self.complete_button)
        layout.addLayout(controls)
        if self._required_pair_indexes:
            first_required = self._required_pair_indexes[0]
            combo_index = self.mesh_combo.findData(first_required)
            if self.mesh_combo.currentIndex() == combo_index:
                self._load_selected(combo_index)
            else:
                self.mesh_combo.setCurrentIndex(combo_index)
        self._update_review_progress()

    @property
    def review_complete(self) -> bool:
        return (
            self.result() == QDialog.DialogCode.Accepted
            and self.pass_check.isChecked()
            and self._required_pair_ids <= self._reviewed_pair_ids
        )

    @Slot(int)
    def _load_selected(self, _index: int) -> None:
        pair_index = self.mesh_combo.currentData()
        if pair_index is None:
            return
        pair = self._pairs[int(pair_index)]
        try:
            original = load_mesh_preview(pair.original_path)
            reconstruction = load_mesh_preview(pair.reconstruction_path)
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            self.status.setText(f"Comparison could not be displayed: {error}")
            return
        self.canvas.set_models(original, reconstruction)
        self.canvas.reset_view()
        self._reviewed_pair_ids.add(pair.pair_id)
        self.status.setText(
            f"Original: {pair.original_path.name} ({original.triangle_count} faces)  |  "
            f"Reconstruction: {pair.reconstruction_path.name} "
            f"({reconstruction.triangle_count} faces)  |  read-only"
        )
        self._update_review_progress()

    @Slot()
    def _navigate_required_specimen(self, direction: int) -> None:
        if not self._required_pair_indexes:
            return
        pair_index = self.mesh_combo.currentData()
        try:
            current_position = self._required_pair_indexes.index(int(pair_index))
        except (TypeError, ValueError):
            current_position = 0 if direction >= 0 else len(self._required_pair_indexes) - 1
        target_position = max(
            0,
            min(
                len(self._required_pair_indexes) - 1,
                current_position + direction,
            ),
        )
        target_pair_index = self._required_pair_indexes[target_position]
        self.mesh_combo.setCurrentIndex(self.mesh_combo.findData(target_pair_index))

    def _update_review_progress(self) -> None:
        reviewed = len(self._reviewed_pair_ids & self._required_pair_ids)
        total = len(self._required_pair_ids)
        complete = reviewed == total and total > 0
        pair_index = self.mesh_combo.currentData()
        try:
            current_position = self._required_pair_indexes.index(int(pair_index))
        except (TypeError, ValueError):
            current_position = -1
        self.previous_specimen_button.setEnabled(current_position > 0)
        self.next_specimen_button.setEnabled(
            0 <= current_position < len(self._required_pair_indexes) - 1
        )
        self.review_progress.setText(
            f"Visual review progress: {reviewed} of {total} pilot specimens opened."
        )
        self.review_gate.setText(
            "All required specimens have been opened. You can now record your "
            "visual-anatomy decision below."
            if complete
            else (
                f"Continue with Next specimen. {total - reviewed} required "
                f"comparison{'s' if total - reviewed != 1 else ''} remain."
            )
        )
        self.review_gate.setObjectName("statusSuccess" if complete else "status")
        self.review_gate.setStyleSheet("")
        self.pass_check.setVisible(complete)
        self.pass_check.setEnabled(complete)
        if not complete:
            self.pass_check.setChecked(False)
        self._update_complete_button()

    @Slot()
    def _update_complete_button(self) -> None:
        self.complete_button.setEnabled(self.pass_check.isEnabled() and self.pass_check.isChecked())


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
        self._visually_reviewed_candidates: set[str] = set()
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
                "Selected configuration:\n" + (str(path) if path is not None else "unavailable")
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
        guidance = stage_guidance(stage)
        question = QLabel(guidance.question)
        question.setObjectName("title")
        question.setWordWrap(True)
        self.content_layout.addWidget(question)
        explanation = QLabel(guidance.explanation)
        explanation.setWordWrap(True)
        self.content_layout.addWidget(explanation)
        task = QFrame()
        task.setObjectName("card")
        task_layout = QVBoxLayout(task)
        task_title = QLabel("What you need to do")
        task_title.setObjectName("sectionTitle")
        task_layout.addWidget(task_title)
        task_text = QLabel(guidance.action)
        task_text.setWordWrap(True)
        task_layout.addWidget(task_text)
        caution = QLabel("Important: " + guidance.caution)
        caution.setWordWrap(True)
        task_layout.addWidget(caution)
        self.content_layout.addWidget(task)
        completed = sum(candidate.status == "completed" for candidate in self._snapshot.candidates)
        self.progress.setRange(0, len(self._snapshot.candidates))
        self.progress.setValue(completed)
        self.progress.setFormat(
            f"{completed} of {len(self._snapshot.candidates)} candidates completed"
        )
        planned_by_id = {candidate.candidate_id: candidate for candidate in stage.candidates}
        tradeoffs = candidate_tradeoff_labels(self._snapshot.candidates)
        for index, candidate in enumerate(self._snapshot.candidates, start=1):
            self.content_layout.addWidget(
                self._candidate_card(
                    candidate,
                    planned_by_id[candidate.candidate_id],
                    option_index=index,
                    tradeoffs=tradeoffs[candidate.candidate_id],
                )
            )
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
                "The calculations are complete. Compare original meshes with their "
                "reconstructions, mark every anatomically acceptable option, then "
                "select one acceptable option."
            )
        )
        if awaiting:
            self.selection_combo = QComboBox()
            self.selection_combo.addItem(
                "After visual QC, choose one acceptable option…",
                None,
            )
            for index, candidate in enumerate(
                self._snapshot.candidates,
                start=1,
            ):
                if candidate.status == "completed":
                    option_letter = chr(ord("A") + index - 1)
                    self.selection_combo.addItem(
                        f"Option {option_letter} — {candidate.label}",
                        candidate.candidate_id,
                    )
            self.content_layout.insertWidget(
                max(0, self.content_layout.count() - 1),
                self.selection_combo,
            )

    def _candidate_card(
        self,
        candidate: CalibrationStudyCandidateState,
        planned: CalibrationCandidate,
        *,
        option_index: int,
        tradeoffs: tuple[str, ...],
    ) -> QWidget:
        card = QFrame()
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        option_letter = chr(ord("A") + option_index - 1)
        title = QLabel(f"Option {option_letter} — {candidate.label}")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        parameter, meaning = candidate_parameter_summary(
            self._snapshot.current_stage,
            planned.values,
            coordinate_unit=self._snapshot.plan.coordinate_unit,
        )
        parameter_label = QLabel(parameter)
        parameter_label.setObjectName("sectionTitle")
        parameter_label.setWordWrap(True)
        layout.addWidget(parameter_label)
        meaning_label = QLabel(meaning)
        meaning_label.setWordWrap(True)
        layout.addWidget(meaning_label)
        rationale = QLabel("Why this option exists: " + planned.rationale)
        rationale.setWordWrap(True)
        layout.addWidget(rationale)
        if candidate.metrics is not None:
            metrics = candidate.metrics
            passed, check_text = automatic_check_summary(metrics)
            check = QLabel(("✓ " if passed else "⚠ ") + check_text)
            check.setWordWrap(True)
            layout.addWidget(check)
            comparison_title = QLabel("How this option compares with the other completed options")
            comparison_title.setObjectName("sectionTitle")
            layout.addWidget(comparison_title)
            comparison = QLabel(
                "\n".join(f"• {label}" for label in tradeoffs)
                if tradeoffs
                else "No relative comparison is available yet."
            )
            comparison.setWordWrap(True)
            layout.addWidget(comparison)
            technical_button = QPushButton("Show technical measurements")
            technical_button.setCheckable(True)
            technical = QLabel(technical_metric_text(metrics))
            technical.setWordWrap(True)
            technical.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            technical.setVisible(False)
            technical_button.toggled.connect(technical.setVisible)
            technical_button.toggled.connect(
                lambda visible, button=technical_button: button.setText(
                    "Hide technical measurements" if visible else "Show technical measurements"
                )
            )
            layout.addWidget(technical_button)
            layout.addWidget(technical)
            row = QHBoxLayout()
            viewer = QPushButton("Compare originals & reconstructions…")
            viewer.clicked.connect(
                lambda _checked=False, value=candidate: self._open_candidate(value)
            )
            approval = QCheckBox("Visual QC passed — clear to revoke")
            visually_reviewed = candidate.candidate_id in self._visually_reviewed_candidates
            approval.setVisible(visually_reviewed)
            approval.setChecked(visually_reviewed)
            approval.setToolTip("Clear this check to revoke the visual QC pass.")
            visual_status = QLabel(
                "Visual QC recorded. This option can now be selected."
                if visually_reviewed
                else (
                    "Visual QC not recorded. Open the guided comparison and inspect "
                    "every pilot specimen."
                )
            )
            visual_status.setObjectName("statusSuccess" if visually_reviewed else "status")
            visual_status.setWordWrap(True)
            self._approval_checks[candidate.candidate_id] = approval
            row.addWidget(viewer)
            row.addWidget(visual_status, 1)
            row.addWidget(approval)
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
            self.status.setText(f"{candidate_id} completed; automatic QC metrics were verified.")
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
            candidate_id: check.isChecked() for candidate_id, check in self._approval_checks.items()
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
            dialog = CalibrationCandidateViewerDialog(
                self.study_directory,
                candidate,
                self,
            )
            dialog.exec()
            if dialog.review_complete:
                self._visually_reviewed_candidates.add(candidate.candidate_id)
                self._render()
                self.status.setText(
                    f"{candidate.candidate_id}: visual anatomy check passed. "
                    "You may still compare other options or revoke this pass."
                )
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
