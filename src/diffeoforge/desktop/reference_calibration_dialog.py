"""Desktop review and execution dialog for staged Deformetrica calibration."""

from __future__ import annotations

import threading
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath

from PySide6.QtCore import QObject, QRunnable, Qt, QUrl, Signal, Slot
from PySide6.QtGui import QCloseEvent, QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
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
    load_reference_calibration_report,
    load_reference_calibration_study,
    normalized_candidate_subject_fit,
    record_reference_calibration_candidate_review,
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
        bounded_fit_minutes: int | None = None,
    ) -> None:
        super().__init__()
        self.runner = runner
        self.continuation = continuation
        self.bounded_fit_minutes = bounded_fit_minutes
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

    def request_cancel(self) -> bool:
        with self._lock:
            if self._finished:
                return False
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
            if self.bounded_fit_minutes is not None:
                from diffeoforge.reference_fit_search import run_fit_search

                result = run_fit_search(
                    self.runner, minutes=self.bounded_fit_minutes, event_callback=emit
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
                result = self.runner.run_current_stage(event_callback=emit)
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
                result = self.runner.run_current_stage(event_callback=emit)
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
        *,
        subject_fit: Mapping[str, float] | None = None,
        pairs: tuple[CalibrationQcPair, ...] | None = None,
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
        self.fail_button.setVisible(True)
        self.fail_button.setEnabled(current_seen)
        self.complete_button.setEnabled(all_pass and not conflicts and self.canvas.comparison_ready)
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
    ) -> None:
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.WindowMinMaxButtonsHint
            | Qt.WindowType.WindowCloseButtonHint
        )
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.study_directory = study_directory.resolve()
        self._snapshot = load_reference_calibration_study(self.study_directory)
        self._viewer_preparation = PreviewMeshLoader(self)
        self._viewer_preparation.loaded.connect(self._candidate_prepared)
        self._viewer_preparation.failed.connect(self._candidate_prepare_failed)
        self._preview_prefetch = PreviewMeshLoader(self)
        self._worker: _CalibrationStageWorker | None = None
        self._fit_search_stop_text: str | None = None
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
        self.fit_minutes = QSpinBox()
        self.fit_minutes.setRange(15, 240)
        self.fit_minutes.setValue(60)
        self.fit_minutes.setSuffix(" min total")
        self.find_fit_button = QPushButton("Find fit")
        self.find_fit_button.setObjectName("primary")
        self.find_fit_button.setToolTip(
            "Four short fits, finer surface matching, then full-target confirmation. "
            "Scientific working targets; original template and all pilot specimens retained. "
            "The budget stops the engine; final file verification may take longer. "
            "Saved results still need your visual QC. Previous pilots are preserved."
        )
        self.find_fit_button.clicked.connect(self._find_fit)
        fit_row.addWidget(self.find_fit_button)
        fit_row.addWidget(self.fit_minutes)
        fit_row.addStretch()
        root.addLayout(fit_row)
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
            "Run all options in this stage, then review the fit. Every pilot "
            "specimen must pass before the next stage. If none passes, "
            "refine the fit around an inspected option."
        )
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
        self._continuation_buttons = {}

    def _update_continuation_labels(self) -> None:
        for letter, button in self._continuation_buttons.items():
            button.setText(f"Continue {letter}: +{self.continuation_iterations.value()} iterations")

    def _render(self, snapshot: ReferenceCalibrationStudySnapshot | None = None) -> None:
        self._snapshot = snapshot or load_reference_calibration_study(self.study_directory)
        for candidate_id, approved in self._snapshot.visual_reviews.items():
            self._visually_reviewed_candidates.add(candidate_id)
            if approved:
                self._visually_approved_candidates.add(candidate_id)
            else:
                self._visually_approved_candidates.discard(candidate_id)
        self._clear_content()
        running = self._worker is not None
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
            recommendation_title = QLabel("Recommended parameter set")
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
                    "This bounded QC follow-up varied attachment width, deformation/control "
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
            self.advance_button.hide()
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
            f"Stage {stage.order} of {len(self._snapshot.plan.stages)} — {stage.title}"
        )
        heading.setObjectName("sectionTitle")
        self.content_layout.addWidget(heading)
        guidance = stage_guidance(stage)
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
                self._snapshot, visual_approvals=self._visual_approvals()
            )
            recommended_option = self._recommended_option_text(assessment)
            summary = QLabel(
                f"Review first: {recommended_option}. "
                + (
                    "Smallest worst-specimen distance; anatomy still needs approval."
                    if self._snapshot.current_stage.kind != "integration_accuracy"
                    else "Numerical integration comparison; anatomy still needs approval."
                )
                if recommended_option
                else "No option currently passes the evidence checks."
            )
            summary.setWordWrap(True)
            summary.setObjectName("statusWarning")
            self.content_layout.addWidget(summary)
            details = QLabel("\n".join(assessment.cautions))
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
        self.fit_minutes.setEnabled(not running)
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
                "Choose an option for visual review…",
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
                        " · lowest measured distance"
                        if candidate.candidate_id == assessment.balanced_candidate_id
                        else ""
                    )
                    self.selection_combo.addItem(
                        f"Option {option_letter} — {candidate.label}"
                        f"{recommendation_suffix}{review_suffix}",
                        candidate.candidate_id,
                    )
            previous_index = self.selection_combo.findData(previous_selection)
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
            fit = normalized_candidate_subject_fit(self._snapshot, candidate)
            if fit:
                fit_label = QLabel("Fit unconfirmed — inspect the overlays.")
                fit_label.setWordWrap(True)
                layout.addWidget(fit_label)
                detail = QLabel(
                    "Distance p95 / original bounding-box diagonal; lower is closer. "
                    "This is a sampled nearest-vertex proxy, not an anatomical pass.\n\n"
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
            layout.addWidget(check)
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
        else:
            detail = QLabel(
                "Ready to run." if candidate.status == "pending" else "Ready for a new attempt."
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
        eligible = selected in self._selectable_candidate_ids()
        approved = self._snapshot.visual_reviews.get(selected) is True
        self.selection_combo.show()
        self.advance_button.show()
        self.advance_button.setEnabled(eligible and approved and not retryable)
        _set_action_emphasis(self.advance_button, eligible and approved and not retryable)
        self.review_next_button.setText("Review selected option")
        self.review_next_button.show()
        self.review_next_button.setEnabled(selected is not None and not retryable)
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
            else "Every specimen passed. You can prepare the next stage."
            if approved and eligible
            else "Review every specimen. After approval, use Prepare next stage."
        )
        if stopped:
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
        if (
            not self._snapshot.selected_candidate_ids
            and not self.advanced_mode.isChecked()
            and not self.adaptive_fit_search.isChecked()
            and not self._snapshot.plan.qc_recalibration_source
        ):
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
        if self._worker is not None:
            return
        self._start_pilot(
            adaptive=False,
            continuation=(candidate.candidate_id, self.continuation_iterations.value()),
        )

    def _start_pilot(
        self,
        *,
        adaptive: bool | None = None,
        continuation: tuple[str, int] | None = None,
        bounded_fit_minutes: int | None = None,
    ) -> None:
        runner = ReferenceCalibrationStudyRunner(self.study_directory)
        worker = _CalibrationStageWorker(
            runner,
            continuation=continuation,
            bounded_fit_minutes=bounded_fit_minutes,
            complete_automatic_pilot=False,
            adaptive_fit_search=(
                self.adaptive_fit_search.isChecked() if adaptive is None else adaptive
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
        self._worker = worker
        self._fit_search_stop_text = None
        self.advanced_mode.setEnabled(False)
        self.afk_mode.setEnabled(False)
        self.adaptive_fit_search.setEnabled(False)
        self.find_fit_button.setEnabled(False)
        self.fit_minutes.setEnabled(False)
        self.collect_evidence_button.setEnabled(False)
        self.review_next_button.setEnabled(False)
        self.advance_button.setEnabled(False)
        self.selection_combo.setEnabled(False)
        self.start_button.setEnabled(False)
        _set_action_emphasis(self.start_button, False)
        self.cancel_button.setEnabled(True)
        self.cancel_button.setVisible(True)
        self.cancel_button.setObjectName("danger")
        self.cancel_button.style().unpolish(self.cancel_button)
        self.cancel_button.style().polish(self.cancel_button)
        self.status.setText(
            "Running the current stage. Visual review follows before the next stage."
        )
        self._thread_pool.start(worker)

    @Slot(object)
    def _event(self, event: Mapping[str, object]) -> None:
        kind = str(event["event"])
        candidate_id = str(event.get("candidate_id", ""))
        if kind in {"fit_search_started", "fit_search_extended"}:
            snapshot = event["snapshot"]
            self.study_directory = snapshot.study_directory
            self._render(snapshot)
            self.status.setText(
                "Fitting full target detail — review follows."
                if event.get("confirmation")
                else "Bounded fit search — completed options can already be reviewed."
            )
        elif kind == "fit_search_stopped":
            self._fit_search_stop_text = (
                "Time budget reached. Saved results remain available for review."
                if event["reason"] == "time_budget"
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
        self._worker = None
        self.study_directory = snapshot.study_directory
        self._render()
        if self._fit_search_stop_text:
            self.status.setText(self._fit_search_stop_text)

    @Slot(str)
    def _failed(self, message: str) -> None:
        self._worker = None
        self._render()
        self.status.setText(f"Calibration stage could not continue: {message}")

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
        if self._worker is None:
            self._start_pilot(adaptive=False, bounded_fit_minutes=self.fit_minutes.value())

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

    @Slot(object, str)
    def _candidate_prepare_failed(self, _key: object, message: str) -> None:
        self.status.setText("Comparison unavailable: " + message)

    @Slot(object, object)
    def _candidate_prepared(self, key: object, prepared: object) -> None:
        root, candidate = key
        pairs, fit = prepared
        try:
            dialog = CalibrationCandidateViewerDialog(
                root,
                candidate,
                self,
                subject_fit=fit,
                pairs=pairs,
            )
            dialog.anatomical_notes.setText(
                self._snapshot.visual_review_notes.get(candidate.candidate_id, "")
            )
            dialog.feature_observations = {
                name: dict(values)
                for name, values in self._snapshot.feature_observations.get(
                    candidate.candidate_id, {}
                ).items()
            }
            dialog.subject_decisions = dict(
                self._snapshot.subject_decisions.get(candidate.candidate_id, {})
            )
            dialog._reviewed_pair_ids.update(
                p.pair_id for p in dialog._pairs if p.original_path.name in dialog.subject_decisions
            )
            dialog.display_scopes.update(
                self._snapshot.visual_display_scopes.get(candidate.candidate_id, {})
            )
            index = dialog.mesh_combo.currentData()
            if index is not None:
                dialog._show_feature_check(dialog._pairs[int(index)])
            dialog._update_review_progress()
            dialog.exec()
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
            super().closeEvent(event)
            return
        QMessageBox.information(
            self,
            "Calibration still running",
            "Cancel safely first and wait until the current candidate reaches a "
            "terminal state before closing this window.",
        )
        event.ignore()

    def reject(self) -> None:
        """Escape must not hide/destroy a running pilot or lose its controller."""
        if self._worker is None:
            super().reject()
