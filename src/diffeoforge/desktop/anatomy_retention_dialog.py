"""Read-only stage comparison of the same specimen against its approved anatomy."""

from threading import Event

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from diffeoforge.desktop.calibration_comparison_widget import CalibrationComparisonCanvas3D
from diffeoforge.desktop.notifications import notify
from diffeoforge.desktop.pilot_preview import load_pilot_preview
from diffeoforge.desktop.preview_mesh_loader import PreviewMeshLoader
from diffeoforge.desktop.reference_calibration_dialog import _FullscreenPilotDialog

_METRICS = {
    "p95": "Whole surface · P95",
    "p99": "Whole surface · P99",
    "original_to_fit_p95": "Original → fit · P95",
    "original_to_fit_p99": "Original → fit · P99",
    "fit_to_original_p95": "Fit → original · P95",
    "fit_to_original_p99": "Fit → original · P99",
    "fixed_material_p95": "Fixed area movement · P95",
    "fixed_material_max": "Fixed area movement · maximum",
}
_CHANGES = {
    "worse": "Farther",
    "better": "Closer",
    "unclear": "No resolved difference",
    "unavailable": "Unavailable",
}


def _interval(values):
    if values is None:
        return "Unavailable"
    low, high = values
    first, last = f"{low:.3g}", f"{high:.3g}"
    return f"{first}%" if first == last else f"{first}–{last}%"


def _verified_previews(surfaces):
    result = []
    for surface in surfaces:
        mesh = load_pilot_preview(surface.path)
        if mesh.sha256 != surface.sha256:
            raise ValueError("The saved surface changed. Reopen the stage comparison.")
        result.append(mesh)
    return tuple(result)


def _first_loss(report):
    """Open the earliest measured regression, giving recorded areas visual priority."""
    for stage in report.stages:
        if not stage.surface or stage.key == "approved":
            continue
        losses = [r for r in report.rows if r.stage_key == stage.key and r.change == "worse"]
        if losses:
            row = max(losses, key=lambda r: (r.area is not None, r.observed[0] - r.approved[1]))
            return stage.key, row.area
    latest = next(
        (s.key for s in reversed(report.stages) if s.surface and s.key != "approved"), None
    )
    return latest, None


