"""Lightweight observation of a running pilot candidate."""

from dataclasses import dataclass, field
from pathlib import Path
from threading import Event, Lock, Thread

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QCheckBox, QFrame, QHBoxLayout, QLabel, QVBoxLayout

from diffeoforge.desktop.calibration_comparison_widget import CalibrationComparisonCanvas3D
from diffeoforge.desktop.preview_mesh_loader import PreviewMeshLoader

POLL_MS = 10_000
_UNAVAILABLE = object()


def _release(binding):
    from diffeoforge.pilot_live_frames import release

    try:
        release(binding)
    except (OSError, ValueError):
        pass  # The short lease also expires without renewal.


@dataclass(eq=False)
class _Attempt:
    run: Path
    request_id: str
    iteration_offset: int
    _lock: Lock = field(default_factory=Lock)
    _closed: Event = field(default_factory=Event)
    _binding: object | None = None

    def read(self, after_iteration):
        from diffeoforge.pilot_live_frames import prepare, read_frame

        with self._lock:
            if self._closed.is_set():
                return None
            if self._binding is None:
                # The manifest and engine assets are published together. Check
                # before prepare so promotion during its call can be retried.
                published = (self.run / "manifest.json").is_file()
                self._binding = prepare(self.run, self.request_id)
                if self._binding is None and published:
                    return _UNAVAILABLE
            if self._binding is not None and not self._closed.is_set():
                return read_frame(self._binding, after_iteration)
        return None

    def close(self):
        self._closed.set()
        # Let an in-flight renewal finish before removing its request.
        if self._lock.locked() or self._binding is not None:
            Thread(target=self._release_binding, daemon=True).start()

    def _release_binding(self):
        with self._lock:
            binding, self._binding = self._binding, None
        if binding is not None:
            _release(binding)


class PilotLivePreviewPanel(QFrame):
    """Only the current attempt can publish a frame to this viewport."""

    def __init__(self, parent=None, *, active=lambda: True):
        super().__init__(parent)
        self.setObjectName("card")
        self._active = active
        self._attempt = None
        self._frame = None
        self._busy = False

        body = QVBoxLayout(self)
        header = QHBoxLayout()
        title = QLabel("Live fit preview")
        title.setObjectName("sectionTitle")
        header.addWidget(title)
        self.status = QLabel()
        self.status.setWordWrap(True)
        header.addWidget(self.status, 1)
        self.control_points = QCheckBox("Show control points")
        self.control_points.setToolTip(
            "Show sampled control points at the deformation endpoint for this snapshot."
        )
        self.control_points.setEnabled(False)
        self.control_points.toggled.connect(self._show_control_points)
        header.addWidget(self.control_points)
        body.addLayout(header)

        self.canvas = CalibrationComparisonCanvas3D(show_inspection_hints=False)
        self.canvas.setAccessibleName("Reduced overlay of the current fit and its target")
        self.canvas.setMinimumHeight(200)
        self.canvas.original_detail.hide()
        self.canvas.fullResolutionReadyChanged.connect(self._update_iteration_label)
        body.addWidget(self.canvas, 1)

        self._loader = PreviewMeshLoader(self)
        self._loader.activity_changed.connect(self._set_busy)
        self._loader.loaded.connect(self._loaded)
        self._loader.failed.connect(self._failed)
        self._timer = QTimer(self)
        self._timer.setInterval(POLL_MS)
        self._timer.timeout.connect(self.poll)
        self.hide()

    def set_run(self, run, request_id, *, iteration_offset=0):
        if (self._attempt is not None and self._attempt.run == run
                and self._attempt.request_id == request_id):
            return
        self.clear()
        self._attempt = _Attempt(run, request_id, iteration_offset)
        self.status.setText("Waiting for the first accepted snapshot…")
        self.show()
        self._timer.start()
        QTimer.singleShot(0, self.poll)

    def clear(self):
        self._timer.stop()
        attempt, self._attempt = self._attempt, None
        if attempt is not None:
            attempt.close()
        self._loader.cancel()
        self._frame = None
        self.control_points.setEnabled(False)
        self.canvas.clear()
        self.canvas.hide()
        self.hide()

    def poll(self):
        attempt = self._attempt
        if attempt is None:
            return
        if not self._active():
            self.clear()
        elif (not self._busy and self.isVisible() and not self.window().isMinimized()
              and not self.visibleRegion().isEmpty()):
            after = self._frame.iteration if self._frame is not None else -1
            self._loader.request_operation(attempt, lambda: attempt.read(after))

    def _set_busy(self, busy):
        self._busy = busy

    def _loaded(self, attempt, frame):
        if attempt is not self._attempt or frame is None or not self._active():
            return
        if frame is _UNAVAILABLE:
            self._timer.stop()
            self.status.setText("Live preview is unavailable for this run.")
            return
        if self._frame is not None and frame.iteration <= self._frame.iteration:
            return
        self._frame = frame
        self.canvas.set_models(frame.target, frame.fit, keep_viewport=True)
        self.control_points.setEnabled(frame.controls is not None and len(frame.controls) > 0)
        self._show_control_points()
        self.canvas.show()

    def _failed(self, attempt, _error):
        if attempt is self._attempt and self._frame is None:
            self.status.setText("Waiting for an available snapshot…")

    def _show_control_points(self, *_):
        points = None
        if self._frame is not None and self.control_points.isChecked():
            points = self._frame.controls
        self.canvas.set_control_points(points)

    def _update_iteration_label(self):
        if self._attempt is not None and self._frame is not None and self.canvas.comparison_ready:
            iteration = self._attempt.iteration_offset + self._frame.iteration
            self.status.setText(f"Accepted iteration {iteration} · reduced overlay")
