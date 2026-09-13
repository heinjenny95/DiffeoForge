"""Interactive original-versus-reconstruction overlay for calibration QC."""

from __future__ import annotations

import math

import numpy as np
from PySide6.QtCore import QPointF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QWheelEvent,
)
from PySide6.QtWidgets import QWidget

from diffeoforge.desktop.landmark_3d_widget import camera_rotation
from diffeoforge.desktop.mesh_preview import MeshPreviewModel
from diffeoforge.desktop.surface_rendering import SurfaceFrameCache, SurfaceLayer, SurfaceScene


class CalibrationComparisonCanvas3D(QWidget):
    """Render an original mesh and its reconstruction in one shared 3D view."""

    fullResolutionReadyChanged = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._original: MeshPreviewModel | None = None
        self._reconstruction: MeshPreviewModel | None = None
        self._original_vertices = np.empty((0, 3), dtype=np.float64)
        self._reconstruction_vertices = np.empty((0, 3), dtype=np.float64)
        self._reconstruction_triangles = np.empty((0, 3), dtype=np.int64)
        self._original_edges = np.empty((0, 2), dtype=np.int64)
        self._frames = SurfaceFrameCache(self)
        self._frames.changed.connect(self.update)
        self._presented_key: tuple | None = None
        self._wheel_timer = QTimer(self)
        self._wheel_timer.setSingleShot(True)
        self._wheel_timer.setInterval(160)
        self._wheel_timer.timeout.connect(self._settle_wheel)
        self._center = np.zeros(3, dtype=np.float64)
        self._scale = 1.0
        self._yaw = -0.55
        self._pitch = 0.30
        self._zoom = 1.0
        self._pan = (0.0, 0.0)
        self._show_original = True
        self._show_reconstruction = True
        self._last_position: QPointF | None = None
        self._drag_button: Qt.MouseButton | None = None
        self._interacting = False
        self.setMinimumHeight(420)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setObjectName("calibrationComparisonCanvas3D")
        self.setAccessibleName(
            "Interactive overlay of original pilot mesh and Deformetrica reconstruction"
        )

    @property
    def original_model(self) -> MeshPreviewModel | None:
        return self._original

    @property
    def reconstruction_model(self) -> MeshPreviewModel | None:
        return self._reconstruction

    def set_models(
        self,
        original: MeshPreviewModel,
        reconstruction: MeshPreviewModel,
    ) -> None:
        """Bind both immutable meshes to a shared camera and viewport."""

        self._original = original
        self._reconstruction = reconstruction
        self._frames.clear()
        self._presented_key = None
        self._original_vertices = np.asarray(original.vertices, dtype=np.float64)
        self._reconstruction_vertices = np.asarray(
            reconstruction.vertices,
            dtype=np.float64,
        )
        self._reconstruction_triangles = np.asarray(
            reconstruction.triangles,
            dtype=np.int64,
        )
        self._original_edges = np.asarray(original.edges, dtype=np.int64)
        combined = np.vstack(
            (self._original_vertices, self._reconstruction_vertices)
        )
        minimum = np.min(combined, axis=0)
        maximum = np.max(combined, axis=0)
        self._center = (minimum + maximum) / 2.0
        self._scale = float(np.max(maximum - minimum))
        if not math.isfinite(self._scale) or self._scale <= 0:
            raise ValueError("Comparison meshes must have positive finite extent")
        self.update()

    def clear(self) -> None:
        """Release the previous pair immediately; it cannot stand in for a new case."""
        self._original = self._reconstruction = None
        self._original_vertices = np.empty((0, 3), dtype=np.float64)
        self._reconstruction_vertices = np.empty((0, 3), dtype=np.float64)
        self._reconstruction_triangles = np.empty((0, 3), dtype=np.int64)
        self._original_edges = np.empty((0, 2), dtype=np.int64)
        self._frames.clear()
        self._presented_key = None
        self.update()

    def _frame_key(self) -> tuple:
        return (id(self._original), id(self._reconstruction), self.width(), self.height(),
                self._yaw, self._pitch, self._zoom, self._pan,
                self._show_original, self._show_reconstruction,
                self._interacting or self._wheel_timer.isActive())

    @property
    def full_resolution_ready(self) -> bool:
        key = self._frame_key()
        return bool(self._original is not None and self._show_original
                    and self._show_reconstruction and not key[-1]
                    and self._presented_key == key and self._frames.ready(key))

    def _settle_wheel(self) -> None:
        self.update()

    def set_show_original(self, visible: bool) -> None:
        self._show_original = bool(visible)
        self.update()

    def set_show_reconstruction(self, visible: bool) -> None:
        self._show_reconstruction = bool(visible)
        self.update()

    def reset_view(self) -> None:
        self._yaw = -0.55
        self._pitch = 0.30
        self._zoom = 1.0
        self._pan = (0.0, 0.0)
        self.update()

    def set_view_preset(self, preset: str) -> None:
        """Apply the same named orthographic orientations used by result viewers."""

        orientations = {
            "three-quarter": (-0.55, 0.30),
            "front": (0.0, 0.0),
            "back": (math.pi, 0.0),
            "left": (-math.pi / 2.0, 0.0),
            "right": (math.pi / 2.0, 0.0),
            "top": (0.0, -math.pi / 2.0),
            "bottom": (0.0, math.pi / 2.0),
        }
        if preset not in orientations:
            raise ValueError(f"Unknown comparison view preset: {preset!r}")
        self._yaw, self._pitch = orientations[preset]
        self._zoom = 1.0
        self._pan = (0.0, 0.0)
        self.update()

    def _project(self, vertices: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        rotation = camera_rotation(self._yaw, self._pitch)
        camera = ((vertices - self._center) / self._scale) @ rotation.T
        viewport = max(1.0, min(float(self.width()), float(self.height())) - 72.0)
        factor = 0.9 * viewport * self._zoom
        screen = np.empty((vertices.shape[0], 2), dtype=np.float64)
        screen[:, 0] = self.width() / 2.0 + self._pan[0] + camera[:, 0] * factor
        screen[:, 1] = self.height() / 2.0 + self._pan[1] - camera[:, 1] * factor
        return camera, screen

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() not in {
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.MiddleButton,
            Qt.MouseButton.RightButton,
        }:
            super().mousePressEvent(event)
            return
        self._last_position = event.position()
        self._drag_button = event.button()
        self._interacting = True
        self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._last_position is None or self._drag_button is None:
            super().mouseMoveEvent(event)
            return
        delta = event.position() - self._last_position
        self._last_position = event.position()
        if self._drag_button == Qt.MouseButton.LeftButton:
            self._yaw += delta.x() * 0.009
            self._pitch += delta.y() * 0.009
        else:
            self._pan = (self._pan[0] + delta.x(), self._pan[1] + delta.y())
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != self._drag_button:
            super().mouseReleaseEvent(event)
            return
        self._last_position = None
        self._drag_button = None
        self._interacting = False
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.update()
        event.accept()

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        delta = event.angleDelta().y()
        if delta:
            self._zoom = min(8.0, max(0.25, self._zoom * math.exp(delta / 900.0)))
            self._wheel_timer.start()
            self.update()
            event.accept()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.reset_view()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#f7f9f9"))
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if self._original is None or self._reconstruction is None:
            painter.setPen(QColor("#64777c"))
            painter.drawText(
                self.rect().adjusted(20, 20, -20, -20),
                Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                "Choose a comparison to load both meshes.",
            )
            painter.end()
            return
        key = self._frame_key()
        layers = []
        if self._show_reconstruction:
            layers.append(SurfaceLayer(self._reconstruction_vertices,
                                       self._reconstruction_triangles, orange=True))
        if self._show_original:
            layers.append(SurfaceLayer(self._original_vertices, self._original_edges,
                                       wireframe=True))
        scene = SurfaceScene(self.width(), self.height(), self._center, self._scale,
                             camera_rotation(self._yaw, self._pitch), self._zoom,
                             self._pan, tuple(layers), navigation=key[-1])
        image = self._frames.request(key, scene)
        if image is not None:
            painter.drawImage(0, 0, image)
        presented = key if self._frames.ready(key) and not scene.navigation else None
        if presented != self._presented_key:
            self._presented_key = presented
            self.fullResolutionReadyChanged.emit()
        if presented is None:
            painter.fillRect(0, 0, self.width(), 34, QColor("#fff3d6"))
            painter.setPen(QColor("#705419"))
            painter.drawText(12, 23, self._frames.error or (
                "Navigation preview — full-resolution QC view follows after movement."
                if scene.navigation else "Rendering full-resolution view in background…"
            ))
        elif not self._show_original or not self._show_reconstruction:
            painter.setPen(QColor("#705419"))
            painter.drawText(12, 23, "Show both layers before confirming the QC inspection.")
        painter.end()
