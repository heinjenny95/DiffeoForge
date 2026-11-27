"""Edit independent surface instructions together, committing only on Save."""

from copy import deepcopy
from threading import Event

import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from diffeoforge.desktop.landmark_3d_widget import InteractiveMeshCanvas3D
from diffeoforge.desktop.preview_mesh_loader import PreviewMeshLoader
from diffeoforge.pilot_regions import BOX_VERSION, EDIT_VERSION, MAX_REGIONS, SYMPTOMS, validate
from diffeoforge.reconstruction_feedback import ReconstructionMaterialUnavailable

_CORRECT_COLOR = "#bc283d"
_PROTECT_COLOR = "#137748"

# Keep the journal values and scientific region handling from the pilot.
_INSTRUCTIONS = SYMPTOMS | {
    "unsure": "Check this area",
    "missing": "Part of the original surface is missing",
    "detail": "A fine feature is missing",
    "distortion": "The fit adds surface, folds or bulges",
}


class RegionFeedbackDialog(QDialog):
    def __init__(self, marking, parent=None, *, regions=(), rotation=None,
                 fit_preview=None, pilot_cache=None, candidate=None, subject=None):
        super().__init__(parent)
        self.setProperty("processRecordingPilotReview", True)
        self.setWindowTitle("Correct fit · click an area")
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
        self.resize(1000, 630)
        self.regions = None
        self.region = None  # Compatibility for a caller inspecting one saved patch.
        self._rows = deepcopy(list(regions))
        self._initial_rows = deepcopy(self._rows)
        self._area_counts = {}
        self._had_rows = bool(self._rows)
        self.marking = marking
        self.model = model = marking.model
        if self._rows:
            validate({"original": self._rows}, {"original": model.sha256})
        self.diagonal = float(np.linalg.norm(np.ptp(np.asarray(model.bounds).reshape(3, 2),
                                                   axis=1)))
        self._loading = False
        self._move = False
        self._correction_mode = "problem:unsure" if fit_preview is not None else "problem:detail"
        self._click_mode = self._correction_mode
        self._fit_preview = fit_preview
        self._fit_marking = None
        self._fit_error = None
        self._diagnosis_key = None
        self._suggestion = None
        self._diagnosis_loader = PreviewMeshLoader(self)
        self._diagnosis_loader.loaded.connect(self._diagnosis_ready)
        self._diagnosis_loader.failed.connect(self._diagnosis_failed)
        self._diagnosis_timer = QTimer(self, singleShot=True, interval=180)
        self._diagnosis_timer.timeout.connect(self._inspect_selected_area)
        self.finished.connect(self._diagnosis_timer.stop)
        self.finished.connect(self._diagnosis_loader.cancel)
        self.center = None
        layout = QVBoxLayout(self)
        intro = QLabel("Pick a tool and click the surface. Select a point to adjust its area.")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        tools = QHBoxLayout()
        layout.addLayout(tools)
        self.click_modes = QButtonGroup(self)
        for text, action, color in (
            ("Red · Correct here", self._correction_mode, _CORRECT_COLOR),
            ("Green · Keep unchanged", "fixed", _PROTECT_COLOR),
        ):
            button = QPushButton(text)
            button.setCheckable(True)
            button.setChecked(action == self._click_mode)
            button.setStyleSheet(
                f"QPushButton {{ border: 2px solid {color}; }} "
                f"QPushButton:checked {{ background: {color}; color: white; }}"
            )
            button.clicked.connect(lambda _checked=False, value=action: self._set_click_mode(value))
            self.click_modes.addButton(button)
            tools.addWidget(button)
        tools.addStretch()
        self.view = QComboBox()
        self.view.setAccessibleName("Surface to display")
        self.view.setToolTip("The overlay shows the fitted surface in purple.")
        if fit_preview is not None:
            self.view.addItem("Overlay", "overlay")
        self.view.addItem("Original", "original")
        if fit_preview is not None:
            self.view.addItem("Fit", "fit")
            tools.addWidget(self.view)
        self.view.currentIndexChanged.connect(self._show_view)
        picking = QHBoxLayout()
        layout.addLayout(picking)
        picking.addWidget(QLabel("Mark on:"))
        self.pick_surface = QComboBox()
        self.pick_surface.setAccessibleName("Surface to mark")
        self.pick_surface.addItem("Original surface", "original")
        if fit_preview is not None:
            self.pick_surface.addItem("Reconstruction surface", "reconstruction")
        self.pick_surface.setToolTip(
            "Select which exact surface receives red corrections in the overlay. "
            "Green protection uses the original surface.")
        self.pick_surface.currentIndexChanged.connect(self._pick_surface_changed)
        picking.addWidget(self.pick_surface)
        self.pick_label = QLabel()
        self.pick_label.setWordWrap(True)
        self.pick_label.setMinimumWidth(0)
        picking.addWidget(self.pick_label, 1)
        self.body = body = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(body, 1)
        self.canvas = InteractiveMeshCanvas3D(progressive_navigation=True)
        self.canvas.setMinimumSize(200, 240)
        self.canvas.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        self.canvas.pick_instruction = "Click: add another area"
        self.canvas.set_model(model, surface_picker=marking.pick)
        if rotation is not None:
            self.canvas.set_view_rotation(rotation)
        self.canvas.original_detail.setText("Load full surface detail (optional, slower)")
        self.canvas.original_detail.setToolTip(
            "Show fine structures on the active surface. Clicks use that surface's exact faces.")
        body.addWidget(self.canvas)
        panel = QWidget()
        panel.setMinimumWidth(0)
        panel.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        controls = QVBoxLayout(panel)
        self.side = side = QScrollArea()
        side.setFrameShape(QScrollArea.Shape.NoFrame)
        side.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        side.setWidgetResizable(True)
        side.setMinimumWidth(260)
        side.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        side.setWidget(panel)
        body.addWidget(side)
        body.setStretchFactor(0, 1)
        body.setStretchFactor(1, 0)
        body.setSizes([640, 330])
        controls.addWidget(QLabel("Points and instructions"))
        self.listing = QListWidget()
        self.listing.setMinimumSize(0, 80)
        self.listing.setWordWrap(True)
        self.listing.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.listing.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.listing.setAccessibleName("Marked points and their individual instructions")
        controls.addWidget(self.listing, 1)
        buttons = QHBoxLayout()
        self.move = QPushButton("Move point")
        self.move.setAccessibleName("Move selected point")
        self.move.setToolTip("Move the selected point with the next surface click")
        self.move.setCheckable(True)
        self.move.toggled.connect(self._move_mode)
        buttons.addWidget(self.move)
        self.remove = QPushButton("Remove point")
        self.remove.setAccessibleName("Remove selected point")
        self.remove.clicked.connect(self._remove)
        buttons.addWidget(self.remove)
        controls.addLayout(buttons)
        controls.addWidget(QLabel("Instruction for selected point"))
        self.action = QComboBox()
        self.action.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.action.setMinimumContentsLength(16)
        self.action.setMinimumWidth(0)
        self.action.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.action.setAccessibleName("Instruction for selected point")
        for key, label in _INSTRUCTIONS.items():
            self.action.addItem(label, "problem:" + key)
        self.action.addItem("Retain this area in place", "fixed")
        self.action.addItem("Retain this part's shape; allow movement", "preserve")
        controls.addWidget(self.action)
        self.action_full = QLabel()
        self.action_full.setAccessibleName("Selected instruction in full")
        self.action_full.setWordWrap(True)
        self.action_full.setMinimumWidth(0)
        self.action_full.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        controls.addWidget(self.action_full)
        self.action.currentTextChanged.connect(self._show_full_instruction)
        note = QLabel("Retain in place fixes the location. Retain shape allows movement.")
        note.setWordWrap(True)
        note.setMinimumWidth(0)
        note.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        controls.addWidget(note)
        self.shape = QComboBox()
        self.shape.setAccessibleName("Area shape for new points or the selected area")
        self.shape.addItem("Surface brush", "sphere")
        self.shape.addItem("3D box", "box")
        controls.addWidget(self.shape)
        self.shape_hint = QLabel(
            "Choose the area shape, then click the surface to set its centre. "
            "A 3D box uses the X, Y and Z size sliders; drag rotates the view.")
        self.shape_hint.setObjectName("areaShapeHint")
        self.shape_hint.setWordWrap(True)
        self.shape_hint.setMinimumWidth(0)
        controls.addWidget(self.shape_hint)
        self.size = QSlider(Qt.Orientation.Horizontal)
        self.size.setRange(1, 40)
        self.size.setValue(8)
        self.size.setAccessibleName("Region radius as percentage of original extent")
        controls.addWidget(QLabel("Area size · smaller ← → larger"))
        controls.addWidget(self.size)
        self.axes = []
        self.axis_rows = []
        for label in ["X", "Y", "Z"]:
            axis_row = QWidget()
            axis_layout = QHBoxLayout(axis_row)
            axis_layout.setContentsMargins(0, 0, 0, 0)
            axis_layout.addWidget(QLabel(label))
            axis = QSlider(Qt.Orientation.Horizontal)
            axis.setRange(1, 60)
            axis.setValue(8)
            axis.setAccessibleName(label + " box half extent as percentage of original size")
            axis.setToolTip(label + " box half extent")
            axis_layout.addWidget(axis, 1)
            controls.addWidget(axis_row)
            axis.valueChanged.connect(self._update)
            self.axes.append(axis)
            self.axis_rows.append(axis_row)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setMinimumWidth(0)
        self.status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        controls.addWidget(self.status)
        self.finding = QLabel()
        self.finding.setWordWrap(True)
        self.finding.setMinimumWidth(0)
        self.finding.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.finding.setObjectName("status")
        self.finding.setVisible(fit_preview is not None)
        controls.addWidget(self.finding)
        self.use_suggestion = QPushButton("Use suggested correction")
        self.use_suggestion.clicked.connect(self._apply_suggestion)
        self.use_suggestion.hide()
        controls.addWidget(self.use_suggestion)
        controls.addWidget(self.canvas.original_detail)
        footer = QHBoxLayout()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        footer.addWidget(cancel)
        footer.addStretch()
        self.save = QPushButton("Save all marked areas")
        self.save.setObjectName("primary")
        self.save.clicked.connect(self._save)
        footer.addWidget(self.save)
        layout.addLayout(footer)
        self.canvas.surfacePointPicked.connect(self._picked)
        self.listing.currentRowChanged.connect(self._selected)
        self.size.valueChanged.connect(self._update)
        self.shape.currentIndexChanged.connect(self._update)
        self.action.currentIndexChanged.connect(self._action_changed)
        self.action.currentTextChanged.connect(self.action.setToolTip)
        self.finished.connect(self.canvas.cancel_pending_pick)
        self._move_mode(False)
        self._refresh_list(0 if self._rows else -1)
        if fit_preview is not None:
            from diffeoforge.desktop.region_marking_geometry import load_region_marking_mesh

            self._show_view()
            self._fit_loader = PreviewMeshLoader(self)
            self._fit_loader.loaded.connect(self._fit_ready)
            self._fit_loader.failed.connect(self._fit_failed)
            self.finished.connect(self._fit_loader.cancel)
            initial = self._initial_rows

            cancelled = Event()
            self._fit_loader.cancelled.connect(cancelled.set)

            def prepare_fit():
                geometry = load_region_marking_mesh(
                    fit_preview.path, fit_preview.sha256, fit_preview, pilot_cache)
                if any(r.get("reconstruction") for r in initial):
                    geometry.prepare_inherited_faces(candidate, subject, initial,
                                                     cancelled=cancelled.is_set)
                return geometry

            self._fit_loader.request_operation(fit_preview.sha256, prepare_fit)

    def resizeEvent(self, event):  # noqa: N802 - Qt API
        super().resizeEvent(event)
        if hasattr(self, "body"):
            orientation = (Qt.Orientation.Vertical if self.width() < 850
                           else Qt.Orientation.Horizontal)
            if self.body.orientation() != orientation:
                self.body.setOrientation(orientation)
                self.body.setSizes([360, 260] if orientation == Qt.Orientation.Vertical
                                   else [max(200, self.width() - 370), 330])
            QTimer.singleShot(0, self._show_full_instruction)

    def _show_full_instruction(self, *_):
        if not hasattr(self, "action_full"):
            return
        text = self.action.currentText()
        self.action_full.setText(text)
        self.action_full.setVisible(self.action.fontMetrics().horizontalAdvance(text)
                                    > self.action.width() - 36)

    @staticmethod
    def _label(row):
        purpose = row.get("purpose", "problem")
        return ("Retain in place" if purpose == "fixed" else
                "Retain shape; allow movement" if purpose == "preserve" else
                _INSTRUCTIONS[row["symptom"]])

    def _refresh_list(self, selected):
        self.listing.blockSignals(True)
        self.listing.clear()
        for i, row in enumerate(self._rows):
            self.listing.addItem(f"{chr(65 + i)} · {self._label(row)}")
        self.listing.setCurrentRow(selected)
        self.listing.blockSignals(False)
        self._selected(selected)

    def _selected(self, index):
        self._loading = True
        row = self._rows[index] if 0 <= index < len(self._rows) else None
        for control in [self.action, self.move, self.remove]:
            control.setEnabled(row is not None)
        if row:
            self.center = tuple(row["center"])
            purpose = row.get("purpose", "problem")
            self.action.setCurrentIndex(self.action.findData(
                "problem:" + row["symptom"] if purpose == "problem" else purpose))
            boxed = row.get("shape") == "box"
            self.shape.setCurrentIndex(1 if boxed else 0)
            self.size.setValue(round(row["radius"] / self.diagonal * 100))
            if boxed:
                half = np.ptp(np.asarray(row["bounds"]).reshape(3, 2), axis=1) / 2
                for slider, value in zip(self.axes, half, strict=True):
                    slider.setValue(round(value / self.diagonal * 100))
        else:
            self.center = None
        self._loading = False
        self._render()

    def _set_click_mode(self, mode):
        self._click_mode = mode
        self.move.setChecked(False)
        self._select_edit_surface(mode)
        self._move_mode(self._move)

    def _select_edit_surface(self, mode):
        if mode in {"problem:missing", "fixed", "preserve"}:
            self.pick_surface.setCurrentIndex(0)
            if self.view.currentData() == "fit":
                self.view.setCurrentIndex(self.view.findData("overlay"))
        elif mode == "problem:distortion" and self.pick_surface.count() > 1:
            self.pick_surface.setCurrentIndex(1)

    def _pick_surface_changed(self, *_):
        if self.pick_surface.currentData() == "reconstruction":
            if self._click_mode == "fixed":
                self.pick_surface.setCurrentIndex(0)
                return
            if self.view.currentData() == "original":
                self.view.setCurrentIndex(self.view.findData("overlay"))
        self._show_view()

    def _active_surface(self):
        if self.view.currentData() == "fit":
            return "reconstruction"
        if self.view.currentData() == "original":
            return "original"
        return self.pick_surface.currentData()

    def _show_view(self, *_):
        mode = self.view.currentData()
        if mode == "fit" and self._click_mode == "fixed":
            self.view.setCurrentIndex(self.view.findData("overlay"))
            return
        data = self._fit_marking if mode == "fit" else self.marking
        visible = data.model if data is not None else self._fit_preview
        picking = self._fit_marking if self._active_surface() == "reconstruction" else self.marking
        original_detail = self.canvas.original_detail.isChecked()
        self.canvas.set_model(visible, surface_picker=picking.pick if picking else None,
                              view_bounds=self.model.bounds,
                              pick_bounds=picking.model.bounds if picking else None,
                              pick_display_model=(self._fit_preview if mode == "overlay"
                                  and self._active_surface() == "reconstruction" else None))
        if original_detail and data is not None:
            self.canvas.original_detail.setChecked(True)
        self.canvas.set_fit_overlay(self._fit_preview if mode == "overlay" else None)
        self.canvas.set_picking_enabled(picking is not None)
        self.pick_label.setText("Red clicks mark the reconstruction; no original face is required."
            if self._active_surface() == "reconstruction" else
            "Clicks mark the original surface.")
        self._move_mode(self._move)
        self._render()

    def _fit_ready(self, digest, marking):
        if (digest != self._fit_preview.sha256 or marking.model.sha256 != digest
                or marking.model.path != self._fit_preview.path):
            return
        self._fit_marking = marking
        self._area_counts.clear()
        self._show_view()

    def _fit_failed(self, _key, message):
        self._fit_error = f"Fit inspection unavailable. {message}"
        self._queue_diagnosis()

    def _diagnosis_state(self):
        index = self.listing.currentRow()
        if index < 0 or self._fit_preview is None:
            return None, None
        row = self._rows[index]
        if row.get("purpose", "problem") != "problem":
            return None, None
        key = (index, tuple(row["center"]), row["radius"], tuple(row.get("bounds", ())),
               repr(row.get("reconstruction")))
        return key, row

    def _queue_diagnosis(self):
        if self._fit_preview is None:
            return
        key, row = self._diagnosis_state()
        can_measure = row is not None and self._fit_marking is not None
        requested = key if can_measure else None
        changed = requested != self._diagnosis_key
        if changed:
            self._diagnosis_key = requested
            self._diagnosis_loader.cancel()
            self._diagnosis_timer.stop()
            self._suggestion = None
        if self._fit_error:
            self.finding.setText(self._fit_error)
        elif self._active_surface() == "reconstruction" and self._fit_marking is None:
            self.finding.setText("Loading the fitted surface for precise clicks…")
        elif row is None:
            self.finding.setText("Click an area to compare the original and the fit."
                                 if self.listing.currentRow() < 0 else
                                 "This area is protected in the next local test.")
        elif self._fit_marking is None:
            self.finding.setText("Loading the fitted surface for local comparison…")
        elif changed:
            self.finding.setText("Checking the marked area…")
            self._diagnosis_timer.start()
        self.use_suggestion.setVisible(bool(row and self._suggestion
                                           and self._suggestion != row["symptom"]))

    def _inspect_selected_area(self):
        from diffeoforge.desktop.marked_area_diagnosis import diagnose

        key, row = self._diagnosis_state()
        if row is None or self._fit_marking is None:
            return
        original, fit, region = self.marking, self._fit_marking, deepcopy(row)
        self._diagnosis_loader.request_operation(key, lambda: diagnose(original, fit, region))

    def _diagnosis_ready(self, key, result):
        active, row = self._diagnosis_state()
        if key == active and row is not None:
            self._suggestion = result["symptom"]
            self.finding.setText(result["message"])
            self.use_suggestion.setVisible(bool(self._suggestion and
                                               self._suggestion != row["symptom"]))

    def _diagnosis_failed(self, key, _message):
        active, _ = self._diagnosis_state()
        if key == active:
            self.finding.setText("Local comparison unavailable. You can choose a correction.")

    def _apply_suggestion(self):
        active, row = self._diagnosis_state()
        if active == self._diagnosis_key and row is not None and self._suggestion:
            choice = self.action.findData("problem:" + self._suggestion)
            if choice >= 0:
                self.action.setCurrentIndex(choice)

    def _move_mode(self, enabled):
        self._move = enabled
        if enabled:
            self._select_edit_surface(self.action.currentData())
        mode = "keep unchanged" if self._click_mode == "fixed" else "correct here"
        self.canvas.pick_instruction = "Click: move selected point" if enabled else f"Click: {mode}"

    def _picked(self, point):
        center = [float(v) for v in point]
        index = self.listing.currentRow()
        if self._move and 0 <= index < len(self._rows):
            row = self._rows[index]
            delta = np.asarray(center) - np.asarray(row["center"])
            if row.get("shape") == "box":
                row["bounds"] = (np.asarray(row["bounds"]).reshape(3, 2)
                                 + delta[:, None]).ravel().tolist()
            row["center"] = center
            self.move.setChecked(False)
        elif len(self._rows) < MAX_REGIONS:
            purpose, _, symptom = self._click_mode.partition(":")
            row = dict(version=EDIT_VERSION, source_sha256=self.model.sha256,
                space="original_mesh_coordinates", center=center,
                radius=self.diagonal * self.size.value() / 100,
                symptom=symptom or "unsure", purpose=purpose)
            self._set_area_shape(row)
            self._rows.append(row)
            index = len(self._rows) - 1
        else:
            self.status.setText("Eight areas marked. Edit or remove a point to add another.")
            return
        if self._active_surface() == "reconstruction":
            if self._fit_marking is None or self._rows[index].get("purpose") != "problem":
                return
            self._bind_reconstruction(self._rows[index])
            if (self._rows[index]["symptom"] == "unsure"
                    and self.marking.count(self._rows[index]) == 0):
                self._rows[index]["symptom"] = "distortion"
        else:
            self._rows[index].pop("reconstruction", None)
        self._refresh_list(index)

    def _bind_reconstruction(self, row):
        from diffeoforge.reconstruction_feedback import bind, topology_sha256

        try:
            row["reconstruction"] = bind(row, self._fit_marking.model)
        except ValueError:
            # Retain the explicit picking role even for an empty draft brush.
            # Such a draft cannot be saved or silently become an original mark.
            model = self._fit_marking.model
            row["reconstruction"] = dict(sha256=model.sha256, face_ids=[],
                topology_sha256=topology_sha256(model.vertices, model.triangles))

    def _action_changed(self, *_):
        index = self.listing.currentRow()
        if self._loading or index < 0:
            return
        row = self._rows[index]
        action = self.action.currentData()
        row["purpose"] = "problem" if action.startswith("problem:") else action
        if row["purpose"] != "problem":
            row.pop("reconstruction", None)
            self._select_edit_surface(action)
        if action.startswith("problem:"):
            row["symptom"] = action.split(":", 1)[1]
        if row["version"] != BOX_VERSION:
            row["version"] = EDIT_VERSION
        self._refresh_list(index)

    def _update(self, *_):
        index = self.listing.currentRow()
        if self._loading:
            return
        if index < 0:
            self._render()  # Preselect shape/extent without creating or changing a mark.
            return
        row = self._rows[index]
        if self._earlier_material(row):
            point = self._fit_marking.tracked_point(row) if self._fit_marking else None
            if point is None:
                self._selected(index)
                return
            row["center"] = list(map(float, point))
        self._set_area_shape(row)
        if row.get("reconstruction") and self._fit_marking is not None:
            self._bind_reconstruction(row)
        self._render()

    def _set_area_shape(self, row):
        if self.shape.currentData() == "box":
            half = self.diagonal * np.array([x.value() for x in self.axes]) / 100
            bounds = np.column_stack((np.asarray(row["center"]) - half,
                                      np.asarray(row["center"]) + half)).ravel().tolist()
            row.update(version=BOX_VERSION, shape="box", bounds=bounds,
                       radius=float(np.linalg.norm(half)))
        else:
            row.pop("shape", None)
            row.pop("bounds", None)
            row.update(version=EDIT_VERSION, radius=self.diagonal * self.size.value() / 100)

    def _remove(self):
        index = self.listing.currentRow()
        if index >= 0:
            self._rows.pop(index)
            self.move.setChecked(False)
            self._refresh_list(min(index, len(self._rows) - 1))

    def _earlier_material(self, row):
        evidence = row.get("reconstruction")
        return evidence and (self._fit_preview is None
                             or evidence["sha256"] != self._fit_preview.sha256)

    def _display_regions(self, selected, counts):
        brushes, markers, colors = [], {}, {}
        selected_brush = None
        for i, (row, count) in enumerate(zip(self._rows, counts, strict=True)):
            if count < 0:
                continue
            if self._earlier_material(row):
                if self._fit_marking is None or self.view.currentData() == "original":
                    continue
                centre = self._fit_marking.tracked_point(row)
                if centre is None:
                    continue
            else:
                if i == selected:
                    selected_brush = len(brushes)
                brushes.append(row)
                centre = tuple(row["center"])
            letter = chr(65 + i)
            markers[letter] = centre
            colors[letter] = (_CORRECT_COLOR if row.get("purpose", "problem") == "problem"
                              else _PROTECT_COLOR)
        self.canvas.set_surface_regions(brushes, selected_brush)
        self.canvas.set_markers(markers, colors=colors)

    def _render(self):
        index = self.listing.currentRow()
        boxed = self.shape.currentData() == "box"
        self.size.setVisible(not boxed)
        for axis_row in self.axis_rows:
            axis_row.setVisible(boxed)
        counts = []
        current_counts = {}
        for row in self._rows:
            evidence = row.get("reconstruction")
            key = (tuple(row["center"]), row["radius"], tuple(row.get("bounds", ())),
                   repr(evidence))
            if key not in self._area_counts:
                if evidence:
                    try:
                        self._area_counts[key] = (len(self._fit_marking.material_faces(row))
                                                  if self._fit_marking else 0)
                    except ReconstructionMaterialUnavailable:
                        self._area_counts[key] = -1
                    except ValueError:
                        self._area_counts[key] = 0
                else:
                    self._area_counts[key] = self.marking.count(row)
            current_counts[key] = self._area_counts[key]
            counts.append(current_counts[key])
        self._area_counts = current_counts
        self._display_regions(index, counts)
        valid = all(count > 0 for count in counts)
        self.save.setEnabled(bool(self._rows) and valid or self._had_rows and not self._rows)
        unmapped = []
        for i, (row, count) in enumerate(zip(self._rows, counts, strict=True)):
            letter = chr(65 + i)
            label = f"{letter} · {self._label(row)}"
            if count < 0:
                label += " · place again on this reconstruction"
                unmapped.append(letter)
            elif count > 0 and self._earlier_material(row):
                label += " · tracked on the fit"
            self.listing.item(i).setText(label)
        if unmapped:
            labels = ", ".join(unmapped)
            self.status.setText(f"Could not locate {labels} on this reconstruction. "
                                "Select the affected mark, choose Reconstruction surface, "
                                "then use Move point to place it again.")
        elif index >= 0 and self._earlier_material(self._rows[index]) and counts[index] > 0:
            self.status.setText(
                f"{chr(65 + index)} · {counts[index]:,} tracked reconstruction faces. "
                "In Fit or Overlay, the letter marks one face in this area. "
                "Resizing draws a new brush at that face.")
        elif index >= 0:
            surface = "reconstruction" if self._rows[index].get("reconstruction") else "original"
            self.status.setText(f"{chr(65 + index)} · {counts[index]:,} {surface} faces selected. "
                + ("Enlarge or move empty areas on the intended surface."
                   if not valid else
                   f"{len(self._rows)} / {MAX_REGIONS} areas. Click to add another point."))
        else:
            self.status.setText("No corrections marked.")
        self._queue_diagnosis()

    def _save(self):
        if not self.save.isEnabled():
            return
        from diffeoforge.mesh import sha256_file
        from diffeoforge.reconstruction_feedback import same_saved_material_mark

        for row in self._rows:
            if row.get("reconstruction") and not same_saved_material_mark(row, self._initial_rows):
                if (self._fit_preview is None
                        or row["reconstruction"]["sha256"] != self._fit_preview.sha256
                        or sha256_file(self._fit_preview.path) != self._fit_preview.sha256):
                    self.finding.setText("The inspected reconstruction changed. Reopen this fit "
                                         "before saving its correction.")
                    return
        self.regions = deepcopy(self._rows)
        self.region = self.regions[-1] if self.regions else None
        self.accept()
