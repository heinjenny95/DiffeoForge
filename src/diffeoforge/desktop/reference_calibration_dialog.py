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
    QInputDialog,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from diffeoforge.desktop.calibration_comparison_widget import (
    CalibrationComparisonCanvas3D,
)
from diffeoforge.desktop.info_disclosure import InfoDisclosure
from diffeoforge.desktop.mesh_preview import load_mesh_preview
from diffeoforge.desktop.reference_calibration_presentation import (
    CalibrationTradeoffAssessment,
    automatic_check_summary,
    candidate_parameter_summary,
    candidate_tradeoff_assessments,
    stage_guidance,
    technical_metric_text,
)
from diffeoforge.reference_calibration import (
    CalibrationCandidate,
    propose_calibration_search_extension,
)
from diffeoforge.reference_calibration_study import (
    CalibrationStudyCandidateState,
    ReferenceCalibrationStudyRunner,
    ReferenceCalibrationStudySnapshot,
    assess_reference_calibration_snapshot,
    create_reference_calibration_search_extension_study,
    load_reference_calibration_report,
    load_reference_calibration_study,
    next_reference_calibration_search_extension_destination,
    record_reference_calibration_provisional_override,
    record_reference_calibration_stage_review,
)
from diffeoforge.result_report import collect_run_report


def _set_action_emphasis(button: QPushButton, emphasized: bool) -> None:
    """Apply the shared primary/secondary action role immediately."""

    button.setObjectName("primary" if emphasized else "secondary")
    style = button.style()
    style.unpolish(button)
    style.polish(button)
    button.update()


def _set_choice_emphasis(combo: QComboBox, emphasized: bool) -> None:
    """Highlight the next required selection control."""

    combo.setObjectName("primaryChoice" if emphasized else "")
    style = combo.style()
    style.unpolish(combo)
    style.polish(combo)
    combo.update()


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
    def __init__(
        self,
        runner: ReferenceCalibrationStudyRunner,
        *,
        complete_automatic_pilot: bool = False,
    ) -> None:
        super().__init__()
        self.runner = runner
        self.complete_automatic_pilot = complete_automatic_pilot
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
            if self.complete_automatic_pilot:
                result = self.runner.run_complete_automatic_pilot(
                    event_callback=self.signals.event.emit
                )
            else:
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
        self._review_decision: bool | None = None
        self.setWindowTitle(f"Visual registration check — {candidate.candidate_id}")
        self.resize(1080, 900)
        self.setMinimumSize(760, 640)
        root = QVBoxLayout(self)
        self.body_scroll = QScrollArea()
        self.body_scroll.setWidgetResizable(True)
        self.body_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.body_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        body = QWidget()
        body.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Preferred,
        )
        layout = QVBoxLayout(body)
        self.body_scroll.setWidget(body)
        root.addWidget(self.body_scroll, 1)
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
        self.previous_specimen_button = QPushButton("← Previous")
        self.previous_specimen_button.clicked.connect(lambda: self._navigate_required_specimen(-1))
        self.next_specimen_button = QPushButton("Next →")
        self.next_specimen_button.clicked.connect(lambda: self._navigate_required_specimen(1))
        _set_action_emphasis(self.previous_specimen_button, False)
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
        reset = QPushButton("Reset view")
        reset.clicked.connect(lambda: self.canvas.reset_view())
        _set_action_emphasis(reset, False)
        toggles.addWidget(reset)
        layout.addLayout(toggles)
        self.status = QLabel()
        self.status.setObjectName("statusSuccess")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.canvas = CalibrationComparisonCanvas3D()
        self.show_original.toggled.connect(self.canvas.set_show_original)
        self.show_reconstruction.toggled.connect(self.canvas.set_show_reconstruction)
        layout.addWidget(self.canvas, 1)
        canvas_help = QLabel(
            "Controls: drag to rotate; right-drag to pan; use the mouse wheel to "
            "zoom; double-click to reset the view."
        )
        canvas_help.setObjectName("hint")
        canvas_help.setWordWrap(True)
        layout.addWidget(canvas_help)

        self.decision_panel = QFrame()
        self.decision_panel.setObjectName("card")
        decision_layout = QVBoxLayout(self.decision_panel)
        self.review_progress = QLabel()
        self.review_progress.setWordWrap(True)
        decision_layout.addWidget(self.review_progress)
        self.review_gate = QLabel()
        self.review_gate.setObjectName("status")
        self.review_gate.setWordWrap(True)
        decision_layout.addWidget(self.review_gate)
        self.pass_check = QCheckBox(
            "Visual QC passed: I checked every pilot specimen, the important anatomy "
            "is preserved, and I see no implausible warping."
        )
        # The explicit decision button is the visible confirmation. This private
        # check remains the immutable completion predicate.
        self.pass_check.hide()
        controls = QHBoxLayout()
        self.close_button = QPushButton("Close without recording")
        self.close_button.clicked.connect(self.reject)
        _set_action_emphasis(self.close_button, False)
        self.fail_button = QPushButton("Record: QC does not pass")
        self.fail_button.setObjectName("danger")
        self.fail_button.clicked.connect(self._record_visual_qc_fail)
        self.complete_button = QPushButton("Record: QC passes")
        self.complete_button.setEnabled(False)
        self.complete_button.clicked.connect(self._record_visual_qc_pass)
        controls.addStretch()
        controls.addWidget(self.close_button)
        controls.addWidget(self.fail_button)
        controls.addWidget(self.complete_button)
        decision_layout.addLayout(controls)
        root.addWidget(self.decision_panel)
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
            self._review_decision is True
            and self.pass_check.isChecked()
            and self._required_pair_ids <= self._reviewed_pair_ids
        )

    @property
    def review_recorded(self) -> bool:
        return self._review_decision is not None

    @property
    def review_passed(self) -> bool:
        return self._review_decision is True

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
        if direction > 0:
            try:
                current_pair_index = int(pair_index)
            except (TypeError, ValueError):
                current_pair_index = self._required_pair_indexes[0]
            unreviewed_indexes = tuple(
                index
                for index in self._required_pair_indexes
                if self._pairs[index].pair_id not in self._reviewed_pair_ids
            )
            if unreviewed_indexes:
                later_indexes = tuple(
                    index for index in unreviewed_indexes if index > current_pair_index
                )
                target_pair_index = (
                    later_indexes[0] if later_indexes else unreviewed_indexes[0]
                )
                self.mesh_combo.setCurrentIndex(
                    self.mesh_combo.findData(target_pair_index)
                )
                return
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
        self.next_specimen_button.setEnabled(not complete)
        self.review_progress.setText(
            f"Visual review progress: {reviewed} of {total} pilot specimens opened."
        )
        self.review_gate.setText(
            "Next: record your decision. Click the green button if the important "
            "anatomy is preserved, or record that this option does not pass."
            if complete
            else (
                f"Next: click the green Next → button. {total - reviewed} required "
                f"comparison{'s' if total - reviewed != 1 else ''} remain."
            )
        )
        self.review_gate.setObjectName("statusSuccess" if complete else "status")
        self.review_gate.setStyleSheet("")
        self.fail_button.setVisible(complete)
        self.fail_button.setEnabled(complete)
        self.complete_button.setEnabled(complete)
        _set_action_emphasis(self.next_specimen_button, not complete)
        _set_action_emphasis(self.complete_button, complete)

    @Slot()
    def _record_visual_qc_pass(self) -> None:
        if self._required_pair_ids <= self._reviewed_pair_ids:
            self._review_decision = True
            self.pass_check.setChecked(True)
            self.accept()

    @Slot()
    def _record_visual_qc_fail(self) -> None:
        if self._required_pair_ids <= self._reviewed_pair_ids:
            self._review_decision = False
            self.pass_check.setChecked(False)
            self.reject()


