"""Interactive native-Qt 3D surface canvas for anatomical landmark placement."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPaintEvent, QPen, QPolygonF, QWheelEvent
from PySide6.QtWidgets import QWidget

from diffeoforge.desktop.mesh_preview import MeshPreviewModel

INTERACTIVE_TRIANGLE_BUDGET = 5_000


@dataclass(frozen=True)
class ProjectedSurface:
    """Camera-space and screen-space geometry for one canvas state."""

    original_vertices: np.ndarray
    camera_vertices: np.ndarray
    screen_vertices: np.ndarray
    triangles: np.ndarray


def camera_rotation(yaw: float, pitch: float) -> np.ndarray:
    """Return a deterministic yaw-then-pitch rotation matrix."""

    cos_yaw, sin_yaw = math.cos(yaw), math.sin(yaw)
    cos_pitch, sin_pitch = math.cos(pitch), math.sin(pitch)
    yaw_matrix = np.array(
        ((cos_yaw, 0.0, sin_yaw), (0.0, 1.0, 0.0), (-sin_yaw, 0.0, cos_yaw)),
        dtype=np.float64,
    )
    pitch_matrix = np.array(
        ((1.0, 0.0, 0.0), (0.0, cos_pitch, -sin_pitch), (0.0, sin_pitch, cos_pitch)),
        dtype=np.float64,
    )
    return pitch_matrix @ yaw_matrix


def project_surface(
    vertices: np.ndarray,
    triangles: np.ndarray,
    *,
    center: np.ndarray,
    scale: float,
    yaw: float,
    pitch: float,
    zoom: float,
    pan: tuple[float, float],
    width: int,
    height: int,
) -> ProjectedSurface:
    """Project exact 3D geometry into one aspect-preserving orthographic viewport."""

    if vertices.ndim != 2 or vertices.shape[1] != 3:
        raise ValueError("vertices must have shape (n, 3)")
    if triangles.ndim != 2 or triangles.shape[1] != 3:
        raise ValueError("triangles must have shape (m, 3)")
    if not math.isfinite(scale) or scale <= 0:
        raise ValueError("scale must be finite and positive")
    rotation = camera_rotation(yaw, pitch)
    camera = ((vertices - center) / scale) @ rotation.T
    viewport = max(1.0, min(float(width), float(height)) - 64.0)
    factor = 0.9 * viewport * zoom
    screen = np.empty((vertices.shape[0], 2), dtype=np.float64)
    screen[:, 0] = float(width) / 2.0 + pan[0] + camera[:, 0] * factor
    screen[:, 1] = float(height) / 2.0 + pan[1] - camera[:, 1] * factor
    return ProjectedSurface(vertices, camera, screen, triangles)


def pick_surface_point(
    surface: ProjectedSurface,
    screen_position: tuple[float, float],
) -> tuple[float, float, float] | None:
    """Return the exact frontmost 3D triangle point below a screen coordinate."""

    if surface.triangles.size == 0:
        return None
    points = surface.screen_vertices[surface.triangles]
    px, py = screen_position
    x0, y0 = points[:, 0, 0], points[:, 0, 1]
    x1, y1 = points[:, 1, 0], points[:, 1, 1]
    x2, y2 = points[:, 2, 0], points[:, 2, 1]
    denominator = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
    usable = np.abs(denominator) > 1e-12
    safe_denominator = np.where(usable, denominator, 1.0)
    first = ((y1 - y2) * (px - x2) + (x2 - x1) * (py - y2)) / safe_denominator
    second = ((y2 - y0) * (px - x2) + (x0 - x2) * (py - y2)) / safe_denominator
    third = 1.0 - first - second
    tolerance = 1e-8
    inside = (
        usable
        & (first >= -tolerance)
        & (second >= -tolerance)
        & (third >= -tolerance)
    )
    candidate_indices = np.flatnonzero(inside)
    if candidate_indices.size == 0:
        return None
    depths = surface.camera_vertices[surface.triangles, 2]
    interpolated_depth = first * depths[:, 0] + second * depths[:, 1] + third * depths[:, 2]
    selected = int(candidate_indices[np.argmax(interpolated_depth[candidate_indices])])
    source_triangle = surface.original_vertices[surface.triangles[selected]]
    point = (
        first[selected] * source_triangle[0]
        + second[selected] * source_triangle[1]
        + third[selected] * source_triangle[2]
    )
    return tuple(float(value) for value in point)


class InteractiveMeshCanvas3D(QWidget):
    """Rotate, zoom, pan, and pick arbitrary points on a mesh surface."""

    surfacePointPicked = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._model: MeshPreviewModel | None = None
        self._vertices = np.empty((0, 3), dtype=np.float64)
        self._triangles = np.empty((0, 3), dtype=np.int64)
        self._center = np.zeros(3, dtype=np.float64)
        self._scale = 1.0
        self._yaw = -0.55
        self._pitch = 0.30
        self._zoom = 1.0
        self._pan = (0.0, 0.0)
        self._markers: dict[str, tuple[float, float, float]] = {}
        self._press_position: QPointF | None = None
        self._last_position: QPointF | None = None
        self._drag_button: Qt.MouseButton | None = None
        self._drag_distance = 0.0
        self._interacting = False
        self.setMinimumHeight(500)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setObjectName("interactiveLandmarkCanvas3D")

    @property
    def yaw(self) -> float:
        return self._yaw

    @property
    def pitch(self) -> float:
        return self._pitch

    @property
    def zoom(self) -> float:
        return self._zoom

    def set_model(self, model: MeshPreviewModel | None) -> None:
        self._model = model
        if model is None:
            self._vertices = np.empty((0, 3), dtype=np.float64)
            self._triangles = np.empty((0, 3), dtype=np.int64)
            self.update()
            return
        self._vertices = np.asarray(model.vertices, dtype=np.float64)
        self._triangles = np.asarray(model.triangles, dtype=np.int64)
        minimum = np.min(self._vertices, axis=0)
        maximum = np.max(self._vertices, axis=0)
        self._center = (minimum + maximum) / 2.0
        self._scale = float(np.max(maximum - minimum))
        if not math.isfinite(self._scale) or self._scale <= 0:
            self._scale = 1.0
        self.update()

    def set_markers(self, markers: dict[str, tuple[float, float, float]]) -> None:
        self._markers = dict(markers)
        self.update()

    def reset_view(self) -> None:
        self._yaw = -0.55
        self._pitch = 0.30
        self._zoom = 1.0
        self._pan = (0.0, 0.0)
        self.update()

    def set_view_preset(self, preset: str) -> None:
        presets = {
            "three-quarter": (-0.55, 0.30),
            "front": (0.0, 0.0),
            "back": (math.pi, 0.0),
            "left": (-math.pi / 2.0, 0.0),
            "right": (math.pi / 2.0, 0.0),
            "top": (0.0, -math.pi / 2.0),
            "bottom": (0.0, math.pi / 2.0),
        }
        if preset not in presets:
            raise ValueError(f"Unsupported 3D view preset: {preset!r}")
        self._yaw, self._pitch = presets[preset]
        self._pan = (0.0, 0.0)
        self.update()

    def _surface(self) -> ProjectedSurface | None:
        if self._model is None or self._vertices.size == 0:
            return None
        return project_surface(
            self._vertices,
            self._triangles,
            center=self._center,
            scale=self._scale,
            yaw=self._yaw,
            pitch=self._pitch,
            zoom=self._zoom,
            pan=self._pan,
            width=self.width(),
            height=self.height(),
        )

    def pick_at(self, position: QPointF) -> tuple[float, float, float] | None:
        """Pick a surface point; public for deterministic GUI verification."""

        surface = self._surface()
        if surface is None:
            return None
        return pick_surface_point(surface, (position.x(), position.y()))

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt API name
        if event.button() not in {
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.MiddleButton,
            Qt.MouseButton.RightButton,
        }:
            super().mousePressEvent(event)
            return
        self._press_position = event.position()
        self._last_position = event.position()
        self._drag_button = event.button()
        self._drag_distance = 0.0
        self._interacting = True
        if event.button() == Qt.MouseButton.LeftButton:
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt API name
        if self._last_position is None or self._drag_button is None:
            super().mouseMoveEvent(event)
            return
        delta = event.position() - self._last_position
        self._last_position = event.position()
        self._drag_distance += abs(delta.x()) + abs(delta.y())
        if self._drag_button == Qt.MouseButton.LeftButton:
            self._yaw += delta.x() * 0.009
            self._pitch += delta.y() * 0.009
        else:
            self._pan = (self._pan[0] + delta.x(), self._pan[1] + delta.y())
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt API name
        if event.button() != self._drag_button:
            super().mouseReleaseEvent(event)
            return
        should_pick = (
            event.button() == Qt.MouseButton.LeftButton
            and self._drag_distance <= 5.0
            and self._press_position is not None
        )
        self._press_position = None
        self._last_position = None
        self._drag_button = None
        self._interacting = False
        self.setCursor(Qt.CursorShape.CrossCursor)
        if should_pick:
            point = self.pick_at(event.position())
            if point is not None:
                self.surfacePointPicked.emit(point)

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802 - Qt API name
        delta = event.angleDelta().y()
        if delta == 0:
            return
        self._zoom = min(8.0, max(0.25, self._zoom * math.exp(delta / 900.0)))
        self.update()
        event.accept()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt API name
        if event.button() == Qt.MouseButton.LeftButton:
            self.reset_view()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 - Qt API name
        del event
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#f7f9f9"))
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        surface = self._surface()
        if surface is None:
            painter.setPen(QColor("#64777c"))
            painter.drawText(
                self.rect().adjusted(20, 20, -20, -20),
                Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                "No mesh has been loaded.",
            )
            painter.end()
            return

        triangles = surface.triangles
        if self._interacting and len(triangles) > INTERACTIVE_TRIANGLE_BUDGET:
            selection = np.linspace(
                0,
                len(triangles) - 1,
                INTERACTIVE_TRIANGLE_BUDGET,
                dtype=np.int64,
            )
            triangles = triangles[selection]
        camera_triangles = surface.camera_vertices[triangles]
        normals = np.cross(
            camera_triangles[:, 1] - camera_triangles[:, 0],
            camera_triangles[:, 2] - camera_triangles[:, 0],
        )
        normal_lengths = np.linalg.norm(normals, axis=1)
        light = np.abs(normals[:, 2]) / np.maximum(normal_lengths, 1e-12)
        depth = np.mean(camera_triangles[:, :, 2], axis=1)
        for triangle_index in np.argsort(depth):
            coordinates = surface.screen_vertices[triangles[triangle_index]]
            polygon = QPolygonF([QPointF(float(x), float(y)) for x, y in coordinates])
            shade = int(198 + 38 * float(light[triangle_index]))
            painter.setBrush(QColor(max(0, shade - 38), shade, max(0, shade - 16), 235))
            painter.setPen(QPen(QColor("#6e9992"), 0.35))
            painter.drawPolygon(polygon)

        rotation = camera_rotation(self._yaw, self._pitch)
        viewport = max(1.0, min(float(self.width()), float(self.height())) - 64.0)
        factor = 0.9 * viewport * self._zoom
        for marker_number, (label, value) in enumerate(self._markers.items(), start=1):
            normalized = (np.asarray(value, dtype=np.float64) - self._center) / self._scale
            camera = normalized @ rotation.T
            rendered = QPointF(
                self.width() / 2.0 + self._pan[0] + float(camera[0]) * factor,
                self.height() / 2.0 + self._pan[1] - float(camera[1]) * factor,
            )
            painter.setPen(QPen(QColor("#ffffff"), 2.0))
            painter.setBrush(QColor("#d9481c"))
            painter.drawEllipse(rendered, 6.5, 6.5)
            painter.setPen(QPen(QColor("#702109"), 1.0))
            painter.drawText(rendered + QPointF(9.0, -9.0), f"{marker_number}: {label}")

        painter.setPen(QColor("#52666b"))
        painter.drawText(
            self.rect().adjusted(14, 10, -14, -10),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom,
            "Click: place/replace landmark  ·  Drag: rotate  ·  Right-drag: pan  ·  "
            "Wheel: zoom  ·  Double-click: reset view",
        )
        painter.end()
