"""Interactive two-point ruler for declaring an anatomical feature scale."""

from __future__ import annotations

import math

import numpy as np
from PySide6.QtCore import Slot
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from diffeoforge.desktop.landmark_3d_widget import InteractiveMeshCanvas3D
from diffeoforge.desktop.mesh_preview import MeshPreviewModel


class FeatureScaleRulerDialog(QDialog):
    """Measure an explicit Euclidean feature scale on the selected template."""

    def __init__(
        self,
        model: MeshPreviewModel,
        *,
        coordinate_unit: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Measure the smallest relevant anatomical feature")
        self.resize(980, 760)
        self._coordinate_unit = coordinate_unit
        self._points: list[tuple[float, float, float]] = []
        self._distance: float | None = None

        layout = QVBoxLayout(self)
        title = QLabel("Two-point anatomical feature ruler")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        explanation = QLabel(
            "Click two homologously interpretable endpoints on the template. The "
            "distance records the smallest anatomical feature that the surface metric "
            "should attempt to preserve. Rotate with left-drag, pan with right-drag, "
            "and zoom with the wheel. This is a researcher decision, not an automatic "
            "measurement of biological importance."
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)

        preset_row = QHBoxLayout()
        for label, preset in (
            ("Three-quarter", "three-quarter"),
            ("Front", "front"),
            ("Left", "left"),
            ("Top", "top"),
        ):
            button = QPushButton(label)
            button.setObjectName("secondary")
            button.clicked.connect(
                lambda _checked=False, selected=preset: self.canvas.set_view_preset(
                    selected
                )
            )
            preset_row.addWidget(button)
        preset_row.addStretch()
        layout.addLayout(preset_row)

        self.canvas = InteractiveMeshCanvas3D()
        self.canvas.setObjectName("featureScaleRulerCanvas")
        self.canvas.set_model(model)
        self.canvas.set_picking_enabled(True)
        self.canvas.surfacePointPicked.connect(self.record_point)
        layout.addWidget(self.canvas, 1)

        self.status_label = QLabel("Click the first endpoint.")
        self.status_label.setObjectName("status")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        button_row = QHBoxLayout()
        clear_button = QPushButton("Clear measurement")
        clear_button.setObjectName("secondary")
        clear_button.clicked.connect(self.clear_measurement)
        cancel_button = QPushButton("Cancel")
        cancel_button.setObjectName("secondary")
        cancel_button.clicked.connect(self.reject)
        self.use_button = QPushButton("Use measured distance")
        self.use_button.setObjectName("primary")
        self.use_button.setEnabled(False)
        self.use_button.clicked.connect(self.accept)
        button_row.addWidget(clear_button)
        button_row.addStretch()
        button_row.addWidget(cancel_button)
        button_row.addWidget(self.use_button)
        layout.addLayout(button_row)

    @property
    def measured_distance(self) -> float | None:
        return self._distance

    @Slot(object)
    def record_point(self, point: object) -> None:
        values = tuple(float(value) for value in point)  # type: ignore[arg-type]
        if len(values) != 3 or not all(math.isfinite(value) for value in values):
            return
        if len(self._points) == 2:
            self._points = []
        self._points.append(values)
        if len(self._points) == 1:
            self._distance = None
            self.canvas.set_markers({"A": values})
            self.status_label.setText("First endpoint recorded. Click the second endpoint.")
            self.use_button.setEnabled(False)
            return
        first = np.asarray(self._points[0], dtype=np.float64)
        second = np.asarray(self._points[1], dtype=np.float64)
        distance = float(np.linalg.norm(second - first))
        self.canvas.set_markers({"A": self._points[0], "B": self._points[1]})
        if not math.isfinite(distance) or distance <= 0:
            self._distance = None
            self.status_label.setText(
                "The endpoints coincide. Click a new first endpoint to measure again."
            )
            self.use_button.setEnabled(False)
            return
        self._distance = distance
        suffix = (
            ""
            if self._coordinate_unit == "unitless"
            else f" {self._coordinate_unit}"
        )
        self.status_label.setText(
            f"Measured feature scale: {distance:.8g}{suffix}. "
            "Click again to start a new measurement, or use this distance."
        )
        self.use_button.setEnabled(True)

    @Slot()
    def clear_measurement(self) -> None:
        self._points = []
        self._distance = None
        self.canvas.set_markers({})
        self.status_label.setText("Click the first endpoint.")
        self.use_button.setEnabled(False)
