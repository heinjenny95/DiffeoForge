"""Inspect what the joint pilot fit retains from a saved individual approval."""

from __future__ import annotations

import math
from contextlib import nullcontext
from pathlib import Path
from threading import Event

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from diffeoforge import pilot_form_progress, pilot_regions
from diffeoforge import reference_calibration_study as study
from diffeoforge import reference_guided_pilot as guided
from diffeoforge.desktop.calibration_comparison_widget import CalibrationComparisonCanvas3D
from diffeoforge.desktop.preview_mesh_loader import PreviewMeshLoader
from diffeoforge.desktop.reference_calibration_dialog import (
    _FullscreenPilotDialog,
    collect_calibration_qc_pairs,
)
from diffeoforge.mesh import sha256_file
from diffeoforge.mesh_filter_worker import mesh_filter_cancellation
from diffeoforge.surface_io import load_surface_mesh

_DIRECTIONS = (
    ("original_to_fit_p95", "Original → fit"),
    ("fit_to_original_p95", "Fit → original"),
)
_CHANGES = {
    "worse": "Farther in both repeats",
    "better": "Closer in both repeats",
    "unclear": "Change not resolved",
    "unavailable": "Incomplete coverage",
}
_PURPOSES = {"problem": "Correct", "fixed": "Keep in place", "preserve": "Keep shape"}


def _verified_surface(path, digest):
    loaded = load_surface_mesh(path)
    if not digest or loaded.metadata.sha256 != digest:
        raise ValueError("The saved mesh no longer matches its review")
    return loaded.geometry


def _subject_pair(snapshot, candidate, target):
    pairs = [p for p in collect_calibration_qc_pairs(snapshot.study_directory, candidate)
             if p.required and p.original_path.name == target]
    if len(pairs) != 1:
        raise ValueError("Expected one reviewed endpoint for the selected specimen")
    return pairs[0]


def measure_transfer(original, individual, shared, regions):
    """Compare matching original-space patches using two repeats in each direction."""
    before = pilot_regions.measure(original, individual, regions)
    after = pilot_regions.measure(original, shared, regions)
    rows = []
    for a, b in zip(before, after, strict=True):
        diagonal = a["diagonal"]
        if a["region"] != b["region"] or diagonal != b["diagonal"] or diagonal <= 0:
            raise ValueError("Local comparison requires the same original patch")
        directions = []
        floor = diagonal * 1e-6
        for key, label in _DIRECTIONS:
            ar, br = _repeat_range(a, key), _repeat_range(b, key)
            change = "unavailable"
            if ar is not None and br is not None:
                if br[0] > ar[1] * 1.05 + floor:
                    change = "worse"
                elif br[1] + floor < ar[0] * 0.95:
                    change = "better"
                else:
                    change = "unclear"
            directions.append(dict(label=label, individual=_percent(ar, diagonal),
                                   shared=_percent(br, diagonal), change=change))
        rows.append(dict(region=a["region"], directions=directions))
    return rows


def _repeat_range(result, key):
    values = [row.get(key) for row in result["repeats"]]
    if len(values) != 2 or any(v is None or not math.isfinite(v) or v < 0 for v in values):
        return None
    return min(values), max(values)


def _percent(values, diagonal):
    return tuple(100 * value / diagonal for value in values) if values is not None else None


