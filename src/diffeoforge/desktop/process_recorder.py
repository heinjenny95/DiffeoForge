"""Opt-in, app-owned UI recording. It never captures the desktop or controls jobs."""

from __future__ import annotations

import queue
import threading
import time
import weakref
from pathlib import Path

import numpy as np
from PySide6.QtCore import (
    QEvent,
    QObject,
    QPoint,
    QSettings,
    QStandardPaths,
    Qt,
    QTimer,
    QUrl,
    Signal,
    Slot,
)
from PySide6.QtGui import QColor, QCursor, QDesktopServices, QImage, QPainter, QPen, QPolygon
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from shiboken6 import isValid

from diffeoforge.desktop.activity import ActivityIndicator
from diffeoforge.process_recording import FPS, SPEEDS, ProcessRecording, recover_recording

UNRESPONSIVE_SECONDS = 2.0


class _RecordingSignals(QObject):
    saved = Signal(object, object)
    failed = Signal(object, object)


def _default_settings():
    return QSettings("DiffeoForge", "ProcessRecording")


class _Encoder:
    def __init__(self, root, size, project, *, recovery=None):
        self.signals = _RecordingSignals()
        self.frames = queue.Queue(maxsize=6)
        self.stop = threading.Event()
        self.root, self.size, self.project, self.recovery = root, size, project, recovery
        self.end_time, self.reason = 0.0, "session"
        self.final_pauses = ()
        self.thread = threading.Thread(
            target=self._run, name="Process recording encoder", daemon=True
        )

    def finish(self, elapsed, project, reason, *, pauses=()):
        self.end_time, self.project, self.reason = elapsed, project, reason
        self.final_pauses = pauses
        self.stop.set()

    def _run(self):
        recording = None
        try:
            if self.recovery is not None:
                path = recover_recording(self.recovery, self.root, self.project)
                self.signals.saved.emit(self, (path, 0, True))
                return
            recording = ProcessRecording(self.root, self.size)
            while not self.stop.is_set() or not self.frames.empty():
                try:
                    elapsed, mode, image, pauses = self.frames.get(timeout=0.1)
                except queue.Empty:
                    continue
                pixels = np.frombuffer(image.constBits(), np.uint8, image.sizeInBytes())
                pixels = pixels.reshape(image.height(), image.bytesPerLine())
                pixels = (
                    pixels[:, : image.width() * 3].reshape(image.height(), image.width(), 3).copy()
                )
                recording.add(pixels, elapsed, mode, pauses=pauses)
            path = recording.finish(
                self.end_time, self.project, self.reason, pauses=self.final_pauses
            )
            self.signals.saved.emit(self, (path, recording.data["capture_gap_count"], False))
        except Exception as error:
            if recording is not None:
                try:
                    recording.fail(error)
                except Exception:
                    pass  # Keep the original failure and all sealed fragments.
            self.signals.failed.emit(self, str(error))