class AnatomyRetentionDialog(_FullscreenPilotDialog):
    def __init__(self, parent, target, prepare):
        super().__init__(parent)
        self.setWindowTitle("Trace approved anatomy across stages")
        self.setProperty("processRecordingPilotReview", True)
        self.resize(1150, 795)
        self.setMinimumSize(500, 420)
        self.report = None
        self.models = ()
        self._cancel = Event()
        self.loader = PreviewMeshLoader(self)
        self.loader.loaded.connect(self._loaded)
        self.loader.failed.connect(self._failed)
        self.loader.activity_changed.connect(
            lambda busy: self.setProperty("processRecordingWaiting", busy)
        )
        self.finished.connect(lambda _result: self._cancel.set())
        self.finished.connect(self.loader.cancel)
        layout = QVBoxLayout(self)
        self.title = QLabel(target)
        self.title.setTextFormat(Qt.TextFormat.PlainText)
        self.title.setWordWrap(True)
        self.title.setObjectName("heading")
        layout.addWidget(self.title)
        self.summary = QLabel("Verifying the saved surfaces and measuring the approved areas…")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        controls = QHBoxLayout()
        self.stage = QComboBox()
        self.stage.setAccessibleName("Comparison stage")
        self.stage.currentIndexChanged.connect(self._select_stage)
        self.area = QComboBox()
        self.area.setAccessibleName("Focus on a saved area")
        self.area.currentIndexChanged.connect(self._select_area)
        controls.addWidget(QLabel("Stage"))
        controls.addWidget(self.stage, 1)
        controls.addWidget(QLabel("Area"))
        controls.addWidget(self.area, 1)
        layout.addLayout(controls)
        self.stage_note = QLabel()
        self.stage_note.setWordWrap(True)
        layout.addWidget(self.stage_note)
        self.canvases = tuple(
            CalibrationComparisonCanvas3D(self, show_inspection_hints=False) for _ in range(2)
        )
        self.current_label = QLabel("Selected stage")
        views = QHBoxLayout()
        for label, canvas in zip(
            (QLabel("Approved individual fit"), self.current_label), self.canvases, strict=True
        ):
            column = QVBoxLayout()
            column.addWidget(label)
            canvas.original_detail.hide()
            canvas.setMinimumSize(120, 110)
            column.addWidget(canvas, 1)
            views.addLayout(column, 1)
        layout.addLayout(views, 1)
        left, right = self.canvases
        left.cameraChanged.connect(right.set_linked_camera)
        right.cameraChanged.connect(left.set_linked_camera)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(
            ("Distance", "Approved fit", "Selected stage", "Change")
        )
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().hide()
        self.table.setMaximumHeight(170)
        layout.addWidget(self.table)
        legend = QLabel(
            "Orange shows the original specimen, blue the reconstruction. "
            "Distances are percentages of the original diagonal. Ranges show the two samples."
        )
        legend.setWordWrap(True)
        layout.addWidget(legend)
        footer = QHBoxLayout()
        footer.addWidget(self.full_screen_button)
        footer.addStretch()
        close = QPushButton("Close comparison")
        close.clicked.connect(self.reject)
        footer.addWidget(close)
        layout.addLayout(footer)
        self.loader.request_operation("report", lambda: prepare(cancelled=self._cancel.is_set))

    def _loaded(self, key, result):
        if key == "report":
            self.report = result
            notify(self, "Anatomy measurements ready", "Inspect the saved areas across stages.")
            self.summary.setText(result.summary)
            self.area.blockSignals(True)
            self.area.addItem("Whole shape", None)
            for index, region in enumerate(result.regions):
                purpose = {
                    "problem": "correct",
                    "fixed": "retain in place",
                    "preserve": "retain shape",
                }
                self.area.addItem(
                    f"{chr(65 + index)} · {purpose[region.get('purpose', 'problem')]}", index
                )
            self.stage.blockSignals(True)
            for stage in result.stages:
                if stage.key != "approved":
                    self.stage.addItem(stage.label, stage.key)
            stage_key, area_index = _first_loss(result)
            if stage_key:
                self.stage.setCurrentIndex(self.stage.findData(stage_key))
            if area_index is not None:
                self.area.setCurrentIndex(self.area.findData(area_index))
            self.area.blockSignals(False)
            self.stage.blockSignals(False)
            self._select_stage()
            return
        if key != self.stage.currentData():
            return
        self.models = result
        for canvas, model in zip(self.canvases, result[1:], strict=True):
            canvas.set_models(result[0], model)
        self._select_area()

    def _select_stage(self):
        self.loader.cancel()
        self.models = ()
        for canvas in self.canvases:
            canvas.set_inspection_markers({})
            canvas.clear()
        if self.report is None or self.stage.currentIndex() < 0:
            return
        stage = next(s for s in self.report.stages if s.key == self.stage.currentData())
        approved = next(s for s in self.report.stages if s.key == "approved")
        self.current_label.setText(stage.label)
        self.stage_note.setText(stage.reason)
        self._select_area()
        if approved.surface and stage.surface and self.report.original:
            surfaces = (self.report.original, approved.surface, stage.surface)
            self.loader.request_operation(stage.key, lambda: _verified_previews(surfaces))

    def _select_area(self):
        if self.report is None:
            return
        index = self.area.currentData()
        stage = self.stage.currentData()
        rows = [r for r in self.report.rows if r.area == index and r.stage_key == stage]
        self.table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            cells = (
                _METRICS[row.metric],
                _interval(row.approved),
                _interval(row.observed),
                _CHANGES[row.change],
            )
            for j, value in enumerate(cells):
                self.table.setItem(i, j, QTableWidgetItem(value))
        self.table.resizeColumnsToContents()
        if not self.models:
            return
        bounds = np.asarray([model.bounds for model in self.models])
        low, high = bounds[:, ::2].min(axis=0), bounds[:, 1::2].max(axis=0)
        center, scale = (low + high) / 2, float(max(high - low))
        markers = {}
        if index is not None:
            region = self.report.regions[index]
            center = np.asarray(region["center"], dtype=float)
            width = 2 * region["radius"]
            if "bounds" in region:
                box = np.asarray(region["bounds"]).reshape(3, 2)
                width = max(box[:, 1] - box[:, 0])
            scale = max(scale * 0.12, 2.5 * width)
            markers[chr(65 + index)] = tuple(center)
        for canvas in self.canvases:
            canvas.reset_view()
            canvas.set_comparison_extent(center, scale)
            canvas.set_inspection_markers(markers)

    def _failed(self, key, message):
        if key == "report":
            notify(self, "Anatomy check needs attention", "Open the comparison for details.",
                   warning=True)
            self.summary.setText("The saved stages could not be verified. " + message)
        elif key == self.stage.currentData():
            self.stage_note.setText("The overlay could not be opened. " + message)


def open_retention(parent, target, prepare):
    dialog = AnatomyRetentionDialog(parent, target, prepare)
    try:
        dialog.exec()
    finally:
        dialog.deleteLater()
