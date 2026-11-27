"""Lightweight observation of a running pilot candidate."""

from dataclasses import dataclass, field
from pathlib import Path
from threading import Event, Lock, Thread
from uuid import uuid4

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel, QVBoxLayout

from diffeoforge.desktop.calibration_comparison_widget import CalibrationComparisonCanvas3D
from diffeoforge.desktop.preview_mesh_loader import PreviewMeshLoader

POLL_MS = 10_000
_UNAVAILABLE = object()
_RESOLUTIONS = (("Light", 1_600), ("Balanced", 6_000), ("Detailed", 16_000))


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
    face_budget: int
    display_id: str = field(default_factory=lambda: uuid4().hex)
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
                self._binding = prepare(self.run, self.display_id, face_budget=self.face_budget)
                if self._binding is None and published:
                    return _UNAVAILABLE
            if self._binding is not None and not self._closed.is_set():
                return read_frame(self._binding, after_iteration)
        return None

    @property
    def binding(self):
        # Only read after the loader has returned; no UI wait on preparation.
        return self._binding

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
        self._displayed_attempt = None
        self._busy = False
        self._preferred_budget = 6_000

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

        options = QHBoxLayout()
        resolution_label = QLabel("Resolution")
        self.resolution = QComboBox()
        self.resolution.setObjectName("pilotLiveResolution")
        self.resolution.setAccessibleName("Live preview resolution")
        for label, budget in _RESOLUTIONS:
            self.resolution.addItem(f"{label} · up to {budget:,} triangles / surface", budget)
        self.resolution.setCurrentIndex(1)
        self.resolution.setToolTip(
            "Display only. Higher detail uses more preview preparation, transfer and rendering "
            "work. Snapshots still update at most once every 20 seconds."
        )
        resolution_label.setBuddy(self.resolution)
        options.addWidget(resolution_label)
        options.addWidget(self.resolution)
        options.addStretch(1)
        body.addLayout(options)
        self.resolution_note = QLabel("Display only. Snapshots update at most every 20 seconds.")
        self.resolution_note.setWordWrap(True)
        body.addWidget(self.resolution_note)
        self.mark_scope = QLabel()
        self.mark_scope.setWordWrap(True)
        self.mark_scope.hide()
        body.addWidget(self.mark_scope)
        self.resolution.currentIndexChanged.connect(self._resolution_changed)

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
        self._restore_resolution_choices()
        self._attempt = _Attempt(run, request_id, iteration_offset, self._preferred_budget)
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
        self._displayed_attempt = None
        self.control_points.setEnabled(False)
        self.mark_scope.clear()
        self.mark_scope.hide()
        self.canvas.clear()
        self.canvas.hide()
        self.hide()

    def _restore_resolution_choices(self):
        self.resolution.blockSignals(True)
        for index in range(self.resolution.count()):
            self.resolution.model().item(index).setEnabled(True)
        self.resolution.setCurrentIndex(self.resolution.findData(self._preferred_budget))
        self.resolution.blockSignals(False)
        self.resolution_note.setText(
            "Display only. Snapshots update at most every 20 seconds. "
            "Higher detail adds preview work."
        )

    def _resolution_changed(self, _index):
        budget = self.resolution.currentData()
        self._preferred_budget = budget
        previous = self._attempt
        if previous is None:
            return
        previous.close()
        self._loader.cancel()
        self._attempt = _Attempt(
            previous.run, previous.request_id, previous.iteration_offset, budget
        )
        if self._frame is None:
            self.status.setText("Preparing the selected preview resolution…")
        else:
            iteration = self._displayed_attempt.iteration_offset + self._frame.iteration
            self.status.setText(
                f"Switching resolution… Last snapshot: accepted iteration {iteration}."
            )
        # Keep the last correctly labelled frame and camera until its replacement
        # arrives. A fresh display identity rejects old-resolution frames.
        self._timer.start()
        QTimer.singleShot(0, self.poll)

    def _update_resolution_support(self, attempt):
        binding = attempt.binding
        if binding is None:
            return
        if getattr(binding, "legacy_runtime", False):
            self.resolution.blockSignals(True)
            self.resolution.setCurrentIndex(0)
            for index in range(1, self.resolution.count()):
                self.resolution.model().item(index).setEnabled(False)
            self.resolution.blockSignals(False)
            self.resolution_note.setText(
                "This prepared run supports Light only. Higher resolutions are available "
                "in newly prepared trials; the saved run is unchanged."
            )

    def poll(self):
        attempt = self._attempt
        if attempt is None:
            return
        if not self._active():
            self.clear()
        elif (not self._busy and self.isVisible() and not self.window().isMinimized()
              and not self.visibleRegion().isEmpty()):
            after = (self._frame.iteration if self._frame is not None
                     and self._displayed_attempt is attempt else -1)
            self._loader.request_operation(attempt, lambda: attempt.read(after))

    def _set_busy(self, busy):
        self._busy = busy

    def _loaded(self, attempt, frame):
        if attempt is not self._attempt or not self._active():
            return
        self._update_resolution_support(attempt)
        scope = getattr(attempt.binding, "region_scope", None)
        if scope:
            self.mark_scope.setText(scope["text"])
            self.mark_scope.show()
        if frame is None:
            return
        if frame is _UNAVAILABLE:
            self._timer.stop()
            self.status.setText("Live preview is unavailable for this run.")
            return
        if (self._displayed_attempt is attempt and self._frame is not None
                and frame.iteration <= self._frame.iteration):
            return
        self._frame = frame
        self._displayed_attempt = attempt
        self.canvas.set_models(frame.target, frame.fit, keep_viewport=True)
        if scope and scope["markers"]:
            markers, colors = {}, {}
            for role, caption, color in (
                ("active", "Active", "#ac391e"), ("fixed", "Fixed", "#147162"),
                ("shape", "Retain shape", "#147162"), ("waiting", "Queued", "#535c68"),
                ("previous", "Recheck", "#4c5292"),
            ):
                for name in scope[role]:
                    if name in scope["markers"]:
                        text = f"{name} · {caption}"
                        markers[text], colors[text] = scope["markers"][name], color
            self.canvas.set_inspection_markers(markers, colors=colors)
        self.control_points.setEnabled(frame.controls is not None and len(frame.controls) > 0)
        self._show_control_points()
        self.canvas.show()

    def _failed(self, attempt, _error):
        if attempt is self._attempt:
            self.status.setText("Waiting for an available snapshot…")

    def _show_control_points(self, *_):
        points = None
        if self._frame is not None and self.control_points.isChecked():
            points = self._frame.controls
        self.canvas.set_control_points(points)

    def _update_iteration_label(self):
        if (self._attempt is not None and self._displayed_attempt is self._attempt
                and self._frame is not None and self.canvas.comparison_ready):
            iteration = self._attempt.iteration_offset + self._frame.iteration
            self.status.setText(
                f"Accepted iteration {iteration} · "
                f"{len(self._frame.fit.triangles):,} / {len(self._frame.target.triangles):,} "
                "triangles (fit / target)"
            )