def prepare_joint_transfer(directory, candidate_id, viewed_pair, marks, *, cancelled=None):
    """Reopen the exact shared endpoint and the approved singleton from the same pilot."""
    def check_cancelled():
        if cancelled is not None and cancelled():
            raise InterruptedError("Joint pilot comparison cancelled.")

    check_cancelled()
    target = viewed_pair.original_path.name
    with study.calibration_verification_scope():
        joint = study.load_reference_calibration_study(directory)
        info = guided.record(joint)
        if not info or info["phase"] != "joint" or target not in info["pilot_order"]:
            raise ValueError("Select a specimen from this pilot's completed joint check")
        candidate = next((c for c in joint.candidates if c.candidate_id == candidate_id), None)
        if candidate is None or candidate.status != "completed":
            raise ValueError("The shared fit has no completed endpoint")
        shared = _subject_pair(joint, candidate, target)
        if shared != viewed_pair:
            raise ValueError("The shared fit shown in the viewer changed. Reopen the joint review.")
        progress = pilot_form_progress.marker(joint)
        matches = [row for row in (progress or {}).get("reviews", ())
                   if row["filename"] == target]
        if len(matches) != 1:
            raise ValueError("This pilot has no verified individual approval for the selected form")
        approval = matches[0]
        guided.verify_approvals([approval])
        previous = study.load_reference_calibration_study(Path(approval["directory"]))
        previous_info = guided.record(previous)
        if (not previous_info or previous_info["phase"] == "joint"
                or previous.plan.pilot_subject_count != 1
                or Path(previous_info["origin"]).resolve() != Path(info["origin"]).resolve()):
            raise ValueError("The individual approval belongs to a different pilot or form")
        earlier = next(c for c in previous.candidates if c.candidate_id == approval["candidate_id"])
        individual = _subject_pair(previous, earlier, target)
        digest = individual.original_sha256
        if (not digest or digest != shared.original_sha256
                or sha256_file(shared.original_path) != digest):
            raise ValueError("Both fits must refer to the exact same original surface")

        saved_marks = previous.problem_regions.get(earlier.candidate_id, {}).get(target, [])
        chosen = saved_marks if marks is None else marks
        if not chosen:
            return individual, shared, []
        chosen = pilot_regions.validate({target: chosen}, {target: digest})[target]
        check_cancelled()
        original_geometry = _verified_surface(individual.original_path, digest)
        check_cancelled()
        individual_geometry = _verified_surface(individual.reconstruction_path,
                                                individual.reconstruction_sha256)
        check_cancelled()
        shared_geometry = _verified_surface(shared.reconstruction_path,
                                            shared.reconstruction_sha256)
        check_cancelled()
        check_scope = nullcontext() if cancelled is None else mesh_filter_cancellation(cancelled)
        with check_scope:
            evidence = measure_transfer(original_geometry, individual_geometry, shared_geometry,
                                        chosen)
        return individual, shared, evidence


