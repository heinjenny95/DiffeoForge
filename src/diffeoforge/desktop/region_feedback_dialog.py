"""Edit independent surface instructions together, committing only on Save."""

from copy import deepcopy

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from diffeoforge.desktop.landmark_3d_widget import InteractiveMeshCanvas3D
from diffeoforge.pilot_regions import BOX_VERSION, EDIT_VERSION, MAX_REGIONS, SYMPTOMS, validate
from diffeoforge.regional_fit import mask


class RegionFeedbackDialog(QDialog):
    def __init__(self, model, parent=None, *, regions=()):
        super().__init__(parent)
        self.setProperty("processRecordingPilotReview", True)
        self.setWindowTitle("Mark areas — give each point its own instruction")
        self.resize(1100, 790)
        self.regions = None
        self.region = None  # Compatibility for a caller inspecting one saved patch.
        self._rows = deepcopy(list(regions))
        self._had_rows = bool(self._rows)
        if self._rows:
            validate({"original": self._rows}, {"original": model.sha256})
        self.model = model
        self.diagonal = float(np.linalg.norm(np.ptp(model.vertices, axis=0)))
        self._centres = np.asarray(model.vertices)[np.asarray(model.triangles, int)].mean(1)
        self._loading = False
        self._move = False
        self.center = None
        layout = QVBoxLayout(self)
        intro = QLabel("Click to add A, B, C… Select a point to change only its instruction "
                       "or size. Drag to rotate; scroll to zoom. Save all areas together.")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        body = QHBoxLayout()
        layout.addLayout(body, 1)
        self.canvas = InteractiveMeshCanvas3D()
        self.canvas.pick_instruction = "Click: add another area"
        self.canvas.set_model(model)
        self.canvas.original_detail.setChecked(True)
        self.canvas.original_detail.hide()
        body.addWidget(self.canvas, 1)
        panel = QWidget()
        panel.setFixedWidth(max(340, self.fontMetrics().horizontalAdvance(
            "Retain this part's shape; allow movement") + 40))
        controls = QVBoxLayout(panel)
        body.addWidget(panel)
        controls.addWidget(QLabel("Points and instructions"))
        self.listing = QListWidget()
        self.listing.setAccessibleName("Marked points and their individual instructions")
        controls.addWidget(self.listing, 1)
        buttons = QHBoxLayout()
        self.move = QPushButton("Move selected point")
        self.move.setCheckable(True)
        self.move.toggled.connect(self._move_mode)
        buttons.addWidget(self.move)
        self.remove = QPushButton("Remove selected")
        self.remove.clicked.connect(self._remove)
        buttons.addWidget(self.remove)
        controls.addLayout(buttons)
        controls.addWidget(QLabel("Instruction for selected point"))
        self.action = QComboBox()
        self.action.setAccessibleName("Instruction for selected point")
        for key, label in SYMPTOMS.items():
            self.action.addItem(label, "problem:" + key)
        self.action.addItem("Retain this area in place", "fixed")
        self.action.addItem("Retain this part's shape; allow movement", "preserve")
        controls.addWidget(self.action)
        note = QLabel("Retain in place protects its current fitted position. Retain shape "
                      "allows movement. These are fitting instructions, not fit approval.")
        note.setWordWrap(True)
        controls.addWidget(note)
        self.shape = QComboBox()
        self.shape.setAccessibleName("Shape of selected area")
        self.shape.addItem("Surface brush", "sphere")
        self.shape.addItem("3D box", "box")
        controls.addWidget(self.shape)
        self.size = QSlider(Qt.Orientation.Horizontal)
        self.size.setRange(1, 40)
        self.size.setValue(8)
        self.size.setAccessibleName("Region radius as percentage of original extent")
        controls.addWidget(QLabel("Area size · smaller ← → larger"))
        controls.addWidget(self.size)
        self.axes = []
        for label in ["X", "Y", "Z"]:
            axis = QSlider(Qt.Orientation.Horizontal)
            axis.setRange(1, 60)
            axis.setValue(8)
            axis.setAccessibleName(label + " box half extent as percentage of original size")
            axis.setToolTip(label + " box half extent")
            controls.addWidget(axis)
            axis.valueChanged.connect(self._update)
            self.axes.append(axis)
        self.status = QLabel()
        self.status.setWordWrap(True)
        controls.addWidget(self.status)
        legend = QLabel("Orange: selected area · Yellow: other improvements · "
                        "Blue: retained areas. Letters identify point centres.")
        legend.setWordWrap(True)
        layout.addWidget(legend)
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
        self._refresh_list(0 if self._rows else -1)

    @staticmethod
    def _label(row):
        purpose = row.get("purpose", "problem")
        return ("Retain in place" if purpose == "fixed" else
                "Retain shape; allow movement" if purpose == "preserve" else
                SYMPTOMS[row["symptom"]])

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
        for control in [self.action, self.shape, self.size, *self.axes, self.move, self.remove]:
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

    def _move_mode(self, enabled):
        self._move = enabled
        self.canvas.pick_instruction = ("Click: move selected point" if enabled else
                                        "Click: add another area")

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
            self._rows.append(dict(version=EDIT_VERSION, source_sha256=self.model.sha256,
                space="original_mesh_coordinates", center=center,
                radius=self.diagonal * self.size.value() / 100,
                symptom="detail", purpose="problem"))
            index = len(self._rows) - 1
        else:
            self.status.setText("Eight areas marked. Edit or remove a point to add another.")
            return
        self._refresh_list(index)

    def _action_changed(self, *_):
        index = self.listing.currentRow()
        if self._loading or index < 0:
            return
        row = self._rows[index]
        action = self.action.currentData()
        row["purpose"] = "problem" if action.startswith("problem:") else action
        if action.startswith("problem:"):
            row["symptom"] = action.split(":", 1)[1]
        if row["version"] != BOX_VERSION:
            row["version"] = EDIT_VERSION
        self._refresh_list(index)

    def _update(self, *_):
        index = self.listing.currentRow()
        if self._loading or index < 0:
            return
        row = self._rows[index]
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
        self._render()

    def _remove(self):
        index = self.listing.currentRow()
        if index >= 0:
            self._rows.pop(index)
            self.move.setChecked(False)
            self._refresh_list(min(index, len(self._rows) - 1))

    def _render(self):
        index = self.listing.currentRow()
        boxed = self.shape.currentData() == "box"
        self.size.setVisible(not boxed)
        for axis in self.axes:
            axis.setVisible(boxed)
        counts = [int(mask(self._centres, [r]).sum()) for r in self._rows]
        self.canvas.set_surface_regions(self._rows, index if index >= 0 else None)
        self.canvas.set_markers({chr(65 + i): tuple(r["center"])
                                 for i, r in enumerate(self._rows)})
        self.save.setEnabled(bool(self._rows) and all(counts) or self._had_rows and not self._rows)
        if index >= 0:
            self.status.setText(f"{chr(65 + index)} · {counts[index]:,} original faces selected. "
                + ("Enlarge or move any empty area before saving." if not all(counts) else
                   f"{len(self._rows)} / {MAX_REGIONS} areas. Click to add another point."))
        else:
            self.status.setText("No areas yet. Click on the surface to add point A.")

    def _save(self):
        if not self.save.isEnabled():
            return
        self.regions = deepcopy(self._rows)
        self.region = self.regions[-1] if self.regions else None
        self.accept()
