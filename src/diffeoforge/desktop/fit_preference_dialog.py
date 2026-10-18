"""Side-by-side human fit ranking with shared camera, scale and verified inputs."""

from pathlib import Path

import numpy as np
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from diffeoforge.desktop.calibration_comparison_widget import CalibrationComparisonCanvas3D
from diffeoforge.desktop.preview_mesh_loader import PreviewMeshLoader
from diffeoforge.reference_fit_preferences import comparison_choices, verified_fit


class FitPreferenceDialog(QDialog):
    def __init__(self, directory, parent=None):
        super().__init__(parent)
        self.directory = Path(directory).resolve()
        self.setWindowTitle("Compare fits — guide the next attempt")
        self.resize(1120, 760)
        self.setMinimumSize(820, 600)
        self.decision = None
        self._descriptor = None
        self._comparison = None
        self._closed = False
        self._ready = False
        layout = QVBoxLayout(self)
        title = QLabel("Which fit is closer to the anatomy you need?")
        title.setObjectName("heading")
        layout.addWidget(title)
        intro = QLabel(
            "Orange: target specimen · Blue: fitted surface. Both views share camera and scale."
        )
        intro.setWordWrap(True)
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
        right.addWidget(QLabel("Current fit"))
        self.current_canvas = CalibrationComparisonCanvas3D()
        right.addWidget(self.current_canvas, 1)
        views.addWidget(self.reference_panel, 1)
        views.addWidget(right_panel, 1)
        layout.addLayout(views, 1)
        for canvas in (self.reference_canvas, self.current_canvas):
            canvas.setMinimumHeight(300)
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
        buttons = QHBoxLayout()
        self.feedback_buttons = {}
        for label, outcome in [
            ("Better, still not right", "better"),
            ("Worse", "worse"),
            ("About the same", "same"),
        ]:
            button = QPushButton(label)
            button.setEnabled(False)
            button.clicked.connect(lambda _checked=False, value=outcome: self._choose(value))
            self.feedback_buttons[outcome] = button
            buttons.addWidget(button)
        self.start_button = QPushButton("Improve from this fit")
        self.start_button.setEnabled(False)
        self.start_button.clicked.connect(lambda: self._choose("starting_point"))
        buttons.addWidget(self.start_button)
        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        buttons.addWidget(close)
        layout.addLayout(buttons)
        note = QLabel(
            "Feedback starts one new attempt. The best starting point stays saved; "
            "anatomical approval is a separate review."
        )
        note.setWordWrap(True)
        note.setObjectName("hint")
        layout.addWidget(note)
        self.loader = PreviewMeshLoader(self)
        self.loader.loaded.connect(self._loaded)
        self.loader.failed.connect(self._failed)
        self.reference_combo.currentIndexChanged.connect(self._load_comparison)
        self.detail.toggled.connect(self._load_comparison)
        self.loader.request_operation("choices", lambda: comparison_choices(self.directory))

    def _load_comparison(self, *_args):
        if self._closed or not self._descriptor:
            return
        self._ready = False
        self._comparison = None
        self.current_canvas.clear()
        self.reference_canvas.clear()
        self._update_actions()
        descriptor = self._descriptor
        reference = self.reference_combo.currentData()
        detail = self.detail.isChecked()
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
                paths.append(other_pair.reconstruction_path)
                expected.append(other_pair.reconstruction_sha256)
            models = []
            for path, digest in zip(paths, expected, strict=True):
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
            self.reference_combo.blockSignals(True)
            best = result["best"]
            choices = result["choices"]
            if best and best != result["current"]:
                self.reference_combo.addItem("Best so far · " + best["study"], best)
            for index, record in enumerate(choices):
                if record == best:
                    continue
                self.reference_combo.addItem(
                    ("Previous attempt · " if index == 0 else "Saved attempt · ") + record["study"],
                    record,
                )
            self.reference_combo.blockSignals(False)
            self.reference_panel.setVisible(bool(choices))
            self.start_button.setVisible(not bool(choices))
            for button in self.feedback_buttons.values():
                button.setVisible(bool(choices))
            self._load_comparison()
            return
        models, comparison = result
        self._comparison = comparison
        self.current_canvas.set_models(models[0], models[1])
        if len(models) == 3:
            self.reference_canvas.set_models(models[0], models[2])
        vertices = np.vstack([m.vertices for m in models])
        low, high = vertices.min(axis=0), vertices.max(axis=0)
        for canvas in (self.reference_canvas, self.current_canvas):
            canvas.set_comparison_extent((low + high) / 2, float(np.max(high - low)))
            canvas.original_detail.blockSignals(True)
            canvas.original_detail.setChecked(self.detail.isChecked())
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
                "Compare with Best so far to guide the next attempt; "
                "other saved fits are available for inspection."
                if reference and not ranked_reference
                else "Better replaces the starting point. Worse or About the same keeps it."
                if reference
                else "First attempt: keep this as your starting point without approving it."
            )

    def _choose(self, outcome):
        self._update_actions()
        button = (
            self.start_button if outcome == "starting_point" else self.feedback_buttons[outcome]
        )
        if not button.isEnabled():
            return
        self.decision = outcome, self._descriptor["current"]["candidate_id"], self._comparison
        self.accept()

    def _failed(self, _key, message):
        self._ready = False
        self._update_actions()
        self.status.setText("Comparison unavailable: " + message)

    def done(self, result):
        self._closed = True
        self.loader.cancel()
        super().done(result)
