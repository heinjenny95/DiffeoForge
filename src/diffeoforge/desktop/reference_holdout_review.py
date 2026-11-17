"""Read-only local-miss review of original and fixed-template holdout surfaces."""

from __future__ import annotations

import hashlib
import json
import math
import stat
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import numpy as np
from PySide6.QtCore import QObject, QRunnable, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from diffeoforge.desktop.activity import ActivityPool
from diffeoforge.desktop.calibration_comparison_widget import CalibrationComparisonCanvas3D
from diffeoforge.desktop.mesh_preview import MeshPreviewModel, load_mesh_preview
from diffeoforge.mesh import TriangleMesh, read_vtk_polydata_with_metadata, sha256_file
from diffeoforge.mesh_filter_worker import mesh_filter_cancellation
from diffeoforge.reference_fit_search import distances_to_surface, surface_samples
from diffeoforge.reference_holdout_study import (
    HOLDOUT_DIGEST,
    HOLDOUT_MANIFEST,
    ReferenceHoldoutStudySnapshot,
    load_reference_holdout_study,
)
from diffeoforge.result_report import collect_run_report

_SAMPLES = 2048
_MAX_FLAGS_PER_DIRECTION = 3
_MIN_NEARBY_SUPPORT = 4
_MAX_MESH_BYTES = 128 * 1024**2
_MAX_MANIFEST_BYTES = 16 * 1024**2


@dataclass(frozen=True)
class SurfaceFlag:
    center: tuple[float, float, float]
    direction: str
    peak_distance: float
    support: int


@dataclass(frozen=True)
class HoldoutOverlay:
    original: MeshPreviewModel
    reconstruction: MeshPreviewModel
    flags: tuple[SurfaceFlag, ...] | None
    threshold: float
    screen_error: str | None


def _check_cancelled(cancelled: Callable[[], bool]) -> None:
    if cancelled():
        raise InterruptedError("Holdout review cancelled.")


def _bound_path(root: Path, value: str, prefix: tuple[str, ...]) -> Path:
    relative = PurePosixPath(value)
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or relative.parts[:len(prefix)] != prefix
        or "\\" in value
        or ":" in value
    ):
        raise ValueError("A bound holdout path falls outside its expected directory.")
    path = root
    for part in relative.parts:
        path /= part
        flags = getattr(path.lstat(), "st_file_attributes", 0)
        if path.is_symlink() or flags & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise ValueError("A bound holdout path contains a link.")
    if not path.is_file():
        raise ValueError("A bound holdout file is missing.")
    return path


def _unique_record(records: Sequence[Mapping], field: str, value: str) -> Mapping:
    matches = [record for record in records if record.get(field) == value]
    if len(matches) != 1:
        raise ValueError("A required holdout artifact has a missing or ambiguous identity.")
    return matches[0]


def load_bound_surface(path: Path, digest: str, size: int) -> TriangleMesh:
    """Read and verify the exact full geometry used for surface screening."""
    if not 0 < size <= _MAX_MESH_BYTES or path.stat().st_size != size:
        raise ValueError("A surface changed size or exceeds the 128 MiB review limit.")
    metadata, mesh = read_vtk_polydata_with_metadata(path)
    if metadata.sha256 != digest:
        raise ValueError("A surface has changed since the sealed run.")
    return mesh


def _direction_flags(points, distance, direction, threshold, radius):
    active = np.flatnonzero(distance > threshold)
    if len(active) < _MIN_NEARBY_SUPPORT:
        return []
    active = active[np.lexsort((active, -distance[active]))]
    flagged = points[active]
    used = np.zeros(len(flagged), dtype=bool)
    flags = []
    for index, point in enumerate(flagged):
        if used[index]:
            continue
        offsets = flagged - point
        neighbors = ~used & (np.einsum("ij,ij->i", offsets, offsets) <= radius**2)
        support = int(np.count_nonzero(neighbors))
        if support < _MIN_NEARBY_SUPPORT:
            continue
        used[neighbors] = True
        flags.append(SurfaceFlag(
            tuple(float(value) for value in point), direction,
            float(distance[active[index]]), support,
        ))
        if len(flags) == _MAX_FLAGS_PER_DIRECTION:
            break
    return flags


