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
from diffeoforge.pilot_regions import SYMPTOMS, VERSION, face_mask


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
        self.symptom = QComboBox()
        for key, label in SYMPTOMS.items():
            self.symptom.addItem(label, key)
        layout.addWidget(self.symptom)
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
        self.finished.connect(self.canvas.cancel_pending_pick)

    def _picked(self, point):
        self.center = tuple(float(v) for v in point)
        self._update()

    def _update(self, *_):
        if self.center is None:
            return
        radius = self.diagonal * self.size.value() / 100
        count = int(face_mask(self.model.vertices, self.model.triangles, self.center, radius).sum())
        self.canvas.set_surface_region(self.center, radius)
        self.canvas.set_markers({"Area centre": self.center})
        self.status.setText(
            f"{count:,} original faces selected · radius {self.size.value()}% of extent. "
            "The area is used to guide tests; the whole shape remains fitted."
        )
        self.save.setEnabled(count > 0)

    def _save(self):
        if self.center is None or not self.save.isEnabled():
            return
        self.region = dict(
            version=VERSION,
            source_sha256=self.model.sha256,
            space="original_mesh_coordinates",
            center=list(self.center),
            radius=self.diagonal * self.size.value() / 100,
            symptom=self.symptom.currentData(),
        )
        self.accept()
