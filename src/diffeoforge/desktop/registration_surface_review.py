"""On-demand surface discrepancy markers for the verified Step 5 specimen."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from diffeoforge.desktop.calibration_comparison_widget import CalibrationComparisonCanvas3D
from diffeoforge.desktop.reference_holdout_review import (
    SurfaceFlag,
    load_bound_surface,
    screen_surface_misses,
)
from diffeoforge.desktop.result_review import ModernResultReview, verify_result_artifact

_THRESHOLD_FRACTION = 0.01


@dataclass(frozen=True)
class LocalSurfaceCheck:
    original_sha256: str
    reconstruction_sha256: str
    flags: tuple[SurfaceFlag, ...]
    threshold: float


def check_registration_surface(
    review: ModernResultReview,
    subject: str,
    *,
    cancelled: Callable[[], bool],
) -> LocalSurfaceCheck:
    """Screen the exact selected original and final reconstruction in atlas coordinates."""
    subjects = [item for item in review.registration_qc if item.subject_name == subject]
    if len(subjects) != 1:
        raise ValueError("The selected specimen has no unique verified reconstruction pair.")
    item = subjects[0]
    meshes = []
    digests = []
    for key in (item.original_artifact_key, item.reconstruction_artifact_key):
        if cancelled():
            raise InterruptedError("Surface check cancelled.")
        artifact = review.artifact(key)
        if artifact.kind != "vtk":
            raise ValueError("The selected specimen requires two bound surfaces.")
        path = verify_result_artifact(review, key)
        meshes.append(load_bound_surface(path, artifact.sha256, artifact.bytes))
        digests.append(artifact.sha256)
    span = np.ptp(np.asarray(meshes[0].vertices), axis=0)
    threshold = float(np.linalg.norm(span)) * _THRESHOLD_FRACTION
    flags = screen_surface_misses(*meshes, threshold, cancelled=cancelled)
    return LocalSurfaceCheck(digests[0], digests[1], flags, threshold)


class _CheckSignals(QObject):
    finished = Signal(object, object, str)


class _LocalCheckWorker(QRunnable):
    def __init__(self, review: ModernResultReview, subject: str) -> None:
        super().__init__()
        self.signals = _CheckSignals()
        self.cancelled = threading.Event()
        self.review = review
        self.subject = subject

    @Slot()
    def run(self) -> None:
        try:
            result = check_registration_surface(
                self.review, self.subject, cancelled=self.cancelled.is_set,
            )
        except Exception as error:
            self.signals.finished.emit(self, None, str(error))
        else:
            self.signals.finished.emit(self, result, "")


class RegistrationSurfaceReview(QWidget):
    """Keep one disposable numerical check tied to the displayed evidence."""

    def __init__(
        self,
        canvas: CalibrationComparisonCanvas3D,
        selected: Callable[[], tuple[ModernResultReview | None, str | None]],
    ) -> None:
        super().__init__()
        self.canvas = canvas
        self._selected = selected
        self._review: ModernResultReview | None = None
        self._subject: str | None = None
        self._worker: _LocalCheckWorker | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.button = QPushButton("Check local surface differences…")
        self.button.setObjectName("secondary")
        self.button.clicked.connect(self._start)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.hide()
        layout.addWidget(self.button)
        layout.addWidget(self.status)
        self.hide()

    def sync_selection(self) -> None:
        review, subject = self._selected()
        if review is not self._review or subject != self._subject:
            self.cancel()
            self._review, self._subject = review, subject
            self.canvas.set_inspection_markers({})
            self.status.clear()
            self.status.hide()
        available = review is not None and subject is not None
        self.setVisible(available)
        self.button.setEnabled(available and self._worker is None)

    def cancel(self) -> None:
        if self._worker is not None:
            self._worker.cancelled.set()

    @Slot()
    def _start(self) -> None:
        self.sync_selection()
        if self._worker is not None or self._review is None or self._subject is None:
            return
        worker = _LocalCheckWorker(self._review, self._subject)
        self._worker = worker
        worker.signals.finished.connect(self._finished)
        self.button.setEnabled(False)
        self.canvas.set_inspection_markers({})
        self.status.setText("Measuring both verified surfaces…")
        self.status.show()
        QThreadPool.globalInstance().start(worker)

    @Slot(object, object, str)
    def _finished(self, worker: _LocalCheckWorker, result: LocalSurfaceCheck | None,
                  error: str) -> None:
        self.sync_selection()
        if worker is not self._worker:
            return
        self._worker = None
        self.button.setEnabled(self._review is not None and self._subject is not None)
        if worker.cancelled.is_set():
            return
        if result is None:
            self.status.setText(f"Local surface check unavailable. {error}")
            return
        original = self.canvas.original_model
        reconstruction = self.canvas.reconstruction_model
        if (
            original is None or reconstruction is None
            or original.sha256 != result.original_sha256
            or reconstruction.sha256 != result.reconstruction_sha256
        ):
            self.status.setText("Load the verified pair again to locate the measured differences.")
            return
        markers = {str(index): flag.center for index, flag in enumerate(result.flags, start=1)}
        self.canvas.set_inspection_markers(markers)
        details = (
            "\n".join(f"{index}. {flag.direction} ({flag.peak_distance:.4g})"
                      for index, flag in enumerate(result.flags, start=1))
            if result.flags else "No cluster exceeded the sampled inspection threshold."
        )
        self.status.setText(
            f"{details}\nNumerical threshold {result.threshold:.4g} mesh units "
            "(1% of the original bounding-box diagonal). Inspect small features directly."
        )