def screen_surface_misses(
    original: TriangleMesh,
    reconstruction: TriangleMesh,
    threshold: float,
    *,
    cancelled: Callable[[], bool],
) -> tuple[SurfaceFlag, ...]:
    """Flag nearby groups of sampled discrepancies in both directions."""
    if not math.isfinite(threshold) or threshold <= 0:
        raise ValueError("The frozen holdout margin is unavailable.")
    diagonal = float(np.linalg.norm(np.ptp(np.asarray(original.vertices), axis=0)))
    if not math.isfinite(diagonal) or diagonal <= 0:
        raise ValueError("The original surface has no finite extent.")
    radius = max(diagonal * 0.05, threshold * 2)
    flags = []
    with mesh_filter_cancellation(cancelled):
        for source, target, direction in (
            (original, reconstruction, "Original surface missed"),
            (reconstruction, original, "Extra reconstructed surface"),
        ):
            _check_cancelled(cancelled)
            points = surface_samples(source.vertices, source.triangles, count=_SAMPLES)
            distance = distances_to_surface(points, target.vertices, target.triangles)
            flags.extend(_direction_flags(points, distance, direction, threshold, radius))
    return tuple(flags)


def load_holdout_overlay(
    snapshot: ReferenceHoldoutStudySnapshot,
    finalist: str,
    subject: str,
    *,
    cancelled: Callable[[], bool],
) -> HoldoutOverlay:
    """Bind one visualization and its diagnostic to the frozen holdout records."""
    _check_cancelled(cancelled)
    root = snapshot.study_directory
    with (root / HOLDOUT_MANIFEST).open("rb") as stream:
        raw = stream.read(_MAX_MANIFEST_BYTES + 1)
    if len(raw) > _MAX_MANIFEST_BYTES:
        raise ValueError("The holdout design exceeds the review size limit.")
    digest = hashlib.sha256(raw).hexdigest()
    current = load_reference_holdout_study(root)
    if (root / HOLDOUT_DIGEST).read_text(encoding="utf-8").strip() != digest:
        raise ValueError("The holdout design changed during review.")
    if current != snapshot or current.status != "completed" or current.assessment is None:
        raise ValueError("Reopen the completed holdout before reviewing its anatomy.")
    if subject not in current.heldout_subjects or finalist not in current.finalist_ids:
        raise ValueError("Select a frozen finalist and a reserved holdout specimen.")
    design = json.loads(raw)
    selected_runs = [row for row in current.runs if row.finalist_id == finalist]
    if len(selected_runs) != 1:
        raise ValueError("The finalist's fixed-template run is ambiguous.")
    selected = selected_runs[0]
    if selected.run_directory is None or selected.status != "completed":
        raise ValueError("The finalist's fixed-template run is incomplete.")
    frozen_run = _unique_record(design["runs"], "run_id", selected.run_id)
    frozen_model = _unique_record(design["trained_models"], "finalist_id", finalist)
    _check_cancelled(cancelled)
    run = selected.run_directory
    report = collect_run_report(run)
    optimization = report.manifest["effective_config"]["optimization"]
    if (
        report.result.get("status") != "completed"
        or any(check.status != "pass" for check in report.checks)
        or report.manifest["source_config"]["sha256"] != frozen_run["config_sha256"]
        or optimization["freeze_template"] is not True
        or optimization["freeze_control_points"] is not True
    ):
        raise ValueError("The sealed registration does not verify against the frozen design.")

    source = _unique_record(report.manifest["inputs"], "role", "template")
    controls = [
        row for row in report.manifest["protected_artifacts"]
        if str(row.get("path", "")).startswith("input/control-points/")
    ]
    if (
        source["geometry"]["sha256"] != frozen_model["template"]["sha256"]
        or len(controls) != 1
        or controls[0]["sha256"] != frozen_model["control_points"]["sha256"]
    ):
        raise ValueError("The run's staged template or controls differ from its frozen model.")
    staged_template = _bound_path(run, source["staged_path"], ("input", "template"))
    staged_controls = _bound_path(run, controls[0]["path"], ("input", "control-points"))
    if (
        sha256_file(staged_template) != frozen_model["template"]["sha256"]
        or sha256_file(staged_controls) != frozen_model["control_points"]["sha256"]
    ):
        raise ValueError("The staged frozen model bytes changed since registration.")
    frozen_inputs = {row["filename"]: row["sha256"] for row in design["subjects"]}
    inputs = [row for row in report.manifest["inputs"] if row.get("role") == "subject"]
    staged_inputs = {PurePosixPath(row["staged_path"]).name: row for row in inputs}
    if (
        len(frozen_inputs) != len(design["subjects"])
        or len(staged_inputs) != len(inputs)
        or {name: row["geometry"]["sha256"] for name, row in staged_inputs.items()}
        != frozen_inputs
        or set(frozen_inputs) != set(current.heldout_subjects)
    ):
        raise ValueError("The run's staged inputs differ from the reserved cohort.")
    original = staged_inputs[subject]
    original_path = _bound_path(run, original["staged_path"], ("input", "subjects"))
    object_id = report.manifest["effective_config"]["model"]["object_id"]
    marker = f"__Reconstruction__{object_id}__subject_{subject}.vtk"
    fits = [row for row in report.inventory if PurePosixPath(row["path"]).name.endswith(marker)]
    if len(fits) != 1:
        raise ValueError("The heldout specimen needs one verified final reconstruction.")
    fit = fits[0]
    fit_path = _bound_path(run, "output/" + fit["path"], ("output",))
    _check_cancelled(cancelled)
    source_mesh = load_bound_surface(
        original_path, frozen_inputs[subject], original["geometry"]["bytes"],
    )
    fit_mesh = load_bound_surface(fit_path, fit["sha256"], fit["bytes"])
    threshold = float(current.assessment.practical_error_margin)
    try:
        flags = screen_surface_misses(source_mesh, fit_mesh, threshold, cancelled=cancelled)
        screen_error = None
    except InterruptedError:
        raise
    except (OSError, RuntimeError, ValueError) as error:
        flags = None
        screen_error = str(error)
    del source_mesh, fit_mesh
    _check_cancelled(cancelled)
    original_preview = load_mesh_preview(original_path, triangle_budget=8_000)
    fit_preview = load_mesh_preview(fit_path, triangle_budget=8_000)
    if original_preview.sha256 != frozen_inputs[subject] or fit_preview.sha256 != fit["sha256"]:
        raise ValueError("A holdout surface changed while its preview was loading.")
    return HoldoutOverlay(original_preview, fit_preview, flags, threshold, screen_error)


