"""Bounded display meshes at unchanged PC1–PC3 scores; no analysis or fitting."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import numpy as np
from PySide6.QtCore import QPointF, Qt, QTimer
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from diffeoforge.desktop.surface_rendering import SurfaceFrameCache, SurfaceLayer, SurfaceScene
from diffeoforge.mesh import sha256_file

_LOADERS = ThreadPoolExecutor(max_workers=1, thread_name_prefix="morphospace-display")


def load_geometry(path, expected=None, scores_expected=None):
    if expected is not None and (
        path.is_symlink()
        or path.stat().st_size != expected["bytes"]
        or sha256_file(path) != expected["sha256"]
    ):
        raise ValueError("3D display data changed since verification")
    with np.load(path, allow_pickle=False) as data:
        scores, vertices, faces = (data[k].copy() for k in ("scores", "vertices", "faces"))
        ratios = data["ratios"].copy()
    if scores.ndim != 2 or scores.shape[1] < 3 or not 1 <= len(scores) <= 2000:
        raise ValueError("The 3D view requires at least three saved principal components.")
    if vertices.ndim != 3 or vertices.shape[0] != len(scores) or vertices.shape[2] != 3:
        raise ValueError("Display meshes do not match saved PCA scores")
    if faces.ndim != 2 or faces.shape[1] != 3 or not np.issubdtype(faces.dtype, np.integer):
        raise ValueError("Invalid display topology")
    if (
        len(faces) > 160
        or vertices.shape[1] > 480
        or faces.size == 0
        or len(faces) * len(scores) > 24000
    ):
        raise ValueError("Display mesh budget exceeded")
    if faces.min() < 0 or faces.max() >= vertices.shape[1]:
        raise ValueError("Display topology escapes its vertices")
    if len(ratios) < 3 or not all(np.isfinite(a).all() for a in (scores, vertices, ratios)):
        raise ValueError("Non-finite morphospace data")
    if scores_expected is not None and not np.array_equal(scores[:, :3], scores_expected):
        raise ValueError("3D positions differ from the saved PCA gallery")
    if expected is not None and sha256_file(path) != expected["sha256"]:
        raise ValueError("3D display data changed while loading")
    return scores[:, :3], vertices, faces, ratios[:3]


class MorphospaceCanvas(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(300, 300)
        self.setMouseTracking(True)
        self.cache = SurfaceFrameCache(self)
        self.cache.changed.connect(self.update)
        self.data = None
        self.glyph_size = 0.045
        self.selected = -1
        self.labels = []
        self.axis_prefix = "PC"
        self.method_label = ""
        self.reset()

    def reset(self):
        self.yaw, self.pitch, self.zoom, self.pan = -0.45, 0.30, 1.0, (0.0, 0.0)
        self.last = None
        self.update()

    def set_data(self, data, labels):
        self.data, self.labels, self.selected = data, labels, -1
        self.cache.clear()
        self.reset()

    def _scene(self):
        scores, vertices, faces, _ = self.data
        center = (scores.min(0) + scores.max(0)) / 2
        scale = max(float(np.ptp(scores, axis=0).max()), 1e-12)
        local_center = (vertices.min(1) + vertices.max(1)) / 2
        mesh_span = max(float(np.ptp(vertices, axis=1).max()), 1e-12)
        placed = (vertices - local_center[:, None, :]) * (scale * self.glyph_size / mesh_span)
        placed += scores[:, None, :]
        indices = faces[None] + np.arange(len(scores))[:, None, None] * vertices.shape[1]
        cy, sy, cp, sp = np.cos(self.yaw), np.sin(self.yaw), np.cos(self.pitch), np.sin(self.pitch)
        rotation = np.array([[cy, 0, sy], [sp * sy, cp, -sp * cy], [-cp * sy, sp, cp * cy]])
        layer = SurfaceLayer(placed.reshape(-1, 3), indices.reshape(-1, 3))
        scene = SurfaceScene(
            self.width(), self.height(), center, scale, rotation, self.zoom, self.pan, (layer,)
        )
        key = (
            id(self.data),
            self.width(),
            self.height(),
            self.yaw,
            self.pitch,
            self.zoom,
            self.pan,
            self.glyph_size,
        )
        return key, scene

    @staticmethod
    def _project(points, scene):
        camera = ((points - scene.center) / scene.scale) @ scene.rotation.T
        factor = 0.9 * max(1.0, min(scene.width, scene.height) - scene.margin) * scene.zoom
        return np.column_stack(
            (
                scene.width / 2 + scene.pan[0] + camera[:, 0] * factor,
                scene.height / 2 + scene.pan[1] - camera[:, 1] * factor,
            )
        )

    def _decorate(self, painter, scene):
        scores, _, _, ratios = self.data
        painter.setPen(QPen(QColor("#526b70"), 1))
        if self.method_label:
            title = painter.fontMetrics().elidedText(
                self.method_label, Qt.TextElideMode.ElideRight, self.width() - 24
            )
            painter.drawText(12, 20, title)
        # One common spatial scale: equal score distances have equal lengths on all axes.
        for axis in range(3):
            a = scene.center.copy()
            b = scene.center.copy()
            a[axis] -= scene.scale * 0.55
            b[axis] += scene.scale * 0.55
            xy = self._project(np.array([a, b]), scene)
            painter.drawLine(QPointF(*xy[0]), QPointF(*xy[1]))
            label = f"{self.axis_prefix}{axis + 1}"
            if ratios is not None:
                label += f" ({ratios[axis]:.1%})"
            painter.drawText(QPointF(*xy[1]), label)
        if self.selected >= 0:
            xy = self._project(scores[self.selected : self.selected + 1], scene)[0]
            painter.setPen(QPen(QColor("#a64e18"), 2))
            painter.drawEllipse(QPointF(*xy), 12, 12)
            painter.drawText(12, 42 if self.method_label else 24, self._label(self.selected))

    def paintEvent(self, event):  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#f7f9f9"))
        if self.data is None:
            painter.drawText(
                self.rect(), Qt.AlignmentFlag.AlignCenter, "3D morphospace is not available yet."
            )
            return
        key, scene = self._scene()
        image = self.cache.request(key, scene)
        if image is not None:
            painter.drawImage(0, 0, image)
            self._decorate(painter, self.cache.image_scene)
        if not self.cache.ready(key):
            painter.drawText(12, self.height() - 12, self.cache.error or "Rendering…")

    def snapshot(self):
        if self.data is None:
            raise ValueError("No 3D morphospace is available for this result.")
        key, scene = self._scene()
        if not self.cache.ready(key):
            raise ValueError("Wait for the current camera view to finish rendering.")
        image = QImage(self.cache.request(key, scene))
        painter = QPainter(image)
        self._decorate(painter, scene)
        painter.end()
        return image

    def _label(self, index):
        name = self.labels[index] if index < len(self.labels) else f"Mesh {index + 1}"
        return (
            name
            + " · "
            + " · ".join(
                f"{self.axis_prefix}{i + 1}: {v:.6g}" for i, v in enumerate(self.data[0][index])
            )
        )

    def _pick(self, position):
        scene = self.cache.image_scene
        if self.data is None or scene is None:
            return -1
        xy = self._project(self.data[0], scene)
        distances = np.linalg.norm(xy - [position.x(), position.y()], axis=1)
        index = int(distances.argmin())
        return index if distances[index] < 25 else -1

    def mousePressEvent(self, event):  # noqa: N802
        self.last = self.press = event.position()

    def mouseMoveEvent(self, event):  # noqa: N802
        if self.last is not None and event.buttons():
            delta = event.position() - self.last
            if event.buttons() & Qt.MouseButton.LeftButton:
                self.yaw += delta.x() * 0.009
                self.pitch += delta.y() * 0.009
            else:
                self.pan = self.pan[0] + delta.x(), self.pan[1] + delta.y()
            self.last = event.position()
            self.update()
        else:
            index = self._pick(event.position())
            self.setToolTip(
                self._label(index)
                if index >= 0
                else "Drag to rotate · Right-drag to pan · Wheel to zoom"
            )

    def mouseReleaseEvent(self, event):  # noqa: N802
        if self.last is not None and (event.position() - self.press).manhattanLength() < 4:
            self.selected = self._pick(event.position())
            self.update()
        self.last = None

    def wheelEvent(self, event):  # noqa: N802
        self.zoom = min(15.0, max(0.15, self.zoom * 1.15 ** (event.angleDelta().y() / 120)))
        self.update()
        event.accept()


class Morphospace3D(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        controls = QHBoxLayout()
        reset = QPushButton("Reset camera")
        self.canvas = MorphospaceCanvas()
        reset.clicked.connect(self.canvas.reset)
        controls.addWidget(reset)
        self.specimens = QComboBox()
        self.specimens.setPlaceholderText("Select a mesh…")
        self.specimens.currentIndexChanged.connect(self._select)
        controls.addWidget(self.specimens, 1)
        controls.addWidget(QLabel("Mesh size"))
        size = QSlider(Qt.Orientation.Horizontal)
        size.setToolTip(
            "Display size only. Meshes are centered on their saved scores; "
            "one common size scale preserves their relative dimensions."
        )
        size.setRange(1, 20)
        size.setValue(5)
        size.valueChanged.connect(self._size)
        controls.addWidget(size)
        layout.addLayout(controls)
        self.status = QLabel(
            "Drag to rotate · Right-drag to pan · Wheel to zoom · Click a mesh for scores"
        )
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        layout.addWidget(self.canvas, 1)
        self.timer = QTimer(self)
        self.timer.setInterval(40)
        self.timer.timeout.connect(self._poll)
        self.future = None

    def _size(self, value):
        self.canvas.glyph_size = value / 100
        self.canvas.update()

    def _select(self, index):
        self.canvas.selected = index
        self.canvas.update()

    def load(self, path, labels, *, expected=None, scores=None):
        self.clear()
        if not path.is_file():
            self.status.setText("Prepare this result's media again to add the 3D view.")
            return
        self.labels = labels
        self.future = _LOADERS.submit(load_geometry, path, expected, scores)
        self.status.setText("Loading 3D display meshes…")
        self.timer.start()

    def clear(self):
        self.timer.stop()
        if self.future is not None:
            self.future.cancel()
        self.future = None
        self.canvas.data = None
        self.specimens.clear()
        self.canvas.cache.clear()
        self.canvas.update()

    def _poll(self):
        if self.future is None or not self.future.done():
            return
        self.timer.stop()
        try:
            self.canvas.set_data(self.future.result(), self.labels)
            self.specimens.addItems(
                [
                    self.labels[i] if i < len(self.labels) else f"Mesh {i + 1}"
                    for i in range(len(self.canvas.data[0]))
                ]
            )
            self.status.setText(
                "Drag to rotate · Right-drag to pan · Wheel to zoom · Click for scores"
            )
        except (OSError, ValueError, KeyError) as error:
            self.status.setText(str(error))
