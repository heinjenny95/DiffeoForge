"""Interactive native-Qt canvas for visual GPA cohort review."""

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

from diffeoforge.desktop.gpa_visualization import GpaAlignmentVisual
from diffeoforge.desktop.landmark_3d_widget import (
    INTERACTIVE_TRIANGLE_BUDGET,
    camera_rotation,
)
from diffeoforge.desktop.mesh_preview import MeshPreviewModel


class GpaAlignmentCanvas3D(QWidget):
    """Render an equal-weight, color-separated overlay of every aligned mesh."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._visual: GpaAlignmentVisual | None = None
        self._detail: MeshPreviewModel | None = None
        self._detail_vertices = np.empty((0, 3), dtype=np.float64)
        self._detail_triangles = np.empty((0, 3), dtype=np.int64)
        self._selected_index = 0
        self._show_cohort = True
        self._show_selected_surface = False
        self._show_landmarks = True
        self._center = np.zeros(3, dtype=np.float64)
        self._scale = 1.0
        self._yaw = -0.55
        self._pitch = 0.30
        self._zoom = 1.0
        self._pan = (0.0, 0.0)
        self._press_position: QPointF | None = None
        self._last_position: QPointF | None = None
        self._drag_button: Qt.MouseButton | None = None
        self._interacting = False
        self.setMinimumHeight(580)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setObjectName("gpaAlignmentCanvas3D")
        self.setAccessibleName("Interactive visual review of GPA-aligned meshes")

    @property
    def selected_index(self) -> int:
        return self._selected_index

    @property
    def show_cohort(self) -> bool:
        return self._show_cohort

    @property
    def show_landmarks(self) -> bool:
        return self._show_landmarks

    @property
    def show_selected_surface(self) -> bool:
        return self._show_selected_surface

    def set_visual(self, visual: GpaAlignmentVisual) -> None:
        self._visual = visual
        x_min, x_max, y_min, y_max, z_min, z_max = visual.bounds
        self._center = np.asarray(
            (
                (x_min + x_max) / 2.0,
                (y_min + y_max) / 2.0,
                (z_min + z_max) / 2.0,
            ),
            dtype=np.float64,
        )
        self._scale = max(x_max - x_min, y_max - y_min, z_max - z_min)
        if not math.isfinite(self._scale) or self._scale <= 0:
            raise ValueError("GPA visual bounds must have positive finite extent")
        self.update()

    def set_selected_detail(
        self,
        index: int,
        detail: MeshPreviewModel,
    ) -> None:
        if self._visual is None:
            raise RuntimeError("Set the GPA visual before selecting a mesh")
        if index < 0 or index >= len(self._visual.meshes):
            raise IndexError("Selected GPA mesh is outside the cohort")
        self._selected_index = index
        self._detail = detail
        self._detail_vertices = np.asarray(detail.vertices, dtype=np.float64)
        self._detail_triangles = np.asarray(detail.triangles, dtype=np.int64)
        self.update()

    def set_show_cohort(self, visible: bool) -> None:
        self._show_cohort = bool(visible)
        self.update()

    def set_show_selected_surface(self, visible: bool) -> None:
        self._show_selected_surface = bool(visible)
        self.update()

    def set_show_landmarks(self, visible: bool) -> None:
        self._show_landmarks = bool(visible)
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
        self._press_position = event.position()
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
        self._press_position = None
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

    def _draw_selected_surface(self, painter: QPainter) -> None:
        if self._detail_vertices.size == 0 or self._detail_triangles.size == 0:
            return
        camera, screen = self._project(self._detail_vertices)
        triangles = self._detail_triangles
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
        normal_lengths = np.linalg.norm(normals, axis=1)
        light = np.abs(normals[:, 2]) / np.maximum(normal_lengths, 1e-12)
        depth = np.mean(camera_triangles[:, :, 2], axis=1)
        for triangle_index in np.argsort(depth):
            coordinates = screen[triangles[triangle_index]]
            polygon = QPolygonF(
                [QPointF(float(x), float(y)) for x, y in coordinates]
            )
            shade = int(205 + 32 * float(light[triangle_index]))
            painter.setBrush(QColor(shade - 34, shade, shade - 12, 220))
            painter.setPen(QPen(QColor(87, 137, 128, 120), 0.30))
            painter.drawPolygon(polygon)

    def _draw_wireframes(self, painter: QPainter) -> None:
        if self._visual is None:
            return
        indices = (
            range(len(self._visual.meshes))
            if self._show_cohort
            else (self._selected_index,)
        )
        for index in indices:
            mesh = self._visual.meshes[index]
            _camera, screen = self._project(mesh.vertices)
            path = QPainterPath()
            for start, end in mesh.edges:
                first = screen[start]
                second = screen[end]
                path.moveTo(float(first[0]), float(first[1]))
                path.lineTo(float(second[0]), float(second[1]))
            selected = index == self._selected_index
            painter.setPen(
                QPen(
                    cohort_overlay_color(
                        index,
                        len(self._visual.meshes),
                        selected=selected,
                    ),
                    1.35 if selected else 0.85,
                )
            )
            painter.drawPath(path)

    def _draw_landmarks(self, painter: QPainter) -> None:
        if self._visual is None or not self._show_landmarks:
            return
        if self._show_cohort:
            painter.setPen(Qt.PenStyle.NoPen)
            for index, mesh in enumerate(self._visual.meshes):
                painter.setBrush(
                    cohort_overlay_color(
                        index,
                        len(self._visual.meshes),
                        selected=False,
                    )
                )
                _camera, points = self._project(mesh.landmarks)
                for x, y in points:
                    painter.drawEllipse(QPointF(float(x), float(y)), 2.2, 2.2)

        selected = self._visual.meshes[self._selected_index]
        _camera, selected_points = self._project(selected.landmarks)
        painter.setPen(QPen(QColor("#ffffff"), 1.2))
        painter.setBrush(QColor("#d9481c"))
        for x, y in selected_points:
            painter.drawEllipse(QPointF(float(x), float(y)), 5.0, 5.0)

        _camera, mean_points = self._project(self._visual.mean_landmarks)
        painter.setPen(QPen(QColor("#0b302f"), 1.5))
        painter.setBrush(QColor("#54c6a1"))
        for label, (x, y) in zip(
            self._visual.landmark_labels,
            mean_points,
            strict=True,
        ):
            point = QPointF(float(x), float(y))
            painter.drawEllipse(point, 5.7, 5.7)
            painter.setPen(QPen(QColor("#0b302f"), 1.0))
            painter.drawText(point + QPointF(8.0, -8.0), label)
            painter.setPen(QPen(QColor("#0b302f"), 1.5))

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#f7f9f9"))
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if self._visual is None or self._detail is None:
            painter.setPen(QColor("#64777c"))
            painter.drawText(
                self.rect().adjusted(20, 20, -20, -20),
                Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                "No GPA-aligned cohort has been loaded.",
            )
            painter.end()
            return

        if self._show_selected_surface:
            self._draw_selected_surface(painter)
        self._draw_wireframes(painter)
        self._draw_landmarks(painter)

        painter.setPen(QColor("#52666b"))
        painter.drawText(
            self.rect().adjusted(14, 10, -14, -10),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom,
            "Drag: rotate  |  Right-drag: pan  |  Wheel: zoom  |  "
            "Double-click: reset view",
        )
        painter.setPen(QColor("#0b302f"))
        painter.drawText(
            self.rect().adjusted(14, 10, -14, -10),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
            f"Colored lines: all {len(self._visual.meshes)} aligned meshes simultaneously  |  "
            "Thicker/brighter: selected mesh  |  Green: GPA consensus landmarks",
        )
        painter.end()


def cohort_overlay_color(
    index: int,
    mesh_count: int,
    *,
    selected: bool = False,
) -> QColor:
    """Return one stable, high-contrast cohort color for a light canvas."""

    if isinstance(index, bool) or not isinstance(index, int):
        raise TypeError("cohort color index must be an integer")
    if isinstance(mesh_count, bool) or not isinstance(mesh_count, int):
        raise TypeError("cohort mesh count must be an integer")
    if mesh_count < 1:
        raise ValueError("cohort mesh count must be positive")
    if index < 0 or index >= mesh_count:
        raise IndexError("cohort color index is outside the cohort")

    hue = (0.57 + index * 0.618033988749895) % 1.0
    cycle = index // 12
    saturation = 0.82 if cycle % 2 == 0 else 0.68
    value = 0.72 if (cycle // 2) % 2 == 0 else 0.61
    color = QColor.fromHsvF(hue, saturation, value)
    ordinary_alpha = max(72, min(190, round(500 / math.sqrt(mesh_count))))
    color.setAlpha(238 if selected else ordinary_alpha)
    return color
