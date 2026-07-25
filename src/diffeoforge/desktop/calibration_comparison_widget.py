"""Interactive original-versus-reconstruction overlay for calibration QC."""

from __future__ import annotations

import math

import numpy as np
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import (
    QColor,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
    QPolygonF,
    QWheelEvent,
)
from PySide6.QtWidgets import QWidget

from diffeoforge.desktop.landmark_3d_widget import (
    INTERACTIVE_TRIANGLE_BUDGET,
    camera_rotation,
)
from diffeoforge.desktop.mesh_preview import MeshPreviewModel


class CalibrationComparisonCanvas3D(QWidget):
    """Render an original mesh and its reconstruction in one shared 3D view."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._original: MeshPreviewModel | None = None
        self._reconstruction: MeshPreviewModel | None = None
        self._original_vertices = np.empty((0, 3), dtype=np.float64)
        self._reconstruction_vertices = np.empty((0, 3), dtype=np.float64)
        self._reconstruction_triangles = np.empty((0, 3), dtype=np.int64)
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
        self.setMinimumHeight(560)
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
        self._original_vertices = np.asarray(original.vertices, dtype=np.float64)
        self._reconstruction_vertices = np.asarray(
            reconstruction.vertices,
            dtype=np.float64,
        )
        self._reconstruction_triangles = np.asarray(
            reconstruction.triangles,
            dtype=np.int64,
        )
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
            self.update()
            event.accept()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.reset_view()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def _draw_reconstruction(self, painter: QPainter) -> None:
        if not self._show_reconstruction or self._reconstruction is None:
            return
        camera, screen = self._project(self._reconstruction_vertices)
        triangles = self._reconstruction_triangles
        if self._interacting and len(triangles) > INTERACTIVE_TRIANGLE_BUDGET:
            selection = np.linspace(
                0,
                len(triangles) - 1,
                INTERACTIVE_TRIANGLE_BUDGET,
                dtype=np.int64,
            )
            triangles = triangles[selection]
        camera_triangles = camera[triangles]
        normals = np.cross(
            camera_triangles[:, 1] - camera_triangles[:, 0],
            camera_triangles[:, 2] - camera_triangles[:, 0],
        )
        lengths = np.linalg.norm(normals, axis=1)
        light = np.abs(normals[:, 2]) / np.maximum(lengths, 1e-12)
        depth = np.mean(camera_triangles[:, :, 2], axis=1)
        for triangle_index in np.argsort(depth):
            coordinates = screen[triangles[triangle_index]]
            polygon = QPolygonF(
                [QPointF(float(x), float(y)) for x, y in coordinates]
            )
            shade = int(218 + 27 * float(light[triangle_index]))
            painter.setBrush(QColor(242, max(150, shade - 42), 116, 190))
            painter.setPen(QPen(QColor(193, 87, 42, 105), 0.30))
            painter.drawPolygon(polygon)

    def _draw_original(self, painter: QPainter) -> None:
        if not self._show_original or self._original is None:
            return
        _camera, screen = self._project(self._original_vertices)
        edges = self._original.edges
        if self._interacting and len(edges) > 20_000:
            indices = np.linspace(0, len(edges) - 1, 20_000, dtype=np.int64)
            edges = tuple(edges[int(index)] for index in indices)
        path = QPainterPath()
        for start, end in edges:
            first = screen[start]
            second = screen[end]
            path.moveTo(float(first[0]), float(first[1]))
            path.lineTo(float(second[0]), float(second[1]))
        painter.setPen(QPen(QColor(17, 94, 163, 220), 1.05))
        painter.drawPath(path)

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
        self._draw_reconstruction(painter)
        self._draw_original(painter)
        painter.setPen(QColor("#52666b"))
        painter.drawText(
            self.rect().adjusted(14, 10, -14, -10),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom,
            "Drag: rotate  |  Right-drag: pan  |  Wheel: zoom  |  "
            "Double-click: reset view",
        )
        painter.end()
