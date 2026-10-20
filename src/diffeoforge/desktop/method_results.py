"""Read-only in-app views of verified post-hoc shape-space methods."""

from __future__ import annotations

import json
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event, Lock

import numpy as np
from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QImage, QPainter
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from diffeoforge.desktop.media_export import MediaExportController
from diffeoforge.desktop.morphospace_3d import Morphospace3D
from diffeoforge.desktop.morphospace_geometry import glyph_topology
from diffeoforge.mesh import sha256_file
from diffeoforge.reference_shape_space_comparison import (
    COMPARISON_MANIFEST,
    SCORES_CSV,
    _read_v03_scores,
    verify_reference_shape_space_comparison,
)

_WORK = ThreadPoolExecutor(max_workers=2, thread_name_prefix="method-display")
_GEOMETRY = OrderedDict()
_GEOMETRY_LOCK = Lock()


def axis_prefix(method_id):
    if method_id == "diffusion_map":
        return "DC"
    if method_id == "isomap":
        return "Dim"
    if method_id == "lddmm_tangent_pcoa":
        return "PCo"
    return "kPC" if "rbf" in method_id else "PC"


def read_method_views(artifact, run):
    root, manifest = artifact.artifact_directory, artifact.manifest
    source = manifest["source"]
    if Path(source["run_directory"]).resolve() != Path(run).resolve():
        raise ValueError("Method results belong to another atlas")
    for name, key in (
        ("manifest.json", "manifest_sha256"),
        ("result.json", "result_sha256"),
        ("output-inventory.json", "output_inventory_sha256"),
    ):
        if sha256_file(Path(run) / name) != source[key]:
            raise ValueError("The method comparison's source result changed")
    if (root / COMPARISON_MANIFEST).is_symlink():
        raise ValueError("Comparison manifest must be a regular file")
    canonical = json.loads((root / COMPARISON_MANIFEST).read_text(encoding="utf-8"))
    if canonical != manifest:
        raise ValueError("Verified comparison manifest changed")
    expected = next((r for r in manifest["artifacts"] if r["path"] == SCORES_CSV), None)
    if expected is None:
        raise ValueError("The comparison has no inventoried scores")
    path = root / SCORES_CSV
    if (
        path.is_symlink()
        or path.stat().st_size != expected["bytes"]
        or sha256_file(path) != expected["sha256"]
    ):
        raise ValueError("Saved method scores changed")
    labels = tuple(source["subject_labels"])
    methods = manifest["methods"]
    dimensions = {
        m["method_id"]: min(
            m["available_dimensions"], manifest["analysis"]["exported_score_dimensions"]
        )
        for m in methods
    }
    scores = _read_v03_scores(
        path, method_ids=tuple(dimensions), subject_labels=labels, method_dimensions=dimensions
    )
    if sha256_file(path) != expected["sha256"]:
        raise ValueError("Method scores changed while loading")
    return labels, methods, scores


