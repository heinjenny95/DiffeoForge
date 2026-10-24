"""An explicit, rotatable 3D surface brush; no scientific job is dispatched."""

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
)

from diffeoforge.desktop.landmark_3d_widget import InteractiveMeshCanvas3D
from diffeoforge.pilot_regions import BOX_VERSION, EDIT_VERSION, SYMPTOMS, face_mask


class RegionFeedbackDialog(QDialog):
    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.setProperty("processRecordingPilotReview", True)
        self.setWindowTitle("Show where the fit needs improvement")
        self.resize(800, 760)
        self.region = None
        self.center = None
        self.model = model
        self.diagonal = float(np.linalg.norm(np.ptp(model.vertices, axis=0)))
        layout = QVBoxLayout(self)
        help_text = QLabel(
            "Click the original, adjust the highlighted area, then rotate to check it."
        )
        help_text.setWordWrap(True)
        layout.addWidget(help_text)
        self.canvas = InteractiveMeshCanvas3D()
        self.canvas.pick_instruction = "Click: select area centre"
        self.canvas.set_model(model)
        # Exact original-face selection; navigation may still use a temporary proxy.
        self.canvas.original_detail.setChecked(True)
        self.canvas.original_detail.hide()
        layout.addWidget(self.canvas, 1)
        self.size = QSlider(Qt.Orientation.Horizontal)
        self.size.setRange(1, 40)
        self.size.setValue(8)
        self.size.setAccessibleName("Region radius as percentage of original extent")
        row = QHBoxLayout()
        row.addWidget(QLabel("Smaller area"))
        row.addWidget(self.size, 1)
        row.addWidget(QLabel("Larger area"))
        layout.addLayout(row)
        self.shape = QComboBox()
        self.shape.setAccessibleName("Shape of problem area")
        self.shape.addItem("Surface brush", "sphere")
        self.shape.addItem("3D box", "box")
        layout.addWidget(self.shape)
        self.axes = []
        for label in ["X", "Y", "Z"]:
            axis = QSlider(Qt.Orientation.Horizontal)
            axis.setRange(1, 60)
            axis.setValue(8)
            axis.setAccessibleName(label + " box half extent as percentage of original size")
            axis.setToolTip(label + " half extent")
            axis.hide()
            layout.addWidget(axis)
            axis.valueChanged.connect(self._update)
            self.axes.append(axis)
        self.symptom = QComboBox()
        for key, label in SYMPTOMS.items():
            self.symptom.addItem(label, key)
        layout.addWidget(self.symptom)
        self.purpose = QComboBox()
        self.purpose.setAccessibleName("How this area should influence fitting")
        self.purpose.addItem("Improve this area", "problem")
        self.purpose.addItem("Preserve this part's shape while moving it", "preserve")
        self.purpose.addItem("Keep this already good area in place", "fixed")
        layout.addWidget(self.purpose)
        self.status = QLabel("No area selected")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        controls = QHBoxLayout()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        controls.addWidget(cancel)
        self.save = QPushButton("Keep this problem area")
        self.save.setObjectName("primary")
        self.save.setEnabled(False)
        self.save.clicked.connect(self._save)
        controls.addWidget(self.save)
        layout.addLayout(controls)
        self.canvas.surfacePointPicked.connect(self._picked)
        self.size.valueChanged.connect(self._update)
        self.shape.currentIndexChanged.connect(self._update)
        self.finished.connect(self.canvas.cancel_pending_pick)

    def _picked(self, point):
        self.center = tuple(float(v) for v in point)
        self._update()

    def _update(self, *_):
        boxed = self.shape.currentData() == "box"
        for axis in self.axes:
            axis.setVisible(boxed)
        self.size.setVisible(not boxed)
        if self.center is None:
            return
        radius = self.diagonal * self.size.value() / 100
        if boxed:
            half = self.diagonal * np.array([x.value() for x in self.axes]) / 100
            self.bounds = np.column_stack((np.asarray(self.center) - half,
                                           np.asarray(self.center) + half)).ravel().tolist()
            from diffeoforge.regional_fit import mask

            count = int(mask(np.asarray(self.model.vertices)[
                np.asarray(self.model.triangles, int)].mean(1),
                             [dict(shape="box", bounds=self.bounds)]).sum())
            self.canvas.set_surface_box(self.bounds)
        else:
            count = int(face_mask(self.model.vertices, self.model.triangles,
                                  self.center, radius).sum())
            self.canvas.set_surface_region(self.center, radius)
        self.canvas.set_markers({"Area centre": self.center})
        self.status.setText(
            f"{count:,} original faces selected · "
            + ("3D box. " if boxed else f"radius {self.size.value()}% of extent. ")
            + "Keep this area, then add other problem or protected areas as needed."
        )
        self.save.setEnabled(count > 0)

    def _save(self):
        if self.center is None or not self.save.isEnabled():
            return
        self.region = dict(
            version=EDIT_VERSION,
            source_sha256=self.model.sha256,
            space="original_mesh_coordinates",
            center=list(self.center),
            radius=self.diagonal * self.size.value() / 100,
            symptom=self.symptom.currentData(),
            purpose=self.purpose.currentData(),
        )
        if self.shape.currentData() == "box":
            self.region.update(version=BOX_VERSION, shape="box", bounds=self.bounds,
                radius=float(np.linalg.norm(np.asarray(self.bounds).reshape(3, 2)[:, 1]
                                            - np.asarray(self.bounds).reshape(3, 2)[:, 0]) / 2))
        self.accept()
