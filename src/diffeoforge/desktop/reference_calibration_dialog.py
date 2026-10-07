"""Desktop review and execution dialog for staged Deformetrica calibration."""

from __future__ import annotations

import threading
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath

from PySide6.QtCore import QObject, QRunnable, Qt, QUrl, Signal, Slot
from PySide6.QtGui import QCloseEvent, QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStyle,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from diffeoforge.desktop.activity import ActivityPool
from diffeoforge.desktop.calibration_comparison_widget import (
    CalibrationComparisonCanvas3D,
)
from diffeoforge.desktop.info_disclosure import InfoDisclosure
from diffeoforge.desktop.preview_mesh_loader import PreviewMeshLoader
from diffeoforge.desktop.reference_calibration_presentation import (
    CalibrationTradeoffAssessment,
    afk_return_summary,
    automatic_check_summary,
    candidate_option_label,
    candidate_parameter_summary,
    candidate_tradeoff_assessments,
    stage_guidance,
    technical_metric_text,
)
from diffeoforge.reference_calibration import (
    CalibrationCandidate,
)
from diffeoforge.reference_calibration_study import (
    CalibrationStudyCandidateState,
    ReferenceCalibrationStudyRunner,
    ReferenceCalibrationStudySnapshot,
    assess_reference_calibration_snapshot,
    calibration_candidate_run_directory,
    iteration_limit_selection_available,
    load_reference_calibration_report,
    load_reference_calibration_study,
    normalized_candidate_subject_fit,
    record_reference_calibration_candidate_review,
    record_reference_calibration_iteration_limit_selection,
    record_reference_calibration_provisional_override,
    record_reference_calibration_stage_review,
)
from diffeoforge.result_report import collect_run_report

_FEASIBILITY_PARAMETER_LABELS = {
    "attachment_kernel_width": "surface-matching detail width",
    "deformation_kernel_width": "deformation spread width",
    "initial_control_point_spacing": "control-point spacing",
    "noise_std": "fit-versus-smoothness setting",
}