def saved_method_views(run):
    """Merge completed method selections without hiding an older computed method."""
    roots = sorted(
        (run / "analysis").glob("reference-shape-space-comparison*"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    labels, methods, scores, notices = None, {}, {}, []
    for root in roots:
        if not (root / COMPARISON_MANIFEST).is_file():
            continue
        try:
            artifact = verify_reference_shape_space_comparison(root)
            current, metadata, values = read_method_views(artifact, run)
            if labels is not None and labels != current:
                raise ValueError("Specimen order differs between saved method selections")
            labels = current
            for method in metadata:
                key = method["method_id"]
                if key not in scores or values[key].shape[1] > scores[key].shape[1]:
                    methods[key], scores[key] = method, values[key]
        except (OSError, RuntimeError, ValueError, KeyError) as error:
            notices.append(f"{root.name}: {error}")
    return ((labels, list(methods.values()), scores) if labels is not None else None), notices


def mesh_glyphs(records, scores, cancelled=None):
    from diffeoforge.analysis.pca_media_rendering import faces, points, read_mesh

    if not records or len(records) > 2000:
        raise ValueError("No supported reconstruction cohort is available")
    scores = np.asarray(scores, dtype=np.float64)
    if scores.shape != (len(records), 3) or not np.isfinite(scores).all():
        raise ValueError("Three finite method coordinates are required for every specimen")

    def check(record):
        if cancelled is not None and cancelled.is_set():
            raise InterruptedError("3D display preparation cancelled")
        path, size, digest = record
        if path.is_symlink() or path.stat().st_size != size or sha256_file(path) != digest:
            raise ValueError("A reconstruction changed since result verification")

    for record in records:
        check(record)
    key = tuple((str(path.resolve()), size, digest) for path, size, digest in records)
    with _GEOMETRY_LOCK:
        cached = _GEOMETRY.get(key)
        if cached is not None:
            _GEOMETRY.move_to_end(key)
            return scores, *cached, None
    meshes, reference, ids, topology = [], None, None, None
    budget = max(8, min(128, 24000 // max(1, len(records))))
    for record in records:
        path, size, digest = record
        check(record)
        mesh = read_mesh(path)
        current = faces(mesh)
        if len(current) == 0 or not np.isfinite(points(mesh)).all():
            raise ValueError("Reconstruction has no finite display surface")
        if reference is None:
            reference = current.copy()
            ids, topology = glyph_topology(mesh, budget)
        if not np.array_equal(reference, current):
            raise ValueError("Reconstruction topology differs from the atlas basis")
        meshes.append(points(mesh)[ids])
        if sha256_file(path) != digest:
            raise ValueError("A reconstruction changed while its display mesh was loaded")
    vertices = np.asarray(meshes)
    for record in records:
        check(record)
    vertices.setflags(write=False)
    topology.setflags(write=False)
    with _GEOMETRY_LOCK:
        _GEOMETRY[key] = (vertices, topology)
        while len(_GEOMETRY) > 2:
            _GEOMETRY.popitem(last=False)
    return scores, vertices, topology, None


class Method3DDialog(QDialog):
    def __init__(self, review, labels, scores, method, parent=None):
        super().__init__(parent)
        self.setWindowTitle(method["label"] + " · 3D")
        self.resize(1000, 760)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.review, self.method = review, method
        self.cancelled = Event()
        layout = QVBoxLayout(self)
        self.viewer = Morphospace3D(self)
        self.viewer.canvas.axis_prefix = axis_prefix(method["method_id"])
        self.viewer.canvas.method_label = method["label"]
        layout.addWidget(self.viewer, 1)
        self.export = QPushButton("Export current view…")
        self.export.clicked.connect(self._export)
        self.export_task = MediaExportController(self)
        self.export_task.active_changed.connect(lambda active: self.export.setEnabled(not active))
        self.export_task.finished.connect(
            lambda path: self.viewer.status.setText(f"Saved {path.name}")
        )
        self.export_task.failed.connect(
            lambda error: QMessageBox.warning(self, "Export failed", error)
        )
        layout.addWidget(self.export)
        layout.addWidget(QLabel("Mesh positions use saved scores; mesh size is for display."))
        by_name = {item.subject_name: item for item in review.registration_qc}
        if set(labels) != set(by_name):
            raise ValueError("Method specimens differ from the loaded atlas reconstructions")
        records = []
        for label in labels:
            artifact = review.artifact(by_name[label].reconstruction_artifact_key)
            records.append((artifact.path, artifact.bytes, artifact.sha256))
        self.viewer.labels = list(labels)
        if getattr(parent, "mesh_images", None) is not None:
            parent.apply_mesh_images(self)
        self.viewer.future = _WORK.submit(mesh_glyphs, tuple(records), scores, self.cancelled)
        self.viewer.status.setText("Loading verified reconstruction display meshes…")
        self.viewer.timer.start()

    def closeEvent(self, event):
        self.cancelled.set()
        self.viewer.clear()
        super().closeEvent(event)

    def _export(self):
        try:
            image = self.viewer.canvas.snapshot()
            name, selected = QFileDialog.getSaveFileName(
                self, "Export 3D method view", "method-3d.png", "PNG (*.png);;JPEG (*.jpg *.jpeg)"
            )
            if name:
                path = Path(name)
                if not path.suffix:
                    path = path.with_suffix(".jpg" if selected.startswith("JPEG") else ".png")
                self.export_task.start(path, image=image, protected=(self.review.run_directory,))
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "Export unavailable", str(error))


class MethodResultsPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.review = self.result = self.future = None
        self.mesh_images = None
        self.dialogs = []
        self._saved = False
        layout = QVBoxLayout(self)
        controls = QHBoxLayout()
        self.methods, self.x_axis, self.y_axis = QComboBox(), QComboBox(), QComboBox()
        self.methods.currentIndexChanged.connect(self._method)
        self.x_axis.currentIndexChanged.connect(self._plot)
        self.y_axis.currentIndexChanged.connect(self._plot)
        controls.addWidget(QLabel("Method"))
        controls.addWidget(self.methods, 1)
        controls.addWidget(self.x_axis)
        controls.addWidget(self.y_axis)
        self.three_d = QPushButton("Open interactive 3D…")
        self.three_d.clicked.connect(self._three_d)
        controls.addWidget(self.three_d)
        self.export = QPushButton("Export plot…")
        self.export.clicked.connect(self._export)
        self.export_task = MediaExportController(self)
        self.export_task.active_changed.connect(
            lambda active: self.export.setEnabled(not active and self.result is not None)
        )
        self.export_task.finished.connect(self._export_finished)
        self.export_task.failed.connect(
            lambda error: QMessageBox.warning(self, "Export failed", error)
        )
        self._export_review = None
        controls.addWidget(self.export)
        layout.addLayout(controls)
        self.status = QLabel("Choose methods above to calculate or reopen their saved results.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.plot = QGraphicsView()
        self.plot.setScene(QGraphicsScene(self.plot))
        self.plot.setMinimumHeight(360)
        self.plot.setRenderHint(QPainter.RenderHint.Antialiasing)
        layout.addWidget(self.plot)
        self.timer = QTimer(self)
        self.timer.setInterval(50)
        self.timer.timeout.connect(self._poll)
        self.hide()
        self.three_d.setEnabled(False)
        self.export.setEnabled(False)

    def clear(self):
        self.timer.stop()
        if self.future is not None:
            self.future.cancel()
        self.review = self.result = self.future = None
        self._saved = False
        for dialog in list(self.dialogs):
            dialog.close()
        self.methods.clear()
        self.plot.scene().clear()
        self.three_d.setEnabled(False)
        self.export.setEnabled(False)
        self.hide()

    def set_mesh_images(self, labels, images, name, run):
        self.mesh_images = (list(labels), list(images), name, run)
        for dialog in list(self.dialogs):
            self.apply_mesh_images(dialog)

    def apply_mesh_images(self, dialog):
        if self.mesh_images is None:
            return
        labels, images, name, run = self.mesh_images
        if dialog.review.run_directory != run or set(dialog.viewer.labels) != set(labels):
            return
        by_label = dict(zip(labels, images, strict=True))
        dialog.viewer.set_images([by_label[label] for label in dialog.viewer.labels])
        dialog.viewer.canvas.mesh_view_label = name

    def load(self, artifact, review):
        self.clear()
        self.review = review

        def read():
            checked = verify_reference_shape_space_comparison(artifact.artifact_directory)
            return read_method_views(checked, review.run_directory)

        self.future = _WORK.submit(read)
        self.status.setText("Loading verified method scores…")
        self.show()
        self.timer.start()

    def load_saved(self, review):
        self.clear()
        self.review = review
        self._saved = True
        self.future = _WORK.submit(saved_method_views, review.run_directory)
        self.status.setText("Verifying saved method results…")
        self.show()
        self.timer.start()

    def _poll(self):
        if self.future is None or not self.future.done():
            return
        self.timer.stop()
        try:
            self.result = self.future.result()
            notices = []
            if self._saved:
                self.result, notices = self.result
            self.status.setToolTip("\n".join(notices))
            if self.result is None:
                if notices:
                    raise ValueError(
                        "Saved method results failed verification; see details in the tooltip."
                    )
                self.hide()
                return
            self.methods.blockSignals(True)
            for method in self.result[1]:
                self.methods.addItem(method["label"], method["method_id"])
            self.methods.blockSignals(False)
            self.export.setEnabled(self.export_task.future is None)
            self._method()
        except (OSError, RuntimeError, ValueError, KeyError) as error:
            self.status.setText(f"Method results unavailable: {error}")

    def _method(self):
        if self.result is None or self.methods.currentData() is None:
            return
        key = self.methods.currentData()
        dimensions = self.result[2][key].shape[1]
        self.x_axis.blockSignals(True)
        self.y_axis.blockSignals(True)
        self.x_axis.clear()
        self.y_axis.clear()
        for index in range(min(10, dimensions)):
            label = f"{axis_prefix(key)}{index + 1}"
            self.x_axis.addItem(label, index)
            self.y_axis.addItem(label, index)
        self.y_axis.setCurrentIndex(min(1, dimensions - 1))
        self.x_axis.blockSignals(False)
        self.y_axis.blockSignals(False)
        self.three_d.setEnabled(dimensions >= 3)
        self.three_d.setToolTip("Requires at least three saved coordinates per specimen.")
        self._plot()

    def _plot(self):
        if self.result is None or self.methods.currentData() is None:
            return
        key = self.methods.currentData()
        x, y = self.x_axis.currentData(), self.y_axis.currentData()
        if x is None or y is None:
            return
        method = next(m for m in self.result[1] if m["method_id"] == key)
        self.status.setText(
            f"{method['label']} · {self.result[2][key].shape[1]} saved axes. "
            "Hover for specimen scores."
        )
        scene = self.plot.scene()
        scene.clear()
        scene.setBackgroundBrush(QColor("white"))
        values = self.result[2][key][:, [x, y]]
        low, high = values.min(0), values.max(0)
        span = np.maximum(high - low, 1e-12)
        for index, value in enumerate(values):
            pos = (value - low) / span * [740, -440]
            item = scene.addEllipse(
                float(pos[0]) - 4, float(pos[1]) - 4, 8, 8, brush=QBrush(QColor("#167c6b"))
            )
            item.setToolTip(
                f"{self.result[0][index]} · {axis_prefix(key)}{x + 1}: {value[0]:.8g} · "
                f"{axis_prefix(key)}{y + 1}: {value[1]:.8g}"
            )
        for j in range(6):
            a, b = low + (high - low) * j / 5
            scene.addSimpleText(f"{a:.4g}").setPos(j * 148 - 16, 15)
            scene.addSimpleText(f"{b:.4g}").setPos(-95, -j * 88 - 8)
        scene.addSimpleText(f"{axis_prefix(key)}{x + 1}").setPos(340, 55)
        scene.addSimpleText(f"{axis_prefix(key)}{y + 1}").setPos(-95, -490)
        scene.addSimpleText(method["label"]).setPos(0, -505)
        scene.setSceneRect(scene.itemsBoundingRect().adjusted(-20, -20, 20, 20))
        self.plot.fitInView(scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def _three_d(self):
        if self.result is None or self.review is None:
            return
        key = self.methods.currentData()
        method = next(m for m in self.result[1] if m["method_id"] == key)
        try:
            for opened in list(self.dialogs):
                opened.close()
            dialog = Method3DDialog(
                self.review, self.result[0], self.result[2][key][:, :3], method, self
            )
            self.dialogs.append(dialog)
            dialog.destroyed.connect(
                lambda: self.dialogs.remove(dialog) if dialog in self.dialogs else None
            )
            dialog.show()
        except (OSError, ValueError, KeyError) as error:
            QMessageBox.warning(self, "3D unavailable", str(error))

    def _export(self):
        if self.result is None:
            return
        image = QImage(2000, 1400, QImage.Format.Format_RGB32)
        image.fill(QColor("white"))
        painter = QPainter(image)
        self.plot.scene().render(painter, QRectF(10, 10, 1980, 1380), self.plot.sceneRect())
        painter.end()
        name, selected = QFileDialog.getSaveFileName(
            self, "Export method plot", "method.png", "PNG (*.png);;JPEG (*.jpg *.jpeg)"
        )
        if name:
            try:
                path = Path(name)
                if not path.suffix:
                    path = path.with_suffix(".jpg" if selected.startswith("JPEG") else ".png")
                self._export_review = self.review
                self.export_task.start(path, image=image, protected=(self.review.run_directory,))
            except (OSError, ValueError) as error:
                QMessageBox.warning(self, "Export failed", str(error))

    def _export_finished(self, path):
        if self.review is self._export_review:
            self.status.setText(f"Saved {path.name}")
