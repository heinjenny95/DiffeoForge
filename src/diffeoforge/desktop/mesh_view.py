"""One source-bound anatomical view shared by PCA image glyphs and 3D scores.

Only display surfaces are read/rendered. No atlas, PCA or sealed media is changed.
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from diffeoforge.mesh import sha256_file

_JOBS = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mesh-view")


def checked_rotation(value):
    rotation = np.asarray(value, dtype=np.float64)
    if (
        rotation.shape != (3, 3)
        or not np.isfinite(rotation).all()
        or not np.allclose(rotation @ rotation.T, np.eye(3), atol=1e-8, rtol=0)
        or not np.isclose(np.linalg.det(rotation), 1, atol=1e-8, rtol=0)
    ):
        raise ValueError("Mesh view must be a finite rotation, without reflection or scaling")
    return rotation.copy()


def turn_view(base, yaw=0, pitch=0, roll=0):
    angles = np.asarray([yaw, pitch, roll], float)
    if not np.isfinite(angles).all():
        raise ValueError("Mesh view angles must be finite")
    y, p, r = np.deg2rad(angles)
    cy, sy, cp, sp, cr, sr = np.cos(y), np.sin(y), np.cos(p), np.sin(p), np.cos(r), np.sin(r)
    return checked_rotation(
        np.array([[cr, -sr, 0], [sr, cr, 0], [0, 0, 1]])
        @ np.array([[1, 0, 0], [0, cp, -sp], [0, sp, cp]])
        @ np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
        @ checked_rotation(base)
    )


def preset_views():
    from diffeoforge.analysis.pca_media_rendering import VIEWS

    result = []
    for label, direction, up in VIEWS:
        direction, up = np.asarray(direction, float), np.asarray(up, float)
        right = np.cross(up, direction)
        result.append((label, checked_rotation(np.array([right, up, direction]))))
    return result


def preference_path(directory):
    identity = sha256_file(directory / "media.json")
    return directory.parent / f"mesh-views-{identity[:20]}.json", identity


def read_views(path, identity):
    if not path.exists():
        return [], None
    if path.is_symlink():
        raise ValueError("Mesh views must be a regular project file")
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("version") != 1 or value.get("media_sha256") != identity:
        raise ValueError("Saved mesh view belongs to a different result")
    views = value.get("views", [])
    if not isinstance(views, list) or len(views) > 24:
        raise ValueError("Invalid saved mesh views")
    names = set()
    for view in views:
        if not isinstance(view, dict):
            raise ValueError("Invalid saved mesh view")
        name = view.get("name")
        if not isinstance(name, str) or not name.strip() or len(name) > 80 or name in names:
            raise ValueError("Mesh views need distinct short names")
        names.add(name)
        checked_rotation(view.get("rotation"))
    selected = value.get("selected")
    if (selected is not None or views) and selected not in names:
        raise ValueError("Selected mesh view is missing")
    return views, selected


def save_view(path, identity, views, name, rotation):
    name = name.strip()
    if not name or len(name) > 80 or path.is_symlink():
        raise ValueError("Give this mesh view a short name")
    value = {"name": name, "rotation": checked_rotation(rotation).tolist()}
    updated = [v for v in views if v["name"] != name] + [value]
    if len(updated) > 24:
        raise ValueError("This result already has 24 named mesh views")
    stage = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        stage.write_text(
            json.dumps(
                {"version": 1, "media_sha256": identity, "selected": name, "views": updated},
                allow_nan=False,
            ),
            encoding="utf-8",
        )
        os.replace(stage, path)
    finally:
        stage.unlink(missing_ok=True)
    return updated


def load_surfaces(directory, expected_scores, cancelled):
    from diffeoforge.analysis.pca_media_rendering import (
        display_proxy,
        faces,
        merge_bounds,
        points,
        read_mesh,
    )

    metadata = json.loads((directory / "media.json").read_text(encoding="utf-8"))
    if sha256_file(directory / "media.json") != (directory / "media.sha256").read_text().strip():
        raise ValueError("Saved media changed before mesh-view preparation")
    labels = metadata["specimen_labels"]
    scores = np.asarray(expected_scores, dtype=np.float64)
    score_path = directory / "PCA-Gallery/mesh-pca.json"
    score_record = next(
        (r for r in metadata["files"] if r["path"] == "PCA-Gallery/mesh-pca.json"), None
    )
    if (
        score_record is None
        or score_path.is_symlink()
        or score_path.stat().st_size != score_record["bytes"]
        or sha256_file(score_path) != score_record["sha256"]
    ):
        raise ValueError("Saved score display data changed")
    saved_scores = [item["scores"][:3] for item in json.loads(score_path.read_text())]
    if not np.array_equal(scores, saved_scores):
        raise ValueError("Mesh-view positions differ from the saved scores")
    if (
        scores.ndim != 2
        or not np.isfinite(scores).all()
        or not 1 <= len(labels) <= 2000
        or len(labels) != len(scores)
        or len(set(labels)) != len(labels)
    ):
        raise ValueError("Mesh identities do not match the saved score rows")
    root = Path(metadata["source_run"]).resolve()
    geometry, bounds, topology, proxy, ids = [], [], None, None, None
    for label in labels:
        if cancelled.is_set():
            raise RuntimeError("Mesh-view preparation cancelled")
        records = [
            r
            for r in metadata["sources"]
            if Path(r["path"]).name.endswith(f"__subject_{label}.vtk")
            and "__Reconstruction__" in Path(r["path"]).name
        ]
        if len(records) != 1:
            raise ValueError("Each score row must bind exactly one reconstruction")
        record = records[0]
        path = Path(record["path"])
        if not path.resolve().is_relative_to(root) or path.is_symlink():
            raise ValueError("Display surface escapes its saved result")
        if path.stat().st_size != record["bytes"] or sha256_file(path) != record["sha256"]:
            raise ValueError("Display surface differs from its verified source")
        mesh = read_mesh(path)
        current_faces = faces(mesh)
        if topology is None:
            topology = current_faces.copy()
            proxy, ids = display_proxy(mesh, budget=20_000)
        elif not np.array_equal(current_faces, topology):
            raise ValueError("Corresponding display surfaces have different topology")
        geometry.append(points(mesh)[ids].copy())
        bounds.append(mesh.GetBounds())
        if sum(a.nbytes for a in geometry) > 256 * 1024 * 1024:
            raise ValueError("Mesh-view display memory budget exceeded")
        if sha256_file(path) != record["sha256"]:
            raise ValueError("Display surface changed while being read")
    return proxy, np.asarray(geometry), merge_bounds(bounds), scores.copy()


def render_views(data, rotation, indices, cancelled):
    from diffeoforge.analysis.pca_media_rendering import SurfaceRenderer, with_points

    rotation = checked_rotation(rotation)
    view = ("Project mesh view", rotation[2], rotation[1])
    proxy, values, bounds, _ = data
    renderer = SurfaceRenderer((420, 360))
    images = []
    try:
        for index in indices:
            if cancelled.is_set():
                raise RuntimeError("Mesh-view rendering cancelled")
            frame = renderer.render(with_points(proxy, values[index]), bounds, view)
            pixels = np.ascontiguousarray(frame)
            images.append(
                QImage(
                    pixels.data,
                    pixels.shape[1],
                    pixels.shape[0],
                    pixels.strides[0],
                    QImage.Format.Format_RGBA8888,
                ).copy()
            )
    finally:
        renderer.close()
    return images


class MeshViewController(QObject):
    images_changed = Signal(object)
    media_changed = Signal(object)
    busy_changed = Signal(bool)
    preview_ready = Signal(object)
    ready_changed = Signal(bool)
    status_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.timer = QTimer(self)
        self.timer.setInterval(40)
        self.timer.timeout.connect(self._poll)
        self.future = None
        self.cancelled = threading.Event()
        box = [self.cancelled]
        self._cancel_box = box
        self.destroyed.connect(lambda: box[0].set())
        self.data = None
        self.pending = None
        self.views, self.selected = [], None
        self._restore_selected = None
        self.rotation = np.eye(3)
        self.label = "Original mesh view"
        self.images = []
        self._generation = 0
        self.all_media = False
        self.directory = None
        self._progress = [None]

    def clear(self):
        self._generation += 1
        self.cancelled.set()
        if self.future is not None:
            self.future.cancel()
        self.future, self.pending, self.data = None, None, None
        self.timer.stop()
        self._progress = [None]
        self.views, self.selected, self.images = [], None, []
        self._restore_selected = None
        self.rotation, self.label = np.eye(3), "Original mesh view"
        self.ready_changed.emit(False)
        self.busy_changed.emit(False)
        self.status_changed.emit("Choose which surface faces you.")

    def load(self, directory, scores, images):
        self.clear()
        self.directory = directory
        self.images = images
        self.path, self.identity = preference_path(directory)
        try:
            self.views, self._restore_selected = read_views(self.path, self.identity)
        except (OSError, ValueError, KeyError, TypeError) as error:
            self.status_changed.emit(str(error))
        self._submit("load", (directory, scores))

    def _submit(self, kind, args):
        self.cancelled = threading.Event()
        self._cancel_box[0] = self.cancelled
        generation = self._generation
        self._kind, self._args, self._active_generation = kind, args, generation
        if kind == "load":
            self.future = _JOBS.submit(load_surfaces, *args, self.cancelled)
        else:
            rotation, indices, _name = args
            if kind == "apply" and self.all_media:
                self._progress = [None]
                self.future = _JOBS.submit(
                    render_all_media,
                    self.directory,
                    rotation,
                    _name,
                    self.cancelled,
                    self._progress,
                )
            else:
                self.future = _JOBS.submit(
                    render_views, self.data, rotation, indices, self.cancelled
                )
        self.timer.start()

    def request(self, rotation, *, preview=None, name=None):
        if self.data is None:
            return
        self._generation += 1
        kind = "preview" if preview is not None else "apply"
        indices = [preview] if preview is not None else list(range(len(self.data[1])))
        args = (checked_rotation(rotation), indices, name or "Project view")
        if self.future is not None:
            self.cancelled.set()
            self.pending = (kind, args)
        else:
            self._submit(kind, args)
        if kind == "apply":
            self.busy_changed.emit(True)
            self.status_changed.emit(
                "Preparing all visualizations…" if self.all_media else "Turning all meshes…"
            )

    def _poll(self):
        if getattr(self, "_active_generation", None) == self._generation and self._progress[0]:
            self.status_changed.emit(self._progress[0])
            self._progress[0] = None
        if self.future is None or not self.future.done():
            return
        future, kind, args, generation = (
            self.future,
            self._kind,
            self._args,
            self._active_generation,
        )
        self.future = None
        self.timer.stop()
        try:
            value = future.result()
            if generation == self._generation:
                if kind == "load":
                    self.data = value
                    self.ready_changed.emit(True)
                    if self._restore_selected:
                        selected = next(
                            v for v in self.views if v["name"] == self._restore_selected
                        )
                        self.request(selected["rotation"], name=self._restore_selected)
                elif kind == "preview":
                    self.preview_ready.emit(value[0])
                else:
                    rotation, _indices, name = args
                    media = None
                    if self.all_media:
                        value, media = value
                    updated = save_view(self.path, self.identity, self.views, name, rotation)
                    self.views, self.rotation, self.label = updated, rotation, name.strip()
                    self.selected = self.label
                    self.images = value
                    if media is not None:
                        self.media_changed.emit(media)
                    self.images_changed.emit(value)
                    self.status_changed.emit(
                        "Applied to all visualizations."
                        if self.all_media
                        else "Applied to all meshes."
                    )
        except (OSError, RuntimeError, ValueError, KeyError, TypeError) as error:
            if generation == self._generation:
                self.status_changed.emit(str(error))
        if self.pending is not None:
            pending, self.pending = self.pending, None
            self._submit(*pending)
        elif kind == "apply":
            self.busy_changed.emit(False)


def render_all_media(directory, rotation, name, cancelled, progress):
    from diffeoforge.oriented_media import prepare_oriented_media

    path = prepare_oriented_media(
        directory, rotation, name, cancelled, lambda text: progress.__setitem__(0, text)
    )
    items = json.loads((path / "PCA-Gallery/mesh-pca.json").read_text())
    images = [QImage(str(path / f"PCA-Gallery/thumbnails/{item['id']}.png")) for item in items]
    if any(image.isNull() for image in images):
        raise ValueError("A prepared specimen view could not be decoded")
    return images, path


class PreviewSession:
    """One warm renderer on one thread; bounded latest-input mailbox, no GUI waits."""

    def __init__(self, data):
        self.data = data
        self.condition = threading.Condition()
        self.pending = self.result = None
        self.closed = False
        self.serial = 0
        self.worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mesh-preview")
        self.future = self.worker.submit(self._run)

    def request(self, rotation, index):
        with self.condition:
            if self.closed:
                return
            self.serial += 1
            self.pending = self.serial, index, checked_rotation(rotation)
            self.condition.notify()

    def take(self):
        with self.condition:
            result, self.result = self.result, None
            return result

    def close(self):
        with self.condition:
            self.closed = True
            self.pending = None
            self.condition.notify()
        self.worker.shutdown(wait=False, cancel_futures=True)

    def _run(self):
        from diffeoforge.analysis.pca_media_rendering import SurfaceRenderer, with_points

        renderer = None
        mesh, current = None, -1
        try:
            renderer = SurfaceRenderer((420, 360))
            while True:
                with self.condition:
                    self.condition.wait_for(lambda: self.closed or self.pending is not None)
                    if self.closed:
                        return
                    serial, index, rotation = self.pending
                    self.pending = None
                try:
                    if index != current:
                        mesh = with_points(self.data[0], self.data[1][index])
                        current = index
                    frame = renderer.render(
                        mesh, self.data[2], ("Preview", rotation[2], rotation[1])
                    )
                    pixels = np.ascontiguousarray(frame)
                    image = QImage(
                        pixels.data,
                        pixels.shape[1],
                        pixels.shape[0],
                        pixels.strides[0],
                        QImage.Format.Format_RGBA8888,
                    ).copy()
                    error = None
                except Exception as failure:
                    image, error = None, str(failure)
                with self.condition:
                    if not self.closed:
                        self.result = serial, index, image, error
        finally:
            if renderer is not None:
                renderer.close()


class MeshViewPreview(QWidget):
    turned = Signal(float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(440, 320)
        self.image = QImage()
        self.last = None

    def paintEvent(self, event):  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), Qt.GlobalColor.white)
        if not self.image.isNull():
            size = self.image.size().scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio)
            painter.drawImage(
                (self.width() - size.width()) // 2,
                (self.height() - size.height()) // 2,
                self.image.scaled(
                    size,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                ),
            )

    def mousePressEvent(self, event):  # noqa: N802
        self.last = event.position()

    def mouseMoveEvent(self, event):  # noqa: N802
        if self.last is not None and event.buttons() & Qt.MouseButton.LeftButton:
            delta = event.position() - self.last
            self.last = event.position()
            self.turned.emit(delta.x() * 0.6, delta.y() * 0.6)

    def mouseReleaseEvent(self, event):  # noqa: N802
        self.last = None


class MeshViewDialog(QDialog):
    def __init__(self, controller, labels, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.source_data = controller.data
        self.session = PreviewSession(self.source_data)
        session = self.session
        self.destroyed.connect(lambda: session.close())
        self.setWindowTitle("Choose the mesh view")
        self.resize(720, 650)
        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel("Turn the relevant surface towards you, then apply it to all visualizations.")
        )
        self.specimens = QComboBox()
        self.specimens.addItems(labels)
        scores = controller.data[3]
        representative = int(np.linalg.norm(scores - scores.mean(0), axis=1).argmin())
        self.specimens.setCurrentIndex(representative)
        layout.addWidget(self.specimens)
        self.preview = MeshViewPreview()
        layout.addWidget(self.preview, 1)
        self.preset = QComboBox()
        self.preset.addItem("Current view", controller.rotation.copy())
        for name, rotation in preset_views():
            self.preset.addItem(name, rotation)
        for view in controller.views:
            self.preset.addItem("Saved: " + view["name"], np.asarray(view["rotation"]))
        layout.addWidget(self.preset)
        row = QHBoxLayout()
        self.angles = []
        for label in ("Turn", "Tilt", "Roll"):
            row.addWidget(QLabel(label))
            spin = QDoubleSpinBox()
            spin.setRange(-180, 180)
            spin.setSingleStep(5)
            spin.setSuffix("°")
            self.angles.append(spin)
            row.addWidget(spin)
        layout.addLayout(row)
        self.name = QLineEdit(controller.label if controller.selected else "Project view")
        self.name.setMaxLength(80)
        self.name.setPlaceholderText("Name this view")
        layout.addWidget(self.name)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Apply to all visualizations")
        buttons.accepted.connect(self._apply)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.debounce = QTimer(self)
        self.debounce.setSingleShot(True)
        self.debounce.setInterval(16)
        self.debounce.timeout.connect(self._request_preview)
        for spin in self.angles:
            spin.valueChanged.connect(self._schedule_preview)
        self.specimens.currentIndexChanged.connect(self._schedule_preview)
        self.preset.currentIndexChanged.connect(self._preset_changed)
        self.preview.turned.connect(self._turn)
        self.frames = QTimer(self)
        self.frames.setInterval(16)
        self.frames.timeout.connect(self._poll_preview)
        self.frames.start()
        self.finished.connect(self._finished)
        if controller.images:
            self._preview_ready(controller.images[representative])
        self.debounce.start()

    def _schedule_preview(self):
        if not self.debounce.isActive():
            self.debounce.start()

    def _poll_preview(self):
        result = self.session.take()
        if result is not None:
            _serial, index, image, error = result
            if index == self.specimens.currentIndex():
                if error:
                    self.preview.setToolTip(error)
                else:
                    self._preview_ready(image)

    def rotation(self):
        return turn_view(self.preset.currentData(), *(spin.value() for spin in self.angles))

    def _preset_changed(self):
        for spin in self.angles:
            spin.setValue(0)
        self.debounce.start()

    def _turn(self, yaw, pitch):
        for spin, delta in zip(self.angles, (yaw, pitch, 0), strict=True):
            spin.setValue(((spin.value() + delta + 180) % 360) - 180)

    def _request_preview(self):
        self.session.request(self.rotation(), self.specimens.currentIndex())

    def _preview_ready(self, image):
        self.preview.image = image
        self.preview.update()

    def _apply(self):
        if self.name.text().strip() and self.controller.data is self.source_data:
            self.debounce.stop()
            self.controller.request(self.rotation(), name=self.name.text().strip())
            self.accept()

    def _finished(self):
        self.debounce.stop()
        self.frames.stop()
        self.session.close()


def mesh_view_button(controller, labels, parent):
    button = QPushButton("Mesh view…")
    button.setToolTip("Choose a shared surface view independently of the PCA camera.")
    button.setEnabled(False)
    controller.ready_changed.connect(button.setEnabled)
    button.clicked.connect(lambda: MeshViewDialog(controller, labels(), parent).exec())
    return button
