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
from diffeoforge.desktop.media_export import export_media
from diffeoforge.desktop.morphospace_3d import Morphospace3D

_EXPORTS = ThreadPoolExecutor(max_workers=1, thread_name_prefix="media-export")


class MediaView(QGraphicsView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.auto_fit = True

    def wheelEvent(self, event):  # noqa: N802
        self.auto_fit = False
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        if 0.05 < self.transform().m11() * factor < 30:
            self.scale(factor, factor)
        event.accept()

    def image(self, path):
        self.auto_fit = True
        self.scene().clear()
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            raise ValueError("Visualization image could not be decoded")
        self.scene().addPixmap(pixmap)
        self.scene().setSceneRect(self.scene().itemsBoundingRect())
        self.fitInView(self.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        if self.auto_fit and not self.sceneRect().isEmpty():
            self.fitInView(self.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        if self.auto_fit and not self.sceneRect().isEmpty():
            self.fitInView(self.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)


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

    def __init__(self, parent=None):
        super().__init__(parent)
        self.directory = None
        self._zip_record = None
        self._items = []
        self._specimen_labels = []
        self._thumbnails = {}
        self._records = {}
        self._export_future = None
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
                    'Mean and ±2 SD: native shooting. Movies: 17 native samples. '
                    'Rendering details are saved in media.json.'
                ),
            )
        )
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)
        self.plot_combo, self.plot_view = self._picture_tab("Mesh PCA")
        self.plot_combo.addItem("PC1 / PC2", (0, 1))
        self.plot_combo.addItem("PC2 / PC3", (1, 2))
        self.plot_combo.currentIndexChanged.connect(self._show_plot)
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
        self.slider.sliderMoved.connect(self.player.setPosition)
        self.player.positionChanged.connect(self.slider.setValue)
        self.player.durationChanged.connect(lambda value: self.slider.setRange(0, value))
        self.player.errorOccurred.connect(
            lambda _error, text: self.status.setText(f"Video: {text}")
        )
        controls.addWidget(self.play)
        controls.addWidget(self.slider, 1)
        video_layout.addLayout(controls)
        self.tabs.addTab(video_page, "Videos · six views")
        self.tabs.currentChanged.connect(lambda index: self.player.pause() if index != 3 else None)
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
        self.directory = None
        self._zip_record = None
        self._items = []
        self._thumbnails.clear()
        self.export.setEnabled(False)
        self.export_current.setEnabled(False)
        self._records = {}
        self.morphospace.clear()
        for combo, view in ((self.sd_combo, self.sd_view), (self.heat_combo, self.heat_view)):
            combo.clear()
            view.scene().clear()
        self.plot_view.scene().clear()
        self.video_combo.clear()

    def load(self, directory: Path):
        # The background preparation worker has verified the complete inventory.
        # Switching pages never repeats mesh parsing, native Shooting or rendering.
        if self.directory == directory:
            return
        self.clear()
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
        for item in self._items:
            image = QImage()
            import base64

            image.loadFromData(base64.b64decode(item["image"].split(",", 1)[1]))
            if image.isNull():
                raise ValueError("Mesh PCA thumbnail could not be decoded")
            self._thumbnails[item["id"]] = QPixmap.fromImage(image).scaled(
                100,
                90,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        for path in sorted((gallery / "figures").glob("*.png")):
            if path.stem.endswith("-SD"):
                self.sd_combo.addItem(path.stem.replace("-SD", " · −2 SD / Mean / +2 SD"), path)
            elif "displacement" in path.stem:
                self.heat_combo.addItem(path.stem.replace("-", " "), path)
        for path in sorted((gallery / "videos").glob("*.mp4")):
            self.video_combo.addItem(path.stem.replace("-", " "), path)
        self._show_plot()
        self.export.setEnabled(self._export_future is None)
        self.export_current.setEnabled(self._export_future is None)
        display_record = self._records.get("morphospace-3d.npz")
        self.morphospace.canvas.method_label = str(metadata["pca_method"])
        if display_record is not None:
            self.morphospace.load(
                directory / "morphospace-3d.npz", self._specimen_labels,
                expected=display_record,
                scores=[item["scores"][:3] for item in self._items],
            )
        else:
            self.morphospace.status.setText("Prepare media again to add a verified 3D view.")
        self.status.setText("Saved PCA · mean and ±2 SD · six synchronized views")

    def _show_plot(self):
        if not self._items:
            return
        x, y = self.plot_combo.currentData()
        if any(len(item["scores"]) <= max(x, y) for item in self._items):
            self.plot_view.scene().clear()
            return
        values = [(item["scores"][x], item["scores"][y]) for item in self._items]
        ranges = [max(p[k] for p in values) - min(p[k] for p in values) for k in (0, 1)]
        scene = self.plot_view.scene()
        scene.clear()
        left = min(v[0] for v in values) / max(ranges[0], 1e-12) * 1000
        top = -max(v[1] for v in values) / max(ranges[1], 1e-12) * 700
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
        for item, (a, b) in zip(self._items, values, strict=True):
            pixmap = self._thumbnails[item["id"]]
            glyph = scene.addPixmap(pixmap)
            glyph.setOffset(-pixmap.width() / 2, -pixmap.height() / 2)
            glyph.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
            glyph.setPos(a / max(ranges[0], 1e-12) * 1000, -b / max(ranges[1], 1e-12) * 700)
            label = (
                self._specimen_labels[item["id"] - 1]
                if len(self._specimen_labels) >= item["id"]
                else f"Mesh {item['id']}"
            )
            glyph.setToolTip(f"{label} · PC{x + 1}: {a:.6g} · PC{y + 1}: {b:.6g}")
        scene.setSceneRect(scene.itemsBoundingRect().adjusted(-80, -80, 80, 80))
        self.plot_view.auto_fit = True
        self.plot_view.fitInView(scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def _show_image(self, combo, view):
        if combo.currentData() is not None:
            view.image(combo.currentData())

    def _select_video(self):
        self.player.stop()
        self.video.clear()
        path = self.video_combo.currentData()
        self.player.setSource(QUrl.fromLocalFile(str(path)) if path else QUrl())

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
        super().hideEvent(event)

    def _play_pause(self):
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def _export(self):
        if self.directory is None:
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
        self._start_export(target, source=source, expected=self._zip_record)

    def _export_current(self):
        if self.directory is None or self._export_future is not None:
            return
        index = self.tabs.currentIndex()
        source = None
        image = None
        filters = "PNG (*.png);;JPEG (*.jpg *.jpeg)"
        name = "morphospace.png"
        try:
            if index == 3:
                source = self.video_combo.currentData()
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
        self._export_future = _EXPORTS.submit(
            export_media, target, protected=(self.directory, self._source_run), **kwargs
        )
        self._export_timer.start()

    def _export_finished(self):
        if self._export_future is None or not self._export_future.done():
            return
        self._export_timer.stop()
        future, self._export_future = self._export_future, None
        try:
            target = future.result()
            self.status.setText(f"Exported: {target.name}")
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "Export failed", str(error))
            self.status.setText("Export failed. Choose another destination or prepare media again.")
        self.export.setEnabled(self.directory is not None)
        self.export_current.setEnabled(self.directory is not None)
