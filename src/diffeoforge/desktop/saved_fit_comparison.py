"""Load a saved alternative only when requested; current-fit QC stays separate."""

from dataclasses import replace
from pathlib import Path

import numpy as np
from PySide6.QtWidgets import QCheckBox, QComboBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from diffeoforge.desktop.calibration_comparison_widget import CalibrationComparisonCanvas3D
from diffeoforge.desktop.full_review_policy import FullSavedComparisonMixin
from diffeoforge.desktop.preview_mesh_loader import PreviewMeshLoader


def trial_label(snapshot, candidate):
    from diffeoforge.reference_guided_pilot import record

    return f"Test {record(snapshot)['screen_trials_spent']} · {candidate.label}"


def common_seed_source(ref):
    """A verified numerical checkpoint may have no separate anatomical review."""
    from diffeoforge.guided_feedback import reference
    from diffeoforge.reference_calibration_study import load_reference_calibration_study

    parent = load_reference_calibration_study(Path(ref["directory"]))
    if reference(parent, ref["candidate_id"], ref["target"]) != ref:
        raise ValueError("The common model's saved numerical starting fit changed")
    return parent


def _common_alternatives(context):
    from diffeoforge.desktop.common_review_metrics import sampled_fit_label
    from diffeoforge.desktop.reference_calibration_dialog import collect_calibration_qc_pairs
    from diffeoforge.guided_feedback import verify_reference

    common = context["common_review"]
    approved, seed = common["approved_individual"], common["numerical_seed"]
    history = [r["reference"] for r in context["choices"] if r["inspected"]]
    refs = [common.get("requested_comparison"), approved, seed, *history]
    result = []
    seen = set()
    for ref in refs:
        if ref is None or ref == common["current"]:
            continue
        identity = (ref["directory"], ref["candidate_id"])
        if identity in seen:
            continue
        seen.add(identity)
        eligible = ref in history or ref == approved
        other = verify_reference(ref) if eligible else common_seed_source(ref)
        candidate = next(c for c in other.candidates if c.candidate_id == ref["candidate_id"])
        pair = next(p for p in collect_calibration_qc_pairs(other.study_directory, candidate)
                    if p.required and p.original_path.name == ref["target"])
        pair = replace(pair,
                       pair_id=f"{other.study_directory.name}/{ref['candidate_id']}/{pair.pair_id}",
                       rating_reference=ref if eligible else None,
                       fit_distance_label=sampled_fit_label(candidate, ref["target"]))
        role = ("Approved individual fit" if ref == approved else
                "Numerical starting fit" if ref == seed else "Saved alternative")
        result.append((ref == approved, role + " · " + trial_label(other, candidate), pair))
    return result, seen


def alternatives(snapshot, identifier, feedback=None):
    """Called during background viewer preparation; bind each separate run/pair."""
    from diffeoforge import reference_calibration_study as study
    from diffeoforge.desktop.reference_calibration_dialog import collect_calibration_qc_pairs
    from diffeoforge.reference_guided_pilot import record

    info = record(snapshot)
    if not info or info["phase"] == "joint":
        return ()
    from diffeoforge.guided_feedback import presentation, verify_reference

    if feedback is None:
        feedback = presentation(snapshot, identifier)
    common = (feedback or {}).get("common_review")
    starting = feedback["comparison"] if feedback else None
    density_pair = snapshot.attachment_comparison.get("early_density_comparison")
    result, bound = _common_alternatives(feedback) if common else ([], set())
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
            identity = (str(other.study_directory), candidate.candidate_id)
            if identity in bound or candidate.status != "completed" or (
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
            if common:
                from diffeoforge.desktop.common_review_metrics import sampled_fit_label

                label = "Inspection only · " + trial_label(other, candidate)
                result.append((False, label, replace(
                    pair, fit_distance_label=sampled_fit_label(candidate, info["target"]))))
                bound.add(identity)
                continue
            is_start = bool(starting and starting["directory"] == str(other.study_directory)
                            and starting["candidate_id"] == candidate.candidate_id)
            label = f"Test {record(other)['screen_trials_spent']} · {candidate.label}"
            paired = density_pair and other.study_directory == snapshot.study_directory
            prefix = "Matched density · " if paired else "Starting fit · " if is_start else ""
            result.append((other.visual_reviews.get(candidate.candidate_id) is True,
                           prefix + label, pair))
    if common:
        return tuple(result)
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
    return tuple(sorted(result, key=lambda r: (not r[1].startswith("Matched density · "),
                                               not r[1].startswith("Starting fit · "), not r[0])))


class _SavedFitComparison(QWidget):
    def __init__(self, current, choices, parent=None, *, cache_directory, common_review=None):
        super().__init__(parent)
        self.current = current
        self.choices = choices
        self.cache_directory = cache_directory
        self.common_review = common_review
        self.waiting_for_current = False
        self.loader = PreviewMeshLoader(self)
        self.loader.loaded.connect(self._loaded)
        self.loader.failed.connect(lambda _key, error: self.status.setText(error))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.toggle = QCheckBox("Show comparison" if common_review else
                                "Show best approved fit / alternatives")
        layout.addWidget(self.toggle)
        views = QHBoxLayout()
        current_panel = QWidget()
        current_layout = QVBoxLayout(current_panel)
        current_layout.setContentsMargins(0, 0, 0, 0)
        self.current_label = QLabel("Common-model check · " + common_review["current_label"]
                                    if common_review else "Current fit")
        self.current_label.setWordWrap(True)
        current_layout.addWidget(self.current_label)
        if common_review:
            metric = QLabel(common_review["current_distances"])
            metric.setWordWrap(True)
            current_layout.addWidget(metric)
        current_layout.addWidget(self.current, 1)
        self.current_label.hide()
        views.addWidget(current_panel, 1)
        self.panel = QWidget()
        panel_layout = QVBoxLayout(self.panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        self.choice = QComboBox()
        self.choice.setAccessibleName("Saved fit alternative")
        for approved, label, pair in choices:
            prefix = "" if common_review else ("Approved · " if approved else "Alternative · ")
            self.choice.addItem(prefix + label, pair)
        panel_layout.addWidget(self.choice)
        if common_review:
            comparison_metric = QLabel()
            comparison_metric.setWordWrap(True)

            def show_distance(_index):
                comparison_metric.setText(self.choice.currentData().fit_distance_label)

            self.choice.currentIndexChanged.connect(show_distance)
            show_distance(0)
            panel_layout.addWidget(comparison_metric)
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
        self.current_label.setVisible(visible or bool(self.common_review))
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