def _set_action_emphasis(button: QPushButton, emphasized: bool) -> None:
    """Apply the shared primary/secondary action role immediately."""

    button.setObjectName("primary" if emphasized else "secondary")
    style = button.style()
    style.unpolish(button)
    style.polish(button)
    button.updateGeometry()
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
    original_sha256: str | None = None
    reconstruction_sha256: str | None = None


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

    run_directory = calibration_candidate_run_directory(candidate)
    report = collect_run_report(run_directory)
    from diffeoforge.reference_calibration_study import _verify_manifest

    manifest = _verify_manifest(root)
    original_hashes = {r["filename"]: r["sha256"] for r in manifest["inputs"]["subjects"]}
    output_hashes = {str(r["path"]): str(r["sha256"]) for r in report.inventory}
    output = (run_directory / "output").resolve()
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
            original_sha256=manifest["inputs"]["template"]["sha256"],
            reconstruction_sha256=output_hashes[atlas_path.relative_to(output).as_posix()],
        )
    ]
    pairs.extend(
        CalibrationQcPair(
            pair_id=f"subject:{name}",
            label=f"Pilot specimen — {name}",
            original_path=path,
            reconstruction_path=reconstructions[name],
            required=True,
            original_sha256=original_hashes[name],
            reconstruction_sha256=output_hashes[
                reconstructions[name].relative_to(output).as_posix()
            ],
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
    finished = Signal(object)


class _CalibrationStageWorker(QRunnable):
    def __init__(
        self,
        runner: ReferenceCalibrationStudyRunner,
        *,
        complete_automatic_pilot: bool = False,
        adaptive_fit_search: bool = False,
        afk: bool = False,
        visual_approvals: Mapping[str, bool] | None = None,
        outward_safety_limits: Mapping[str, tuple[float, float]] | None = None,
        continuation: tuple[str, int] | None = None,
        specimen_fit: bool = False,
        specimen_action: tuple[str, str, int] | None = None,
        retain_previous: bool = False,
        provisional_candidate_id: str | None = None,
        finish_candidate_id: str | None = None,
        early_screen: bool = False,
        screen_subjects: tuple[str, ...] | None = None,
        retry_screens: bool = False,
        finer_resolution: bool = False,
        qualification: bool = False,
        qualification_source: str | None = None,
        qualification_iterations: int = 100,
        strict_optimizer: bool = False,
        finer_model: bool = False,
        integration_tolerances: Mapping[str, float] | None = None,
    ) -> None:
        super().__init__()
        self.runner = runner
        self.continuation = continuation
        self.specimen_fit = specimen_fit
        self.specimen_action = specimen_action
        self.retain_previous = retain_previous
        self.provisional_candidate_id = provisional_candidate_id
        self.finish_candidate_id = finish_candidate_id
        self.early_screen = early_screen
        self.retry_screens = retry_screens
        self.finer_resolution = finer_resolution
        self.qualification = qualification
        self.qualification_source = qualification_source
        self.qualification_iterations = qualification_iterations
        self.strict_optimizer = strict_optimizer
        self.finer_model = finer_model
        self.screen_subjects = screen_subjects
        self.integration_tolerances = integration_tolerances
        self.adaptive_fit_search = adaptive_fit_search
        self.complete_automatic_pilot = complete_automatic_pilot
        self.afk = afk
        self.outward_safety_limits = (
            dict(outward_safety_limits) if outward_safety_limits is not None else None
        )
        self.visual_approvals = dict(visual_approvals or {})
        self.signals = _CalibrationSignals()
        self._lock = threading.Lock()
        self._finished = False
        self.error_message = None

    @property
    def is_finished(self) -> bool:
        with self._lock:
            return self._finished

    def request_cancel(self) -> bool:
        with self._lock:
            if self._finished:
                return False
        if self.finish_candidate_id is not None:
            return False  # Atomic completion verifies/saves evidence; no engine is running.
        return self.runner.request_cancel()

    @Slot()
    def run(self) -> None:
        def emit(event):
            if event["event"] in {"candidate_completed", "adaptive_search_extended"}:
                snapshot = load_reference_calibration_study(self.runner.study_directory)
                for candidate in snapshot.candidates:
                    if candidate.metrics:
                        normalized_candidate_subject_fit(snapshot, candidate)
                event = dict(event, snapshot=snapshot)
            self.signals.event.emit(event)

        try:
            if self.finish_candidate_id is not None:
                from diffeoforge.reference_pilot_completion import finish

                result, _assessment = finish(self.runner.study_directory, self.finish_candidate_id)
            elif self.provisional_candidate_id is not None:
                result, _assessment = record_reference_calibration_iteration_limit_selection(
                    self.runner.study_directory,
                    selected_candidate_id=self.provisional_candidate_id,
                )
            elif self.qualification:
                if self.finer_model or self.strict_optimizer:
                    from diffeoforge.reference_pilot_qualification import run

                    result = run(
                        self.runner,
                        event_callback=emit,
                        candidate_id=self.qualification_source,
                        iterations=self.qualification_iterations,
                        finer_model=self.finer_model,
                    )
                else:
                    from diffeoforge.reference_pilot_completion import run

                    result = run(
                        self.runner, event_callback=emit, candidate_id=self.qualification_source
                    )
            elif self.finer_resolution:
                from diffeoforge.reference_integration_check import add_finer_resolution

                result = add_finer_resolution(self.runner.study_directory)
                emit(dict(event="integration_resolution_prepared", snapshot=result))
                result = self.runner.run_current_stage(event_callback=emit)
            elif self.retry_screens:
                from diffeoforge.reference_stage_screening import retry_failed_screens

                result = retry_failed_screens(self.runner.study_directory)
            elif self.early_screen:
                from diffeoforge.reference_stage_screening import run_next_screen

                result = run_next_screen(
                    self.runner, subjects=self.screen_subjects, event_callback=emit
                )
            elif self.retain_previous:
                from diffeoforge.reference_stage_retention import keep_previous_fit

                result = keep_previous_fit(self.runner.study_directory)
            elif self.specimen_fit or self.specimen_action is not None:
                from diffeoforge.reference_sequential_fit import run_specimen_sequence

                result = run_specimen_sequence(
                    self.runner,
                    action=self.specimen_action,
                    event_callback=emit,
                )
            elif self.continuation is not None:
                from diffeoforge.reference_adaptive_calibration import create_selected_continuation
                from diffeoforge.reference_calibration_study import (
                    next_reference_calibration_search_extension_destination,
                )

                candidate_id, iterations = self.continuation
                destination = next_reference_calibration_search_extension_destination(
                    self.runner.study_directory
                )
                snapshot = create_selected_continuation(
                    self.runner.study_directory,
                    destination,
                    candidate_id=candidate_id,
                    iterations=iterations,
                )
                self.runner.study_directory = snapshot.study_directory
                emit(dict(event="selected_continuation_started", snapshot=snapshot))
                result = self.runner.run_current_stage(
                    event_callback=emit, integration_tolerances=self.integration_tolerances
                )
            elif self.adaptive_fit_search:
                from diffeoforge.reference_adaptive_calibration import run_adaptive_stage

                result = run_adaptive_stage(self.runner, event_callback=emit)
            elif self.complete_automatic_pilot:
                result = self.runner.run_complete_automatic_pilot(
                    event_callback=emit,
                    **(
                        {
                            "afk": True,
                            "visual_approvals": self.visual_approvals,
                            "afk_outward_safety_limits": self.outward_safety_limits,
                        }
                        if self.afk
                        else {}
                    ),
                )
            else:
                result = self.runner.run_current_stage(
                    event_callback=emit, integration_tolerances=self.integration_tolerances
                )
        except Exception as error:
            self.error_message = f"{type(error).__name__}: {error or 'Background task failed'}"
            self.signals.failed.emit(self.error_message)
        else:
            self.signals.succeeded.emit(result)
        finally:
            with self._lock:
                self._finished = True
            self.signals.finished.emit(self)


class CalibrationCandidateViewerDialog(QDialog):
    """Review the atlas and all subject reconstructions from one immutable run."""

    def __init__(
        self,
        study_directory: Path,
        candidate: CalibrationStudyCandidateState,
        parent: QWidget | None = None,
        *,
        subject_fit: Mapping[str, float] | None = None,
        pairs: tuple[CalibrationQcPair, ...] | None = None,
        allow_plan_b: bool = False,
        read_only: bool = False,
    ) -> None:
        super().__init__(parent)
        if candidate.run_directory is None:
            raise ValueError("Candidate has no completed run directory")
        self._pairs = (
            pairs if pairs is not None else collect_calibration_qc_pairs(study_directory, candidate)
        )
        self._preview_cache = study_directory / "display-cache"
        self.display_scopes: dict[str, str] = {}
        self._fit = dict(subject_fit or {})
        self._pairs = tuple(
            sorted(
                self._pairs,
                key=lambda p: (
                    not p.required,
                    -self._fit.get(p.original_path.name, 0.0),
                    p.original_path.name,
                ),
            )
        )
        self.subject_decisions: dict[str, str] = {}
        self._reviewed_pair_ids: set[str] = set()
        self._required_pair_ids = {pair.pair_id for pair in self._pairs if pair.required}
        self._required_pair_indexes = tuple(
            index for index, pair in enumerate(self._pairs) if pair.required
        )
        self._review_decision: bool | None = None
        self._keep_as_plan_b = False
        self._allow_plan_b = allow_plan_b
        self._read_only = read_only
        self.feature_observations: dict[str, dict[str, object]] = {}
        self._mesh_loader = PreviewMeshLoader(self)
        self._mesh_loader.loaded.connect(self._pair_loaded)
        self._mesh_loader.failed.connect(self._pair_failed)
        self.setWindowTitle(f"Visual registration check — {candidate.candidate_id}")
        self.resize(1080, 900)
        self.setMinimumSize(760, 640)
        root = QVBoxLayout(self)
        self.body_scroll = QScrollArea()
        self.body_scroll.setWidgetResizable(True)
        self.body_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.body_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        body.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Preferred,
        )
        layout = QVBoxLayout(body)
        self.body_scroll.setWidget(body)
        root.addWidget(self.body_scroll, 1)
        title = QLabel("Does the reconstruction preserve the original anatomy?")
        if read_only:
            title.setText("Current fit (blue) / Plan B (orange)")
        title.setObjectName("title")
        layout.addWidget(title)
        intro = QLabel(
            "Blue lines are the original pilot mesh. The orange surface is what "
            "Deformetrica reconstructed from the atlas. Where they overlap closely, "
            "the blue lines should sit on the orange surface."
        )
        intro.setWordWrap(True)
        if read_only:
            intro.setText(
                "Compare the saved shapes. Close this view to return to your current fit."
            )
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
        layout.addWidget(InfoDisclosure("What to check", instructions))
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
        self.canvas.fullResolutionReadyChanged.connect(self._pair_original_presented)
        self.canvas.originalDetailRequested.connect(self._load_original_detail)
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
        self.specimen_decision = QComboBox()
        self.specimen_decision.setAccessibleName("Surface fit of this specimen")
        for label, value in (
            ("This specimen: not assessed", "unassessed"),
            ("Fit and anatomy preserved", "pass"),
            ("Does not fit / anatomy lost", "fail"),
            ("Uncertain — needs review", "uncertain"),
        ):
            self.specimen_decision.addItem(label, value)
        self.specimen_decision.currentIndexChanged.connect(self._store_specimen_decision)

        feature_box = QWidget()
        feature_layout = QVBoxLayout(feature_box)
        feature_layout.setContentsMargins(0, 0, 0, 0)
        tip_help = QLabel(
            "Optional study-specific feature check — name the feature or region that "
            "matters for this dataset. Record whether it is preserved. Add paired counts "
            "only when counting is meaningful. These are your observations."
        )
        tip_help.setWordWrap(True)
        feature_layout.addWidget(tip_help)
        self.feature_criterion = QLineEdit()
        self.feature_criterion.setMaxLength(500)
        self.feature_criterion.setPlaceholderText("Feature or region for this dataset")
        self.feature_criterion.setAccessibleName("Study-specific anatomical criterion")
        self.feature_criterion.textChanged.connect(self._store_feature_check)
        self.feature_judgement = QComboBox()
        for label, value in (
            ("Not assessed", "unassessed"),
            ("Preserved", "preserved"),
            ("Not preserved", "not_preserved"),
            ("Uncertain", "uncertain"),
        ):
            self.feature_judgement.addItem(label, value)
        self.feature_judgement.currentIndexChanged.connect(self._store_feature_check)
        feature_controls = QHBoxLayout()
        feature_controls.addWidget(self.feature_criterion, 1)
        feature_controls.addWidget(self.feature_judgement)
        feature_layout.addLayout(feature_controls)
        tip_controls = QHBoxLayout()
        self.original_feature_count = QSpinBox()
        self.reconstruction_feature_count = QSpinBox()
        for label, spin in (
            ("Original count (optional)", self.original_feature_count),
            ("Reconstruction count (optional)", self.reconstruction_feature_count),
        ):
            spin.setRange(-1, 999)
            spin.setSpecialValueText("Not counted")
            spin.setValue(-1)
            spin.setAccessibleName(label)
            spin.valueChanged.connect(self._store_feature_check)
            tip_controls.addWidget(QLabel(label))
            tip_controls.addWidget(spin)
        feature_layout.addLayout(tip_controls)
        layout.addWidget(InfoDisclosure("Optional anatomical checks", feature_box))

        self.decision_panel = QFrame()
        self.decision_panel.setObjectName("card")
        decision_layout = QVBoxLayout(self.decision_panel)
        layout.addWidget(InfoDisclosure("Optional individual assessment", self.specimen_decision))
        self.review_progress = QLabel()
        self.review_progress.setWordWrap(True)
        decision_layout.addWidget(self.review_progress)
        self.review_gate = QLabel()
        self.review_gate.setObjectName("status")
        self.review_gate.setWordWrap(True)
        decision_layout.addWidget(self.review_gate)
        self.anatomical_notes = QLineEdit()
        self.anatomical_notes.setMaxLength(4000)
        self.anatomical_notes.setPlaceholderText(
            "Optional anatomical notes: specimen, tip/branch or region, and observed mismatch"
        )
        self.anatomical_notes.setAccessibleName("Anatomical review notes")
        decision_layout.addWidget(self.anatomical_notes)
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
        self.fail_button = QPushButton("Reject option")
        self.fail_button.setObjectName("danger")
        self.fail_button.clicked.connect(self._record_visual_qc_fail)
        self.complete_button = QPushButton("Approve all specimens")
        self.maybe_button = QPushButton("Maybe / Plan B → try next")
        self.maybe_button.setVisible(allow_plan_b and not read_only)
        self.maybe_button.setToolTip(
            "Save this fallback and test new parameters for this specimen. "
            "This does not approve or reject it."
        )
        self.maybe_button.clicked.connect(self._record_plan_b)
        controls.addWidget(self.maybe_button)
        # Reserve the shared primary style's wider padding before its role changes.
        self.complete_button.setMinimumWidth(
            self.complete_button.fontMetrics().horizontalAdvance(self.complete_button.text()) + 64
        )
        self.complete_button.setToolTip("I inspected every specimen and accept all their fits.")
        self.complete_button.setEnabled(False)
        self.complete_button.clicked.connect(self._record_visual_qc_pass)
        controls.addStretch()
        controls.addWidget(self.close_button)
        controls.addWidget(self.fail_button)
        controls.addWidget(self.complete_button)
        decision_layout.addLayout(controls)
        root.addWidget(self.decision_panel)
        if read_only:
            close_comparison = QPushButton("Close comparison")
            close_comparison.clicked.connect(self.reject)
            root.addWidget(close_comparison)
        if self._required_pair_indexes:
            first_required = self._required_pair_indexes[0]
            combo_index = self.mesh_combo.findData(first_required)
            if self.mesh_combo.currentIndex() == combo_index:
                self._load_selected(combo_index)
            else:
                self.mesh_combo.setCurrentIndex(combo_index)
        elif self.mesh_combo.count():
            self._load_selected(self.mesh_combo.currentIndex())
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

    @property
    def keep_as_plan_b(self) -> bool:
        return self._keep_as_plan_b

    @Slot()
    def _record_plan_b(self) -> None:
        if (
            self._allow_plan_b
            and not self._read_only
            and self.canvas.comparison_ready
            and self._required_pair_ids
        ):
            self._keep_as_plan_b = True
            self.accept()

    @Slot(int)
    def _load_selected(self, _index: int) -> None:
        pair_index = self.mesh_combo.currentData()
        if pair_index is None:
            return
        pair = self._pairs[int(pair_index)]
        self._show_feature_check(pair)
        self.canvas.clear()
        self.status.setText("Loading comparison and preparing reduced displays…")
        self._mesh_loader.request_paths(
            int(pair_index),
            (pair.original_path, pair.reconstruction_path),
            pilot_cache=self._preview_cache,
            expected=(pair.original_sha256, pair.reconstruction_sha256),
        )
        self._update_review_progress()

    def _show_feature_check(self, pair: CalibrationQcPair) -> None:
        self.specimen_decision.blockSignals(True)
        self.specimen_decision.setCurrentIndex(
            self.specimen_decision.findData(
                self.subject_decisions.get(pair.original_path.name, "unassessed")
            )
        )
        self.specimen_decision.blockSignals(False)
        self.specimen_decision.setEnabled(False)
        observation = self.feature_observations.get(pair.original_path.name, {})
        self.feature_criterion.blockSignals(True)
        self.feature_judgement.blockSignals(True)
        self.feature_criterion.setText(observation.get("criterion", ""))
        self.feature_judgement.setCurrentIndex(
            self.feature_judgement.findData(observation.get("judgement", "unassessed"))
        )
        self.feature_criterion.setEnabled(pair.required)
        self.feature_judgement.setEnabled(pair.required)
        self.feature_criterion.blockSignals(False)
        self.feature_judgement.blockSignals(False)
        for key, spin in (
            ("original", self.original_feature_count),
            ("reconstruction", self.reconstruction_feature_count),
        ):
            spin.blockSignals(True)
            value = observation.get(key)
            spin.setValue(-1 if value is None else value)
            spin.setEnabled(pair.required)
            spin.blockSignals(False)

    @Slot()
    def _store_specimen_decision(self) -> None:
        index = self.mesh_combo.currentData()
        if index is None:
            return
        pair = self._pairs[int(index)]
        if (
            not pair.required
            or pair.pair_id not in self._reviewed_pair_ids
            or not self.canvas.comparison_ready
        ):
            return
        value = self.specimen_decision.currentData()
        if value == "unassessed":
            self.subject_decisions.pop(pair.original_path.name, None)
        else:
            self.subject_decisions[pair.original_path.name] = value
        self._update_review_progress()

    @Slot()
    def _store_feature_check(self) -> None:
        index = self.mesh_combo.currentData()
        if index is None or not self._pairs[int(index)].required:
            return
        name = self._pairs[int(index)].original_path.name
        values = {
            key: None if spin.value() < 0 else spin.value()
            for key, spin in (
                ("original", self.original_feature_count),
                ("reconstruction", self.reconstruction_feature_count),
            )
        }
        values["criterion"] = self.feature_criterion.text().strip()
        values["judgement"] = self.feature_judgement.currentData()
        if (
            values["original"] is None
            and values["reconstruction"] is None
            and not values["criterion"]
            and values["judgement"] == "unassessed"
        ):
            self.feature_observations.pop(name, None)
        else:
            self.feature_observations[name] = values
        self._update_review_progress()

    def _feature_conflicts(self) -> list[str]:
        return [
            name
            for name, values in self.feature_observations.items()
            if not values["criterion"]
            or values["judgement"] != "preserved"
            or values["original"] != values["reconstruction"]
        ]

    @Slot(object, str)
    def _pair_failed(self, _key: object, message: str) -> None:
        self.canvas.clear()
        self.status.setText(f"Comparison could not be displayed: {message}")
        self._update_review_progress()

    @Slot(object, object)
    def _pair_loaded(self, index: object, models: object) -> None:
        detail = isinstance(index, tuple)
        if detail:
            index = index[0]
        if index != self.mesh_combo.currentData():
            return
        pair = self._pairs[int(index)]
        original, reconstruction = models
        self.canvas.set_models(original, reconstruction)
        if detail:
            self.canvas.original_detail.setChecked(True)
        else:
            self.canvas.reset_view()
        self.status.setText(
            f"Original: {pair.original_path.name} ({original.triangle_count} faces)  |  "
            f"Reconstruction: {pair.reconstruction_path.name} "
            f"({reconstruction.triangle_count} faces)  |  read-only"
        )
        self._update_review_progress()

    @Slot()
    def _pair_original_presented(self) -> None:
        if self.canvas.comparison_ready:
            index = self.mesh_combo.currentData()
            if index is not None:
                pair = self._pairs[int(index)]
                self._reviewed_pair_ids.add(pair.pair_id)
                self.display_scopes[pair.original_path.name] = (
                    "original" if self.canvas.full_resolution_ready else "preview"
                )
        self._update_review_progress()

    @Slot()
    def _load_original_detail(self) -> None:
        index = self.mesh_combo.currentData()
        if index is not None:
            pair = self._pairs[int(index)]
            self.status.setText(
                "Loading optional original detail… Preview decisions remain recorded."
            )
            self._mesh_loader.request_paths(
                (index, "detail"),
                (pair.original_path, pair.reconstruction_path),
                expected=(pair.original_sha256, pair.reconstruction_sha256),
            )

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
                target_pair_index = later_indexes[0] if later_indexes else unreviewed_indexes[0]
                self.mesh_combo.setCurrentIndex(self.mesh_combo.findData(target_pair_index))
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
        conflicts = self._feature_conflicts()
        concerns = any(value in {"fail", "uncertain"} for value in self.subject_decisions.values())
        all_pass = complete and not concerns
        pair_index = self.mesh_combo.currentData()
        try:
            current_position = self._required_pair_indexes.index(int(pair_index))
        except (TypeError, ValueError):
            current_position = -1
        self.previous_specimen_button.setEnabled(current_position > 0)
        self.next_specimen_button.setEnabled(total > 1)
        pair = self._pairs[int(pair_index)] if pair_index is not None else None
        current_seen = bool(pair and pair.required and self.canvas.comparison_ready)
        self.specimen_decision.setEnabled(current_seen)
        self.review_progress.setText(f"Inspected: {reviewed} / {total} specimens.")
        self.review_gate.setText(
            "Approve once if all inspected specimens fit. Original detail is optional."
            if all_pass
            else "Resolve the individual concern before approval, or reject this option."
            if concerns
            else f"View the remaining {total - reviewed} specimens, then approve once. "
            "You can reject now."
        )
        self.review_gate.setObjectName("statusSuccess" if complete else "status")
        if conflicts:
            self.review_gate.setText(
                "QC pass blocked: unresolved study-specific feature check for "
                + ", ".join(conflicts)
                + ". Review the named feature and any counts, or record QC failure."
            )
            self.review_gate.setObjectName("statusError")
        self.review_gate.setStyleSheet("")
        self.fail_button.setVisible(not self._read_only)
        self.fail_button.setEnabled(current_seen)
        self.complete_button.setEnabled(all_pass and not conflicts and self.canvas.comparison_ready)
        self.maybe_button.setEnabled(current_seen)
        if self._read_only:
            self.complete_button.hide()
            self.decision_panel.hide()
            self.close_button.setText("Close comparison")
        _set_action_emphasis(self.next_specimen_button, not all_pass)
        _set_action_emphasis(self.complete_button, all_pass and not conflicts)

    @Slot()
    def _record_visual_qc_pass(self) -> None:
        required_names = {p.original_path.name for p in self._pairs if p.required}
        if (
            required_names
            and self._required_pair_ids <= self._reviewed_pair_ids
            and not self._feature_conflicts()
            and not any(
                self.subject_decisions.get(name) in {"fail", "uncertain"} for name in required_names
            )
            and self.canvas.comparison_ready
        ):
            self.subject_decisions.update({name: "pass" for name in required_names})
            self._review_decision = True
            self.pass_check.setChecked(True)
            self.accept()
        else:
            self._update_review_progress()
            if not self.canvas.comparison_ready:
                self.review_gate.setText("Wait for both mesh layers to finish loading.")

    @Slot()
    def _record_visual_qc_fail(self) -> None:
        index = self.mesh_combo.currentData()
        pair = self._pairs[int(index)] if index is not None else None
        if pair and pair.required and self.canvas.comparison_ready:
            self.subject_decisions[pair.original_path.name] = "fail"
            self._review_decision = False
            self.pass_check.setChecked(False)
            self.reject()
        else:
            self.review_gate.setText(
                "Load a pilot specimen with both mesh layers to reject this option."
            )


class ReferenceCalibrationDialog(QDialog):
    """Batch each stage and require every-specimen fit review before advancing."""

    def __init__(
        self,
        study_directory: Path,
        parent: QWidget | None = None,
        *,
        verified_snapshot: ReferenceCalibrationStudySnapshot | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.WindowMinMaxButtonsHint
            | Qt.WindowType.WindowCloseButtonHint
        )
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.study_directory = study_directory.resolve()
        if (
            verified_snapshot is not None
            and verified_snapshot.study_directory.resolve() != self.study_directory
        ):
            raise ValueError("Verified pilot snapshot belongs to a different study")
        self._snapshot = verified_snapshot or load_reference_calibration_study(self.study_directory)
        self._viewer_preparation = PreviewMeshLoader(self)
        self._viewer_preparation.loaded.connect(self._candidate_prepared)
        self._viewer_preparation.failed.connect(self._candidate_prepare_failed)
        self._preview_prefetch = PreviewMeshLoader(self)
        self._saved_search_loader = PreviewMeshLoader(self)
        self._saved_search_loader.loaded.connect(self._saved_search_loaded)
        self._saved_search_loader.failed.connect(self._saved_search_failed)
        self._audit_loader = PreviewMeshLoader(self)
        self._audit_loader.loaded.connect(
            lambda _key, path: self.status.setText(f"Verified pilot audit saved: {path}")
        )
        self._audit_loader.failed.connect(
            lambda _key, error: self.status.setText(f"Audit export failed: {error}")
        )
        self._restoring_search = False
        self._worker: _CalibrationStageWorker | None = None
        self._fit_search_stop_text: str | None = None
        self._notification_keys = set()
        self._progress_context = {}
        self._assessment = None
        self._tray = QSystemTrayIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxInformation), self
        )
        self._tray.setToolTip("DiffeoForge pilot")
        self._tray.messageClicked.connect(self._show_pilot_notification)
        self._thread_pool = ActivityPool(self)
        self._approval_checks: dict[str, QCheckBox] = {}
        self._review_buttons: dict[str, QPushButton] = {}
        self._continuation_buttons: dict[str, QPushButton] = {}
        self._visually_reviewed_candidates: set[str] = set()
        self._visually_approved_candidates: set[str] = set()
        self.setWindowTitle("Automatic Deformetrica pilot calibration")
        self.resize(1040, 820)
        self.setMinimumSize(850, 650)

        root = QVBoxLayout(self)
        title = QLabel("Automatic staged pilot calibration")
        title.setObjectName("title")
        root.addWidget(title)
        root.addWidget(self._thread_pool.indicator)
        boundary = QLabel(
            "Run the options in this stage, then inspect every specimen before advancing."
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
        self.afk_mode = QCheckBox(
            "AFK / overnight: continue with eligible provisional recommendations"
        )
        self.afk_mode.setToolTip(
            "Explicit confirmation at Start. Existing pilot grid only; ambiguous or boundary "
            "choices remain provisional. No visual approval, outward search or atlas launch."
        )
        self.afk_mode.toggled.connect(self._afk_toggled)
        self.advanced_mode.toggled.connect(
            lambda checked: self.afk_mode.setChecked(False) if checked else None
        )
        root.addWidget(self.afk_mode)
        self.outward_mode = QCheckBox(
            "…and widen the search outward when the best value sits at a boundary"
        )
        self.outward_mode.setToolTip(
            "Without this, an unattended pilot accepts a boundary winner and the "
            "opportunity to widen the search is spent. With it, the pilot keeps adding "
            "outward candidates until the winner is no longer at the edge, or until it "
            "reaches the feasibility limits shown at Start."
        )
        self.outward_mode.setEnabled(False)
        if self._snapshot.plan.qc_recalibration_source:
            self.advanced_mode.blockSignals(True)
            self.advanced_mode.setChecked(True)
            self.advanced_mode.blockSignals(False)
            title.setText("QC follow-up calibration")
            boundary.setText(
                "Bounded neighboring settings around the previous atlas. All recorded QC "
                "concerns and retained controls are included. Inspect the selected candidate "
                "after each stage. No automatic anatomical approval or outward search. "
                "The original template is retained; unresolved fits may require template review. "
                "After selection, run a new full-cohort atlas and repeat QC."
            )
            self.advanced_mode.hide()
            self.afk_mode.hide()
            self.outward_mode.hide()
        self.afk_mode.toggled.connect(
            lambda checked: self.outward_mode.setChecked(False) if not checked else None
        )
        root.addWidget(self.outward_mode)
        self.adaptive_fit_search = QCheckBox(
            "Automatically improve fit (up to 12 extra runs per stage)"
        )
        self.adaptive_fit_search.setChecked(False)
        self.adaptive_fit_search.setVisible(not bool(self._snapshot.plan.qc_recalibration_source))
        self.adaptive_fit_search.setToolTip(
            "Up to 3 rounds, 300 iterations per added run. Compare every specimen, "
            "continue useful results and test relative parameter changes within recorded bounds. "
            "Stop at a plateau, trade-off or budget. Visual approval is still required."
        )
        root.addWidget(self.adaptive_fit_search)
        fit_row = QHBoxLayout()
        self.find_fit_button = QPushButton("Find fit")
        self.find_fit_button.setObjectName("primary")
        self.find_fit_button.setToolTip(
            "One specimen and one attempt at a time. Reject starts the next parameters for "
            "this specimen; approve starts the next specimen. A common deformation basis "
            "is retained after the first approval. All approved individual "
            "fits initialize a new combined original-target confirmation, which needs fresh QC. "
            "Saved results still need your visual QC. Previous pilots are preserved."
        )
        self.find_fit_button.clicked.connect(self._find_fit)
        fit_row.addWidget(self.find_fit_button)
        self.saved_searches_button = QPushButton("Saved fit searches…")
        self.saved_searches_button.clicked.connect(self._choose_saved_search)
        fit_row.addWidget(self.saved_searches_button)
        self.plan_b_button = QPushButton("Review / use Plan B")
        self.plan_b_button.clicked.connect(self._restore_plan_b)
        self.plan_b_button.setToolTip("Return to your saved fallback. A fresh review is required.")
        fit_row.addWidget(self.plan_b_button)
        self.compare_plan_b_button = QPushButton("Compare Plan B")
        self.compare_plan_b_button.clicked.connect(self._compare_plan_b)
        fit_row.addWidget(self.compare_plan_b_button)
        self.denser_model_button = QPushButton("Test denser common model")
        self.denser_model_button.setToolTip(
            "More control points; starts with this specimen. All specimens need fresh QC "
            "on this new basis. Earlier searches and approvals stay saved."
        )
        self.denser_model_button.clicked.connect(self._test_denser_model)
        fit_row.addWidget(self.denser_model_button)
        fit_row.addStretch()
        root.addLayout(fit_row)
        self.keep_previous_button = QPushButton("Keep previously approved fit")
        self.keep_previous_button.setToolTip(
            "Use the unchanged, previously approved reconstruction. No new fit or repeated QC."
        )
        self.keep_previous_button.clicked.connect(self._keep_previous_fit)
        root.addWidget(self.keep_previous_button)
        self.screen_controls = QWidget()
        screen_layout = QHBoxLayout(self.screen_controls)
        screen_layout.setContentsMargins(0, 0, 0, 0)
        self.screen_enabled = QCheckBox("Review one specimen before joint comparisons")
        self.screen_enabled.setChecked(True)
        self.screen_enabled.toggled.connect(lambda _checked: self._render())
        screen_layout.addWidget(self.screen_enabled)
        self.screen_subject = QComboBox()
        self.screen_subject.setToolTip("First screening specimen; choose a difficult fit.")
        screen_layout.addWidget(self.screen_subject)
        self.screen_second_subject = QComboBox()
        self.screen_second_subject.setToolTip("Optional second, contrasting specimen.")
        screen_layout.addWidget(self.screen_second_subject)
        self.screen_notice = QLabel()
        self.screen_notice.setWordWrap(True)
        self.screen_notice.setObjectName("status")
        root.addWidget(self.screen_controls)
        root.addWidget(self.screen_notice)
        self.retry_screens_button = QPushButton("Retry technically failed screens")
        self.retry_screens_button.clicked.connect(
            lambda: self._start_pilot(adaptive=False, retry_screens=True)
        )
        root.addWidget(self.retry_screens_button)
        self.retry_screens_button.hide()
        self._screen_selector_stage = None
        from diffeoforge.reference_integration_check import DEFAULT_TOLERANCES

        numerical_panel = QWidget()
        numerical_layout = QVBoxLayout(numerical_panel)
        self.integration_fields = {}
        for key, label in (
            ("atlas_rms_relative", "Atlas RMS / reference diagonal"),
            ("objective_relative", "Relative objective difference"),
            ("residual_relative", "Worst specimen residual difference"),
        ):
            row = QHBoxLayout()
            row.addWidget(QLabel(label))
            control = QDoubleSpinBox()
            control.setRange(0.001, 100.0)
            control.setDecimals(3)
            control.setSuffix(" %")
            control.setValue(DEFAULT_TOLERANCES[key] * 100)
            row.addWidget(control)
            numerical_layout.addLayout(row)
            self.integration_fields[key] = control
        self.integration_notice = QLabel(
            "All timepoint options use every pilot specimen. Criteria are recorded before "
            "the first run; they measure numerical stability, not anatomical accuracy."
        )
        self.integration_notice.setWordWrap(True)
        numerical_layout.addWidget(self.integration_notice)
        self.integration_controls = InfoDisclosure("Numerical comparison criteria", numerical_panel)
        root.addWidget(self.integration_controls)
        self.finer_resolution_button = QPushButton("Test finer resolution")
        self.finer_resolution_button.setToolTip(
            "Adds one finer full-pilot comparison, starting from the finest saved fit. "
            "Previous results and numerical tolerances remain unchanged. New fits need visual QC."
        )
        self.finer_resolution_button.clicked.connect(
            lambda: self._start_pilot(adaptive=False, finer_resolution=True)
        )
        self.finer_resolution_button.hide()
        root.addWidget(self.finer_resolution_button)
        self.qualification_button = QPushButton("Check time resolution (no optimization)")
        _set_action_emphasis(self.qualification_button, True)
        self.qualification_button.setToolTip(
            "Fixed-state Shooting at N, 2N−1 and 4N−3 timepoints, or reuse of an existing "
            "verified check. No new optimization. This does not approve anatomy."
        )
        self.qualification_button.clicked.connect(
            lambda: self._start_pilot(adaptive=False, qualification=True)
        )
        qualification_actions = QHBoxLayout()
        qualification_actions.addWidget(self.qualification_button)
        self.finer_model_button = QPushButton("Refit a finer model")
        _set_action_emphasis(self.finer_model_button, False)
        self.finer_model_button.setToolTip(
            "New warm fit at 2N−1 timepoints. Retains the old fit; then review and qualify it."
        )
        self.finer_model_button.clicked.connect(
            lambda: self._start_pilot(
                adaptive=False,
                qualification=True,
                finer_model=True,
                qualification_iterations=self.continuation_iterations.value(),
            )
        )
        qualification_actions.addWidget(self.finer_model_button)
        root.addLayout(qualification_actions)
        self.audit_button = QPushButton("Export pilot audit")
        _set_action_emphasis(self.audit_button, False)
        self.audit_button.clicked.connect(self._export_audit)
        root.addWidget(self.audit_button)
        continuation_controls = QWidget()
        continuation_layout = QHBoxLayout(continuation_controls)
        continuation_layout.setContentsMargins(0, 0, 0, 0)
        continuation_layout.addWidget(QLabel("Additional iterations for a selected option"))
        self.continuation_iterations = QSpinBox()
        self.continuation_iterations.setRange(1, 20_000)
        self.continuation_iterations.setValue(300)
        self.continuation_iterations.valueChanged.connect(self._update_continuation_labels)
        continuation_layout.addWidget(self.continuation_iterations)
        continuation_layout.addStretch()
        root.addWidget(InfoDisclosure("Continuation budget", continuation_controls))
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
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
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
        self.selection_combo.currentIndexChanged.connect(self._update_stage_review_action)
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
        self.advance_button = QPushButton("Prepare next stage")
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
        self.advanced_mode.blockSignals(True)
        self.advanced_mode.setChecked(True)
        self.advanced_mode.blockSignals(False)
        self.advanced_mode.hide()
        self.afk_mode.hide()
        self.outward_mode.hide()
        boundary.setText(
            "Find fit: one specimen, one attempt, then your review. "
            "Reject tries new parameters; approve continues. "
            "A combined fit is checked afterwards."
        )
        self._render(self._snapshot)

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
        self._continuation_buttons = {}

    def _update_continuation_labels(self) -> None:
        for letter, button in self._continuation_buttons.items():
            prefix = "Continue saved fit" if self._individual_checkpoint() else f"Continue {letter}"
            if self._snapshot.current_stage and self._snapshot.current_stage.order == 4:
                prefix = "Optional strict check"
            button.setText(f"{prefix}: +{self.continuation_iterations.value()} iterations")

    def _render(self, snapshot: ReferenceCalibrationStudySnapshot | None = None) -> None:
        self.finer_resolution_button.hide()
        self._assessment = None
        self._snapshot = snapshot or load_reference_calibration_study(self.study_directory)
        self.screen_controls.hide()
        self.screen_notice.hide()
        stage = self._snapshot.current_stage
        self.qualification_button.setVisible(bool(stage and stage.order == 4))
        self.finer_model_button.setVisible(bool(stage and stage.order == 4))
        self.finer_model_button.setEnabled(
            self._worker is None
            and not self._restoring_search
            and any(c.metrics for c in self._snapshot.candidates)
        )
        self.qualification_button.setEnabled(self._worker is None and not self._restoring_search)
        self.integration_controls.setVisible(
            False
        )  # Historical refit criteria remain in the saved report.
        for key, field in self.integration_fields.items():
            if self._snapshot.integration_tolerances:
                field.setValue(self._snapshot.integration_tolerances[key] * 100)
            field.setEnabled(
                not self._worker
                and not self._restoring_search
                and not self._snapshot.integration_tolerances
                and not any(c.attempts for c in self._snapshot.candidates)
            )
        from diffeoforge.reference_sequential_fit import sequence_info, sequence_progress

        self._sequence_info = sequence_info(self.study_directory)
        self._sequence_progress = sequence_progress(self.study_directory)
        stage = self._snapshot.current_stage
        can_keep = bool(
            stage
            and stage.order in (2, 3)
            and len(self._snapshot.selected_candidate_ids) == stage.order - 1
            and not self._snapshot.plan.qc_recalibration_source
            and not self._individual_checkpoint()
        )
        self.keep_previous_button.setVisible(can_keep)
        self.keep_previous_button.setEnabled(
            can_keep and self._worker is None and not self._restoring_search
        )
        if can_keep:
            provisional_baseline = iteration_limit_selection_available(
                self._snapshot, stage.stage_id + "-retained"
            )
            self.keep_previous_button.setText(
                f"Keep {'provisional' if provisional_baseline else 'approved'} "
                f"stage {stage.order - 1} fit → stage {stage.order + 1}"
            )
        for candidate_id, approved in self._snapshot.visual_reviews.items():
            self._visually_reviewed_candidates.add(candidate_id)
            if approved:
                self._visually_approved_candidates.add(candidate_id)
            else:
                self._visually_approved_candidates.discard(candidate_id)
        self._clear_content()
        running = self._worker is not None or self._restoring_search
        from diffeoforge.reference_calibration_study import STUDY_MANIFEST, _read_json

        context = _read_json(self.study_directory / STUDY_MANIFEST, "study")
        directory = context["inputs"].get("full_cohort", {}).get("directory")
        if directory:
            dataset = QLabel("Pilot data: " + " / ".join(Path(directory).parts[-4:]))
            dataset.setWordWrap(True)
            dataset.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            dataset.setToolTip(
                str(directory)
                + " — Opening completed results does not change the Data & Alignment inputs."
            )
            self.content_layout.addWidget(dataset)
        fallback = bool(self._sequence_progress and self._sequence_progress["fallback"])
        for button in (self.plan_b_button, self.compare_plan_b_button):
            button.setVisible(fallback and self._individual_checkpoint())
            button.setEnabled(not running)
        self.adaptive_fit_search.setVisible(
            not self._sequence_info and not bool(self._snapshot.plan.qc_recalibration_source)
        )
        if self._sequence_progress:
            progress = self._sequence_progress
            caption = (
                f"{progress['approved']} of {progress['total']} approved · "
                f"{progress['remaining']} still to review"
            )
            if self._individual_checkpoint():
                caption += (
                    f" · Specimen {self._sequence_info['index'] + 1} of "
                    f"{progress['total']}: {self._sequence_info['filename']}"
                )
            else:
                caption = (
                    f"Individual fits: {progress['approved']} of {progress['total']} approved · "
                    + (
                        "Combined pilot complete"
                        if self._snapshot.status == "completed"
                        else f"Joint stage {stage.order}: "
                        + (
                            "running — see live progress above"
                            if running
                            else "ready to run"
                            if self._snapshot.status == "ready"
                            else "review joint results"
                        )
                    )
                )
            notice = QLabel(caption)
            notice.setObjectName("statusSuccess")
            notice.setWordWrap(True)
            self.content_layout.addWidget(notice)
        self.afk_mode.setEnabled(not running and self._snapshot.status != "completed")
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
            completion = report.get("final_pilot_completion") if report else None
            if completion:
                self.status.setText(
                    "Pilot finished provisionally: the selected joint fit remains non-converged. "
                    "Prepare the full-cohort atlas and review its reconstructions."
                    if completion["provisional"]
                    else "Pilot finished with native convergence, integration checks and "
                    "anatomical approval. Full-cohort atlas and QC are still required."
                )
            recommendation_title = QLabel(
                "Provisionally selected parameter set"
                if completion and completion["provisional"]
                else "Selected parameter set"
                if completion
                else "Recommended parameter set"
            )
            recommendation_title.setObjectName("title")
            recommendation_layout.addWidget(recommendation_title)
            if report is not None:
                afk_summary = afk_return_summary(report)
                if afk_summary:
                    notice = QLabel(afk_summary)
                    notice.setTextFormat(Qt.TextFormat.PlainText)
                    notice.setWordWrap(True)
                    notice.setObjectName("statusWarning")
                    recommendation_layout.addWidget(notice)
                unit = str(report["coordinate_unit"])
                for parameter in report["recommended_parameters"]:
                    value = parameter["value"]
                    rendered = (
                        str(value) if parameter["unit"] is None else f"{float(value):.8g} {unit}"
                    )
                    line = QLabel(f"<b>{parameter['title']}:</b> {rendered}")
                    line.setTextFormat(Qt.TextFormat.RichText)
                    line.setWordWrap(True)
                    recommendation_layout.addWidget(line)
                meaning = QWidget()
                meaning_layout = QVBoxLayout(meaning)
                meaning_layout.setContentsMargins(0, 0, 0, 0)
                for parameter in report["recommended_parameters"]:
                    explanation = QLabel(f"<b>{parameter['title']}</b><br>{parameter['meaning']}")
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
                    "Native optimizer convergence, unchanged-state integration checks and "
                    "recorded anatomical approval are separate. A capped result remains "
                    "provisional; state-drift diagnostics and old qualification receipts "
                    "retain their original meaning in the report."
                    if completion
                    else "This bounded QC follow-up varied attachment width, deformation/control "
                    "spacing, noise and time points around the previous settings. "
                    "Each selected stage required visual review. It is adaptive calibration, "
                    "not independent validation; a new full-cohort atlas and QC are still required."
                    if self._snapshot.plan.qc_recalibration_source
                    else "DiffeoForge first screened attachment and deformation scales "
                    "together, then refined deformation, regularization, and numerical "
                    "accuracy. Standard automatic choices require stability; AFK can accept "
                    "eligible ambiguous or boundary-limited choices provisionally. "
                    "The complete report preserves every alternative, "
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
            self.advance_button.setText("Return to full atlas setup")
            self.advance_button.setEnabled(not running)
            self.advance_button.setToolTip("Apply the saved parameters. No atlas starts now.")
            self.advance_button.show()
            _set_action_emphasis(self.advance_button, not running)
            self.review_next_button.hide()
            self.selection_combo.hide()
            self.cancel_button.hide()
            self.advanced_mode.setEnabled(True)
            self.content_layout.addStretch()
            return
        stage = self._snapshot.current_stage
        assert stage is not None
        automatic_mode = False
        self.advanced_mode.setEnabled(
            not running and not self._snapshot.plan.qc_recalibration_source
        )
        heading = QLabel(
            "Individual fit — inspect, approve, reject or keep as Plan B"
            if self._individual_checkpoint()
            else ("Combined pilot — " if self._sequence_info else "")
            + f"Stage {stage.order} of {len(self._snapshot.plan.stages)} — {stage.title}"
        )
        heading.setObjectName("sectionTitle")
        self.content_layout.addWidget(heading)
        guidance = stage_guidance(stage)
        if stage.order == 4:
            heading.setText("Stage 4 of 4 — Check time resolution and finish")
            guidance = replace(
                guidance,
                question="Is this saved fit ready for the full-cohort atlas?",
                explanation="Check the unchanged saved state on three time grids. "
                "No optimization runs. Existing verified integration checks are reused.",
                action="Review the joint fit, check its time resolution, then finish. "
                "An iteration-limited fit requires an explicit provisional finish.",
                caution="Engineering checks do not establish "
                "biological validity or a global optimum.",
            )
        if self._snapshot.plan.qc_recalibration_source:
            guidance = replace(
                guidance,
                action="Run this bounded stage, choose an eligible option, and inspect all "
                "of its pilot reconstructions before advancing. No automatic selection.",
            )
            if stage.stage_id == "attachment":
                guidance = replace(
                    guidance,
                    question="Which matching-detail width preserves the anatomy?",
                    explanation="Compare half, unchanged and double the previous attachment "
                    "width. Deformation settings stay fixed in this stage. This local "
                    "follow-up does not test every interaction between parameters.",
                )
        question = QLabel(guidance.question)
        if self._individual_checkpoint():
            question.setText("Does this fit preserve the original shape?")
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
                "Grey = context only · Yellow = trade-off · Red = unfavorable relative "
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
            assessment = assess_reference_calibration_snapshot(
                self._snapshot,
                visual_approvals=self._visual_approvals(),
                completion_preview=stage.order == 4,
            )
            self._assessment = assessment
            recommended_option = self._recommended_option_text(assessment)
            summary = QLabel(
                f"Review first: {recommended_option}. "
                + (
                    "Smallest worst-specimen distance; anatomy still needs approval."
                    if self._snapshot.current_stage.kind != "integration_accuracy"
                    else "Numerical integration comparison; anatomy still needs approval."
                )
                if recommended_option
                else "No option qualifies yet. The reason and next action appear on each result."
            )
            summary.setWordWrap(True)
            summary.setObjectName("statusWarning")
            if self._individual_checkpoint():
                summary.setText("Inspect this specimen and choose the best surface fit.")
                summary.setObjectName("status")
            self.content_layout.addWidget(summary)
            details = QLabel("\n".join(assessment.cautions))
            if self._individual_checkpoint():
                details.setText(
                    "Individual probes need your visual decision. Combined convergence and "
                    "all-specimen QC follow after the last specimen."
                )
            details.setWordWrap(True)
            self.content_layout.addWidget(InfoDisclosure("How options are ranked", details))
        completed = sum(candidate.status == "completed" for candidate in self._snapshot.candidates)
        if automatic_mode:
            completed_before = sum(
                len(planned_stage.candidates)
                for planned_stage in self._snapshot.plan.stages
                if planned_stage.stage_id in self._snapshot.selected_candidate_ids
            )
            total_candidates = sum(
                len(planned_stage.candidates) for planned_stage in self._snapshot.plan.stages
            )
            total_completed = completed_before + completed
            self.progress.setRange(0, total_candidates)
            self.progress.setValue(total_completed)
            self.progress.setFormat(f"{total_completed} of {total_candidates} pilot runs completed")
        elif stage.order == 4:
            checks = [
                c for c in self._snapshot.candidates if c.candidate_id.startswith("qualification-")
            ]
            self.progress.setRange(0, max(1, len(checks)))
            self.progress.setValue(sum(c.status == "completed" for c in checks))
            self.progress.setFormat(
                f"{sum(c.status == 'completed' for c in checks)} of {len(checks)} "
                "saved-model checks completed"
                if checks
                else "Saved model ready to check"
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
        self._candidate_state_labels = {}
        for index, candidate in enumerate(self._snapshot.candidates, start=1):
            if (
                stage.order == 4
                and candidate.status == "pending"
                and not (candidate.candidate_id.startswith("qualification-"))
            ):
                continue  # Historical refit grid is not part of the new check.
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
        if (
            not self._snapshot.selected_candidate_ids
            and not self.advanced_mode.isChecked()
            and not self._snapshot.plan.qc_recalibration_source
        ):
            self.start_button.setText("Find fit")
        self.adaptive_fit_search.setEnabled(not running)
        self.find_fit_button.setEnabled(
            not running
            and not self._snapshot.selected_candidate_ids
            and not self._snapshot.plan.qc_recalibration_source
        )
        self.find_fit_button.setText(
            "Improve this specimen"
            if self._individual_checkpoint()
            else "New fit search"
            if self._sequence_info
            else "Find fit"
        )
        self.saved_searches_button.setEnabled(not running)
        self.denser_model_button.setVisible(self._individual_checkpoint())
        self.denser_model_button.setEnabled(not running)
        if self._individual_checkpoint():
            self.find_fit_button.setToolTip(
                "Try the next coarse-to-fine attempt for this specimen. Saved deformations "
                "can initialize finer matching; previous approvals remain in this sequence."
            )
        elif self._sequence_info:
            self.find_fit_button.setToolTip(
                "Starts a separate sequence at specimen 1 around the selected settings. "
                "All previous results are retained."
            )
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
        if awaiting:
            previous_selection = self.selection_combo.currentData()
            self.selection_combo.blockSignals(True)
            self.selection_combo.clear()
            self.selection_combo.addItem(
                "Choose an option…",
                None,
            )
            for index, candidate in enumerate(
                self._snapshot.candidates,
                start=1,
            ):
                if candidate.status == "completed" and candidate.metrics is not None:
                    option_letter = candidate_option_label(index)
                    review_suffix = (
                        " · visual QC passed"
                        if candidate.candidate_id in self._visually_approved_candidates
                        else " · fit rejected"
                        if candidate.candidate_id in self._visually_reviewed_candidates
                        else " · fit not reviewed"
                    )
                    recommendation_suffix = (
                        " · converged, integration checked, approved"
                        if stage.order == 4
                        and candidate.candidate_id == assessment.balanced_candidate_id
                        else " · lowest measured distance"
                        if candidate.candidate_id == assessment.balanced_candidate_id
                        else ""
                    )
                    self.selection_combo.addItem(
                        f"Option {option_letter} — {candidate.label}"
                        f"{recommendation_suffix}{review_suffix}",
                        candidate.candidate_id,
                    )
            previous_index = self.selection_combo.findData(previous_selection)
            if stage.order == 4 and previous_index <= 0:
                previous_index = next(
                    (
                        self.selection_combo.findData(c.candidate_id)
                        for c in reversed(self._snapshot.candidates)
                        if c.status == "completed"
                        and self._snapshot.visual_reviews.get(c.candidate_id) is not False
                    ),
                    0,
                )
            if self._individual_checkpoint() and self.selection_combo.count() == 2:
                previous_index = 1
            if previous_index >= 0:
                self.selection_combo.setCurrentIndex(previous_index)
            self.selection_combo.blockSignals(False)
            self.collect_evidence_button.show()
            self._update_stage_review_action()
        elif running:
            self.status.setText(
                "Running. Inspect any completed option while the next option computes."
            )
        else:
            self.status.setText("Next: click the green Run all candidates in this stage button.")
        if stage and stage.order == 4:
            pending = any(
                c.candidate_id.startswith("qualification-") and c.status != "completed"
                for c in self._snapshot.candidates
            )
            label = (
                "Resume previously declared optimizer check"
                if pending
                else "Check time resolution (no optimization)"
            )
            for button in (self.start_button, self.qualification_button):
                button.setText(label)
                button.setToolTip(
                    "This unfinished check retains its original declared optimizer settings."
                    if pending
                    else "Reuse verified checks or shoot the unchanged saved state on nested "
                    "time grids. This action does not optimize the atlas."
                )
            if self._worker is None and (
                self._snapshot.status == "ready" or self.selection_combo.currentData() is None
            ):
                self.status.setText(
                    "An older optimizer check is unfinished. Resume keeps its original settings."
                    if pending
                    else "Choose a saved joint fit and review it. Check time resolution reuses "
                    "verified evidence or shoots the unchanged state; no optimization runs."
                )
        self._render_screening()

    def _render_screening(self) -> None:
        stage = self._snapshot.current_stage
        active = bool(
            stage
            and stage.order in (2, 3)
            and not self._snapshot.plan.qc_recalibration_source
            and not self._individual_checkpoint()
        )
        self.screen_controls.setVisible(active)
        self.screen_notice.setVisible(active)
        self.retry_screens_button.hide()
        if not active:
            return
        state = self._snapshot.early_screening
        running = self._worker is not None or self._restoring_search
        if state and state["technical_failures"]:
            self.retry_screens_button.show()
            self.retry_screens_button.setEnabled(not running)
            self.retry_screens_button.setText(
                f"Retry technically failed screens ({len(state['technical_failures'])})"
            )
        pending = any(c.status != "completed" for c in self._snapshot.candidates)
        if self._screen_selector_stage != (self.study_directory, stage.stage_id):
            self._screen_selector_stage = (self.study_directory, stage.stage_id)
            self.screen_subject.clear()
            self.screen_second_subject.clear()
            self.screen_second_subject.addItem("No second specimen", None)
            names = [s.filename for s in self._snapshot.plan.selected_pilot_subjects]
            for name in names:
                self.screen_subject.addItem(name, name)
                self.screen_second_subject.addItem(name, name)
            # Use measured prior mismatch when available, without hardcoded species.
            baseline = next(
                (c for c in self._snapshot.candidates if c.candidate_id.endswith("-retained")), None
            )
            fit = (baseline.metrics or {}).get("original_surface_fit", {}) if baseline else {}
            if fit:
                worst = max(fit, key=lambda n: float(fit[n]["p95"]) / float(fit[n]["diagonal"]))
                self.screen_subject.setCurrentIndex(self.screen_subject.findData(worst))
        configurable = not state and pending and not running
        self.screen_enabled.setEnabled(configurable)
        self.screen_subject.setEnabled(configurable and self.screen_enabled.isChecked())
        self.screen_second_subject.setEnabled(configurable and self.screen_enabled.isChecked())
        if not state:
            self.screen_notice.setText(
                "One option, one specimen, then your decision. Joint fits need separate review."
                if pending
                else "Existing joint results are preserved; no screening rerun needed."
            )
            if pending and self.screen_enabled.isChecked():
                self.start_button.setText("Start early specimen review")
                self.start_button.setVisible(True)
                self.start_button.setEnabled(not running)
            return
        self.screen_subject.setCurrentIndex(self.screen_subject.findData(state["subjects"][0]))
        if len(state["subjects"]) == 2:
            self.screen_second_subject.setCurrentIndex(
                self.screen_second_subject.findData(state["subjects"][1])
            )
        self.screen_notice.setText(
            f"Early review: {state['reviewed']} of {len(state['candidate_ids'])} options decided · "
            f"{len(state['kept'])} kept · {len(state['rejected'])} discarded"
            + f" · {len(state['technical_failures'])} technical failures"
            + (
                " · Joint fits still need all-specimen QC."
                if state["complete"]
                else f" · {state['next_subject']}"
            )
        )
        if not state["complete"]:
            self.selection_combo.hide()
            self.advance_button.hide()
            self.review_next_button.hide()
            self.collect_evidence_button.hide()
            self.start_button.setVisible(True)
            self.start_button.setText(
                "Review this specimen"
                if state["current_status"] == "completed"
                else "Test next option"
                if state["current_child"] is None
                else "Retry this screen"
            )
            self.start_button.setEnabled(not running)
            if not running:
                self.status.setText("Review this screen; keeping an option permits its joint test.")
        elif any(
            c.status not in {"completed", "screened_out", "screen_failed"}
            for c in self._snapshot.candidates
        ):
            self.start_button.setText(
                f"Run kept options with all {self._snapshot.plan.pilot_subject_count} specimens"
            )
            self.start_button.setVisible(True)
            self.start_button.setEnabled(not running)
        elif state["technical_failures"]:
            self.start_button.hide()
            if not running:
                self.status.setText(
                    "Technical screens failed. Retry them; existing fits are preserved."
                )
        self.adaptive_fit_search.setEnabled(False)

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
        option_letter = candidate_option_label(option_index)
        title = QLabel(f"Option {option_letter} — {candidate.label}")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        if self._assessment:
            row = next(
                (
                    r
                    for r in self._assessment.candidates
                    if r.candidate_id == candidate.candidate_id
                ),
                None,
            )
            if row and row.rejection_reasons and candidate.metrics:
                blockers = QLabel("Next: " + "; ".join(row.rejection_reasons))
                blockers.setWordWrap(True)
                blockers.setObjectName("statusWarning")
                layout.addWidget(blockers)
        parameter, meaning = candidate_parameter_summary(
            self._snapshot.current_stage,
            planned.values,
            coordinate_unit=self._snapshot.plan.coordinate_unit,
        )
        parameter_label = QLabel(parameter)
        parameter_label.setObjectName("sectionTitle")
        parameter_label.setWordWrap(True)
        option_help = QWidget()
        option_help_layout = QVBoxLayout(option_help)
        option_help_layout.setContentsMargins(0, 0, 0, 0)
        option_help_layout.addWidget(parameter_label)
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
            fit = normalized_candidate_subject_fit(self._snapshot, candidate)
            if fit:
                fit_label = QLabel(
                    "Anatomical review approved."
                    if self._snapshot.visual_reviews.get(candidate.candidate_id) is True
                    else "Anatomical review rejected."
                    if self._snapshot.visual_reviews.get(candidate.candidate_id) is False
                    else "Anatomical review needed — inspect the overlays."
                )
                fit_label.setWordWrap(True)
                layout.addWidget(fit_label)
                detail = QLabel(
                    "Distance p95 / original bounding-box diagonal; lower is closer. "
                    + (
                        "Area-sampled point-to-triangle distances; anatomy needs visual review.\n\n"
                        if metrics.get("original_surface_fit")
                        else "This is a sampled nearest-vertex proxy, not an anatomical pass.\n\n"
                    )
                    + "\n".join(
                        f"{value:.4g} bbox diagonals — {name}"
                        for name, value in sorted(fit.items(), key=lambda item: -item[1])
                    )
                )
                detail.setWordWrap(True)
                layout.addWidget(
                    InfoDisclosure("Technical distance proxy — not fit quality", detail)
                )
            passed, check_text = automatic_check_summary(metrics)
            check = QLabel(("✓ " if passed else "⚠ ") + check_text)
            check.setWordWrap(True)
            option_help_layout.addWidget(check)
            comparison_title = QLabel("Relative measurements — anatomy needs review")
            comparison_title.setObjectName("sectionTitle")
            option_help_layout.addWidget(comparison_title)
            if tradeoffs:
                comparison_details_title = QLabel(
                    "How to interpret the automatic comparison signals"
                )
                comparison_details_title.setObjectName("sectionTitle")
                option_help_layout.addWidget(comparison_details_title)
                for tradeoff in tradeoffs:
                    comparison = QLabel(self._tradeoff_assessment_summary_html(tradeoff))
                    comparison.setObjectName(
                        {
                            "favorable": "tradeoffFavorable",
                            "caution": "tradeoffCaution",
                            "unfavorable": "tradeoffUnfavorable",
                            "neutral": "tradeoffNeutral",
                        }[tradeoff.tone]
                    )
                    comparison.setTextFormat(Qt.TextFormat.RichText)
                    comparison.setWordWrap(True)
                    option_help_layout.addWidget(comparison)
                    comparison_detail = QLabel(self._tradeoff_assessment_html(tradeoff))
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
                option_help_layout.addWidget(comparison)
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
                    "ⓘ Hide technical measurements" if visible else "ⓘ Technical measurements"
                )
            )
            technical_row = QHBoxLayout()
            technical_row.addWidget(technical_button)
            technical_row.addStretch()
            layout.addLayout(technical_row)
            layout.addWidget(technical)
            reviewed = candidate.candidate_id in self._visually_reviewed_candidates
            approved = candidate.candidate_id in self._visually_approved_candidates
            if self._sequence_progress and self._sequence_progress["fresh_review_required"]:
                approved = False
            viewer = QPushButton("Review fit again…" if reviewed else "Inspect surface fit…")
            viewer.clicked.connect(
                lambda _checked=False, value=candidate: self._open_candidate(value)
            )
            _set_action_emphasis(viewer, False)
            self._review_buttons[candidate.candidate_id] = viewer
            viewer.setEnabled(candidate.status == "completed")
            approval = QCheckBox("Visual QC passed")
            approval.setVisible(approved)
            approval.setChecked(approved)
            approval.setEnabled(False)
            approval.setToolTip("Review this option again to change the recorded decision.")
            visual_status = QLabel(
                "Your review: approved."
                if approved
                else ("Your review: rejected." if reviewed else "Awaiting your review.")
            )
            visual_status.setObjectName(
                "statusSuccess" if approved else ("statusError" if reviewed else "status")
            )
            visual_status.setWordWrap(True)
            self._approval_checks[candidate.candidate_id] = approval
            review_controls = QHBoxLayout()
            review_controls.addWidget(viewer)
            continuation = QPushButton(
                f"Continue {option_letter}: +{self.continuation_iterations.value()} iterations"
            )
            self._continuation_buttons[option_letter] = continuation
            _set_action_emphasis(continuation, False)
            continuation.setToolTip(
                "Same parameters and learned state; only additional iterations."
            )
            if self._snapshot.current_stage.order == 4:
                continuation.setText(
                    f"Optional strict check: +{self.continuation_iterations.value()} iterations"
                )
                continuation.setToolTip(
                    "An optional legacy check at tolerance 1e-6 or tighter. It can take hours "
                    "and is not required for explicit provisional completion. "
                    "Existing fits stay saved."
                )
            if self._individual_checkpoint():
                continuation.setText(
                    f"Continue saved fit: +{self.continuation_iterations.value()} iterations"
                )
                continuation.setToolTip(
                    "Continues this specimen from its verified saved momentum field. "
                    "Same template, control points and parameters; optimizer history restarts. "
                    "Earlier approvals remain unchanged."
                )
            continuation.setEnabled(
                self._worker is None
                and self._snapshot.status == "awaiting_review"
                and metrics.get("invalid_face_count") == 0
                and metrics.get("optimizer_stop_signal")
                in {"maximum_iterations", "tolerance_threshold"}
            )
            continuation.clicked.connect(
                lambda _checked=False, value=candidate: self._start_selected_continuation(value)
            )
            review_controls.addWidget(continuation)
            review_controls.addWidget(approval)
            review_controls.addStretch()
            layout.addLayout(review_controls)
            layout.addWidget(visual_status)
            notes = getattr(self._snapshot, "visual_review_notes", {}).get(candidate.candidate_id)
            if notes:
                note_label = QLabel("Recorded anatomical notes: " + notes)
                note_label.setTextFormat(Qt.TextFormat.PlainText)
                note_label.setWordWrap(True)
                layout.addWidget(note_label)
        elif candidate.error:
            error = QLabel(candidate.error)
            error.setWordWrap(True)
            layout.addWidget(error)
            reason = self._snapshot.early_screening.get("failure_reasons", {}).get(
                candidate.candidate_id
            )
            if reason:
                details = QLabel(reason)
                details.setTextFormat(Qt.TextFormat.PlainText)
                details.setWordWrap(True)
                details.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                layout.addWidget(InfoDisclosure("Technical failure details", details))
        else:
            detail = QLabel(
                "Ready to run." if candidate.status == "pending" else "Ready for a new attempt."
            )
            self._candidate_state_labels[candidate.candidate_id] = detail
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
            "neutral": "○ Context only",
        }[assessment.tone]
        return f"<b>{prefix}: {assessment.label}</b><br>{assessment.interpretation}"

    @staticmethod
    def _tradeoff_assessment_summary_html(
        assessment: CalibrationTradeoffAssessment,
    ) -> str:
        prefix = {
            "favorable": "✓ Favorable",
            "caution": "↔ Trade-off",
            "unfavorable": "⚠ Unfavorable",
            "neutral": "○ Context only",
        }[assessment.tone]
        return f"<b>{prefix}:</b> {assessment.label}"

    def _selectable_candidate_ids(self) -> set[str]:
        if self._snapshot.current_stage and self._snapshot.current_stage.order == 4:
            return (
                {c.candidate_id for c in self._assessment.candidates if c.eligible}
                if self._assessment
                else set()
            )
        explicitly_failed = self._visually_reviewed_candidates - self._visually_approved_candidates
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

    def _recommended_option_text(self, assessment: object) -> str | None:
        """Return the human-facing option name for the balanced pilot candidate."""

        candidate_id = getattr(assessment, "balanced_candidate_id", None)
        if candidate_id is None:
            return None
        for index, candidate in enumerate(self._snapshot.candidates, start=1):
            if candidate.candidate_id == candidate_id:
                option_letter = candidate_option_label(index)
                return f"Option {option_letter} — {candidate.label}"
        return None

    @Slot()
    def _update_stage_review_action(self) -> None:
        if self._snapshot.status != "awaiting_review":
            return
        retryable = any(
            c.status in {"failed", "interrupted", "orphaned"} for c in self._snapshot.candidates
        )
        selected = self.selection_combo.currentData()
        if self._individual_checkpoint():
            candidate = next(
                (c for c in self._snapshot.candidates if c.candidate_id == selected), None
            )
            eligible = bool(
                candidate
                and candidate.status == "completed"
                and candidate.metrics
                and candidate.metrics.get("invalid_face_count") == 0
            )
            approved = self._snapshot.visual_reviews.get(selected) is True
            if self._sequence_progress and self._sequence_progress["fresh_review_required"]:
                approved = False
            info = self._sequence_info
            last = info["index"] + 1 == info["total"]
            self.selection_combo.show()
            self.selection_combo.setEnabled(self._worker is None)
            self.advance_button.setText(
                "Run combined confirmation" if last else "Fit next specimen →"
            )
            self.advance_button.show()
            self.advance_button.setEnabled(eligible and approved and self._worker is None)
            _set_action_emphasis(self.advance_button, self.advance_button.isEnabled())
            self.review_next_button.setText("Review this specimen")
            self.review_next_button.show()
            self.review_next_button.setEnabled(selected is not None)
            self.collect_evidence_button.hide()
            self.use_provisional_button.hide()
            self.afk_mode.setEnabled(False)
            self.outward_mode.setEnabled(False)
            self.adaptive_fit_search.setEnabled(False)
            self.find_fit_button.setEnabled(self._worker is None and not self._restoring_search)
            self.status.setText(
                f"Specimen {info['index'] + 1} of {info['total']}: {info['filename']}. "
                + (
                    "Approved. Run combined confirmation."
                    if last and approved
                    else "Approved. Fit the next specimen."
                    if approved
                    else "Review this attempt. Reject tries new parameters; "
                    "approve fits the next specimen."
                )
            )
            return
        eligible = selected in self._selectable_candidate_ids()
        stage = self._snapshot.current_stage
        provisional = iteration_limit_selection_available(self._snapshot, selected)
        final_provisional = False
        if stage.order == 4:
            from diffeoforge.reference_pilot_completion import provisional_available

            final_provisional = provisional_available(self._snapshot, selected)
        last = stage.order == len(self._snapshot.plan.stages)
        self.advance_button.setText(
            "Finish pilot provisionally → full atlas setup"
            if final_provisional
            else f"Use approved fit provisionally → stage {stage.order + 1}"
            if provisional
            else "Use approved option and finish pilot"
            if last
            else f"Use approved option → stage {stage.order + 1}"
        )
        self.advance_button.setToolTip(
            "Verifies the saved fit and returns to full atlas setup. No atlas starts now."
            if last
            else "Keeps this exact saved fit for parameter exploration. Convergence is not "
            "established; stage 4 still requires numerical qualification. No fit starts now."
            if provisional
            else "Records this selection and prepares the next stage."
        )
        approved = self._snapshot.visual_reviews.get(selected) is True
        self.selection_combo.show()
        self.advance_button.show()
        can_advance = (
            (eligible or provisional or final_provisional)
            and approved
            and self._worker is None
            and not self._restoring_search
        )
        self.advance_button.setEnabled(can_advance)
        _set_action_emphasis(self.advance_button, can_advance)
        self.review_next_button.setText("Review selected option")
        self.review_next_button.show()
        self.review_next_button.setEnabled(selected is not None)
        self.collect_evidence_button.setText("Improve fit automatically")
        self.collect_evidence_button.setVisible(
            not self._snapshot.plan.qc_recalibration_source
            and self._snapshot.current_stage.kind != "integration_accuracy"
        )
        stopped = self._snapshot.adaptive_search_status.get("stop_reason")
        self.collect_evidence_button.setEnabled(
            not retryable and self._worker is None and not stopped
        )
        self.collect_evidence_button.setToolTip(
            "Chooses the search center from all measured fits and runs up to 12 new comparisons."
        )
        self.status.setText(
            "Retry incomplete options first."
            if retryable
            else "Review an option, or let the pilot improve the fit automatically."
            if selected is None
            else "Approved. Use this option to continue."
            if approved and eligible
            else "Visually approved; iteration limit reached. Keep this fit provisionally "
            "to explore stage " + str(stage.order + 1) + ". Convergence is not established."
            if approved and provisional
            else "Iteration limit reached. Review all specimens before choosing this fit "
            "provisionally; convergence is not established."
            if provisional
            else "Review this option before continuing."
        )
        if final_provisional:
            self.advance_button.setToolTip(
                "Records the reviewed fit with its iteration-limit warning. No scientific "
                "qualification is claimed; no full-cohort atlas starts automatically."
            )
            self.status.setText(
                "Time resolution checked. Review this fit, then finish provisionally. "
                "Optimizer convergence remains unconfirmed."
                if not approved
                else "Approved; time resolution checked. Finish provisionally "
                "to prepare the full atlas. "
                "Optimizer convergence remains unconfirmed."
            )
        if (
            approved
            and not eligible
            and not provisional
            and not final_provisional
            and not retryable
        ):
            row = (
                next((r for r in self._assessment.candidates if r.candidate_id == selected), None)
                if self._assessment
                else None
            )
            self.status.setText(
                "Visually approved. " + "; ".join(row.rejection_reasons)
                if row
                else "Visually approved; run the saved-model qualification."
            )
        if stopped and not (approved and provisional):
            messages = {
                "budget_reached": "Automatic search budget reached.",
                "fit_plateau": "Automatic search stopped: fit no longer improved enough.",
                "specimen_tradeoff": "Search stopped: improving one fit worsened another.",
                "no_new_trial_within_bounds": "Search stopped at the declared parameter limits.",
                "no_valid_fit_evidence": "Search needs complete, valid fit measurements.",
            }
            self.status.setText(
                messages.get(stopped, "Automatic search stopped.")
                + " Choose an option for visual review; this is not a fit approval."
            )
        if self._worker is not None:
            self.advance_button.setEnabled(False)
            self.review_next_button.setEnabled(False)
            self.selection_combo.setEnabled(False)
        else:
            self.selection_combo.setEnabled(True)

    @Slot()
    def _open_next_review(self) -> None:
        completed = tuple(
            candidate for candidate in self._snapshot.candidates if candidate.status == "completed"
        )
        if self.selection_combo.currentData() is not None:
            selected = self.selection_combo.currentData()
            chosen = next((item for item in completed if item.candidate_id == selected), None)
            if chosen is not None:
                self._open_candidate(chosen)
                return
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

    @Slot(bool)
    def _afk_toggled(self, checked: bool) -> None:
        if checked:
            self.advanced_mode.setChecked(False)
        self.outward_mode.setEnabled(checked)

    @Slot()
    def _start(self) -> None:
        if self._worker is not None:
            return
        stage = self._snapshot.current_stage
        state = self._snapshot.early_screening
        if (
            stage
            and stage.order in (2, 3)
            and not self._individual_checkpoint()
            and not self._snapshot.plan.qc_recalibration_source
        ):
            if state and not state["complete"]:
                if state["current_status"] == "completed":
                    self._review_early_screen()
                else:
                    self._start_pilot(adaptive=False, early_screen=True)
                return
            if (
                not state
                and self.screen_enabled.isChecked()
                and any(c.status != "completed" for c in self._snapshot.candidates)
            ):
                subjects = [self.screen_subject.currentData()]
                second = self.screen_second_subject.currentData()
                if second:
                    subjects.append(second)
                if len(set(subjects)) != len(subjects):
                    self.status.setText("Choose a different second screening specimen.")
                    return
                self._start_pilot(
                    adaptive=False, early_screen=True, screen_subjects=tuple(subjects)
                )
                return
            if state and state["complete"]:
                self._start_pilot(adaptive=False)
                return
        if (
            not self._snapshot.selected_candidate_ids
            and not self.advanced_mode.isChecked()
            and not self.adaptive_fit_search.isChecked()
            and not self._snapshot.plan.qc_recalibration_source
        ):
            if self._sequence_info:
                self._start_pilot(adaptive=False, specimen_fit=True)
            else:
                self._find_fit()
            return
        try:
            self._start_pilot()
        except Exception as error:
            # Qt reports uncaught slot exceptions only to stderr, which the
            # windowed executable hides. Keep startup failures visible and
            # retryable without bypassing consent or starting a second worker.
            self._worker = None
            self.advanced_mode.setEnabled(True)
            self.afk_mode.setEnabled(True)
            self.outward_mode.setEnabled(self.afk_mode.isChecked())
            self.start_button.setEnabled(True)
            _set_action_emphasis(self.start_button, True)
            self.cancel_button.setEnabled(False)
            self.cancel_button.hide()
            message = f"Pilot start failed: {type(error).__name__}: {error}"
            self.status.setText(message)
            QMessageBox.critical(self, "Pilot could not start", message)

    def _start_selected_continuation(self, candidate: CalibrationStudyCandidateState) -> None:
        if self._worker is not None or self._restoring_search:
            return
        if self._snapshot.current_stage and self._snapshot.current_stage.order == 4:
            self._start_pilot(
                adaptive=False,
                qualification=True,
                qualification_source=candidate.candidate_id,
                qualification_iterations=self.continuation_iterations.value(),
                strict_optimizer=True,
            )
            return
        if self._individual_checkpoint():
            self._start_pilot(
                adaptive=False,
                specimen_action=(
                    "retry",
                    candidate.candidate_id,
                    self.continuation_iterations.value(),
                ),
            )
            return
        self._start_pilot(
            adaptive=False,
            continuation=(candidate.candidate_id, self.continuation_iterations.value()),
        )

    def _start_pilot(self, **kwargs) -> None:
        try:
            self._dispatch_pilot(**kwargs)
        except Exception as error:
            self._worker = None
            self._render()
            self.start_button.setEnabled(True)
            self.cancel_button.setEnabled(False)
            self.cancel_button.hide()
            message = f"Pilot start failed: {type(error).__name__}: {error}"
            self.status.setText(message)
            QMessageBox.critical(self, "Pilot could not start", message)

    def _dispatch_pilot(
        self,
        *,
        adaptive: bool | None = None,
        continuation: tuple[str, int] | None = None,
        specimen_fit: bool = False,
        specimen_action: tuple[str, str, int] | None = None,
        retain_previous: bool = False,
        provisional_candidate_id: str | None = None,
        finish_candidate_id: str | None = None,
        early_screen: bool = False,
        screen_subjects: tuple[str, ...] | None = None,
        retry_screens: bool = False,
        finer_resolution: bool = False,
        qualification: bool = False,
        qualification_source: str | None = None,
        qualification_iterations: int = 100,
        strict_optimizer: bool = False,
        finer_model: bool = False,
    ) -> None:
        if self._restoring_search:
            raise ValueError("Wait until the saved search has finished loading")
        runner = ReferenceCalibrationStudyRunner(self.study_directory)
        qualification = qualification or bool(
            self._snapshot.current_stage
            and self._snapshot.current_stage.order == 4
            and not finer_resolution
            and not continuation
        )
        worker = _CalibrationStageWorker(
            runner,
            continuation=continuation,
            specimen_fit=specimen_fit,
            specimen_action=specimen_action,
            retain_previous=retain_previous,
            provisional_candidate_id=provisional_candidate_id,
            finish_candidate_id=finish_candidate_id,
            early_screen=early_screen,
            screen_subjects=screen_subjects,
            retry_screens=retry_screens,
            finer_resolution=finer_resolution,
            qualification=qualification,
            qualification_source=qualification_source
            or (self.selection_combo.currentData() if qualification else None),
            qualification_iterations=qualification_iterations,
            strict_optimizer=strict_optimizer,
            finer_model=finer_model,
            integration_tolerances=(
                {k: f.value() / 100 for k, f in self.integration_fields.items()}
                if self._snapshot.current_stage
                and self._snapshot.current_stage.order == 4
                and not self._snapshot.integration_tolerances
                and not any(c.attempts for c in self._snapshot.candidates)
                else None
            ),
            complete_automatic_pilot=False,
            adaptive_fit_search=(
                False
                if self._snapshot.current_stage and self._snapshot.current_stage.order == 4
                else self.adaptive_fit_search.isChecked()
                if adaptive is None
                else adaptive
            ),
            visual_approvals={
                key: value
                for key, value in self._visual_approvals().items()
                if key in {c.candidate_id for c in self._snapshot.candidates}
            },
        )
        worker.signals.event.connect(self._event)
        worker.signals.succeeded.connect(self._succeeded)
        worker.signals.failed.connect(self._failed)
        worker.signals.finished.connect(self._worker_finished)
        self._worker = worker
        self._fit_search_stop_text = None
        self.advanced_mode.setEnabled(False)
        self.afk_mode.setEnabled(False)
        self.adaptive_fit_search.setEnabled(False)
        self.find_fit_button.setEnabled(False)
        self.collect_evidence_button.setEnabled(False)
        self.review_next_button.setEnabled(False)
        self.advance_button.setEnabled(False)
        self.keep_previous_button.setEnabled(False)
        self.finer_resolution_button.setEnabled(False)
        self.qualification_button.setEnabled(False)
        self.finer_model_button.setEnabled(False)
        self.selection_combo.setEnabled(False)
        self.start_button.setEnabled(False)
        _set_action_emphasis(self.start_button, False)
        self.cancel_button.setEnabled(finish_candidate_id is None)
        self.cancel_button.setVisible(finish_candidate_id is None)
        self.cancel_button.setObjectName("danger")
        self.cancel_button.style().unpolish(self.cancel_button)
        self.cancel_button.style().polish(self.cancel_button)
        self.status.setText(
            "Verifying saved pilot and preparing full atlas setup… No atlas starts now."
            if finish_candidate_id
            else "Recording provisional selection and preserving the saved fit… No fit is running."
            if provisional_candidate_id
            else "Preparing the next attempt…"
        )
        self._thread_pool.start(worker)
        if finish_candidate_id:
            self._thread_pool.indicator.label.setText(self.status.text())

    @Slot()
    def _keep_previous_fit(self) -> None:
        if self._worker is not None or self._restoring_search:
            return
        self._start_pilot(adaptive=False, retain_previous=True)

    @Slot(object)
    def _event(self, event: Mapping[str, object]) -> None:
        if event["event"] == "qualification_progress":
            if event["phase"] == "integration_cached":
                self.status.setText(
                    "Verified time-resolution check reused. No computation was started."
                )
            elif event["phase"] == "optimizer_check":
                self.status.setText(
                    f"Checking optimizer stability: up to {event['iterations']} "
                    "tighter-tolerance iterations. Saved model retained."
                )
            else:
                self.status.setText(
                    f"Fixed-model Shooting: {event['timepoints']} timepoints · "
                    f"{event['completed_subjects']} / {event['total_subjects']} "
                    "specimens written · "
                    f"{event['elapsed_seconds'] / 60:.1f} min. Fixed learned state."
                )
            self._thread_pool.indicator.label.setText(self.status.text())
            return
        if event["event"] == "integration_resolution_prepared":
            self._render(event["snapshot"])
            count = self._snapshot.current_stage.candidates[-1].values["timepoints"]
            self.status.setText(
                f"Testing {int(count)} time points with all "
                f"{self._snapshot.plan.pilot_subject_count} pilot specimens."
            )
            return
        if event["event"] == "screen_progress":
            state = self._snapshot.early_screening
            label = self._candidate_state_labels.get(state.get("next_candidate"))
            if label is not None:
                label.setText("Early specimen screening is running — see live progress above.")
            probe = event.get("probe_event", {})
            if probe.get("event") == "candidate_worker_event":
                worker = probe["worker_event"]
                payload = worker["payload"]
                if worker["kind"] == "progress":
                    self._progress_context.update(
                        iteration=payload["iteration"], cap=payload["maximum_iterations"]
                    )
                suffix = (
                    f" · iteration {self._progress_context['iteration']} "
                    f"/ {self._progress_context['cap']}"
                    if self._progress_context.get("iteration") is not None
                    else ""
                )
                if worker["kind"] == "activity":
                    suffix += f" · {payload['elapsed_seconds'] / 60:.1f} min"
            else:
                suffix = ""
                self._progress_context = {}
            self.status.setText(
                f"Early screen · {state.get('next_subject', 'one specimen')}"
                f" · {state.get('next_candidate', '')}{suffix}. Review follows."
            )
            self._thread_pool.indicator.label.setText(self.status.text())
            return
        if event["event"] == "specimen_sequence_preparing":
            self.status.setText(str(event["message"]))
            return
        kind = str(event["event"])
        candidate_id = str(event.get("candidate_id", ""))
        if kind == "specimen_sequence_changed":
            self.study_directory = event["snapshot"].study_directory
            self._visually_reviewed_candidates.clear()
            self._visually_approved_candidates.clear()
            self._render(event["snapshot"])
        elif kind == "specimen_sequence_paused":
            info = event["sequence"]
            finished = all(c.status == "completed" for c in event["snapshot"].candidates)
            phase_label = {
                "capture": "broad shape capture",
                "refine": "surface refinement",
                "continue": "saved fit continuation",
            }.get(info.get("fit_phase"), "initial probe")
            self._fit_search_stop_text = (
                "Stopped before this step finished. Saved results remain available."
                if not finished
                else (
                    f"Specimen {info['index'] + 1} of {info['total']} ready "
                    f"({phase_label}). "
                    "Review this attempt. Reject tries new parameters; approve continues."
                    if info["phase"] == "individual"
                    else "Combined fit finished. Review all specimens before the next stage."
                )
            )
            self.status.setText(self._fit_search_stop_text)
        elif kind in {"fit_search_started", "fit_search_extended"}:
            snapshot = event["snapshot"]
            self.study_directory = snapshot.study_directory
            self._render(snapshot)
            self.status.setText(
                "Fitting full target detail — review follows."
                if event.get("confirmation")
                else "Fit search — completed options can already be reviewed."
            )
        elif kind == "fit_search_stopped":
            self._fit_search_stop_text = (
                "Fit search stopped. Saved results remain available for review."
                if event["reason"] == "cancelled"
                else (
                    "Fit search finished. Inspect the full-target option before continuing."
                    if event.get("full_target_completed")
                    else "No full-target confirmation completed. Review saved screening results."
                )
            )
            self.status.setText(self._fit_search_stop_text)
        elif kind == "selected_continuation_started":
            snapshot = event["snapshot"]
            self.study_directory = snapshot.study_directory
            self._render(snapshot)
            self.status.setText(
                "Continuing only the selected option. Previous results are preserved."
            )
        elif kind == "adaptive_search_extended":
            self.study_directory = Path(str(event["study_directory"])).resolve()
            self._render(event.get("snapshot"))
            self.status.setText(
                f"Automatic fit search, round {event['round_index']}: "
                f"{event['new_runs']} new comparisons. Existing fits are preserved."
            )
        elif kind == "adaptive_search_decision":
            self.status.setText(str(event["rationale"]))
        elif kind == "candidate_started":
            self._progress_context = dict(
                candidate=candidate_id, phase="Preparing reference fit", iteration=None, cap=None
            )
            self.status.setText(f"{self._progress_label(candidate_id)}: preparing reference fit.")
            label = self._candidate_state_labels.get(candidate_id)
            if label is not None:
                label.setText("Running — see live progress above.")
        elif kind == "candidate_worker_event":
            worker = event["worker_event"]
            payload = worker["payload"]
            if worker["kind"] == "progress":
                self._progress_context.update(
                    candidate=candidate_id,
                    phase="Optimizing",
                    iteration=payload["iteration"],
                    cap=payload["maximum_iterations"],
                )
                self.status.setText(
                    f"{self._progress_label(candidate_id)}: Deformetrica iteration "
                    f"{payload['iteration']} of {payload['maximum_iterations']}."
                )
            elif worker["kind"] == "phase":
                self._progress_context.update(
                    candidate=candidate_id, phase=payload["message"], iteration=None
                )
                self.status.setText(f"{self._progress_label(candidate_id)}: {payload['message']}")
            elif worker["kind"] == "activity":
                self.status.setText(
                    f"{self._progress_label(candidate_id)}: "
                    f"{self._progress_context.get('phase', 'Engine active')}"
                    + (
                        f" · iteration {self._progress_context['iteration']} "
                        f"/ {self._progress_context['cap']}"
                        if self._progress_context.get("iteration") is not None
                        else ""
                    )
                    + f" · {float(payload['elapsed_seconds']) / 60:.1f} min."
                )
            self._thread_pool.indicator.label.setText(self.status.text())
        elif kind == "candidate_completed":
            self._render(event.get("snapshot"))
            candidate = next(c for c in self._snapshot.candidates if c.candidate_id == candidate_id)
            root = self.study_directory

            def prefetch():
                from diffeoforge.desktop.pilot_preview import load_pilot_preview

                for pair in collect_calibration_qc_pairs(root, candidate):
                    if pair.required:
                        for path in (pair.original_path, pair.reconstruction_path):
                            load_pilot_preview(path, cache_directory=root / "display-cache")

            self._preview_prefetch.request_operation(candidate_id, prefetch)
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
        finishing = getattr(self._worker, "finish_candidate_id", None) is not None
        self._worker = None
        self.study_directory = snapshot.study_directory
        if finishing and snapshot.status == "completed":
            self._snapshot = snapshot
            # Parent's existing finished handler applies parameters, never runs an atlas.
            self.accept()
            return
        self._render()
        if snapshot.current_stage and snapshot.current_stage.order == 4:
            latest = next(
                (
                    c
                    for c in reversed(snapshot.candidates)
                    if c.candidate_id.startswith("qualification-") and c.status == "completed"
                ),
                None,
            )
            if latest:
                self.selection_combo.setCurrentIndex(
                    self.selection_combo.findData(latest.candidate_id)
                )
        self._notify_review_ready()
        if self._fit_search_stop_text:
            self.status.setText(self._fit_search_stop_text)
        pending = getattr(self, "_pending_specimen_review", None)
        self._pending_specimen_review = None
        if pending:
            self._continue_specimen_review(*pending)

    def _continue_specimen_review(self, root, candidate_id, approved) -> None:
        """Dispatch only a persisted decision for the currently displayed checkpoint."""
        if (
            Path(root).resolve() != self.study_directory.resolve()
            or not self._individual_checkpoint()
        ):
            return
        if self._worker is not None:
            self._pending_specimen_review = (root, candidate_id, approved)
            return
        self._start_pilot(
            adaptive=False,
            specimen_action=("advance" if approved else "reject", candidate_id, 0),
        )

    @Slot(str)
    def _failed(self, message: str) -> None:
        self._worker = None
        self._render()
        self.status.setText(f"Calibration stage could not continue: {message}")
        self._notify_review_ready(failure=message)

    def _progress_label(self, candidate_id):
        index = next(
            (
                i
                for i, c in enumerate(self._snapshot.candidates, 1)
                if c.candidate_id == candidate_id
            ),
            None,
        )
        stage = self._snapshot.current_stage
        return (
            f"Stage {stage.order} · Option {candidate_option_label(index)}"
            if stage and index
            else candidate_id
        )

    def _notify_review_ready(self, *, failure=None):
        early = self._snapshot.early_screening
        early_ready = early.get("current_status") == "completed" and not early.get("complete")
        if not failure and self._snapshot.status != "awaiting_review" and not early_ready:
            return
        key = (
            str(self.study_directory),
            self._snapshot.current_stage.stage_id if self._snapshot.current_stage else "complete",
            failure
            or (early.get("current_child") if early_ready else None)
            or tuple(
                (c.candidate_id, c.attempts)
                for c in self._snapshot.candidates
                if c.status == "completed"
            ),
        )
        if key in self._notification_keys:
            return
        self._notification_keys.add(key)
        message = (
            "Pilot needs attention. Saved fits remain available."
            if failure
            else f"Stage {self._snapshot.current_stage.order}: "
            + ("early specimen review ready. " if early_ready else "result ready. ")
            + "Open the pilot to review and continue."
        )
        QApplication.alert(self, 0)
        if QSystemTrayIcon.isSystemTrayAvailable():
            self._tray.show()
            self._tray.showMessage(
                "DiffeoForge", message, QSystemTrayIcon.MessageIcon.Information, 10000
            )

    @Slot()
    def _show_pilot_notification(self):
        self._tray.hide()
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _export_audit(self):
        from uuid import uuid4

        from diffeoforge.reference_pilot_qualification import export_audit

        root = self.study_directory
        destination = root / "audit" / ("pilot-audit-" + uuid4().hex + ".json")
        self.status.setText("Verifying and exporting the pilot history…")
        self._audit_loader.request_operation(str(root), lambda: export_audit(root, destination))

    @Slot(object)
    def _worker_finished(self, worker: _CalibrationStageWorker) -> None:
        # A prior completion may already have dispatched a new specimen worker.
        if self._worker is worker:
            self._worker = None
            self._pending_specimen_review = None
            self._render()
            self.status.setText(
                worker.error_message
                or "The background task ended. Saved fits are retained; retry or close."
            )

    def _release_finished_worker(self) -> None:
        if self._worker is not None and getattr(self._worker, "is_finished", False):
            self._worker_finished(self._worker)

    def _visual_approvals(self) -> dict[str, bool]:
        current_ids = {candidate.candidate_id for candidate in self._snapshot.candidates}
        return {
            candidate_id: candidate_id in self._visually_approved_candidates
            for candidate_id in self._visually_reviewed_candidates
            if candidate_id in current_ids
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
        if self._worker is not None:
            return
        if not self._snapshot.selected_candidate_ids and not self.advanced_mode.isChecked():
            self._find_fit()
            return
        self.adaptive_fit_search.setChecked(True)
        self._start()

    @Slot()
    def _find_fit(self) -> None:
        if self._worker is None and not self._restoring_search:
            if self._sequence_info:
                selected = self.selection_combo.currentData()
                if not selected and self._individual_checkpoint():
                    completed = [c for c in self._snapshot.candidates if c.status == "completed"]
                    if len(completed) != 1:
                        self.status.setText(
                            "Choose a completed fit before improving this specimen."
                        )
                        return
                    selected = completed[0].candidate_id
                self._start_pilot(
                    adaptive=False,
                    specimen_action=(
                        "improve" if self._individual_checkpoint() else "restart",
                        str(selected or ""),
                        0,
                    ),
                )
                return
            self._start_pilot(adaptive=False, specimen_fit=True)

    @Slot()
    def _test_denser_model(self) -> None:
        if self._worker is not None or self._restoring_search or not self._individual_checkpoint():
            return
        response = QMessageBox.question(
            self,
            "New common control basis",
            "Test more control points, starting with this specimen? All specimens need "
            "new approval on this model. Your earlier searches and approvals stay saved.",
        )
        if response == QMessageBox.StandardButton.Yes:
            self._start_pilot(adaptive=False, specimen_action=("denser", "", 0))

    @Slot()
    def _choose_saved_search(self) -> None:
        if self._worker is not None or self._restoring_search:
            return
        from diffeoforge.reference_sequential_fit import saved_sequences

        origin = self.study_directory
        self._restoring_search = True
        self._render(self._snapshot)
        self.status.setText("Loading saved searches…")
        self._saved_search_loader.request_operation(
            ("list", origin), lambda: saved_sequences(origin)
        )

    @Slot(object, str)
    def _saved_search_failed(self, _key: object, message: str) -> None:
        self._restoring_search = False
        self._render(self._snapshot)
        self.status.setText("Saved search unavailable: " + message)

    @Slot(object, object)
    def _saved_search_loaded(self, key: object, result: object) -> None:
        kind, origin = key
        if self._worker is not None or self.study_directory != origin:
            self._restoring_search = False
            return
        if kind == "list":
            rows = result
            if not rows:
                self._saved_search_failed(key, "No compatible saved specimen search found.")
                return
            from diffeoforge.reference_sequential_fit import saved_sequence_label

            labels = [saved_sequence_label(r) for r in rows]
            current_index = next((i for i, r in enumerate(rows) if r["is_current"]), 0)
            label, accepted = QInputDialog.getItem(
                self,
                "Saved fit searches",
                "Resume the current checkpoint of a search:",
                labels,
                current_index,
                False,
            )
            if not accepted:
                self._restoring_search = False
                self._render(self._snapshot)
                return
            from diffeoforge.reference_sequential_fit import restore_saved_sequence

            selected = Path(rows[labels.index(label)]["directory"])
            self.status.setText("Verifying saved fits and approvals…")
            self._saved_search_loader.request_operation(
                ("restore", origin), lambda: restore_saved_sequence(origin, selected)
            )
            return
        self._restoring_search = False
        self.study_directory = result.study_directory
        self._visually_reviewed_candidates.clear()
        self._visually_approved_candidates.clear()
        self._fit_search_stop_text = None
        self._render(result)

    def _individual_checkpoint(self) -> bool:
        return bool(
            getattr(self, "_sequence_info", None) and self._sequence_info["phase"] == "individual"
        )

    @Slot()
    def _cancel(self) -> None:
        self._release_finished_worker()
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
        if self._worker is not None or self._restoring_search:
            return
        if self._snapshot.status == "completed":
            self.accept()
            return
        selected = self.selection_combo.currentData()
        if selected is None:
            QMessageBox.warning(
                self,
                "Select a candidate",
                "Choose one automatically valid candidate before continuing.",
            )
            return
        approvals = self._visual_approvals()
        if self._individual_checkpoint():
            self._start_pilot(adaptive=False, specimen_action=("advance", str(selected), 0))
            return
        if self._snapshot.current_stage.order == 4:
            from diffeoforge.reference_pilot_completion import capped

            candidate = next(c for c in self._snapshot.candidates if c.candidate_id == selected)
            if capped(candidate):
                answer = QMessageBox.question(
                    self,
                    "Finish pilot provisionally?",
                    "This joint fit reached its iteration limit. Its time-resolution checks "
                    "pass and you approved its anatomy, but optimizer stability and stable "
                    "momenta are not established. Keep these warnings and prepare the "
                    "full-cohort atlas configuration? No atlas starts now.",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if answer != QMessageBox.StandardButton.Yes:
                    return
            self._start_pilot(adaptive=False, finish_candidate_id=str(selected))
            return
        if iteration_limit_selection_available(self._snapshot, selected):
            self._start_pilot(adaptive=False, provisional_candidate_id=str(selected))
            return
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
            else ("failed" if selected in self._visually_reviewed_candidates else "not performed")
        )
        self.status.setText(
            f"Selection recorded: {selected}. The next calibration stage is ready. "
            f"Visual QC: {visual_status}."
        )

    def _open_candidate(self, candidate: CalibrationStudyCandidateState) -> None:
        if candidate.status != "completed":
            self.status.setText("This option is still computing. Inspect a completed option.")
            return
        root, snapshot = self.study_directory, self._snapshot
        self.status.setText("Preparing comparison in background… The pilot can continue.")
        self._viewer_preparation.request_operation(
            (root, candidate),
            lambda: (
                collect_calibration_qc_pairs(root, candidate),
                normalized_candidate_subject_fit(snapshot, candidate),
            ),
        )

    def _review_early_screen(self) -> None:
        state = self._snapshot.early_screening
        if not state or not state["current_child"] or self._worker is not None:
            return
        origin = self.study_directory
        child = origin / state["current_child"]

        def prepare():
            snapshot = load_reference_calibration_study(child)
            candidate = snapshot.candidates[0]
            if candidate.status != "completed":
                raise ValueError("The current screen has not completed")
            return (
                snapshot,
                collect_calibration_qc_pairs(child, candidate),
                normalized_candidate_subject_fit(snapshot, candidate),
            )

        self.status.setText("Loading this specimen's screening fit…")
        self._viewer_preparation.request_operation(("early-screen", origin, child), prepare)

    @Slot(object, str)
    def _candidate_prepare_failed(self, _key: object, message: str) -> None:
        self.status.setText("Comparison unavailable: " + message)

    @Slot(object, object)
    def _candidate_prepared(self, key: object, prepared: object) -> None:
        if key[0] == "compare-plan-b":
            root, candidate, pairs = prepared
            dialog = CalibrationCandidateViewerDialog(
                root, candidate, self, pairs=pairs, read_only=True
            )
            dialog.setWindowTitle("Plan B comparison — current fit (blue) / Plan B (orange)")
            dialog.exec()
            return
        screen_parent = None
        if key[0] == "early-screen":
            screen_parent = key[1]
            if screen_parent != self.study_directory or self._worker is not None:
                return
            reviewed_snapshot, pairs, fit = prepared
            root, candidate = reviewed_snapshot.study_directory, reviewed_snapshot.candidates[0]
        else:
            root, candidate = key
            pairs, fit = prepared
        try:
            reviewed_snapshot = load_reference_calibration_study(root)
            dialog = CalibrationCandidateViewerDialog(
                root,
                candidate,
                self,
                subject_fit=fit,
                pairs=pairs,
                allow_plan_b=self._individual_checkpoint()
                and Path(root).resolve() == self.study_directory.resolve(),
            )
            dialog.anatomical_notes.setText(
                reviewed_snapshot.visual_review_notes.get(candidate.candidate_id, "")
            )
            dialog.feature_observations = {
                name: dict(values)
                for name, values in reviewed_snapshot.feature_observations.get(
                    candidate.candidate_id, {}
                ).items()
            }
            # Re-review is a new human decision. Previous decisions remain in the
            # journal but must not silently pre-pass specimens or lock bulk approval.
            dialog.subject_decisions = {}
            dialog._reviewed_pair_ids.update(
                p.pair_id for p in dialog._pairs if p.original_path.name in dialog.subject_decisions
            )
            dialog.display_scopes.update(
                reviewed_snapshot.visual_display_scopes.get(candidate.candidate_id, {})
            )
            from diffeoforge.reference_sequential_fit import sequence_info

            checkpoint = sequence_info(root)
            if screen_parent:
                dialog.setWindowTitle("Early specimen review — joint fit not yet calculated")
                dialog.fail_button.setText("Discard option → next screen")
                dialog.complete_button.setText("Keep option → next screen")
                dialog.complete_button.setToolTip(
                    "Keeps this option for joint testing. This is not joint-fit approval."
                )
            elif checkpoint and checkpoint["phase"] == "individual":
                dialog.fail_button.setText("Reject → next parameters")
                dialog.fail_button.setToolTip(
                    "Keeps this result and starts a new attempt for the same specimen."
                )
                dialog.complete_button.setText(
                    "Approve → combined confirmation"
                    if checkpoint["index"] + 1 == checkpoint["total"]
                    else "Approve → next specimen"
                )
            index = dialog.mesh_combo.currentData()
            if index is not None:
                dialog._show_feature_check(dialog._pairs[int(index)])
            dialog._update_review_progress()
            dialog.exec()
            if dialog.keep_as_plan_b:
                if Path(root).resolve() == self.study_directory.resolve() and self._worker is None:
                    self._start_pilot(
                        adaptive=False, specimen_action=("maybe", candidate.candidate_id, 0)
                    )
                return
            if dialog.review_recorded:
                record_reference_calibration_candidate_review(
                    root,
                    candidate_id=candidate.candidate_id,
                    approved=dialog.review_passed,
                    reviewed_subjects=tuple(
                        p.original_path.name
                        for p in dialog._pairs
                        if p.required and p.pair_id in dialog._reviewed_pair_ids
                    ),
                    anatomical_notes=dialog.anatomical_notes.text(),
                    feature_observations=dialog.feature_observations,
                    subject_decisions=dialog.subject_decisions,
                    display_scopes={
                        p.original_path.name: dialog.display_scopes[p.original_path.name]
                        for p in dialog._pairs
                        if p.required and p.pair_id in dialog._reviewed_pair_ids
                    },
                )
                if screen_parent:
                    from diffeoforge.reference_stage_screening import record_screen_review

                    record_screen_review(screen_parent, root)
                    self._render()
                    if not self._snapshot.early_screening["complete"]:
                        self._start_pilot(adaptive=False, early_screen=True)
                    return
                if Path(root).resolve() != self.study_directory.resolve():
                    return
                self._visually_reviewed_candidates.add(candidate.candidate_id)
                if dialog.review_passed:
                    self._visually_approved_candidates.add(candidate.candidate_id)
                else:
                    self._visually_approved_candidates.discard(candidate.candidate_id)
                self._render()
                self._continue_specimen_review(root, candidate.candidate_id, dialog.review_passed)
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            self.status.setText("Comparison unavailable: " + str(error))
            QMessageBox.warning(self, "Candidate viewer unavailable", str(error))

    def closeEvent(self, event: QCloseEvent) -> None:
        self._release_finished_worker()
        if self._worker is None:
            super().closeEvent(event)
            return
        QMessageBox.information(
            self,
            "Pilot completion in progress"
            if getattr(self._worker, "finish_candidate_id", None) is not None
            else "Calibration still running",
            "Wait until saved evidence is verified. The atlas setup will open automatically."
            if getattr(self._worker, "finish_candidate_id", None) is not None
            else "Cancel safely first and wait until the current candidate reaches a "
            "terminal state before closing this window.",
        )
        event.ignore()

    def reject(self) -> None:
        """Escape must not hide/destroy a running pilot or lose its controller."""
        self._release_finished_worker()
        if self._worker is None:
            super().reject()

    def _restore_plan_b(self) -> None:
        if self._worker is None and not self._restoring_search:
            self._start_pilot(adaptive=False, specimen_action=("restore", "", 0))

    def _compare_plan_b(self) -> None:
        if self._worker is not None or self._restoring_search:
            return
        root, current_snapshot = self.study_directory, self._snapshot

        def prepare():
            from diffeoforge.mesh import sha256_file
            from diffeoforge.reference_sequential_fit import (
                _fallback_snapshot,
                _read,
                sequence_info,
            )

            info = sequence_info(root)
            series = Path(info["root"])
            state = _read(series)
            record = state.get("fallbacks", {}).get(str(len(state["approved"])))
            if record is None:
                raise ValueError("No Plan B is saved for this specimen")
            fallback = _fallback_snapshot(series, state, record)
            saved = next(c for c in fallback.candidates if c.candidate_id == record["candidate_id"])
            current = next(c for c in current_snapshot.candidates if c.status == "completed")
            current_pair = next(
                p for p in collect_calibration_qc_pairs(root, current) if p.required
            )
            saved_pair = next(
                p
                for p in collect_calibration_qc_pairs(fallback.study_directory, saved)
                if p.required
            )
            compare = CalibrationQcPair(
                pair_id="compare-plan-b",
                label="Current fit / Plan B",
                original_path=current_pair.reconstruction_path,
                reconstruction_path=saved_pair.reconstruction_path,
                required=False,
                original_sha256=sha256_file(current_pair.reconstruction_path),
                reconstruction_sha256=sha256_file(saved_pair.reconstruction_path),
            )
            return fallback.study_directory, saved, (compare,)

        self.status.setText("Preparing Plan B comparison…")
        self._viewer_preparation.request_operation(("compare-plan-b", root), prepare)