class _ReviewSignals(QObject):
    succeeded = Signal(object)
    failed = Signal(str)


class _ReviewWorker(QRunnable):
    def __init__(self, snapshot, finalist, subject) -> None:
        super().__init__()
        self.signals = _ReviewSignals()
        self.cancelled = threading.Event()
        self.selection = (snapshot, finalist, subject)

    @Slot()
    def run(self) -> None:
        try:
            overlay = load_holdout_overlay(*self.selection, cancelled=self.cancelled.is_set)
        except Exception as error:
            self.signals.failed.emit(str(error))
        else:
            self.signals.succeeded.emit(overlay)


class ReferenceHoldoutReviewDialog(QDialog):
    """Inspect a finalist and heldout specimen without writing any decisions."""

    def __init__(self, snapshot: ReferenceHoldoutStudySnapshot, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Review holdout anatomy")
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.resize(960, 740)
        self._snapshot = snapshot
        self._pool = ActivityPool(self)
        self._worker = None
        self._layout = QVBoxLayout(self)

        self.finalist = QComboBox()
        self.finalist.addItems(snapshot.finalist_ids)
        self.subject = QComboBox()
        self.subject.addItems(snapshot.heldout_subjects)
        if snapshot.assessment is not None and snapshot.assessment.preferred_finalist_id:
            self.finalist.setCurrentText(snapshot.assessment.preferred_finalist_id)
        self.load_button = QPushButton("Load verified overlay")
        self.load_button.setObjectName("primary")
        self.load_button.clicked.connect(self._load)
        selectors = QHBoxLayout()
        for label, combo in (("Finalist", self.finalist), ("Reserved specimen", self.subject)):
            selector_label = QLabel(label)
            selector_label.setBuddy(combo)
            selectors.addWidget(selector_label)
            selectors.addWidget(combo, 1)
            combo.currentIndexChanged.connect(self._clear)
        selectors.addWidget(self.load_button)
        self._layout.addLayout(selectors)
        self._layout.addWidget(self._pool.indicator)

        self.canvas = CalibrationComparisonCanvas3D(show_inspection_hints=False)
        self.canvas.original_detail.hide()
        self.canvas.setAccessibleName("Original and frozen-template holdout reconstruction")
        self._layout.addWidget(self.canvas, 1)
        controls = QHBoxLayout()
        for label, toggle in (
            ("Original wireframe", self.canvas.set_show_original),
            ("Reconstructed surface", self.canvas.set_show_reconstruction),
        ):
            checkbox = QCheckBox(label)
            checkbox.setChecked(True)
            checkbox.toggled.connect(toggle)
            controls.addWidget(checkbox)
        controls.addStretch()
        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        controls.addWidget(close)
        self._layout.addLayout(controls)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self._layout.addWidget(self.status)
        self._clear()

    @Slot()
    def _clear(self) -> None:
        self.canvas.clear()
        self.status.setText("Pick a reserved specimen and a finalist to inspect the overlay.")

    @Slot()
    def _load(self) -> None:
        if self._worker is not None:
            return
        self.canvas.clear()
        self.status.setText("Verifying saved holdout evidence and measuring local surface misses…")
        worker = _ReviewWorker(
            self._snapshot, self.finalist.currentText(), self.subject.currentText(),
        )
        self._worker = worker
        worker.signals.succeeded.connect(self._show_overlay)
        worker.signals.failed.connect(self._failed)
        self._enable_selection(False)
        self._pool.start(worker)

    def _enable_selection(self, enabled: bool) -> None:
        self.finalist.setEnabled(enabled)
        self.subject.setEnabled(enabled)
        self.load_button.setEnabled(enabled)

    @Slot(object)
    def _show_overlay(self, result: HoldoutOverlay) -> None:
        self._worker = None
        self._enable_selection(True)
        self.canvas.set_models(result.original, result.reconstruction)
        self.canvas.set_inspection_markers({
            str(index): flag.center for index, flag in enumerate(result.flags or (), start=1)
        })
        if result.flags is None:
            text = f"Local surface screening unavailable. {result.screen_error}"
        elif result.flags:
            flags = [
                f"{index}. {flag.direction} ({flag.peak_distance:.4g} mesh units)"
                for index, flag in enumerate(result.flags, start=1)
            ]
            text = "Inspect marked regions. " + " · ".join(flags)
        else:
            text = "The sampled screen located no cluster of substantial surface misses."
        self.status.setText(
            f"{text}\nFrozen numerical margin {result.threshold:.4g} mesh units. "
            "Small features can escape both sampling and the reduced display. "
            "Review anatomical correspondence directly."
        )

    @Slot(str)
    def _failed(self, message: str) -> None:
        self._worker = None
        self._enable_selection(True)
        self.status.setText(f"Verified holdout overlay unavailable. {message}")

    def done(self, result: int) -> None:
        if self._worker is not None:
            self._worker.cancelled.set()
        super().done(result)