class JointPilotTransferDialog(_FullscreenPilotDialog):
    """Linked overlays and local distances with no decision controls."""

    def __init__(self, parent, directory, candidate_id, pair, marks):
        super().__init__(parent)
        self.setWindowTitle("Compare individual and joint pilot fits")
        self.resize(1070, 730)
        self.setMinimumSize(560, 410)
        self.setProperty("processRecordingPilotReview", True)
        self._source = None
        layout = QVBoxLayout(self)
        title = QLabel(pair.original_path.name)
        title.setTextFormat(Qt.TextFormat.PlainText)
        title.setObjectName("title")
        title.setWordWrap(True)
        layout.addWidget(title)
        guidance = QLabel("Orange lines show the same original in both views. Blue shows the "
                          "saved fit. Drag either view to inspect the same area.")
        guidance.setWordWrap(True)
        layout.addWidget(guidance)
        self.canvases = tuple(CalibrationComparisonCanvas3D(
            self, show_inspection_hints=False) for _ in range(2))
        views = QHBoxLayout()
        for label, canvas in zip(("Approved individual", "Shared joint fit"), self.canvases,
                                 strict=True):
            column = QVBoxLayout()
            column.addWidget(QLabel(label))
            canvas.setMinimumHeight(180)
            canvas.original_detail.hide()
            column.addWidget(canvas, 1)
            views.addLayout(column, 1)
        layout.addLayout(views, 1)
        left, right = self.canvases
        left.cameraChanged.connect(right.set_linked_camera)
        right.cameraChanged.connect(left.set_linked_camera)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(("Area", "Distance sampled from", "Individual",
                                              "Shared", "Repeat comparison"))
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().hide()
        self.table.setMaximumHeight(180)
        self.table.hide()
        layout.addWidget(self.table)
        self.evidence_note = QLabel()
        self.evidence_note.setWordWrap(True)
        layout.addWidget(self.evidence_note)
        self.status = QLabel("Verifying saved fits and checking marked areas…")
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        footer = QHBoxLayout()
        footer.addWidget(self.full_screen_button)
        self.detail = QCheckBox("Load full detail (optional, slower)")
        self.detail.setEnabled(False)
        self.detail.toggled.connect(self._request_meshes)
        footer.addWidget(self.detail)
        footer.addStretch()
        close = QPushButton("Close comparison")
        close.clicked.connect(self.reject)
        footer.addWidget(close)
        layout.addLayout(footer)
        self._cache = Path(directory) / "display-cache"
        self.loader = PreviewMeshLoader(self)
        self.loader.loaded.connect(self._loaded)
        self.loader.failed.connect(self._failed)
        self.loader.activity_changed.connect(
            lambda busy: self.setProperty("processRecordingWaiting", busy))
        cancelled = Event()
        self.finished.connect(cancelled.set)
        self.finished.connect(self.loader.cancel)
        self.loader.request_operation("prepare", lambda: prepare_joint_transfer(
            directory, candidate_id, pair, marks, cancelled=cancelled.is_set))

    def _request_meshes(self, detail):
        paths, hashes, _ = self._source
        self.status.setText("Loading both verified overlays…")
        self.loader.request_paths(detail, paths, expected=hashes,
                                  pilot_cache=None if detail else self._cache)

    def _loaded(self, key, result):
        if key == "prepare":
            individual, shared, evidence = result
            self._source = (
                (individual.original_path, individual.reconstruction_path,
                 shared.reconstruction_path),
                (individual.original_sha256, individual.reconstruction_sha256,
                 shared.reconstruction_sha256), evidence,
            )
            self._request_meshes(False)
            return
        if key != self.detail.isChecked():
            return
        original, individual, shared = result
        _, _, evidence = self._source
        bounds = np.asarray([model.bounds for model in result])
        low, high = bounds[:, ::2].min(axis=0), bounds[:, 1::2].max(axis=0)
        markers = {chr(65 + i): tuple(row["region"]["center"]) for i, row in enumerate(evidence)}
        for canvas, fitted in zip(self.canvases, (individual, shared), strict=True):
            canvas.set_models(original, fitted)
            canvas.set_comparison_extent((low + high) / 2, float(max(high - low)))
            canvas.set_inspection_markers(markers)
            canvas.original_detail.setChecked(key)
        self._show_evidence(evidence)
        self.detail.setEnabled(True)
        self.status.clear()

    def _show_evidence(self, evidence):
        if not evidence:
            self.evidence_note.setText("No marked areas for this pair. Use the overlays to inspect "
                                       "the two fits.")
            return
        self.evidence_note.setText(
            "Each interval is P95 from two samples in the marked area, as a percentage of the "
            "original mesh diagonal. A change requires both repeat ranges to clear a 5% margin. "
            "Distances cannot establish anatomical correspondence.")
        self.table.setRowCount(2 * len(evidence))
        for index, row in enumerate(evidence):
            area = f"{chr(65 + index)} · {_PURPOSES[row['region'].get('purpose', 'problem')]}"
            for direction, values in enumerate(row["directions"]):
                cells = (area, values["label"], _range_label(values["individual"]),
                         _range_label(values["shared"]), _CHANGES[values["change"]])
                for column, value in enumerate(cells):
                    self.table.setItem(2 * index + direction, column, QTableWidgetItem(value))
        self.table.resizeColumnsToContents()
        self.table.show()

    def _failed(self, key, message):
        if key == "prepare" or key == self.detail.isChecked():
            self.status.setText("Comparison unavailable. " + message)
            if self._source is not None:
                self.detail.setEnabled(True)


def _range_label(values):
    return ("Unavailable" if values is None else f"{values[0]:.3g}–{values[1]:.3g}%")
