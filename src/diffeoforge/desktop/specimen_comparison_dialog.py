"""Read-only side-by-side inspection of a verified atlas specimen."""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from diffeoforge.desktop.calibration_comparison_widget import CalibrationComparisonCanvas3D
from diffeoforge.desktop.display_proxy import DEFAULT_DISPLAY_FACES
from diffeoforge.desktop.result_mesh_loader import ResultMeshLoader
from diffeoforge.desktop.result_review import ModernResultReview


def _pca_orientation(view) -> tuple | None:
    if view is None:
        return None
    try:
        _, direction, up = view
        direction = np.asarray(direction, dtype=np.float64)
        up = np.asarray(up, dtype=np.float64)
        if direction.shape != (3,) or up.shape != (3,) or not np.isfinite([direction, up]).all():
            return None
        length = np.linalg.norm(direction)
        if length <= 1e-12:
            return None
        direction = direction / length
        right = np.cross(up, direction)
        length = np.linalg.norm(right)
        if length <= 1e-12:
            return None
        right /= length
        return tuple(map(tuple, (right, np.cross(direction, right), direction)))
    except (TypeError, ValueError):
        return None


class SpecimenComparisonDialog(QDialog):
    """Inspect the supplied original and reconstruction with one shared camera."""

    def __init__(
        self, review: ModernResultReview, subject_name: str, parent=None, *, pca_view=None
    ) -> None:
        super().__init__(parent)
        self._review = review
        self._key = f"registration-qc:{subject_name}"
        self._pca_orientation = _pca_orientation(pca_view)
        self.setWindowTitle("Original and reconstruction")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.resize(1080, 600)
        layout = QVBoxLayout(self)
        specimen = QLabel(subject_name)
        specimen.setObjectName("sectionTitle")
        specimen.setTextFormat(Qt.TextFormat.PlainText)
        specimen.setWordWrap(True)
        layout.addWidget(specimen)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("View"))
        self.preset = QComboBox()
        self.preset.setAccessibleName("Shared orientation")
        if self._pca_orientation is not None:
            self.preset.addItem("PCA view", "pca")
        for view in ("front", "back", "left", "right", "top", "bottom", "three-quarter"):
            self.preset.addItem(view.capitalize(), view)
        controls.addWidget(self.preset)
        self.reset_button = QPushButton("Reset view")
        controls.addWidget(self.reset_button)
        controls.addStretch()
        layout.addLayout(controls)

        views = QHBoxLayout()
        self.original_canvas = CalibrationComparisonCanvas3D(show_inspection_hints=False)
        self.reconstruction_canvas = CalibrationComparisonCanvas3D(show_inspection_hints=False)
        self.original_canvas.set_show_reconstruction(False)
        self.original_canvas.set_original_wireframe(False)
        self.reconstruction_canvas.set_show_original(False)
        for label, canvas in (
            ("Original in atlas coordinates", self.original_canvas),
            ("Atlas reconstruction", self.reconstruction_canvas),
        ):
            panel = QVBoxLayout()
            panel.addWidget(QLabel(label))
            canvas.setAccessibleName(label)
            canvas.setMinimumHeight(310)
            canvas.original_detail.hide()
            panel.addWidget(canvas, 1)
            views.addLayout(panel, 1)
        layout.addLayout(views, 1)
        self.original_canvas.cameraChanged.connect(self.reconstruction_canvas.set_linked_camera)
        self.reconstruction_canvas.cameraChanged.connect(self.original_canvas.set_linked_camera)
        self.preset.currentIndexChanged.connect(self._apply_preset)
        self.reset_button.clicked.connect(self._reset_view)
        self.preset.setEnabled(False)
        self.reset_button.setEnabled(False)

        self.status = QLabel("Verifying and loading both surfaces…")
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._loader = ResultMeshLoader(self, triangle_budget=DEFAULT_DISPLAY_FACES)
        self._loader.loaded.connect(self._loaded)
        self._loader.failed.connect(self._failed)
        self.finished.connect(self._close_views)
        self._loader.request(review, self._key)

    def _close_views(self) -> None:
        self._loader.cancel()
        self.original_canvas.clear()
        self.reconstruction_canvas.clear()

    def _apply_preset(self) -> None:
        preset = self.preset.currentData()
        if preset == "pca":
            self.original_canvas.set_base_orientation(self._pca_orientation)
        else:
            self.original_canvas.set_view_preset(preset)

    def _reset_view(self) -> None:
        self.preset.setCurrentIndex(0)
        self._apply_preset()

    def _loaded(self, review, key, models) -> None:
        if review is not self._review or key != self._key:
            return
        try:
            original, reconstruction = models
            bounds = np.asarray((original.bounds, reconstruction.bounds)).reshape(2, 3, 2)
            low, high = bounds[:, :, 0].min(axis=0), bounds[:, :, 1].max(axis=0)
            for canvas in (self.original_canvas, self.reconstruction_canvas):
                canvas.set_models(original, reconstruction)
                canvas.set_comparison_extent((low + high) / 2, float(np.max(high - low)))
        except (AttributeError, TypeError, ValueError) as error:
            self._failed(review, key, str(error))
            return
        self.preset.setEnabled(True)
        self.reset_button.setEnabled(True)
        self._apply_preset()
        proxy = " · Display preview" if any(model.geometry_is_proxy for model in models) else ""
        self.status.setText(f"Shared rotation, pan and zoom{proxy}")

    def _failed(self, review, key, error: str) -> None:
        if review is not self._review or key != self._key:
            return
        self.original_canvas.clear()
        self.reconstruction_canvas.clear()
        self.preset.setEnabled(False)
        self.reset_button.setEnabled(False)
        self.status.setText(f"Comparison could not be loaded. {error}")
