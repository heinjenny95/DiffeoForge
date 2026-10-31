"""Load a saved alternative only when requested; current-fit QC stays separate."""

from dataclasses import replace
from pathlib import Path

import numpy as np
from PySide6.QtWidgets import QCheckBox, QComboBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from diffeoforge.desktop.calibration_comparison_widget import CalibrationComparisonCanvas3D
from diffeoforge.desktop.full_review_policy import FullSavedComparisonMixin
from diffeoforge.desktop.preview_mesh_loader import PreviewMeshLoader


def alternatives(snapshot, identifier):
    """Called during background viewer preparation; bind each separate run/pair."""
    from diffeoforge import reference_calibration_study as study
    from diffeoforge.desktop.reference_calibration_dialog import collect_calibration_qc_pairs
    from diffeoforge.reference_guided_pilot import record

    info = record(snapshot)
    if not info or info["phase"] == "joint":
        return ()
    from diffeoforge.guided_feedback import presentation, verify_reference

    feedback = presentation(snapshot, identifier)
    starting = feedback["comparison"] if feedback else None
    result = []
    sources = [
        snapshot,
        *(
            study.load_reference_calibration_study(Path(r["directory"]))
            for r in reversed(info["history"])
        ),
    ]
    for other in sources:
        if [s.filename for s in other.plan.selected_pilot_subjects] != [info["target"]]:
            continue
        for candidate in other.candidates:
            if candidate.status != "completed" or (
                other.study_directory == snapshot.study_directory
                and candidate.candidate_id == identifier
            ):
                continue
            if (candidate.metrics or {}).get("invalid_face_count") != 0:
                continue
            pair = next(
                p
                for p in collect_calibration_qc_pairs(other.study_directory, candidate)
                if p.required
            )
            pair = replace(pair, pair_id=(
                f"{other.study_directory.name}/{candidate.candidate_id}/{pair.pair_id}"))
            is_start = bool(starting and starting["directory"] == str(other.study_directory)
                            and starting["candidate_id"] == candidate.candidate_id)
            label = f"Test {record(other)['screen_trials_spent']} · {candidate.label}"
            result.append((other.visual_reviews.get(candidate.candidate_id) is True,
                           ("Starting fit · " if is_start else "") + label, pair))
    if starting and not any(r[1].startswith("Starting fit · ") for r in result):
        other = verify_reference(starting)
        candidate = next(c for c in other.candidates if c.candidate_id == starting["candidate_id"])
        pair = next(p for p in collect_calibration_qc_pairs(other.study_directory, candidate)
                    if p.required and p.original_path.name == starting["target"])
        pair = replace(pair, pair_id=(
            f"{other.study_directory.name}/{candidate.candidate_id}/{pair.pair_id}"))
        result.append((other.visual_reviews.get(candidate.candidate_id) is True,
                       "Starting fit · " + candidate.label, pair))
    # An explicit approval is preferred. Never label an unreviewed fit approved/best.
    return tuple(sorted(result, key=lambda r: (not r[1].startswith("Starting fit · "), not r[0])))


class _SavedFitComparison(QWidget):
    def __init__(self, current, choices, parent=None, *, cache_directory):
        super().__init__(parent)
        self.current = current
        self.choices = choices
        self.cache_directory = cache_directory
        self.loader = PreviewMeshLoader(self)
        self.loader.loaded.connect(self._loaded)
        self.loader.failed.connect(lambda _key, error: self.status.setText(error))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.toggle = QCheckBox("Show best approved fit / alternatives")
        layout.addWidget(self.toggle)
        views = QHBoxLayout()
        current_panel = QWidget()
        current_layout = QVBoxLayout(current_panel)
        current_layout.setContentsMargins(0, 0, 0, 0)
        self.current_label = QLabel("Current fit")
        current_layout.addWidget(self.current_label)
        current_layout.addWidget(self.current, 1)
        self.current_label.hide()
        views.addWidget(current_panel, 1)
        self.panel = QWidget()
        panel_layout = QVBoxLayout(self.panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        self.choice = QComboBox()
        self.choice.setAccessibleName("Saved fit alternative")
        for approved, label, pair in choices:
            self.choice.addItem(("Approved · " if approved else "Alternative · ") + label, pair)
        panel_layout.addWidget(self.choice)
        self.current_label.setMinimumHeight(self.choice.sizeHint().height())
        self.canvas = CalibrationComparisonCanvas3D()
        self.canvas.setMinimumHeight(250)
        self.canvas.original_detail.hide()
        panel_layout.addWidget(self.canvas, 1)
        views.addWidget(self.panel, 1)
        layout.addLayout(views, 1)
        self.status = QLabel("Saved comparison; acceptance applies to the current fit on the left.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.status.hide()
        self.panel.hide()
        self.toggle.toggled.connect(self._toggle)
        self.choice.currentIndexChanged.connect(self._request)
        current.cameraChanged.connect(self.canvas.set_linked_camera)
        self.canvas.cameraChanged.connect(current.set_linked_camera)

    def _toggle(self, visible):
        self.panel.setVisible(visible)
        self.current_label.setVisible(visible)
        self.status.setVisible(visible)
        if visible:
            self._request()
        else:
            self.loader.cancel()
            self.canvas.clear()

    def _request(self, *_args):
        if not self.toggle.isChecked() or self.choice.currentData() is None:
            return
        pair = self.choice.currentData()
        self.status.setText("Loading saved comparison…")
        self.loader.request_paths(
            pair.pair_id,
            (pair.original_path, pair.reconstruction_path),
            expected=(pair.original_sha256, pair.reconstruction_sha256),
            pilot_cache=self.cache_directory,
        )

    def _loaded(self, key, models):
        pair = self.choice.currentData()
        if not self.toggle.isChecked() or pair.pair_id != key:
            return
        original = self.current.original_model
        reconstructed = self.current.reconstruction_model
        if original is None or reconstructed is None or original.sha256 != models[0].sha256:
            self.status.setText("This saved fit belongs to a different original specimen.")
            return
        self.canvas.set_models(*models)
        points = np.vstack([original.vertices, reconstructed.vertices, models[1].vertices])
        low, high = points.min(axis=0), points.max(axis=0)
        for canvas in (self.current, self.canvas):
            canvas.set_comparison_extent((low + high) / 2, float(np.max(high - low)))
        self.canvas.set_linked_camera(self.current.camera_state())
        self.status.setText("Saved comparison. Acceptance applies to the current fit on the left.")


class SavedFitComparison(FullSavedComparisonMixin, _SavedFitComparison):
    """Fit decisions require complete, matching display geometry."""
