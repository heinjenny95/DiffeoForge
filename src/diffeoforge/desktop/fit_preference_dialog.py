"""Side-by-side human fit ranking with shared camera, scale and verified inputs."""

from pathlib import Path

import numpy as np
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from diffeoforge.desktop.calibration_comparison_widget import CalibrationComparisonCanvas3D
from diffeoforge.desktop.preview_mesh_loader import PreviewMeshLoader
from diffeoforge.reference_fit_preferences import comparison_choices, verified_fit


class FitPreferencePanel(QWidget):
    selectionChanged = Signal()

    def __init__(self, directory, parent=None, *, current_canvas=None):
        super().__init__(parent)
        self.directory = Path(directory).resolve()
        self._shared_canvas = current_canvas is not None
        self._current_models = None
        self.decision = None
        self._descriptor = None
        self._comparison = None
        self._closed = False
        self._ready = False
        self._same_surface = False
        layout = QVBoxLayout(self)
        title = QLabel("Inspect current fit and compare with your best")
        title.setObjectName("heading")
        title.setVisible(not self._shared_canvas)
        layout.addWidget(title)
        intro = QLabel(
            "Orange: target specimen · Blue: fitted surface. Both views share camera and scale."
        )
        intro.setWordWrap(True)
        intro.setVisible(not self._shared_canvas)
        layout.addWidget(intro)
        controls = QHBoxLayout()
        controls.addWidget(QLabel("Compare with"))
        self.reference_combo = QComboBox()
        self.reference_combo.setAccessibleName("Saved fit to compare")
        controls.addWidget(self.reference_combo, 1)
        self.detail = QCheckBox("Original detail")
        controls.addWidget(self.detail)
        reset = QPushButton("Reset view")
        controls.addWidget(reset)
        layout.addLayout(controls)
        views = QHBoxLayout()
        self.reference_panel = QWidget()
        left = QVBoxLayout(self.reference_panel)
        left.setContentsMargins(0, 0, 0, 0)
        self.reference_label = QLabel("Saved fit")
        left.addWidget(self.reference_label)
        self.reference_canvas = CalibrationComparisonCanvas3D()
        left.addWidget(self.reference_canvas, 1)
        right_panel = QWidget()
        right = QVBoxLayout(right_panel)
        right.setContentsMargins(0, 0, 0, 0)
        self.current_label = QLabel("Current fit")
        right.addWidget(self.current_label)
        self.current_canvas = current_canvas or CalibrationComparisonCanvas3D()
        right.addWidget(self.current_canvas, 1)
        views.addWidget(self.reference_panel, 1)
        views.addWidget(right_panel, 1)
        layout.addLayout(views, 1)
        for canvas in (self.reference_canvas, self.current_canvas):
            canvas.setMinimumHeight(220 if self._shared_canvas else 300)
            if canvas is self.reference_canvas or not self._shared_canvas:
                canvas.original_detail.hide()
            canvas.fullResolutionReadyChanged.connect(self._update_actions)
        self.reference_canvas.cameraChanged.connect(self.current_canvas.set_linked_camera)
        self.current_canvas.cameraChanged.connect(self.reference_canvas.set_linked_camera)
        self.reference_canvas.cameraChanged.connect(lambda _state: self._update_actions())
        self.current_canvas.cameraChanged.connect(lambda _state: self._update_actions())
        reset.clicked.connect(self.current_canvas.reset_view)
        self.status = QLabel("Loading saved comparisons…")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.feedback_controls = QWidget()
        self.feedback_controls.setStyleSheet(
            "QPushButton { background: #f2f8f6; border: 1px solid #cee3dd; "
            "border-radius: 6px; min-height: 28px; padding: 2px 10px; }"
            "QPushButton:checked { background: #167c6b; border-color: #167c6b; color: white; }"
            "QPushButton:disabled { color: #78918d; background: #f2f5f4; }"
        )
        feedback_layout = QVBoxLayout(self.feedback_controls)
        feedback_layout.setContentsMargins(0, 0, 0, 0)
        self.step_label = QLabel("1. Compared with the saved fit")
        feedback_layout.addWidget(self.step_label)
        buttons = QHBoxLayout()
        self.button_group = QButtonGroup(self)
        self.feedback_buttons = {}
        for label, outcome in [
            ("Better", "better"),
            ("Worse", "worse"),
            ("About the same", "same"),
        ]:
            button = QPushButton(label)
            button.setEnabled(False)
            button.setCheckable(True)
            self.button_group.addButton(button)
            button.clicked.connect(lambda _checked=False, value=outcome: self._choose(value))
            self.feedback_buttons[outcome] = button
            buttons.addWidget(button)
        self.start_button = QPushButton("First fit — use as starting point")
        self.start_button.setEnabled(False)
        self.start_button.setCheckable(True)
        self.button_group.addButton(self.start_button)
        self.start_button.clicked.connect(lambda: self._choose("starting_point"))
        buttons.addWidget(self.start_button)
        feedback_layout.addLayout(buttons)
        layout.addWidget(self.feedback_controls)
        self.loader = PreviewMeshLoader(self)
        self.loader.loaded.connect(self._loaded)
        self.loader.failed.connect(self._failed)
        self.reference_combo.currentIndexChanged.connect(self._load_comparison)
        self.detail.setVisible(not self._shared_canvas)
        self.detail.toggled.connect(self._load_comparison)
        self.loader.request_operation("choices", lambda: comparison_choices(self.directory))

    def _load_comparison(self, *_args):
        if self._closed or not self._descriptor:
            return
        self._ready = False
        self._same_surface = False
        self._comparison = None
        self.decision = None
        self.button_group.setExclusive(False)
        for button in self.button_group.buttons():
            button.setChecked(False)
        self.button_group.setExclusive(True)
        if not self._shared_canvas:
            self.current_canvas.clear()
        self.reference_canvas.clear()
        self._update_actions()
        descriptor = self._descriptor
        reference = self.reference_combo.currentData()
        detail = (
            self.current_canvas.original_detail.isChecked()
            if self._shared_canvas else self.detail.isChecked()
        )
        current_models = self._current_models
        if self._shared_canvas and current_models is None:
            self.status.setText("Load the current specimen to compare its fit.")
            return
        self.status.setText("Loading the selected surfaces…")

        def prepare():
            from diffeoforge.desktop.mesh_preview import load_mesh_preview
            from diffeoforge.desktop.pilot_preview import load_pilot_preview
            from diffeoforge.desktop.reference_calibration_dialog import (
                collect_calibration_qc_pairs,
            )
            from diffeoforge.mesh import sha256_file
            from diffeoforge.reference_sequential_fit import _read

            root = Path(descriptor["root"])
            state = _read(root)
            if state["current"] != descriptor["current"]["study"]:
                raise ValueError("Current fit changed; reopen the comparison")
            current = verified_fit(root, state, descriptor["current"])
            candidate = next(
                c
                for c in current.candidates
                if c.candidate_id == descriptor["current"]["candidate_id"]
            )
            pair = next(
                p
                for p in collect_calibration_qc_pairs(current.study_directory, candidate)
                if p.required
            )
            paths = [pair.original_path, pair.reconstruction_path]
            expected = [pair.original_sha256, pair.reconstruction_sha256]
            if reference:
                if (reference["study"], reference["candidate_id"]) == (
                    descriptor["current"]["study"], descriptor["current"]["candidate_id"]
                ):
                    raise ValueError("The selected saved fit is the current attempt")
                saved = verified_fit(root, state, reference)
                other = next(
                    c for c in saved.candidates if c.candidate_id == reference["candidate_id"]
                )
                other_pair = next(
                    p
                    for p in collect_calibration_qc_pairs(saved.study_directory, other)
                    if p.required
                )
                if pair.original_sha256 != other_pair.original_sha256:
                    raise ValueError("Compared fits do not share the same original specimen")
                if pair.reconstruction_path.resolve() == other_pair.reconstruction_path.resolve():
                    raise ValueError("Saved and current fits point to the same reconstruction")
                paths.append(other_pair.reconstruction_path)
                expected.append(other_pair.reconstruction_sha256)
            models = list(current_models or ())
            if current_models and any(
                model.sha256 != digest or model.path.resolve() != path.resolve()
                for model, path, digest in zip(current_models, paths[:2], expected[:2], strict=True)
            ):
                raise ValueError("Displayed current specimen differs from the bound fit")
            offset = 2 if current_models else 0
            for path, digest in zip(paths[offset:], expected[offset:], strict=True):
                if sha256_file(path) != digest:
                    raise ValueError("A compared surface changed")
                model = (
                    load_mesh_preview(path)
                    if detail
                    else load_pilot_preview(path, cache_directory=self.directory / "display-cache")
                )
                if model.sha256 != digest:
                    raise ValueError("A compared surface changed during loading")
                models.append(model)
            return models, dict(
                current=descriptor["current"], reference=reference, best=descriptor["best"]
            )

        self.loader.request_operation("surfaces", prepare)

    def _loaded(self, key, result):
        if self._closed:
            return
        if key == "choices":
            self._descriptor = result
            self.current_label.setText("Current fit · " + result["current"]["study"])
            self.reference_combo.blockSignals(True)
            self.reference_combo.clear()
            best = result["best"]
            choices = result["choices"]
            already_best = best == result["current"]
            if best and not already_best:
                self.reference_combo.addItem("Best so far · " + best["study"], best)
            for index, record in enumerate([] if already_best else choices):
                if record == best:
                    continue
                self.reference_combo.addItem(
                    ("Previous attempt · " if index == 0 else "Saved attempt · ") + record["study"],
                    record,
                )
            self.reference_combo.blockSignals(False)
            has_reference = bool(self.reference_combo.count())
            self.reference_panel.setVisible(has_reference)
            self.reference_combo.setVisible(has_reference)
            self.start_button.setVisible(not has_reference)
            if already_best:
                self.start_button.setText("Keep saved best as starting point")
            self.step_label.setText(
                "1. Compared with your best / selected previous fit"
                if has_reference else "1. Saved best fit" if already_best
                else "1. First fit — no previous attempt"
            )
            for button in self.feedback_buttons.values():
                button.setVisible(has_reference)
            self._load_comparison()
            return
        models, comparison = result
        # Bind the delivered surfaces to the visible attempt selection as well as
        # the loader's generation token. Never label a late result as a newer fit.
        if not self._descriptor or comparison != dict(
            current=self._descriptor["current"],
            reference=self.reference_combo.currentData(),
            best=self._descriptor["best"],
        ):
            return
        reference = comparison["reference"]
        if reference and (
            (reference["study"], reference["candidate_id"]) == (
                comparison["current"]["study"], comparison["current"]["candidate_id"]
            )
            or len(models) != 3
            or models[1].path.resolve() == models[2].path.resolve()
        ):
            self._failed(key, "Saved and current fits must be different attempts and files")
            return
        if self._shared_canvas and (
            not self._current_models or any(
                shown.path.resolve() != loaded.path.resolve() or shown.sha256 != loaded.sha256
                for shown, loaded in zip(self._current_models, models[:2], strict=True)
            )
        ):
            self._failed(key, "Displayed current specimen changed; reopen the inspection")
            return
        self._comparison = comparison
        self._same_surface = bool(reference and models[1].sha256 == models[2].sha256)
        if not self._shared_canvas:
            self.current_canvas.set_models(models[0], models[1])
        if len(models) == 3:
            self.reference_canvas.set_models(models[0], models[2])
        vertices = np.vstack([m.vertices for m in models])
        low, high = vertices.min(axis=0), vertices.max(axis=0)
        for canvas in (self.reference_canvas, self.current_canvas):
            canvas.set_comparison_extent((low + high) / 2, float(np.max(high - low)))
            canvas.original_detail.blockSignals(True)
            if canvas is self.reference_canvas or not self._shared_canvas:
                canvas.original_detail.setChecked(
                    self.current_canvas.original_detail.isChecked()
                    if self._shared_canvas else self.detail.isChecked()
                )
            canvas.original_detail.blockSignals(False)
        self.reference_canvas.set_linked_camera(self.current_canvas.camera_state())
        self.reference_label.setText(self.reference_combo.currentText())
        self._ready = True
        self._update_actions()

    def _update_actions(self):
        if not hasattr(self, "feedback_buttons"):
            return
        comparison = self._comparison
        reference = comparison.get("reference") if comparison else None
        ready = self._ready and self.current_canvas.comparison_ready
        if reference:
            ready = ready and self.reference_canvas.comparison_ready
        ranked_reference = bool(
            reference and (not comparison["best"] or reference == comparison["best"])
        )
        for button in self.feedback_buttons.values():
            button.setEnabled(bool(ready and ranked_reference))
        self.start_button.setEnabled(bool(ready and not reference))
        if self._ready:
            self.status.setText(
                ("These separate runs exported identical surfaces. " if self._same_surface else "")
                + (
                    "Compare with Best so far to guide the next attempt; "
                    "other saved fits are available for inspection."
                    if reference and not ranked_reference
                    else "Choose relative fit, then accept or reject to save."
                    if reference
                    else "Keep this starting point, then accept or reject the fit."
                )
            )
        self.selectionChanged.emit()

    def _choose(self, outcome):
        if self._closed:
            return
        self._update_actions()
        button = (
            self.start_button if outcome == "starting_point" else self.feedback_buttons[outcome]
        )
        if not button.isEnabled():
            return
        self.decision = outcome, self._descriptor["current"]["candidate_id"], self._comparison
        button.setChecked(True)
        self.selectionChanged.emit()

    @property
    def selection_ready(self):
        if not self.decision or not self._ready or not self.current_canvas.comparison_ready:
            return False
        if self._comparison.get("reference") and not self.reference_canvas.comparison_ready:
            return False
        return self.decision[2] == self._comparison

    def set_current_models(self, pair, models):
        self._current_models = tuple(models) if pair.required else None
        self._load_comparison()

    def _failed(self, _key, message):
        self._ready = False
        self._comparison = None
        self.reference_canvas.clear()
        self._update_actions()
        self.status.setText("Comparison unavailable: " + message)

    def shutdown(self):
        self._closed = True
        self.loader.cancel()

    def closeEvent(self, event):
        self.shutdown()
        super().closeEvent(event)