class ProcessRecorder(QObject):
    """Own the recording lifecycle separately from scientific ActivityPool workers."""

    def __init__(
        self, window, *, settings=None, staging_root=None, allowed=True, size=(1920, 1080)
    ):
        super().__init__(window)
        self.window = window
        self.settings = settings if settings is not None else _default_settings()
        self.root = (
            Path(staging_root)
            if staging_root is not None
            else Path(
                QStandardPaths.writableLocation(
                    QStandardPaths.StandardLocation.AppLocalDataLocation
                )
            )
            / "process-recordings"
        )
        self.size, self.allowed = size, allowed
        self.current = None
        self.encoders = set()
        self.started = 0.0
        self.last_input = time.monotonic()
        self.last_capture = 0.0
        self.next_capture = 0.0
        self._last_context_check = -100.0
        self._cached_config = None
        self._cached_context = None
        self.last_mode = "active"
        self.project = None
        self.last_output = None
        self._closing = False
        self._finished_manually = False
        self._click = None
        self._last_capture_window = None
        self._native_dialogs_previous = QApplication.testAttribute(
            Qt.ApplicationAttribute.AA_DontUseNativeDialogs
        )
        self._capture_cost = []
        self._queue_drops = 0
        self._last_tick = None
        self._pending_pauses = []
        self.panel = QWidget()
        layout = QVBoxLayout(self.panel)
        layout.setContentsMargins(0, 8, 0, 0)
        self.enabled = QCheckBox("Auto-record process")
        self.enabled.setStyleSheet("QCheckBox { color: #eff8f7; }")
        self.enabled.setToolTip(
            "Remember this choice. Record normal interaction at 10× and pilot fit "
            "evaluation at 2×; record busy "
            "calculation and loading phases at 1000×. Mouse movement and clicks do not "
            "change that speed. Keep the whole project "
            "session together, including pilot attempts, reviews and the atlas plot. "
            "Save one MP4 with Finish recording or when closing the app. Changing "
            "projects or turning recording off also saves the current video. "
            "Time while the interface is unresponsive is omitted after it recovers. "
            "No desktop or audio capture."
        )
        self.status = QLabel("Actions 10× · pilot review 2× · calculations 1000×")
        self.status.setWordWrap(True)
        self.status.setObjectName("railCaption")
        row = QHBoxLayout()
        self.finish_button = QPushButton("Finish recording")
        self.finish_button.setToolTip(
            "Save this continuous video. This does not stop the pilot or atlas."
        )
        self.folder_button = QPushButton("Videos")
        self.recover_button = QPushButton("Recover interrupted video…")
        for button in (self.finish_button, self.folder_button, self.recover_button):
            button.setObjectName("secondary")
        row.addWidget(self.finish_button)
        row.addWidget(self.folder_button)
        layout.addWidget(self.enabled)
        layout.addWidget(self.status)
        layout.addLayout(row)
        layout.addWidget(self.recover_button)
        self.recover_button.setToolTip(
            "Recover only completed recording fragments; scientific runs are untouched."
        )
        self.finish_button.setEnabled(False)
        self.folder_button.setEnabled(False)
        self.enabled.setChecked(allowed and self.settings.value("enabled", False, type=bool))
        self.enabled.toggled.connect(self._toggle)
        self.finish_button.clicked.connect(self.finish_manually)
        self.folder_button.clicked.connect(self.open_folder)
        self.recover_button.clicked.connect(self.recover)
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.setInterval(33)
        self.timer.timeout.connect(self._tick)
        QApplication.instance().installEventFilter(self)
        if self.enabled.isChecked():
            QApplication.setAttribute(Qt.ApplicationAttribute.AA_DontUseNativeDialogs, True)
            self.timer.start()
        QTimer.singleShot(0, self._tick)

    def _owned(self, widget):
        if not isinstance(widget, QWidget) or not isValid(widget):
            return False
        while widget is not None:
            if type(widget).__name__ == "DemoWindow":
                return False
            if widget is self.window:
                return True
            widget = widget.parentWidget()
        return False

    def eventFilter(self, watched, event):  # noqa: N802
        if not self._owned(watched):
            return False
        kind = event.type()
        if kind in {
            QEvent.Type.MouseMove,
            QEvent.Type.MouseButtonPress,
            QEvent.Type.MouseButtonRelease,
            QEvent.Type.Wheel,
            QEvent.Type.KeyPress,
            QEvent.Type.TouchBegin,
            QEvent.Type.Show,
            QEvent.Type.WindowActivate,
        }:
            self.last_input = time.monotonic()
            target = watched.window()
            if self._owned(target) and target.isVisible():
                self._last_capture_window = weakref.ref(target)
            if kind == QEvent.Type.MouseButtonPress:
                self._click = (self.last_input, QCursor.pos())
        return False

    def _toggle(self, enabled):
        if not self.allowed:
            return
        self.settings.setValue("enabled", bool(enabled))
        self.settings.sync()
        if self.settings.status() != QSettings.Status.NoError:
            self.status.setText("Recording choice could not be saved")
        self._finished_manually = False
        QApplication.setAttribute(
            Qt.ApplicationAttribute.AA_DontUseNativeDialogs,
            True if enabled else self._native_dialogs_previous,
        )
        if enabled:
            self.last_input = time.monotonic()
            self.timer.start()
            self._tick()
        else:
            self._capture(force=True)
            self._finish_current("disabled")
            self.timer.stop()

    def _context(self):
        # Landmarking can finish before a config exists. An explicitly selected,
        # existing project directory already identifies its local recording home.
        field = getattr(self.window, "project_edit", None)
        if field is not None and not field.hasFocus() and field.text().strip():
            selected = Path(field.text().strip()).expanduser()
            if selected.is_dir():
                return selected.resolve()
        for result in (
            getattr(self.window, "_result", None),
            getattr(self.window, "_review", None),
        ):
            config = getattr(result, "config_path", None)
            if config is not None:
                config = Path(config)
                if config == self._cached_config:
                    return self._cached_context
                if config.is_file():
                    self._cached_config = config
                    self._cached_context = config.resolve().parent
                    return self._cached_context
        return None

    def _start(self):
        if (
            self.current is not None
            or self._closing
            or self._finished_manually
            or not self.enabled.isChecked()
        ):
            return
        self.project = self._context()
        self.started = time.monotonic()
        self._last_tick = self.started
        self._pending_pauses = []
        self.last_capture = -100.0
        self.next_capture = 0.0
        self.last_mode = "active"
        encoder = _Encoder(self.root, self.size, self.project)
        self.encoders.add(encoder)
        encoder.signals.saved.connect(self._saved)
        encoder.signals.failed.connect(self._failed)
        self.current = encoder
        encoder.thread.start()
        self.finish_button.setEnabled(True)
        self.timer.start()

    def _tick(self):
        if not self.allowed or not isValid(self.window) or self._closing:
            return
        if not self.enabled.isChecked() or self._finished_manually:
            return
        self._observe_tick(time.monotonic())
        if not self.window.isVisible():
            return
        self._start()
        now = time.monotonic()
        if now - self._last_context_check >= 1:
            self._last_context_check = now
            context = self._context()
            if self.project is None:
                self.project = context
            elif context is not None and context != self.project:
                self._capture(force=True)
                self._finish_current("project_changed")
                self._start()
        self._capture()

    def _observe_tick(self, now):
        """Detect a stalled GUI heartbeat, including stalls while grabbing a frame."""
        previous = self._last_tick
        if self.current is not None and previous is not None:
            start = max(previous, self.last_capture)
            if now - start > UNRESPONSIVE_SECONDS:
                self._pending_pauses.append({
                    "source_start": start - self.started,
                    "source_end": now - self.started,
                    "reason": "interface_unresponsive",
                })
        self._last_tick = now

    def _capture(self, *, force=False):
        if self.current is None:
            return
        now = time.monotonic()
        self._observe_tick(now)
        mode = self._recording_mode()
        interval = SPEEDS[mode] / FPS
        if not force and mode == self.last_mode and now < self.next_capture:
            return
        before = time.perf_counter()
        image = self._image(now, mode)
        now = time.monotonic()
        self._observe_tick(now)
        self._capture_cost.append(time.perf_counter() - before)
        if len(self._capture_cost) > 100:
            self._capture_cost.pop(0)
        if image is None:
            return
        try:
            self.current.frames.put_nowait(
                (now - self.started, mode, image, tuple(self._pending_pauses))
            )
        except queue.Full:
            self._queue_drops += 1
            self.status.setText("Recording delayed · encoder busy")
            return
        self._pending_pauses.clear()
        if mode != self.last_mode or force or self.next_capture <= 0:
            self.next_capture = now + interval
        else:
            self.next_capture += interval
            if self.next_capture <= now:
                self.next_capture = now + interval
        self.last_capture, self.last_mode = now, mode
        self.status.setText("Recording · " + {
            "active": "actions 10×",
            "pilot_review": "pilot review 2×",
            "waiting": "calculation 1000×",
        }[mode])

    def _recording_mode(self):
        """Slow only ready pilot fit evaluation, including its owned popups."""
        target = self._capture_window()
        busy = any(
            indicator.tasks
            for indicator in self.window.findChildren(ActivityIndicator)
        )
        pilot_review = False
        while self._owned(target):
            busy |= target.property("processRecordingWaiting") is True
            pilot_review |= target.property("processRecordingPilotReview") is True
            if target is self.window:
                break
            target = target.parentWidget()
        if busy:
            return "waiting"
        return "pilot_review" if pilot_review else "active"

    def _capture_window(self):
        pilot = getattr(self.window, "_reference_calibration_dialog", None)
        pilot_visible = self._owned(pilot) and pilot.isVisible()
        for target in (QApplication.activeModalWidget(), QApplication.activeWindow()):
            if self._owned(target) and target.isVisible():
                if target is self.window and pilot_visible:
                    continue
                self._last_capture_window = weakref.ref(target)
                return target
        # Retain the actual owned workflow window when another application takes
        # focus. A foreign window must never enter an application-only recording.
        previous = self._last_capture_window() if self._last_capture_window else None
        while self._owned(previous):
            if previous.isVisible() and (previous is not self.window or not pilot_visible):
                return previous
            previous = previous.parentWidget()
        if pilot_visible:
            self._last_capture_window = weakref.ref(pilot)
            return pilot
        return self.window

    def _image(self, now, mode):
        window = self._capture_window()
        # QWidget.grab renders only our widget hierarchy. QScreen.grabWindow can
        # include other applications covering the window and is deliberately unused.
        pixmap = window.grab()
        if pixmap.isNull():
            self.status.setText("Recording paused · application frame unavailable")
            return None
        w, h = self.size
        image = QImage(w, h, QImage.Format.Format_RGB888)
        image.fill(QColor("#e9eff0"))
        painter = QPainter(image)
        scaled = pixmap.scaled(
            w,
            h - 44,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        x, y = (w - scaled.width()) // 2, (h - 44 - scaled.height()) // 2
        painter.drawPixmap(x, y, scaled)
        scale = scaled.width() / max(1, window.width())
        for popup in QApplication.topLevelWidgets():
            if popup is window or not popup.isVisible() or not self._owned(popup):
                continue
            if popup.windowType() != Qt.WindowType.Popup:
                continue
            offset = window.mapFromGlobal(popup.mapToGlobal(QPoint(0, 0)))
            p = popup.grab().scaled(round(popup.width() * scale), round(popup.height() * scale))
            painter.drawPixmap(x + round(offset.x() * scale), y + round(offset.y() * scale), p)
        point = window.mapFromGlobal(QCursor.pos())
        if window.rect().contains(point) and self._owned(QApplication.activeWindow()):
            cx, cy = x + round(point.x() * scale), y + round(point.y() * scale)
            painter.setPen(QPen(QColor("white"), 2))
            painter.setBrush(QColor("#172b30"))
            painter.drawPolygon(
                QPolygon(
                    [
                        QPoint(cx, cy),
                        QPoint(cx + 5, cy + 19),
                        QPoint(cx + 10, cy + 12),
                        QPoint(cx + 18, cy + 9),
                    ]
                )
            )
        if self._click is not None and now - self._click[0] < 0.7:
            pos = window.mapFromGlobal(self._click[1])
            painter.setPen(QPen(QColor("#e88825"), 3))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(
                QPoint(x + round(pos.x() * scale), y + round(pos.y() * scale)), 14, 14
            )
        painter.fillRect(0, h - 44, w, 44, QColor("#143c3b"))
        painter.setPen(QColor("white"))
        font = painter.font()
        font.setPixelSize(20 if w >= 1000 else 12)
        painter.setFont(font)
        elapsed = int(now - self.started)
        clock = f"{elapsed // 3600:02}:{elapsed // 60 % 60:02}:{elapsed % 60:02}"
        rate = {
            "active": "Actions · 10×",
            "pilot_review": "Pilot review · 2×",
            "waiting": "Calculation · 1000×",
        }[mode]
        title = window.windowTitle().strip() or type(window).__name__
        caption = f"DiffeoForge · {title} · session {clock} · {rate}"
        caption = painter.fontMetrics().elidedText(caption, Qt.TextElideMode.ElideRight, w - 36)
        painter.drawText(18, h - 15, caption)
        painter.end()
        return image

    def _finish_current(self, reason):
        if self.current is None:
            return
        encoder, self.current = self.current, None
        encoder.finish(
            time.monotonic() - self.started, self.project, reason,
            pauses=tuple(self._pending_pauses),
        )
        self._pending_pauses.clear()
        self.finish_button.setEnabled(False)
        self.status.setText("Exporting MP4…")

    def finish_manually(self):
        self._capture(force=True)
        self._finished_manually = True
        self._finish_current("manual_finish")
        self.timer.stop()
        self.finish_button.setText("New recording")
        self.finish_button.setEnabled(True)
        self.finish_button.clicked.disconnect()
        self.finish_button.clicked.connect(self._restart)

    def _restart(self):
        self._finished_manually = False
        self.finish_button.setText("Finish recording")
        self.finish_button.clicked.disconnect()
        self.finish_button.clicked.connect(self.finish_manually)
        self.last_input = time.monotonic()
        self._tick()

    @Slot(object, object)
    def _saved(self, encoder, value):
        self.encoders.discard(encoder)
        self.last_output, gaps, recovered = value
        self.folder_button.setEnabled(True)
        prefix = "Partial video recovered" if recovered else "MP4 saved"
        suffix = f" · {gaps} capture gap(s)" if gaps else ""
        self.status.setText(prefix + suffix)
        self.status.setToolTip(str(self.last_output))
        if self._closing and not self.encoders:
            QTimer.singleShot(0, self.window.close)

    @Slot(object, object)
    def _failed(self, encoder, message):
        self.encoders.discard(encoder)
        if self.current is encoder:
            self.current = None
            self._finished_manually = True
            self.timer.stop()
        self._closing = False
        self.status.setText("Recording/export failed · completed fragments retained")
        self.status.setToolTip(str(message) + "\n" + str(self.root))

    def open_folder(self):
        if self.last_output is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(self.last_output).parent)))

    def recover(self):
        name, _ = QFileDialog.getOpenFileName(
            self.window,
            "Recover interrupted recording",
            str(self.root),
            "Recording session (session.json)",
        )
        if not name:
            return
        encoder = _Encoder(self.root, self.size, self._context(), recovery=Path(name).parent)
        self.encoders.add(encoder)
        encoder.signals.saved.connect(self._saved)
        encoder.signals.failed.connect(self._failed)
        encoder.thread.start()
        self.status.setText("Recovering completed video fragments…")

    def handle_close(self):
        """Return true only while presentation export needs the window to stay alive."""
        if not self._closing:
            self._capture(force=True)
            self._closing = True
            self._finish_current("application_close")
            self.timer.stop()
        if self.encoders:
            self.status.setText("Finishing MP4 export before closing…")
            return True
        QApplication.instance().removeEventFilter(self)
        QApplication.setAttribute(
            Qt.ApplicationAttribute.AA_DontUseNativeDialogs, self._native_dialogs_previous
        )
        return False
