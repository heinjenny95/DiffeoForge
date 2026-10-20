"""In-app cached mesh morphospace, SD views, heatmaps and six-view video playback."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PySide6.QtCore import QRectF, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer, QVideoSink
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QGraphicsItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSlider,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from diffeoforge.desktop.info_disclosure import InfoDisclosure
from diffeoforge.desktop.media_comparison import VideoComparison
from diffeoforge.desktop.media_export import export_media
from diffeoforge.desktop.mesh_view import MeshViewController, mesh_view_button
from diffeoforge.desktop.morphospace_3d import Morphospace3D

_EXPORTS = ThreadPoolExecutor(max_workers=1, thread_name_prefix="media-export")


class MediaView(QGraphicsView):
    hovered = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.auto_fit = True
        self.fit_width = False
        self.setMouseTracking(True)

    def mouseMoveEvent(self, event):  # noqa: N802
        super().mouseMoveEvent(event)
        item = self.itemAt(event.position().toPoint())
        self.hovered.emit(str(item.data(0) or "") if item is not None else "")

    def leaveEvent(self, event):  # noqa: N802
        self.hovered.emit("")
        super().leaveEvent(event)

    def wheelEvent(self, event):  # noqa: N802
        self.auto_fit = False
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        if 0.05 < self.transform().m11() * factor < 30:
            self.scale(factor, factor)
        event.accept()

    def image(self, path):
        self.auto_fit = True
        self.fit_width = False
        self.scene().clear()
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            raise ValueError("Visualization image could not be decoded")
        self.scene().addPixmap(pixmap)
        self.scene().setSceneRect(self.scene().itemsBoundingRect())
        self.fit_content()

    def fit_content(self):
        if self.fit_width and self.sceneRect().width() > 0:
            self.resetTransform()
            factor = max(0.05, (self.viewport().width() - 24) / self.sceneRect().width())
            self.scale(factor, factor)
            self.verticalScrollBar().setValue(self.verticalScrollBar().minimum())
        else:
            self.fitInView(self.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        if self.auto_fit and not self.sceneRect().isEmpty():
            self.fit_content()

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        if self.auto_fit and not self.sceneRect().isEmpty():
            self.fit_content()


class ResponsiveMediaImage(QLabel):
    """Keep inline SD rows in the available card width at every window size/DPI."""

    def __init__(self, path, parent=None):
        super().__init__(parent)
        self.original = QPixmap(str(path))
        self.setMinimumWidth(1)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        if not self.original.isNull():
            scaled = self.original.scaledToWidth(
                max(1, self.width()), Qt.TransformationMode.SmoothTransformation
            )
            self.setPixmap(scaled)
            self.setFixedHeight(scaled.height())


class VisualizationPanel(QWidget):
    retry_requested = Signal()
    cancel_requested = Signal()
    view_applied = Signal(object)
    mesh_images_applied = Signal(object, object, str, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.directory = None
        self.base_directory = None
        self._zip_record = None
        self._items = []
        self._specimen_labels = []
        self._thumbnails = {}
        self.mesh_views = MeshViewController(self)
        self.mesh_views.all_media = True
        self.mesh_views.media_changed.connect(self._use_media)
        self.mesh_views.images_changed.connect(self._mesh_images_changed)
        self.mesh_views.busy_changed.connect(self._view_busy)
        self._records = {}
        self._export_future = None
        self._view_preparing = False
        self._export_timer = QTimer(self)
        self._export_timer.setInterval(50)
        self._export_timer.timeout.connect(self._export_finished)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        title = QLabel("Visualization")
        title.setObjectName("title")
        layout.addWidget(title)
        self.status = QLabel("Open a reviewed atlas result to view its PCA media.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        actions = QHBoxLayout()
        self.retry = QPushButton("Retry media preparation")
        self.retry.clicked.connect(self.retry_requested)
        self.retry.hide()
        self.cancel = QPushButton("Cancel preparation")
        self.cancel.clicked.connect(self.cancel_requested)
        self.cancel.hide()
        self.export = QPushButton("Export gallery ZIP…")
        self.export.setObjectName("primary")
        self.export.setEnabled(False)
        self.export.clicked.connect(self._export)
        actions.addWidget(self.retry)
        actions.addWidget(self.cancel)
        actions.addStretch()
        self.export_current = QPushButton("Export current view…")
        self.export_current.setEnabled(False)
        self.export_current.clicked.connect(self._export_current)
        actions.addWidget(self.export_current)
        actions.addWidget(self.export)
        layout.addLayout(actions)
        layout.addWidget(
            InfoDisclosure(
                "Methods",
                (
                    "Mean and ±2 SD: native shooting. Movies: 17 native samples. "
                    "Rendering details are saved in media.json."
                ),
            )
        )
        self.tabs = QTabWidget()
        self.mesh_view_controls = QWidget()
        view_controls = QHBoxLayout(self.mesh_view_controls)
        view_controls.setContentsMargins(0, 0, 0, 0)
        view_controls.addWidget(
            mesh_view_button(
                self.mesh_views,
                lambda: self._specimen_labels,
                self,
            )
        )
        self.mesh_view_status = QLabel("Choose which surface faces you.")
        self.mesh_view_status.setTextFormat(Qt.TextFormat.PlainText)
        self.mesh_views.status_changed.connect(self.mesh_view_status.setText)
        view_controls.addWidget(self.mesh_view_status, 1)
        self.mesh_size_label = QLabel("Mesh size")
        view_controls.addWidget(self.mesh_size_label)
        self.mesh_size = QSlider(Qt.Orientation.Horizontal)
        self.mesh_size.setRange(30, 180)
        self.mesh_size.setValue(90)
        self.mesh_size.setMaximumWidth(130)
        self.mesh_size.valueChanged.connect(self._show_plot)
        view_controls.addWidget(self.mesh_size)
        layout.addWidget(self.mesh_view_controls)
        self.tabs.currentChanged.connect(lambda index: self.mesh_size.setVisible(index == 0))
        self.tabs.currentChanged.connect(lambda index: self.mesh_size_label.setVisible(index == 0))
        layout.addWidget(self.tabs, 1)
        self.plot_combo, self.plot_view = self._picture_tab("Mesh PCA")
        self.plot_combo.addItem("PC1 / PC2", (0, 1))
        self.plot_combo.addItem("PC1 / PC3", (0, 2))
        self.plot_combo.addItem("PC2 / PC3", (1, 2))
        self.plot_combo.addItem("All pairs", "all")
        self.plot_combo.currentIndexChanged.connect(self._show_plot)
        self.hover_label = QLabel()
        self.hover_label.setTextFormat(Qt.TextFormat.PlainText)
        self.plot_view.parentWidget().layout().addWidget(self.hover_label)
        self.plot_view.hovered.connect(self.hover_label.setText)
        self.sd_combo, self.sd_view = self._picture_tab("±2 SD")
        self.heat_combo, self.heat_view = self._picture_tab("Heatmaps")
        heat_legend = QLabel("Displacement · model units. Signed: along mean normal +, against −.")
        self.heat_view.parentWidget().layout().insertWidget(1, heat_legend)
        self.sd_combo.currentIndexChanged.connect(
            lambda: self._show_image(self.sd_combo, self.sd_view)
        )
        self.heat_combo.currentIndexChanged.connect(
            lambda: self._show_image(self.heat_combo, self.heat_view)
        )
        video_page = QWidget()
        video_layout = QVBoxLayout(video_page)
        self.video_combo = QComboBox()
        self.video_combo.currentIndexChanged.connect(self._select_video)
        video_layout.addWidget(self.video_combo)
        self.video = QLabel()
        self.video.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.video.setMinimumHeight(300)
        video_layout.addWidget(self.video, 1)
        self.video_comparison = VideoComparison()
        video_layout.addWidget(self.video_comparison, 1)
        self.video_comparison.hide()
        self.video_comparison.failed.connect(lambda text: self.status.setText(f"Video: {text}"))
        self.player = QMediaPlayer(self)
        self.player.setLoops(QMediaPlayer.Loops.Infinite)
        self.audio = QAudioOutput(self)
        self.audio.setMuted(True)
        self.player.setAudioOutput(self.audio)
        self.video_sink = QVideoSink(self)
        self.player.setVideoSink(self.video_sink)
        self.video_sink.videoFrameChanged.connect(self._video_frame)
        controls = QHBoxLayout()
        self.play = QPushButton("Play / Pause")
        self.play.clicked.connect(self._play_pause)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.sliderMoved.connect(self._seek_video)
        self.player.positionChanged.connect(
            lambda value: (
                self.slider.setValue(value) if self.video_combo.currentData() != "all" else None
            )
        )
        self.player.durationChanged.connect(
            lambda value: (
                self.slider.setRange(0, value) if self.video_combo.currentData() != "all" else None
            )
        )
        self.video_comparison.position_changed.connect(self.slider.setValue)
        self.video_comparison.duration_changed.connect(lambda value: self.slider.setRange(0, value))
        self.player.errorOccurred.connect(
            lambda _error, text: self.status.setText(f"Video: {text}")
        )
        controls.addWidget(self.play)
        controls.addWidget(self.slider, 1)
        video_layout.addLayout(controls)
        self.tabs.addTab(video_page, "Videos · six views")
        self.tabs.currentChanged.connect(lambda index: self.player.pause() if index != 3 else None)
        self.tabs.currentChanged.connect(
            lambda index: self.video_comparison.pause() if index != 3 else None
        )
        self.morphospace = Morphospace3D()
        self.tabs.addTab(self.morphospace, "3D · PC1–PC3")

    def _picture_tab(self, title):
        page = QWidget()
        layout = QVBoxLayout(page)
        combo, view = QComboBox(), MediaView()
        layout.addWidget(combo)
        layout.addWidget(view, 1)
        self.tabs.addTab(page, title)
        return combo, view

    def set_busy(self, text):
        self.retry.hide()
        self.cancel.show()
        self.status.setText(text)

    def clear(self):
        self.cancel.hide()
        self.player.stop()
        self.player.setSource(QUrl())
        self.video_comparison.clear()
        self.directory = None
        self.base_directory = None
        self._zip_record = None
        self._items = []
        self._thumbnails.clear()
        self.mesh_views.clear()
        self.export.setEnabled(False)
        self.export_current.setEnabled(False)
        self._records = {}
        self.morphospace.clear()
        for combo, view in ((self.sd_combo, self.sd_view), (self.heat_combo, self.heat_view)):
            combo.clear()
            view.scene().clear()
        self.plot_view.scene().clear()
        self.hover_label.clear()
        self.video_combo.clear()

    def load(self, directory: Path):
        # The background preparation worker has verified the complete inventory.
        # Switching pages never repeats mesh parsing, native Shooting or rendering.
        if self.base_directory == directory:
            return
        self.clear()
        self.base_directory = directory
        self._use_media(directory)
        self.mesh_views.load(
            directory, [item["scores"][:3] for item in self._items], self._full_images
        )

    def _use_media(self, directory):
        # Called only after every medium in the derivative has verified successfully.
        selections = [
            combo.currentText() for combo in (self.sd_combo, self.heat_combo, self.video_combo)
        ]
        self.player.stop()
        self.player.setSource(QUrl())
        self.video_comparison.clear()
        for combo in (self.sd_combo, self.heat_combo, self.video_combo):
            combo.blockSignals(True)
            combo.clear()
        self._thumbnails.clear()
        self.directory = directory
        gallery = directory / "PCA-Gallery"
        metadata = json.loads((directory / "media.json").read_text(encoding="utf-8"))
        self._records = {r["path"]: r for r in metadata["files"]}
        self._source_run = Path(metadata["source_run"])
        self._specimen_labels = metadata.get("specimen_labels", [])
        self._zip_record = next(
            (r for r in metadata["files"] if r["path"] == "PCA-Gallery.zip"), None
        )
        if self._zip_record is None:
            raise ValueError("Verified sharing archive is not inventoried")
        self._items = json.loads((gallery / "mesh-pca.json").read_text())
        full_images = []
        for item in self._items:
            image = QImage()
            import base64

            image.loadFromData(base64.b64decode(item["image"].split(",", 1)[1]))
            if image.isNull():
                raise ValueError("Mesh PCA thumbnail could not be decoded")
            full_images.append(image)
            self._thumbnails[item["id"]] = QPixmap.fromImage(image)
        self._full_images = full_images
        for path in sorted((gallery / "figures").glob("*.png")):
            if path.stem.endswith("-SD"):
                self.sd_combo.addItem(path.stem.replace("-SD", " · −2 SD / Mean / +2 SD"), path)
            elif "displacement" in path.stem:
                self.heat_combo.addItem(path.stem.replace("-", " "), path)
        for path in sorted((gallery / "videos").glob("*.mp4")):
            self.video_combo.addItem(path.stem.replace("-", " "), path)
        for combo, selection in zip(
            (self.sd_combo, self.heat_combo, self.video_combo), selections, strict=True
        ):
            if combo.count() > 1:
                combo.addItem("All · side by side", "all")
            previous = combo.findText(selection)
            if previous >= 0:
                combo.setCurrentIndex(previous)
            combo.blockSignals(False)
        self._show_image(self.sd_combo, self.sd_view)
        self._show_image(self.heat_combo, self.heat_view)
        self._select_video()
        self._show_plot()
        self.export.setEnabled(self._export_future is None)
        self.export_current.setEnabled(self._export_future is None)
        display_record = self._records.get("morphospace-3d.npz")
        self.morphospace.canvas.method_label = str(metadata["pca_method"])
        if display_record is not None:
            self.morphospace.load(
                directory / "morphospace-3d.npz",
                self._specimen_labels,
                expected=display_record,
                scores=[item["scores"][:3] for item in self._items],
                images=full_images,
            )
        else:
            self.morphospace.status.setText("Prepare media again to add a verified 3D view.")
        self.status.setText("Saved PCA · mean and ±2 SD · six synchronized views")
        self.view_applied.emit(directory)
        view_label = metadata.get("mesh_view", {}).get("name", "Original mesh view")
        self.mesh_images_applied.emit(
            self._specimen_labels, full_images, view_label, self._source_run
        )

    def _view_busy(self, busy):
        self._view_preparing = busy
        enabled = not busy and self.directory is not None and self._export_future is None
        self.export.setEnabled(enabled)
        self.export_current.setEnabled(enabled)

    def _mesh_images_changed(self, images):
        if len(images) != len(self._items):
            raise ValueError("Mesh views do not match the saved score rows")
        self._thumbnails = {
            item["id"]: QPixmap.fromImage(image)
            for item, image in zip(self._items, images, strict=True)
        }
        self.morphospace.set_images(images)
        self.morphospace.canvas.mesh_view_label = self.mesh_views.label
        self._show_plot()
        self.mesh_images_applied.emit(
            self._specimen_labels, images, self.mesh_views.label, self._source_run
        )

    def _show_plot(self):
        if not self._items:
            return
        selection = self.plot_combo.currentData()
        pairs = [(0, 1), (0, 2), (1, 2)] if selection == "all" else [selection]
        scene = self.plot_view.scene()
        scene.clear()
        self.hover_label.clear()
        for panel, pair in enumerate(pairs):
            self._draw_plot(pair, panel, len(pairs))
        scene.setSceneRect(scene.itemsBoundingRect().adjusted(-80, -80, 80, 80))
        self.plot_view.auto_fit = True
        self.plot_view.fitInView(scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def _draw_plot(self, pair, panel=0, count=1):
        x, y = pair
        if any(len(item["scores"]) <= max(x, y) for item in self._items):
            return
        values = [(item["scores"][x], item["scores"][y]) for item in self._items]
        ranges = [max(p[k] for p in values) - min(p[k] for p in values) for k in (0, 1)]
        scene = self.plot_view.scene()
        offset_x = panel * 1240 - min(v[0] for v in values) / max(ranges[0], 1e-12) * 1000
        offset_y = max(v[1] for v in values) / max(ranges[1], 1e-12) * 700
        left, top = panel * 1240, 0
        pen = QPen(QColor("#dfe9ec"))
        for j in range(6):
            scene.addLine(left + j * 200, top, left + j * 200, top + 700, pen)
            scene.addLine(left, top + j * 140, left + 1000, top + j * 140, pen)
            a = min(v[0] for v in values) + ranges[0] * j / 5
            b = max(v[1] for v in values) - ranges[1] * j / 5
            tx = scene.addSimpleText(f"{a:.3g}")
            tx.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
            tx.setPos(left + j * 200 - 15, top + 725)
            ty = scene.addSimpleText(f"{b:.3g}")
            ty.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
            ty.setPos(left - 70, top + j * 140)
        title = scene.addSimpleText(f"PC{x + 1} / PC{y + 1}")
        title.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
        title.setPos(left + 400, top - 60)
        caption = scene.addSimpleText("Mesh view: " + self.mesh_views.label)
        caption.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
        caption.setPos(left, top - 90)
        for item, (a, b) in zip(self._items, values, strict=True):
            pixmap = self._thumbnails[item["id"]].scaled(
                max(20, self.mesh_size.value() // count),
                max(20, self.mesh_size.value() // count),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            glyph = scene.addPixmap(pixmap)
            glyph.setOffset(-pixmap.width() / 2, -pixmap.height() / 2)
            glyph.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
            glyph.setPos(
                offset_x + a / max(ranges[0], 1e-12) * 1000,
                offset_y - b / max(ranges[1], 1e-12) * 700,
            )
            label = (
                self._specimen_labels[item["id"] - 1]
                if len(self._specimen_labels) >= item["id"]
                else f"Mesh {item['id']}"
            )
            glyph.setToolTip(f"{label} · PC{x + 1}: {a:.6g} · PC{y + 1}: {b:.6g}")
            glyph.setData(0, glyph.toolTip())

    def _show_image(self, combo, view):
        if combo.currentData() == "all":
            scene = view.scene()
            scene.clear()
            entries = [(combo.itemText(i), combo.itemData(i)) for i in range(combo.count() - 1)]
            if combo is self.heat_combo:
                entries.sort(key=lambda entry: (entry[1].stem.split("-", 1)[-1], entry[1].stem))
            for index, (title, path) in enumerate(entries):
                pixmap = QPixmap(str(path)).scaledToWidth(
                    1260, Qt.TransformationMode.SmoothTransformation
                )
                row, column = divmod(index, 3)
                x, y = column * 1300, row * 930
                label = scene.addSimpleText(title)
                label.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
                label.setPos(x, y)
                scene.addPixmap(pixmap).setPos(x, y + 40)
            scene.setSceneRect(scene.itemsBoundingRect().adjusted(-20, -20, 20, 20))
            view.auto_fit = True
            view.fit_width = True
            view.fit_content()
        elif combo.currentData() is not None:
            view.image(combo.currentData())

    def _select_video(self):
        self.player.stop()
        self.video.clear()
        path = self.video_combo.currentData()
        all_videos = path == "all"
        self.video.setVisible(not all_videos)
        self.video_comparison.setVisible(all_videos)
        self.video_comparison.pause()
        if all_videos:
            self.player.setSource(QUrl())
            self.video_comparison.load(
                [
                    (self.video_combo.itemText(i), self.video_combo.itemData(i))
                    for i in range(self.video_combo.count() - 1)
                ]
            )
            return
        self.player.setSource(QUrl.fromLocalFile(str(path)) if path else QUrl())

    def _seek_video(self, position):
        if self.video_combo.currentData() == "all":
            self.video_comparison.seek(position)
        else:
            self.player.setPosition(position)

    def _video_frame(self, frame):
        if frame.isValid():
            image = frame.toImage()
            if not image.isNull():
                self.video.setPixmap(
                    QPixmap.fromImage(image).scaled(
                        self.video.size(),
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )

    def hideEvent(self, event):  # noqa: N802
        self.player.pause()
        self.video_comparison.pause()
        super().hideEvent(event)

    def _play_pause(self):
        if self.video_combo.currentData() == "all":
            self.video_comparison.toggle()
            return
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def _export(self):
        if self.directory is None or self._view_preparing:
            return
        source = self.directory / "PCA-Gallery.zip"
        destination, _ = QFileDialog.getSaveFileName(
            self, "Export PCA gallery", "PCA-Gallery.zip", "ZIP (*.zip)"
        )
        if not destination:
            return
        target = Path(destination)
        if not target.suffix:
            target = target.with_suffix(".zip")
        if self.mesh_views.selected is not None and not self.mesh_views.all_media:
            self._start_export(
                target,
                source=source,
                expected=self._zip_record,
                mesh_view={
                    "items": self._items,
                    "images": list(self.mesh_views.images),
                    "rotation": self.mesh_views.rotation.copy(),
                    "name": self.mesh_views.label,
                },
            )
        else:
            self._start_export(target, source=source, expected=self._zip_record)

    def _export_current(self):
        if self.directory is None or self._export_future is not None or self._view_preparing:
            return
        index = self.tabs.currentIndex()
        source = None
        image = None
        filters = "PNG (*.png);;JPEG (*.jpg *.jpeg)"
        name = "morphospace.png"
        try:
            if index == 3:
                source = self.video_combo.currentData()
                if source == "all":
                    return self._export_video_comparison()
                filters, name = "MP4 (*.mp4)", source.name if source else "movie.mp4"
            elif index == 4:
                image = self.morphospace.canvas.snapshot()
            elif index == 0:
                scene = self.plot_view.scene()
                if scene.itemsBoundingRect().isEmpty():
                    raise ValueError("No plot is available for the selected components")
                image = QImage(2400, 1600, QImage.Format.Format_RGB32)
                image.fill(QColor("white"))
                painter = QPainter(image)
                scene.render(
                    painter,
                    QRectF(20, 20, 2360, 1560),
                    scene.sceneRect(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                )
                painter.end()
            else:
                combo = self.sd_combo if index == 1 else self.heat_combo
                source = combo.currentData()
                if source == "all":
                    view = self.sd_view if index == 1 else self.heat_view
                    height = max(
                        200,
                        min(
                            6000, round(3600 * view.sceneRect().height() / view.sceneRect().width())
                        ),
                    )
                    image = QImage(3600, height, QImage.Format.Format_RGB32)
                    image.fill(QColor("white"))
                    painter = QPainter(image)
                    view.scene().render(
                        painter,
                        QRectF(0, 0, 3600, height),
                        view.sceneRect(),
                        Qt.AspectRatioMode.KeepAspectRatio,
                    )
                    painter.end()
                    source = None
                if source:
                    name = source.name
                    filters += ";;PDF (*.pdf)"
            if image is None and source is None:
                raise ValueError("No saved medium is selected")
            destination, selected = QFileDialog.getSaveFileName(
                self, "Export current medium", name, filters
            )
            if not destination:
                return
            target = Path(destination)
            if not target.suffix:
                target = target.with_suffix(
                    ".mp4"
                    if index == 3
                    else ".jpg"
                    if selected.startswith("JPEG")
                    else ".pdf"
                    if selected.startswith("PDF")
                    else ".png"
                )
            if source is not None and index != 3:
                if target.suffix.lower() == ".pdf":
                    source = source.with_suffix(".pdf")
            expected = (
                self._records.get(source.relative_to(self.directory).as_posix()) if source else None
            )
            if source is not None and expected is None:
                raise ValueError("The selected saved medium is not in the verified inventory")
            self._start_export(target, source=source, image=image, expected=expected)
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "Export failed", str(error))

    def _start_export(self, target, **kwargs):
        if self._export_future is not None:
            return
        self.export.setEnabled(False)
        self.export_current.setEnabled(False)
        self.status.setText("Exporting…")
        self._export_source = self.directory
        protected = tuple(
            p for p in (self.base_directory, self.directory, self._source_run) if p is not None
        )
        selected_view = kwargs.pop("mesh_view", None)
        comparison = kwargs.pop("comparison", None)
        if comparison is not None:
            from diffeoforge.desktop.video_export import export_video_comparison

            self._export_future = _EXPORTS.submit(
                export_video_comparison,
                target,
                comparison,
                protected=protected,
            )
        elif selected_view is not None:
            from diffeoforge.desktop.mesh_view_export import export_oriented_gallery

            self._export_future = _EXPORTS.submit(
                export_oriented_gallery,
                target,
                protected=protected,
                **kwargs,
                **selected_view,
            )
        else:
            self._export_future = _EXPORTS.submit(
                export_media, target, protected=protected, **kwargs
            )
        self._export_timer.start()

    def _export_video_comparison(self):
        destination, _ = QFileDialog.getSaveFileName(
            self, "Export all videos", "PCs-side-by-side.mp4", "MP4 (*.mp4)"
        )
        if destination:
            target = Path(destination)
            if not target.suffix:
                target = target.with_suffix(".mp4")
            entries = []
            for i in range(self.video_combo.count() - 1):
                path = self.video_combo.itemData(i)
                entries.append((path, self._records[path.relative_to(self.directory).as_posix()]))
            self._start_export(target, comparison=entries)

    def _export_finished(self):
        if self._export_future is None or not self._export_future.done():
            return
        self._export_timer.stop()
        future, self._export_future = self._export_future, None
        try:
            target = future.result()
            if self.directory == self._export_source:
                self.status.setText(f"Exported: {target.name}")
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "Export failed", str(error))
            if self.directory == self._export_source:
                self.status.setText(
                    "Export failed. Choose another destination or prepare media again."
                )
        self._view_busy(self._view_preparing)
