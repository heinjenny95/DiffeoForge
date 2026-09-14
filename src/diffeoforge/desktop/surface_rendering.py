"""Cancellable, exact-resolution QImage rendering outside the GUI thread.

Only the short-lived navigation frame is sampled. No mesh or analysis is changed.
Workers own QImage/QPainter instances and never access QWidget objects.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from queue import Empty, SimpleQueue

import numpy as np
from PySide6.QtCore import QObject, QPointF, QRunnable, QThreadPool, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen, QPolygonF

NAVIGATION_FACES = 1_500
NAVIGATION_EDGES = 6_000


@dataclass(frozen=True)
class SurfaceLayer:
    vertices: np.ndarray
    indices: np.ndarray
    wireframe: bool = False
    orange: bool = False
    color: tuple[int, int, int, int] | None = None


@dataclass(frozen=True)
class SurfaceScene:
    width: int
    height: int
    center: np.ndarray
    scale: float
    rotation: np.ndarray
    zoom: float
    pan: tuple[float, float]
    layers: tuple[SurfaceLayer, ...]
    navigation: bool = False
    margin: float = 72.0


def render_surface_scene(scene: SurfaceScene, cancelled: threading.Event) -> QImage | None:
    """Rasterize immutable geometry; use every supplied face/edge in a settled view."""
    image = QImage(max(1, scene.width), max(1, scene.height), QImage.Format.Format_ARGB32)
    image.fill(QColor("#f7f9f9"))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    try:
        factor = 0.9 * max(1.0, min(scene.width, scene.height) - scene.margin) * scene.zoom
        for layer in scene.layers:
            if cancelled.is_set():
                return None
            indices = layer.indices
            if scene.navigation:
                budget = NAVIGATION_EDGES if layer.wireframe else NAVIGATION_FACES
                if len(indices) > budget:
                    indices = indices[np.linspace(0, len(indices) - 1, budget, dtype=np.int64)]
            # Transform only referenced vertices in a navigation frame.
            if scene.navigation and indices.size:
                selected, inverse = np.unique(indices, return_inverse=True)
                vertices = layer.vertices[selected]
                indices = inverse.reshape(indices.shape)
            else:
                vertices = layer.vertices
            camera = ((vertices - scene.center) / scene.scale) @ scene.rotation.T
            screen = np.empty((len(vertices), 2), dtype=np.float64)
            screen[:, 0] = scene.width / 2 + scene.pan[0] + camera[:, 0] * factor
            screen[:, 1] = scene.height / 2 + scene.pan[1] - camera[:, 1] * factor
            if layer.wireframe:
                painter.setPen(QPen(QColor(*(layer.color or (17, 94, 163, 220))), 1.05))
                # Bounded chunks allow cancellation during very dense wireframes.
                for offset in range(0, len(indices), 1024):
                    if cancelled.is_set():
                        return None
                    path = QPainterPath()
                    for start, end in indices[offset : offset + 1024]:
                        first, second = screen[start], screen[end]
                        path.moveTo(float(first[0]), float(first[1]))
                        path.lineTo(float(second[0]), float(second[1]))
                    painter.drawPath(path)
                continue
            camera_triangles = camera[indices]
            normals = np.cross(
                camera_triangles[:, 1] - camera_triangles[:, 0],
                camera_triangles[:, 2] - camera_triangles[:, 0],
            )
            light = np.abs(normals[:, 2]) / np.maximum(np.linalg.norm(normals, axis=1), 1e-12)
            order = np.argsort(np.mean(camera_triangles[:, :, 2], axis=1))
            painter.setPen(
                QPen(QColor(193, 87, 42, 105), 0.30)
                if layer.orange
                else QPen(QColor("#6e9992"), 0.35)
            )
            for count, index in enumerate(order):
                if count % 128 == 0 and cancelled.is_set():
                    return None
                shade = int(
                    (218 + 27 * light[index]) if layer.orange else (198 + 38 * light[index])
                )
                painter.setBrush(
                    QColor(242, max(150, shade - 42), 116, 190)
                    if layer.orange
                    else QColor(shade - 38, shade, shade - 16, 255)
                )
                painter.drawPolygon(
                    QPolygonF([QPointF(float(x), float(y)) for x, y in screen[indices[index]]])
                )
        return None if cancelled.is_set() else image
    finally:
        painter.end()


class _FrameMailbox:
    """Python-only handoff: a pool worker never owns a GUI-thread QObject."""

    def __init__(self) -> None:
        self.results: SimpleQueue[tuple[tuple, QImage | None, str]] = SimpleQueue()
        self.cancelled: threading.Event | None = None

    def cancel(self) -> None:
        # Connected to cache.destroyed without retaining/accessing the cache.
        if self.cancelled is not None:
            self.cancelled.set()


class _FrameWorker(QRunnable):
    def __init__(self, key: tuple, scene: SurfaceScene, results: SimpleQueue) -> None:
        super().__init__()
        self.key, self.scene = key, scene
        self.cancelled = threading.Event()
        self.results = results

    @Slot()
    def run(self) -> None:
        try:
            image = render_surface_scene(self.scene, self.cancelled)
            error = ""
        except Exception as exception:  # Worker failure must never leave a frame approved.
            image, error = None, str(exception)
        # Releasing a runnable must not destroy a GUI-affine signal QObject from
        # a pool thread. The queue transfers values without that QObject lifetime coupling.
        self.results.put((self.key, image, error))


class SurfaceFrameCache(QObject):
    """One active job, one latest pending view, one cached image; no job backlog."""

    changed = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._active: _FrameWorker | None = None
        self._pending: tuple[tuple, SurfaceScene] | None = None
        self._wanted: tuple | None = None
        self._image_key: tuple | None = None
        self._image: QImage | None = None
        self.error = ""
        self.render_count = 0
        self._mailbox = _FrameMailbox()
        self.destroyed.connect(self._mailbox.cancel)
        self._poller = QTimer(self)
        self._poller.setInterval(10)
        self._poller.timeout.connect(self._take_result)

    def clear(self) -> None:
        self._wanted = self._image_key = None
        self._image = self._pending = None
        self.error = ""
        if self._active is not None:
            self._active.cancelled.set()

    def ready(self, key: tuple) -> bool:
        return self._image is not None and self._image_key == key

    def request(self, key: tuple, scene: SurfaceScene) -> QImage | None:
        if key != self._wanted:
            self._wanted = key
            self.error = ""
            self._pending = (key, scene)
            if self._active is not None:
                self._active.cancelled.set()
        if self._active is None and self._pending is not None:
            pending_key, pending_scene = self._pending
            self._pending = None
            self._active = _FrameWorker(pending_key, pending_scene, self._mailbox.results)
            self._mailbox.cancelled = self._active.cancelled
            self.render_count += 1
            self._poller.start()
            QThreadPool.globalInstance().start(self._active)
        # Callers clear on specimen changes and visibly label a pending camera view.
        return self._image

    @Slot()
    def _take_result(self) -> None:
        try:
            result = self._mailbox.results.get_nowait()
        except Empty:
            return
        self._poller.stop()
        self._finished(*result)

    def _finished(self, key: tuple, image: QImage | None, error: str) -> None:
        cancelled = self._active is None or self._active.cancelled.is_set()
        self._active = None
        self._mailbox.cancelled = None
        if not cancelled and key == self._wanted and image is not None:
            self._image_key, self._image = key, image
        if not cancelled and key == self._wanted:
            self.error = error
        if self._pending is not None:
            pending_key, scene = self._pending
            self.request(pending_key, scene)
        self.changed.emit()