class ReferenceCalibrationDialog(QDialog):
    """Execute a complete automatic pilot or use optional stage-by-stage control."""

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
        self._review_buttons: dict[str, QPushButton] = {}
        self._visually_reviewed_candidates: set[str] = set()
        self._visually_approved_candidates: set[str] = set()
        self.setWindowTitle("Automatic Deformetrica pilot calibration")
        self.resize(1040, 820)
        self.setMinimumSize(850, 650)

        root = QVBoxLayout(self)
        title = QLabel("Automatic staged pilot calibration")
        title.setObjectName("title")
        root.addWidget(title)
        boundary = QLabel(
            "Standard mode runs all four parameter comparisons in one operation. "
            "Candidate sets are centered on the biological priorities you already "
            "declared. DiffeoForge then records a transparent provisional recommendation "
            "from the automatic evidence and creates a final report. This is not an "
            "automatic claim of anatomical correctness; optional visual QC and a manual "
            "stage-by-stage mode remain available."
        )
        boundary.setWordWrap(True)
        root.addWidget(
            InfoDisclosure(
                "How pilot calibration works",
                boundary,
                accessible_name="Information about automatic pilot calibration",
            )
        )
        self.advanced_mode = QCheckBox(
            "Advanced mode: pause after each stage and select every option manually"
        )
        self.advanced_mode.setToolTip(
            "Use this only when you want to override the transparent provisional "
            "recommendation after each parameter family."
        )
        self.advanced_mode.toggled.connect(lambda _checked: self._render())
        root.addWidget(self.advanced_mode)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.progress.setFormat("Ready")
        root.addWidget(self.progress)
        self.status = QLabel()
        self.status.setObjectName("statusSuccess")
        self.status.setWordWrap(True)
        root.addWidget(self.status)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.content = QWidget()
        self.content.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Preferred,
        )
        self.content_layout = QVBoxLayout(self.content)
        self.scroll.setWidget(self.content)
        root.addWidget(self.scroll, 1)

        footer = QHBoxLayout()
        self.footer = footer
        self.cancel_button = QPushButton("Cancel safely")
        self.cancel_button.clicked.connect(self._cancel)
        self.review_next_button = QPushButton("Review next option")
        self.review_next_button.clicked.connect(self._open_next_review)
        self.review_next_button.hide()
        self.selection_combo = QComboBox()
        self.selection_combo.setMaximumWidth(360)
        self.selection_combo.currentIndexChanged.connect(
            self._update_stage_review_action
        )
        self.selection_combo.hide()
        self.start_button = QPushButton("Run all candidates in this stage")
        self.start_button.clicked.connect(self._start)
        self.use_provisional_button = QPushButton("Use provisional recommendation")
        self.use_provisional_button.clicked.connect(self._use_provisional)
        self.use_provisional_button.hide()
        self.compare_options_button = QPushButton("Compare options")
        self.compare_options_button.clicked.connect(self._compare_options)
        self.compare_options_button.hide()
        self.collect_evidence_button = QPushButton("Collect more evidence…")
        self.collect_evidence_button.clicked.connect(self._collect_more_evidence)
        self.collect_evidence_button.hide()
        self.advance_button = QPushButton("Select option & prepare next stage")
        self.advance_button.clicked.connect(self._advance)
        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        self.close_button = close
        _set_action_emphasis(self.cancel_button, False)
        _set_action_emphasis(self.review_next_button, False)
        _set_action_emphasis(self.start_button, True)
        _set_action_emphasis(self.use_provisional_button, True)
        _set_action_emphasis(self.compare_options_button, False)
        _set_action_emphasis(self.collect_evidence_button, False)
        _set_action_emphasis(self.advance_button, False)
        _set_action_emphasis(self.close_button, False)
        footer.addWidget(self.cancel_button)
        footer.addStretch()
        footer.addWidget(self.review_next_button)
        footer.addWidget(self.selection_combo)
        footer.addWidget(self.collect_evidence_button)
        footer.addWidget(self.compare_options_button)
        footer.addWidget(self.use_provisional_button)
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
        self._review_buttons = {}

    def _render(self) -> None:
        self._snapshot = load_reference_calibration_study(self.study_directory)
        self._clear_content()
        running = self._worker is not None
        if self._snapshot.status == "completed":
            self.status.setText(
                "All four pilot stages are complete. DiffeoForge created a provisional "
                "parameter recommendation and a report. A full-cohort confirmation is "
                "still required before scientific use."
            )
            path = self._snapshot.final_config_path
            report = None
            if self._snapshot.report_json_path is not None:
                report = load_reference_calibration_report(self.study_directory)
            recommendation = QFrame()
            recommendation.setObjectName("card")
            recommendation_layout = QVBoxLayout(recommendation)
            recommendation_title = QLabel("Recommended parameter set")
            recommendation_title.setObjectName("title")
            recommendation_layout.addWidget(recommendation_title)
            if report is not None:
                unit = str(report["coordinate_unit"])
                for parameter in report["recommended_parameters"]:
                    value = parameter["value"]
                    rendered = (
                        str(value)
                        if parameter["unit"] is None
                        else f"{float(value):.8g} {unit}"
                    )
                    line = QLabel(
                        f"<b>{parameter['title']}:</b> {rendered}"
                    )
                    line.setTextFormat(Qt.TextFormat.RichText)
                    line.setWordWrap(True)
                    recommendation_layout.addWidget(line)
                meaning = QWidget()
                meaning_layout = QVBoxLayout(meaning)
                meaning_layout.setContentsMargins(0, 0, 0, 0)
                for parameter in report["recommended_parameters"]:
                    explanation = QLabel(
                        f"<b>{parameter['title']}</b><br>{parameter['meaning']}"
                    )
                    explanation.setTextFormat(Qt.TextFormat.RichText)
                    explanation.setWordWrap(True)
                    meaning_layout.addWidget(explanation)
                recommendation_layout.addWidget(
                    InfoDisclosure(
                        "What these parameters mean",
                        meaning,
                        accessible_name="Explanation of recommended parameters",
                    )
                )
                method = QLabel(
                    "DiffeoForge first screened attachment and deformation scales "
                    "jointly, then refined deformation, regularization, and numerical "
                    "accuracy. Automatic choices had to remain stable under metric-weight "
                    "changes, an independent rank analysis, and pilot-subject resampling "
                    "when available. The complete report preserves every alternative, "
                    "evidence grade, sensitivity warning, and limitation."
                )
                method.setWordWrap(True)
                recommendation_layout.addWidget(
                    InfoDisclosure(
                        "How this recommendation was calculated",
                        method,
                    )
                )
            else:
                legacy = QLabel(
                    "This study predates the integrated recommendation report. Its "
                    "selected configuration remains available below."
                )
                legacy.setWordWrap(True)
                recommendation_layout.addWidget(legacy)
            self.content_layout.addWidget(recommendation)

            actions = QHBoxLayout()
            if self._snapshot.report_html_path is not None:
                report_button = QPushButton("Open full recommendation report")
                _set_action_emphasis(report_button, True)
                report_button.clicked.connect(
                    lambda: QDesktopServices.openUrl(
                        QUrl.fromLocalFile(str(self._snapshot.report_html_path))
                    )
                )
                actions.addWidget(report_button)
            if path is not None:
                open_button = QPushButton("Open recommended atlas configuration")
                _set_action_emphasis(
                    open_button,
                    self._snapshot.report_html_path is None,
                )
                open_button.clicked.connect(
                    lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
                )
                actions.addWidget(open_button)
            actions.addStretch()
            self.content_layout.addLayout(actions)
            self.progress.setRange(0, 1)
            self.progress.setValue(1)
            self.progress.setFormat("Calibration complete")
            self.start_button.hide()
            self.advance_button.hide()
            self.review_next_button.hide()
            self.selection_combo.hide()
            self.cancel_button.hide()
            self.advanced_mode.setEnabled(True)
            self.content_layout.addStretch()
            return
        stage = self._snapshot.current_stage
        assert stage is not None
        automatic_mode = not self.advanced_mode.isChecked()
        self.advanced_mode.setEnabled(not running)
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
        stage_help = QWidget()
        stage_help_layout = QVBoxLayout(stage_help)
        stage_help_layout.setContentsMargins(0, 0, 0, 0)
        explanation = QLabel(guidance.explanation)
        explanation.setWordWrap(True)
        stage_help_layout.addWidget(explanation)
        task_title = QLabel("What you need to do")
        task_title.setObjectName("sectionTitle")
        stage_help_layout.addWidget(task_title)
        task_text = QLabel(guidance.action)
        task_text.setWordWrap(True)
        stage_help_layout.addWidget(task_text)
        caution = QLabel("Important: " + guidance.caution)
        caution.setWordWrap(True)
        stage_help_layout.addWidget(caution)
        self.content_layout.addWidget(
            InfoDisclosure(
                "Decision guidance for this stage",
                stage_help,
                accessible_name=f"Information about {stage.title}",
            )
        )
        if any(candidate.metrics is not None for candidate in self._snapshot.candidates):
            comparison_legend = QLabel(
                "How to read candidate colors: Green = favorable automatic signal · "
                "Yellow = context-dependent trade-off · Red = unfavorable relative "
                "signal. Colors describe one measurement at a time; they do not select "
                "the anatomically best option."
            )
            comparison_legend.setObjectName("tradeoffLegend")
            comparison_legend.setWordWrap(True)
            self.content_layout.addWidget(
                InfoDisclosure(
                    "How to interpret the comparison colors",
                    comparison_legend,
                )
            )
        if self._snapshot.status == "awaiting_review":
            assessment = assess_reference_calibration_snapshot(self._snapshot)
            weight_support = (
                "not available"
                if assessment.weight_stability is None
                else f"{assessment.weight_stability:.1%}"
            )
            subject_support = (
                "not available"
                if assessment.subject_bootstrap_stability is None
                else f"{assessment.subject_bootstrap_stability:.1%}"
            )
            flags = (
                "<br>".join(f"• {flag}" for flag in assessment.sensitivity_flags)
                if assessment.sensitivity_flags
                else "No material sensitivity warning was triggered."
            )
            confidence = QLabel(
                f"<b>Evidence grade: {assessment.recommendation_confidence.upper()}</b><br>"
                f"Winner support across metric priorities: {weight_support}<br>"
                f"Winner support across pilot-subject resampling: {subject_support}<br>"
                f"{flags}"
            )
            confidence.setTextFormat(Qt.TextFormat.RichText)
            confidence.setWordWrap(True)
            confidence.setObjectName(
                "statusSuccess"
                if assessment.automatic_selection_allowed
                else "statusWarning"
            )
            self.content_layout.addWidget(confidence)
        completed = sum(candidate.status == "completed" for candidate in self._snapshot.candidates)
        if automatic_mode:
            completed_before = sum(
                len(planned_stage.candidates)
                for planned_stage in self._snapshot.plan.stages
                if planned_stage.stage_id in self._snapshot.selected_candidate_ids
            )
            total_candidates = sum(
                len(planned_stage.candidates)
                for planned_stage in self._snapshot.plan.stages
            )
            total_completed = completed_before + completed
            self.progress.setRange(0, total_candidates)
            self.progress.setValue(total_completed)
            self.progress.setFormat(
                f"{total_completed} of {total_candidates} pilot runs completed"
            )
        else:
            self.progress.setRange(0, len(self._snapshot.candidates))
            self.progress.setValue(completed)
            self.progress.setFormat(
                f"{completed} of {len(self._snapshot.candidates)} candidates completed"
            )
        planned_by_id = {candidate.candidate_id: candidate for candidate in stage.candidates}
        tradeoffs = candidate_tradeoff_assessments(self._snapshot.candidates)
        candidate_container = QWidget()
        candidate_layout = QVBoxLayout(candidate_container)
        candidate_layout.setContentsMargins(0, 0, 0, 0)
        for index, candidate in enumerate(self._snapshot.candidates, start=1):
            candidate_layout.addWidget(
                self._candidate_card(
                    candidate,
                    planned_by_id[candidate.candidate_id],
                    option_index=index,
                    tradeoffs=tradeoffs[candidate.candidate_id],
                )
            )
        if automatic_mode:
            self.content_layout.addWidget(
                InfoDisclosure(
                    f"See all {len(self._snapshot.candidates)} pilot candidates",
                    candidate_container,
                    accessible_name="Detailed pilot candidate list",
                )
            )
        else:
            self.content_layout.addWidget(candidate_container)
        self.content_layout.addStretch()
        awaiting = self._snapshot.status == "awaiting_review"
        retryable = any(
            candidate.status in {"failed", "interrupted", "orphaned"}
            for candidate in self._snapshot.candidates
        )
        if automatic_mode:
            self.start_button.setText(
                "Continue complete four-stage pilot"
                if self._snapshot.selected_candidate_ids or awaiting
                else "Run complete four-stage pilot"
            )
            self.start_button.setVisible(True)
        else:
            self.start_button.setText(
                "Retry failed candidates"
                if awaiting and retryable
                else "Run all candidates in this stage"
            )
            self.start_button.setVisible(not awaiting or retryable)
        self.start_button.setEnabled(not running)
        self.cancel_button.setEnabled(running)
        self.cancel_button.setVisible(running)
        self.review_next_button.hide()
        _set_action_emphasis(self.review_next_button, False)
        self.selection_combo.hide()
        _set_choice_emphasis(self.selection_combo, False)
        self.advance_button.hide()
        self.advance_button.setEnabled(False)
        self.use_provisional_button.hide()
        self.compare_options_button.hide()
        self.collect_evidence_button.hide()
        _set_action_emphasis(
            self.start_button,
            automatic_mode or not awaiting or retryable,
        )
        _set_action_emphasis(self.advance_button, False)
        if automatic_mode:
            if running:
                self.status.setText(
                    "DiffeoForge is running the complete four-stage pilot. It will "
                    "continue automatically and present one recommendation report at "
                    "the end. You can cancel safely."
                )
            elif awaiting:
                assessment = assess_reference_calibration_snapshot(self._snapshot)
                if assessment.automatic_selection_allowed:
                    self.status.setText(
                        "This stage has a robust winner. Next: click the green Continue "
                        "complete four-stage pilot button; DiffeoForge will record the "
                        "uncertainty-qualified choice and continue automatically."
                    )
                else:
                    self.start_button.hide()
                    self.use_provisional_button.setEnabled(
                        assessment.balanced_candidate_id is not None
                    )
                    self.use_provisional_button.show()
                    self.compare_options_button.show()
                    self.collect_evidence_button.show()
                    if assessment.search_range_status == "not_bounded":
                        self.status.setText(
                            "Paused checkpoint: the provisional winner is on a tested "
                            "parameter boundary, so the search range is not bounded. "
                            "Nothing was selected automatically. Collect outward pilot "
                            "evidence before treating it as an enclosed optimum, or "
                            "explicitly authorize the displayed value as provisional."
                        )
                    else:
                        self.status.setText(
                            "Paused checkpoint: the pilot evidence does not support one "
                            "robust unique winner. Nothing was selected and Advanced mode "
                            "was not enabled. You can explicitly use the displayed balanced "
                            "recommendation provisionally, compare every option yourself, "
                            "or collect more pilot evidence."
                        )
            else:
                self.status.setText(
                    "Next: click the green Run complete four-stage pilot button. You "
                    "will receive one recommendation report after all four stages."
                )
        elif awaiting:
            previous_selection = self.selection_combo.currentData()
            self.selection_combo.blockSignals(True)
            self.selection_combo.clear()
            self.selection_combo.addItem(
                "Choose an option from the evidence and trade-offs…",
                None,
            )
            for index, candidate in enumerate(
                self._snapshot.candidates,
                start=1,
            ):
                if candidate.candidate_id in self._selectable_candidate_ids():
                    option_letter = chr(ord("A") + index - 1)
                    review_suffix = (
                        " · visual QC passed"
                        if candidate.candidate_id
                        in self._visually_approved_candidates
                        else " · visual QC optional / not performed"
                    )
                    self.selection_combo.addItem(
                        f"Option {option_letter} — {candidate.label}{review_suffix}",
                        candidate.candidate_id,
                    )
            previous_index = self.selection_combo.findData(previous_selection)
            if previous_index >= 0:
                self.selection_combo.setCurrentIndex(previous_index)
            self.selection_combo.blockSignals(False)
            self._update_stage_review_action()
        elif running:
            self.status.setText(
                "Running the declared candidates. You can cancel safely; no review "
                "action is required until all calculations finish."
            )
        else:
            self.status.setText(
                "Next: click the green Run all candidates in this stage button."
            )

    def _candidate_card(
        self,
        candidate: CalibrationStudyCandidateState,
        planned: CalibrationCandidate,
        *,
        option_index: int,
        tradeoffs: tuple[CalibrationTradeoffAssessment, ...],
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
        option_help = QWidget()
        option_help_layout = QVBoxLayout(option_help)
        option_help_layout.setContentsMargins(0, 0, 0, 0)
        meaning_label = QLabel(meaning)
        meaning_label.setWordWrap(True)
        option_help_layout.addWidget(meaning_label)
        rationale = QLabel("Why this option exists: " + planned.rationale)
        rationale.setWordWrap(True)
        option_help_layout.addWidget(rationale)
        layout.addWidget(
            InfoDisclosure(
                "About this option",
                option_help,
                accessible_name=f"Information about option {option_letter}",
            )
        )
        if candidate.metrics is not None:
            metrics = candidate.metrics
            passed, check_text = automatic_check_summary(metrics)
            check = QLabel(("✓ " if passed else "⚠ ") + check_text)
            check.setWordWrap(True)
            layout.addWidget(check)
            comparison_title = QLabel("Pros and cons compared with the other options")
            comparison_title.setObjectName("sectionTitle")
            layout.addWidget(comparison_title)
            if tradeoffs:
                comparison_details_title = QLabel(
                    "How to interpret the automatic comparison signals"
                )
                comparison_details_title.setObjectName("sectionTitle")
                option_help_layout.addWidget(comparison_details_title)
                for tradeoff in tradeoffs:
                    comparison = QLabel(
                        self._tradeoff_assessment_summary_html(tradeoff)
                    )
                    comparison.setObjectName(
                        {
                            "favorable": "tradeoffFavorable",
                            "caution": "tradeoffCaution",
                            "unfavorable": "tradeoffUnfavorable",
                        }[tradeoff.tone]
                    )
                    comparison.setTextFormat(Qt.TextFormat.RichText)
                    comparison.setWordWrap(True)
                    layout.addWidget(comparison)
                    comparison_detail = QLabel(
                        self._tradeoff_assessment_html(tradeoff)
                    )
                    comparison_detail.setTextFormat(Qt.TextFormat.RichText)
                    comparison_detail.setWordWrap(True)
                    option_help_layout.addWidget(comparison_detail)
            else:
                comparison = QLabel(
                    "No standout relative signal was detected for this option; "
                    "that is a neutral comparison result, not missing evidence."
                    if all(
                        item.status == "completed" and item.metrics is not None
                        for item in self._snapshot.candidates
                    )
                    else "Relative comparison appears after all candidates finish."
                )
                comparison.setObjectName("status")
                comparison.setWordWrap(True)
                layout.addWidget(comparison)
            technical_button = QPushButton("ⓘ Technical measurements")
            technical_button.setCheckable(True)
            technical_button.setSizePolicy(
                QSizePolicy.Policy.Maximum,
                QSizePolicy.Policy.Fixed,
            )
            _set_action_emphasis(technical_button, False)
            technical = QLabel(technical_metric_text(metrics))
            technical.setWordWrap(True)
            technical.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            technical.setVisible(False)
            technical_button.toggled.connect(technical.setVisible)
            technical_button.toggled.connect(
                lambda visible, button=technical_button: button.setText(
                    "ⓘ Hide technical measurements"
                    if visible
                    else "ⓘ Technical measurements"
                )
            )
            technical_row = QHBoxLayout()
            technical_row.addWidget(technical_button)
            technical_row.addStretch()
            layout.addLayout(technical_row)
            layout.addWidget(technical)
            reviewed = candidate.candidate_id in self._visually_reviewed_candidates
            approved = candidate.candidate_id in self._visually_approved_candidates
            viewer = QPushButton(
                "Optional plausibility gate: review again…"
                if reviewed
                else "Optional plausibility gate: inspect originals & reconstructions…"
            )
            viewer.clicked.connect(
                lambda _checked=False, value=candidate: self._open_candidate(value)
            )
            _set_action_emphasis(viewer, False)
            self._review_buttons[candidate.candidate_id] = viewer
            approval = QCheckBox("Visual QC passed")
            approval.setVisible(approved)
            approval.setChecked(approved)
            approval.setEnabled(False)
            approval.setToolTip("Review this option again to change the recorded decision.")
            visual_status = QLabel(
                "Plausibility gate: passed; this option remains eligible."
                if approved
                else (
                    "Plausibility gate: failed. This option is currently excluded."
                    if reviewed
                    else (
                        "Plausibility gate: not performed. Automatic numerical "
                        "ranking remains available, but anatomical validity is unreviewed."
                    )
                )
            )
            visual_status.setObjectName(
                "statusSuccess"
                if approved
                else ("statusError" if reviewed else "status")
            )
            visual_status.setWordWrap(True)
            self._approval_checks[candidate.candidate_id] = approval
            review_controls = QHBoxLayout()
            review_controls.addWidget(viewer)
            review_controls.addWidget(approval)
            review_controls.addStretch()
            layout.addLayout(review_controls)
            layout.addWidget(visual_status)
        elif candidate.error:
            error = QLabel(candidate.error)
            error.setWordWrap(True)
            layout.addWidget(error)
        else:
            detail = QLabel(
                "Ready to run."
                if candidate.status == "pending"
                else "Ready for a new attempt."
            )
            detail.setWordWrap(True)
            layout.addWidget(detail)
        return card

    @staticmethod
    def _tradeoff_assessment_html(
        assessment: CalibrationTradeoffAssessment,
    ) -> str:
        prefix = {
            "favorable": "✓ Favorable signal",
            "caution": "↔ Context-dependent trade-off",
            "unfavorable": "⚠ Unfavorable signal",
        }[assessment.tone]
        return (
            f"<b>{prefix}: {assessment.label}</b><br>"
            f"{assessment.interpretation}"
        )

    @staticmethod
    def _tradeoff_assessment_summary_html(
        assessment: CalibrationTradeoffAssessment,
    ) -> str:
        prefix = {
            "favorable": "✓ Favorable",
            "caution": "↔ Trade-off",
            "unfavorable": "⚠ Unfavorable",
        }[assessment.tone]
        return f"<b>{prefix}:</b> {assessment.label}"

    def _selectable_candidate_ids(self) -> set[str]:
        explicitly_failed = (
            self._visually_reviewed_candidates
            - self._visually_approved_candidates
        )
        selectable: set[str] = set()
        for candidate in self._snapshot.candidates:
            if (
                candidate.status != "completed"
                or candidate.metrics is None
                or candidate.candidate_id in explicitly_failed
            ):
                continue
            passed, _summary = automatic_check_summary(candidate.metrics)
            if passed:
                selectable.add(candidate.candidate_id)
        return selectable

    @Slot()
    def _update_stage_review_action(self) -> None:
        if self._snapshot.status != "awaiting_review":
            return
        retryable = any(
            candidate.status in {"failed", "interrupted", "orphaned"}
            for candidate in self._snapshot.candidates
        )
        selectable_ids = self._selectable_candidate_ids()
        selected = self.selection_combo.currentData()
        selected_is_selectable = selected in selectable_ids
        ready = selected_is_selectable and not retryable
        self.advance_button.setEnabled(ready)
        _set_action_emphasis(self.advance_button, ready)
        self.review_next_button.hide()
        _set_action_emphasis(self.review_next_button, False)
        self.selection_combo.hide()
        self.advance_button.hide()
        if retryable:
            _set_choice_emphasis(self.selection_combo, False)
            self.status.setText(
                "Next: click the green Retry failed candidates button."
            )
            return
        if not selectable_ids:
            self.status.setText(
                "No option is currently selectable. Automatic validity checks failed, "
                "or every option was explicitly rejected by optional visual QC. Review "
                "the evidence or repeat visual QC for a rejected option."
            )
            return
        self.selection_combo.show()
        if not selected_is_selectable:
            _set_choice_emphasis(self.selection_combo, True)
            self.status.setText(
                "Next: compare the explained pros and cons, then choose one option from "
                "the green menu. Opening the reconstruction viewer is optional."
            )
            return
        self.advance_button.show()
        _set_choice_emphasis(self.selection_combo, False)
        self.status.setText(
            "Next: click the green Select option & prepare next stage button. "
            "Optional visual QC status will be recorded in the provenance."
        )

    @Slot()
    def _open_next_review(self) -> None:
        completed = tuple(
            candidate
            for candidate in self._snapshot.candidates
            if candidate.status == "completed"
        )
        candidate = next(
            (
                item
                for item in completed
                if item.candidate_id not in self._visually_reviewed_candidates
            ),
            completed[0] if completed else None,
        )
        if candidate is not None:
            self._open_candidate(candidate)

    @Slot()
    def _start(self) -> None:
        if self._worker is not None:
            return
        automatic_mode = not self.advanced_mode.isChecked()
        runner = ReferenceCalibrationStudyRunner(self.study_directory)
        worker = _CalibrationStageWorker(
            runner,
            complete_automatic_pilot=automatic_mode,
        )
        worker.signals.event.connect(self._event)
        worker.signals.succeeded.connect(self._succeeded)
        worker.signals.failed.connect(self._failed)
        self._worker = worker
        self.advanced_mode.setEnabled(False)
        self.start_button.setEnabled(False)
        _set_action_emphasis(self.start_button, False)
        self.cancel_button.setEnabled(True)
        self.cancel_button.setVisible(True)
        self.cancel_button.setObjectName("danger")
        self.cancel_button.style().unpolish(self.cancel_button)
        self.cancel_button.style().polish(self.cancel_button)
        self.status.setText(
            (
                "DiffeoForge is running all remaining pilot stages sequentially and "
                "will create one final recommendation report. "
                if automatic_mode
                else "DiffeoForge is running this stage sequentially. "
            )
            + "Closing is disabled until the current candidate reaches a terminal state."
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
            self._render()
            self.status.setText(f"{candidate_id} completed; automatic QC metrics were verified.")
        elif kind == "automatic_stage_selected":
            self._render()
            self.status.setText(
                f"Stage {event['completed_stage_count']} of {event['stage_count']} "
                f"completed. Provisional selection: {candidate_id}. Continuing "
                "automatically with the next parameter family."
            )
        elif kind == "automatic_search_extended":
            self.study_directory = Path(str(event["study_directory"])).resolve()
            self._render()
            self.status.setText(
                f"Search extension {event['extension_round']} created from verified "
                "evidence. Running only the new outward candidates now."
            )
        elif kind in {"candidate_failed", "candidate_interrupted"}:
            self.status.setText(f"{candidate_id}: {event['error']}")

    @Slot(object)
    def _succeeded(self, snapshot: ReferenceCalibrationStudySnapshot) -> None:
        self._worker = None
        self.study_directory = snapshot.study_directory
        self._render()

    @Slot(str)
    def _failed(self, message: str) -> None:
        self._worker = None
        self._render()
        if "Search range not bounded" in message:
            self.status.setText(
                "Paused checkpoint: the provisional winner is at a tested parameter "
                "boundary, so the search range is not bounded. No option was selected "
                "automatically; collect outward evidence or explicitly authorize the "
                "displayed value as provisional."
            )
        elif "refused to invent a unique winner" in message:
            self.status.setText(
                "Paused checkpoint: no robust unique winner was found. No option was "
                "selected automatically; choose one of the explicit actions below."
            )
        else:
            self.status.setText(f"Calibration stage could not continue: {message}")

    def _visual_approvals(self) -> dict[str, bool]:
        return {
            candidate_id: candidate_id in self._visually_approved_candidates
            for candidate_id in self._visually_reviewed_candidates
        }

    @Slot()
    def _use_provisional(self) -> None:
        assessment = assess_reference_calibration_snapshot(
            self._snapshot,
            visual_approvals=self._visual_approvals(),
        )
        candidate_id = assessment.balanced_candidate_id
        if candidate_id is None:
            QMessageBox.warning(
                self,
                "No eligible provisional option",
                "Every candidate failed an automatic or recorded plausibility gate.",
            )
            return
        try:
            snapshot, _assessment = record_reference_calibration_provisional_override(
                self.study_directory,
                visual_approvals=self._visual_approvals(),
                selected_candidate_id=candidate_id,
            )
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            QMessageBox.warning(self, "Provisional selection rejected", str(error))
            return
        self._render()
        if snapshot.status != "completed":
            self._start()

    @Slot()
    def _compare_options(self) -> None:
        self.advanced_mode.setChecked(True)

    @Slot()
    def _collect_more_evidence(self) -> None:
        assessment = assess_reference_calibration_snapshot(
            self._snapshot,
            visual_approvals=self._visual_approvals(),
        )
        if assessment.search_range_status == "not_bounded":
            proposal = propose_calibration_search_extension(
                self._snapshot.plan,
                assessment,
            )
            rendered = []
            for candidate in proposal.candidates:
                values = ", ".join(
                    f"{name}={value:.6g}"
                    for name, value in candidate.parameter_values
                )
                rendered.append(f"• {candidate.label}: {values}")
            boundaries = dict(
                boundary.split(":", maxsplit=1)
                for boundary in assessment.search_boundary_parameters
            )
            limits: dict[str, tuple[float, float]] = {}
            assert self._snapshot.current_stage is not None
            for parameter, direction in boundaries.items():
                tested = [
                    candidate.values[parameter]
                    for candidate in self._snapshot.current_stage.candidates
                    if parameter in candidate.values
                ]
                proposed = [
                    candidate.values[parameter]
                    for candidate in proposal.candidates
                    if parameter in candidate.values
                ]
                observed_low = min((*tested, *proposed))
                observed_high = max((*tested, *proposed))
                if direction == "minimum":
                    outward_limit, accepted = QInputDialog.getDouble(
                        self,
                        "Declare lower feasibility limit",
                        f"Minimum allowed {parameter} (must be ≤ {observed_low:.9g}):",
                        observed_low,
                        1e-15,
                        1e15,
                        12,
                    )
                    if not accepted:
                        return
                    limits[parameter] = (outward_limit, observed_high)
                elif direction == "maximum":
                    outward_limit, accepted = QInputDialog.getDouble(
                        self,
                        "Declare upper feasibility limit",
                        f"Maximum allowed {parameter} (must be ≥ {observed_high:.9g}):",
                        observed_high,
                        1e-15,
                        1e15,
                        12,
                    )
                    if not accepted:
                        return
                    limits[parameter] = (observed_low, outward_limit)
                else:
                    QMessageBox.warning(
                        self,
                        "Cannot extend this grid",
                        f"{parameter} has only one tested value, so no logarithmic "
                        "outward step can be derived.",
                    )
                    return
            destination = next_reference_calibration_search_extension_destination(
                self.study_directory
            )
            if destination.exists():
                QMessageBox.warning(
                    self,
                    "Outward successor already exists",
                    "The deterministic successor destination already exists and will "
                    "not be reused or overwritten:\n" + str(destination),
                )
                return
            confirmation = QMessageBox.question(
                self,
                "Create and start outward pilot evidence",
                "The current search range is not bounded. DiffeoForge derived these "
                "hash-bound logarithmic neighbors without changing the immutable pilot:\n\n"
                + "\n".join(rendered)
                + "\n\nCreate the immutable successor and start it here?\n"
                + str(destination)
                + "\n\nOnly these new candidates will run. The entered feasibility "
                "limits and all source evidence will be hash-bound. If the winner "
                "remains on the same boundary, DiffeoForge will continue outward "
                "automatically until it becomes interior or reaches the limit.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if confirmation != QMessageBox.StandardButton.Yes:
                return
            try:
                successor = create_reference_calibration_search_extension_study(
                    self.study_directory,
                    destination,
                    safety_limits=limits,
                )
            except (OSError, RuntimeError, TypeError, ValueError) as error:
                QMessageBox.warning(
                    self,
                    "Could not create outward successor",
                    str(error),
                )
                return
            self.study_directory = successor.study_directory
            self._snapshot = successor
            self._visually_reviewed_candidates.clear()
            self._visually_approved_candidates.clear()
            self._render()
            self.status.setText(
                "Outward successor created. Preserved candidates remain complete; "
                "starting only the new neighbors now."
            )
            self._start()
            return
        QMessageBox.information(
            self,
            "Collect more pilot evidence",
            "This immutable pilot remains preserved. Close this dialog and create a "
            "new parameter proposal with a larger, deliberately more diverse pilot "
            "subset. Include known biological extremes or declared strata when they "
            "exist; the current candidates will not be silently changed.",
        )

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
                "Choose one automatically valid candidate before continuing.",
            )
            return
        approvals = self._visual_approvals()
        try:
            _snapshot, _assessment = record_reference_calibration_stage_review(
                self.study_directory,
                visual_approvals=approvals,
                selected_candidate_id=str(selected),
            )
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            QMessageBox.warning(self, "Stage selection rejected", str(error))
            return
        self._render()
        visual_status = (
            "passed"
            if selected in self._visually_approved_candidates
            else (
                "failed"
                if selected in self._visually_reviewed_candidates
                else "not performed"
            )
        )
        self.status.setText(
            f"Selection recorded: {selected}. The next calibration stage is ready. "
            f"Optional visual QC: {visual_status}."
        )

    def _open_candidate(self, candidate: CalibrationStudyCandidateState) -> None:
        try:
            dialog = CalibrationCandidateViewerDialog(
                self.study_directory,
                candidate,
                self,
            )
            dialog.exec()
            if dialog.review_recorded:
                self._visually_reviewed_candidates.add(candidate.candidate_id)
                if dialog.review_passed:
                    self._visually_approved_candidates.add(candidate.candidate_id)
                else:
                    self._visually_approved_candidates.discard(candidate.candidate_id)
                self._render()
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
