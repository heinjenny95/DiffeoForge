"""Interactive native-Qt 3D surface canvas for anatomical landmark placement."""

from __future__ import annotations

import math
from dataclasses import dataclass
from threading import Event

import numpy as np
from PySide6.QtCore import QPointF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPaintEvent, QPen, QWheelEvent
from PySide6.QtWidgets import QCheckBox, QWidget

from diffeoforge.desktop.display_proxy import DEFAULT_DISPLAY_FACES
from diffeoforge.desktop.mesh_preview import MeshPreviewModel
from diffeoforge.desktop.preview_mesh_loader import PreviewMeshLoader
from diffeoforge.desktop.surface_rendering import SurfaceFrameCache, SurfaceLayer, SurfaceScene
from diffeoforge.desktop.surface_snap import closest_surface_point

INTERACTIVE_TRIANGLE_BUDGET = 5_000
SURFACE_OPACITY = 255


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
    inside = usable & (first >= -tolerance) & (second >= -tolerance) & (third >= -tolerance)
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
        self._frames = SurfaceFrameCache(self)
        self._frames.changed.connect(self.update)
        self._presented_key: tuple | None = None
        self._pick_view_key: tuple | None = None
        self._pick_loader = PreviewMeshLoader(self)
        self._pick_loader.loaded.connect(self._transfer_finished)
        self._pick_loader.failed.connect(self._transfer_failed)
        self._pick_cancel = Event()
        self._pick_pending = False
        self._pick_error = ""
        self._wheel_timer = QTimer(self)
        self._wheel_timer.setSingleShot(True)
        self._wheel_timer.setInterval(160)
        self._wheel_timer.timeout.connect(self.update)
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
        self._picking_enabled = True
        self.original_detail = QCheckBox("Original detail (slower)", self)
        self.original_detail.move(12, 38)
        self.original_detail.setToolTip(
            "Click either view to place landmarks on the original surface. "
            "Reduced-view clicks snap to the nearest original face; "
            "original detail is optional for inspecting small features."
        )
        self.original_detail.toggled.connect(self._resolution_changed)
        self.setMinimumHeight(500)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setObjectName("interactiveLandmarkCanvas3D")

    @property
    def picking_enabled(self) -> bool:
        return self._picking_enabled

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
        self.cancel_pending_pick()
        self._model = model
        self._frames.clear()
        self._presented_key = None
        self.original_detail.setChecked(False)
        self.original_detail.setEnabled(model is not None and not model.geometry_is_proxy)
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
        # Also called on label changes, undo and clear: a delayed transfer must
        # never place a point under a different landmark label.
        self.cancel_pending_pick()
        self._markers = dict(markers)
        self.update()

    def cancel_pending_pick(self) -> None:
        self._pick_cancel.set()
        self._pick_loader.cancel()
        self._pick_pending = False
        self._pick_error = ""
        self._pick_view_key = None

    def hideEvent(self, event) -> None:  # noqa: N802 - Qt API name
        self.cancel_pending_pick()
        super().hideEvent(event)

    def _frame_key(self) -> tuple:
        return (
            id(self._model),
            self.width(),
            self.height(),
            self._yaw,
            self._pitch,
            self._zoom,
            self._pan,
            self.original_detail.isChecked(),
            self._interacting or self._wheel_timer.isActive(),
        )

    def _resolution_changed(self, _checked: bool) -> None:
        self.cancel_pending_pick()
        self._frames.clear()
        self._presented_key = self._pick_view_key = None
        self.update()

    @property
    def full_resolution_ready(self) -> bool:
        key = self._frame_key()
        return bool(
            self._model is not None
            and not key[-1]
            and not self._model.geometry_is_proxy
            and (
                self.original_detail.isChecked()
                or self._model.triangle_count <= DEFAULT_DISPLAY_FACES
            )
            and self._presented_key == key
            and self._frames.ready(key)
        )

    @property
    def picking_ready(self) -> bool:
        """Only pick a settled, presented frame backed by original geometry."""

        key = self._frame_key()
        return bool(
            self._picking_enabled
            and not self._pick_pending
            and self._model is not None
            and not self._model.geometry_is_proxy
            and not key[-1]
            and len(self._display_geometry()[1])
            and self._presented_key == key
            and self._frames.ready(key)
        )

    def set_picking_enabled(self, enabled: bool) -> None:
        """Switch between landmark placement and neutral mesh viewing."""

        self._picking_enabled = bool(enabled)
        if not enabled:
            self.cancel_pending_pick()
        self.setCursor(
            Qt.CursorShape.CrossCursor if self._picking_enabled else Qt.CursorShape.OpenHandCursor
        )
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

    def _display_geometry(self) -> tuple[np.ndarray, np.ndarray]:
        if self._model is not None and not self.original_detail.isChecked():
            proxy = self._model.display_proxy
            if proxy is not None:
                return proxy.vertices, proxy.triangles
            if len(self._triangles) > DEFAULT_DISPLAY_FACES:
                return np.empty((0, 3)), np.empty((0, 3), dtype=np.int64)
        return self._vertices, self._triangles

    def _surface(self, *, displayed: bool = False) -> ProjectedSurface | None:
        if self._model is None or self._vertices.size == 0:
            return None
        vertices, triangles = (
            self._display_geometry() if displayed else (self._vertices, self._triangles)
        )
        return project_surface(
            vertices,
            triangles,
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
        """Synchronous original-detail ray pick for deterministic verification."""

        surface = self._surface()
        if surface is None:
            return None
        return pick_surface_point(surface, (position.x(), position.y()))

    def _pick_displayed_surface(self, position: QPointF) -> None:
        model = self._model
        if model is None or model.geometry_is_proxy:
            return
        surface = self._surface(displayed=True)
        if surface is None:
            return
        point = pick_surface_point(surface, (position.x(), position.y()))
        if point is None:
            return
        self._pick_error = ""
        proxy = model.display_proxy
        if self.original_detail.isChecked() or proxy is None or not proxy.reduced:
            self.surfacePointPicked.emit(point)
            return
        self._pick_cancel = Event()
        cancel = self._pick_cancel
        vertices, triangles = self._vertices, self._triangles
        self._pick_pending = True
        self._pick_loader.request_operation(
            id(model), lambda: closest_surface_point(point, vertices, triangles, cancel=cancel)
        )

    def _transfer_finished(self, model_id: object, point: object) -> None:
        self._pick_pending = False
        if model_id == id(self._model) and point is not None and self._picking_enabled:
            self.surfacePointPicked.emit(point)
        self.update()

    def _transfer_failed(self, _model_id: object, error: str) -> None:
        self._pick_pending = False
        self._pick_error = f"Landmark not placed: {error}"
        self.update()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt API name
        if event.button() not in {
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.MiddleButton,
            Qt.MouseButton.RightButton,
        }:
            super().mousePressEvent(event)
            return
        self._pick_view_key = self._frame_key() if self.picking_ready else None
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
            self._picking_enabled
            and event.button() == Qt.MouseButton.LeftButton
            and self._drag_distance <= 5.0
            and self._press_position is not None
        )
        self._press_position = None
        self._last_position = None
        self._drag_button = None
        self._interacting = False
        self.setCursor(
            Qt.CursorShape.CrossCursor if self._picking_enabled else Qt.CursorShape.OpenHandCursor
        )
        # Mouse-move paints may use the bounded interactive triangle preview.
        # Always schedule a new paint after release so that preview can never
        # remain as the apparent final surface.
        self.update()
        if should_pick and self._pick_view_key == self._frame_key():
            self._pick_displayed_surface(event.position())

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802 - Qt API name
        delta = event.angleDelta().y()
        if delta == 0:
            return
        self._zoom = min(8.0, max(0.25, self._zoom * math.exp(delta / 900.0)))
        self._wheel_timer.start()
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
        if self._model is None:
            painter.setPen(QColor("#64777c"))
            painter.drawText(
                self.rect().adjusted(20, 20, -20, -20),
                Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                "No mesh has been loaded.",
            )
            painter.end()
            return

        navigation = self._interacting or self._wheel_timer.isActive()
        key = self._frame_key()
        vertices, triangles = self._display_geometry()
        scene = SurfaceScene(
            self.width(),
            self.height(),
            self._center,
            self._scale,
            camera_rotation(self._yaw, self._pitch),
            self._zoom,
            self._pan,
            (SurfaceLayer(vertices, triangles),),
            navigation=navigation,
            margin=64.0,
        )
        image = self._frames.request(key, scene)
        if image is not None:
            painter.drawImage(0, 0, image)
        self._presented_key = key if self._frames.ready(key) and not navigation else None
        if (
            navigation or not self._frames.ready(key) or not self.full_resolution_ready
            or self._pick_pending or self._pick_error
        ):
            painter.fillRect(0, 0, self.width(), 34, QColor("#fff3d6"))
            painter.setPen(QColor("#705419"))
            painter.drawText(
                12,
                23,
                self._pick_error
                or ("Transferring landmark to original surface…" if self._pick_pending else None)
                or self._frames.error
                or (
                    "Landmark picking needs the original mesh, not a display-only model."
                    if self._model.geometry_is_proxy else None
                )
                or (
                    self._model.display_proxy_error
                    if not self.original_detail.isChecked()
                    else None
                )
                or (
                    "Navigation preview — release to place landmarks."
                    if navigation
                    else (
                        "Rendering selected display resolution in background…"
                        if not self._frames.ready(key)
                        else f"Display proxy: {len(triangles):,} faces. "
                        "Clicks snap to the original surface."
                    )
                ),
            )

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
            ("Click: place/replace landmark  ·  " if self._picking_enabled else "")
            + "Drag: rotate  ·  Right-drag: pan  "
            "·  Wheel: zoom  ·  Double-click: reset view",
        )
        painter.end()
