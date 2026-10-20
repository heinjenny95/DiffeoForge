from __future__ import annotations

import json
import threading
import time
from types import SimpleNamespace

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("imageio_ffmpeg")
from PySide6.QtCore import QObject, QPoint, QSettings, Qt, Signal, Slot
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QLineEdit, QVBoxLayout, QWidget

from diffeoforge.desktop.activity import ActivityIndicator, ActivityPool
from diffeoforge.desktop.process_recorder import ProcessRecorder


@pytest.fixture
def application(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication(["recording-engineering-test"])


def wait(application, condition, seconds=12):
    deadline = time.monotonic() + seconds
    while not condition() and time.monotonic() < deadline:
        application.processEvents()
        QTest.qWait(10)
    assert condition()


def setup(tmp_path, *, cls=ProcessRecorder):
    window = QWidget()
    window.resize(640, 400)
    window.setStyleSheet("background: #226622")
    layout = QVBoxLayout(window)
    layout.addWidget(QLabel("Public workflow fixture"))
    config = tmp_path / "project" / "project.yaml"
    config.parent.mkdir(exist_ok=True)
    config.write_text("public fixture", encoding="utf-8")
    window._result = SimpleNamespace(config_path=config)
    settings = QSettings(str(tmp_path / "recording.ini"), QSettings.Format.IniFormat)
    recorder = cls(window, settings=settings, staging_root=tmp_path / "staging", size=(640, 400))
    layout.addWidget(recorder.panel)
    window.show()
    return window, recorder, settings


def stop(application, window, recorder):
    if recorder.current is not None:
        recorder._capture(force=True)
        recorder._finish_current("engineering_cleanup")
    recorder.timer.stop()
    wait(application, lambda: not recorder.encoders)
    recorder.handle_close()
    window.close()
    application.processEvents()


def test_pilot_attempts_and_atlas_steps_stay_in_one_real_video(application, tmp_path):
    gui_thread = threading.get_ident()
    deliveries = []

    class ProbeRecorder(ProcessRecorder):
        @Slot(object, object)
        def _saved(self, encoder, value):
            deliveries.append((threading.get_ident(), value))
            super()._saved(encoder, value)

    window, rec, settings = setup(tmp_path, cls=ProbeRecorder)
    try:
        assert rec.current is None and not rec.enabled.isChecked()
        rec.enabled.setChecked(True)
        QTest.qWait(750)
        application.processEvents()
        first = rec.current
        assert first is not None and first.frames.maxsize == 6
        indicator = ActivityIndicator(window)
        indicator.show()
        application.processEvents()
        for name in ("_ProjectWorker", "_ProcrustesPreviewWorker",
                     "_CalibrationStageWorker", "_CalibrationStageWorker",
                     "_ReferenceAtlasWorker", "_ReferencePCADeformationWorker",
                     "_AtlasWorker", "_RemoteAtlasWorker"):
            indicator.task_finished.emit(type(name, (), {})())
            QTest.qWait(100)
            application.processEvents()
        QTest.qWait(600)  # Beyond the former delayed rotation.
        assert rec.current is first and rec.last_output is None
        assert not list((tmp_path / "project").glob("recordings/*.mp4"))
        # A visible plot change after the attempts belongs to the same encoder.
        window.setStyleSheet("background: #992244")
        rec._capture(force=True)
        rec.finish_manually()
        wait(application, lambda: not rec.encoders)
        assert rec.current is None
        data = json.loads(rec.last_output.with_suffix(".json").read_text(encoding="utf-8"))
        assert data["finish_reason"] == "manual_finish"
        assert data["capture_samples"] >= 3
        assert all(thread == gui_thread for thread, _value in deliveries)
        assert settings.value("enabled", type=bool) is True
        assert len(deliveries) == 1
        assert len(list((tmp_path / "project" / "recordings").glob("*.mp4"))) == 1
        rec._restart()
        assert rec.current is not None and rec.current is not first
        QTest.qWait(400)
        assert rec.handle_close() is True
        wait(application, lambda: not rec.encoders)
        assert rec.handle_close() is False
    finally:
        stop(application, window, rec)


def test_owned_dialog_capture_excludes_foreign_windows_and_wait_mode(application, tmp_path):
    window, rec, _settings = setup(tmp_path)
    foreign = QWidget()
    foreign.setStyleSheet("background: #0000ff")
    foreign.resize(640, 400)
    dialog = QDialog(window)
    dialog.resize(640, 400)
    dialog.setStyleSheet("background: #ff0000")
    try:
        rec.enabled.setChecked(True)
        dialog.show()
        dialog.activateWindow()
        application.processEvents()
        image = rec._image(time.monotonic(), "active")
        assert image.pixelColor(320, 160).red() > 200
        dialog.hide()
        foreign.show()
        foreign.activateWindow()
        application.processEvents()
        image = rec._image(time.monotonic(), "active")
        assert image.pixelColor(320, 160).blue() < 150
        indicator = ActivityIndicator(window)
        indicator.set_task("compute", "Running atlas")
        rec._capture(force=True)
        assert rec.last_mode == "waiting"
        indicator.set_task("compute", None)
        rec._capture(force=True)
        assert rec.last_mode == "active"
    finally:
        foreign.close()
        dialog.close()
        stop(application, window, rec)


def test_real_gui_stall_pauses_video_without_splitting_or_cutting_responsive_waits(
    application, tmp_path,
):
    window, rec, _settings = setup(tmp_path)
    try:
        rec.enabled.setChecked(True)
        first = rec.current
        QTest.qWait(500)
        rec._tick()
        time.sleep(2.15)  # Deliberately block only this engineering GUI event loop.
        rec._tick()
        assert rec.current is first
        indicator = ActivityIndicator(window)
        indicator.set_task("compute", "Running atlas")
        rec._capture(force=True)
        QTest.qWait(2200)  # Responsive event loop while backend-style waiting.
        rec.finish_manually()
        wait(application, lambda: not rec.encoders)
        data = json.loads(rec.last_output.with_suffix(".json").read_text())
        assert len(data["pauses"]) == 1
        pause = data["pauses"][0]
        assert pause["reason"] == "interface_unresponsive"
        assert 2.0 < pause["source_end"] - pause["source_start"] < 2.5
        # Responsive review time remains real-time; only the blocked GUI is cut.
        assert 1.4 < data["output"]["seconds"] < 2.2
        assert data["source_seconds"] > 4.5
    finally:
        stop(application, window, rec)


def test_speed_follows_worker_completion_and_review_not_mouse_or_keyboard(
    application, tmp_path,
):
    class Signals(QObject):
        succeeded = Signal(object)
        failed = Signal(str)

    window, rec, _settings = setup(tmp_path)
    dialog = QDialog(window)
    try:
        queued = []
        pool = ActivityPool(window, pool=SimpleNamespace(start=queued.append))
        worker = SimpleNamespace(signals=Signals())
        rec.enabled.setChecked(True)
        first = rec.current
        pool.start(worker)
        rec._capture(force=True)
        assert rec.last_mode == "waiting"
        QTest.mouseMove(window, QPoint(25, 25))
        QTest.mouseClick(window, Qt.MouseButton.LeftButton)
        QTest.keyClick(window, Qt.Key.Key_Shift)
        rec._capture(force=True)
        assert rec.last_mode == "waiting" and rec.current is first
        # Opening another owned window must not slow a calculation video.
        dialog.show()
        dialog.activateWindow()
        application.processEvents()
        assert rec._recording_mode() == "waiting"
        dialog.setProperty("processRecordingWaiting", True)
        assert rec._recording_mode() == "waiting"  # Review meshes still loading.
        dialog.setProperty("processRecordingWaiting", False)
        assert rec._recording_mode() == "waiting"
        dialog.hide()
        window.activateWindow()
        application.processEvents()
        assert rec._recording_mode() == "waiting"
        worker.signals.succeeded.emit(None)
        application.processEvents()
        rec._capture(force=True)
        assert rec.last_mode == "active" and rec.current is first
        dialog.show()
        dialog.activateWindow()
        application.processEvents()
        assert rec._recording_mode() == "active"
        dialog.setProperty("processRecordingWaiting", True)
        assert rec._recording_mode() == "waiting"
        dialog.setProperty("processRecordingWaiting", False)
        dialog.hide()
        rec.finish_manually()
        wait(application, lambda: not rec.encoders)
        data = json.loads(rec.last_output.with_suffix(".json").read_text())
        assert data["speeds"] == {"active": 1, "waiting": 1000}
        assert [t["speed"] for t in data["timeline"]] == [1, 1000, 1]
    finally:
        dialog.close()
        stop(application, window, rec)


def test_remembered_opt_in_starts_after_show_and_smoke_opt_out_preserves_choice(
    application, tmp_path
):
    settings = QSettings(str(tmp_path / "remember.ini"), QSettings.Format.IniFormat)
    settings.setValue("enabled", True)
    window = QWidget()
    rec = ProcessRecorder(
        window, settings=settings, staging_root=tmp_path / "staging", size=(640, 400)
    )
    application.processEvents()  # Hidden initially: timer must keep checking.
    assert rec.current is None
    window.show()
    wait(application, lambda: rec.current is not None)
    stop(application, window, rec)
    other = QWidget()
    disabled = ProcessRecorder(other, settings=settings, allowed=False)
    other.show()
    application.processEvents()
    assert disabled.current is None
    assert settings.value("enabled", type=bool) is True
    disabled.handle_close()
    other.close()


def test_ready_fit_review_is_captured_at_real_time_after_fast_loading(application, tmp_path):
    window, rec, _settings = setup(tmp_path)
    dialog = QDialog(window)
    dialog.resize(640, 400)
    try:
        dialog.setProperty("processRecordingWaiting", True)
        dialog.show()
        dialog.activateWindow()
        application.processEvents()
        rec.enabled.setChecked(True)
        rec._capture(force=True)
        QTest.qWait(250)
        dialog.setProperty("processRecordingWaiting", False)
        rec._capture(force=True)
        QTest.qWait(1200)
        rec.finish_manually()
        wait(application, lambda: not rec.encoders)
        data = json.loads(rec.last_output.with_suffix(".json").read_text())
        assert [t["speed"] for t in data["timeline"]] == [1000, 1]
        review = data["timeline"][1]
        review_seconds = data["source_seconds"] - review["source_start"]
        assert review_seconds >= 1.2
        assert abs(data["output"]["seconds"] - review_seconds - 1) < 0.05
        # The old ten-times capture cadence would provide only a few samples.
        assert data["capture_samples"] >= 18
    finally:
        dialog.close()
        stop(application, window, rec)


def test_encoder_failure_does_not_retry_or_close_the_application(
    application, tmp_path, monkeypatch
):
    from diffeoforge.desktop import process_recorder as module

    def fail(*args, **kwargs):
        raise OSError("public disk failure fixture")

    monkeypatch.setattr(module, "ProcessRecording", fail)
    window, rec, settings = setup(tmp_path)
    rec.enabled.setChecked(True)
    wait(application, lambda: rec.current is None and not rec.encoders)
    assert window.isVisible() and "failed" in rec.status.text()
    assert settings.value("enabled", type=bool) is True
    rec._tick()
    assert rec.current is None
    stop(application, window, rec)


def test_existing_pilot_close_guard_precedes_recording_finalization(application, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from diffeoforge.desktop.widgets import DiffeoForgeWindow

    window = DiffeoForgeWindow(recording_allowed=False)
    dialog = QDialog(window)
    window._reference_calibration_dialog = dialog
    monkeypatch.setattr(QMessageBox, "information", lambda *args: None)
    window.show()
    window.close()
    assert window.isVisible() and not window.process_recorder._closing
    window._reference_calibration_dialog = None
    dialog.close()
    window.close()


def test_actual_saved_pilot_open_path_has_recordable_owner(application, tmp_path, monkeypatch):
    from test_reference_calibration_study import _review_ready_stage

    from diffeoforge.desktop.widgets import DiffeoForgeWindow

    _runner, snapshot = _review_ready_stage(tmp_path, monkeypatch)
    window = DiffeoForgeWindow(recording_allowed=False)
    window._pilot_open_context_key = "public-owner-fixture"
    monkeypatch.setattr(window, "_reference_calibration_context", lambda: None)
    monkeypatch.setattr(
        window, "_pilot_status_context_key", lambda _context: "public-owner-fixture"
    )
    window.show()
    window._reference_calibration_opened(snapshot)
    dialog = window._reference_calibration_dialog
    assert dialog.parentWidget() is window
    assert window.process_recorder._owned(dialog)
    dialog.activateWindow()
    application.processEvents()
    assert window.process_recorder._capture_window() is dialog
    dialog.close()
    application.processEvents()
    window.close()
    application.processEvents()


def test_external_focus_keeps_last_owned_workflow_window(application, tmp_path, monkeypatch):
    window, rec, _settings = setup(tmp_path)
    dialog = QDialog(window)
    dialog.setWindowTitle("Owned workflow fixture")
    dialog.setStyleSheet("background: #ff0000")
    dialog.resize(640, 400)
    try:
        dialog.show()
        dialog.activateWindow()
        application.processEvents()
        assert rec._capture_window() is dialog
        monkeypatch.setattr(QApplication, "activeWindow", staticmethod(lambda: None))
        monkeypatch.setattr(QApplication, "activeModalWidget", staticmethod(lambda: None))
        assert rec._capture_window() is dialog
        assert rec._image(time.monotonic(), "active").pixelColor(320, 160).red() > 200
        dialog.hide()
        assert rec._capture_window() is window
    finally:
        dialog.close()
        stop(application, window, rec)


def test_landmark_recording_uses_selected_project_before_config_exists(application, tmp_path):
    window, rec, _settings = setup(tmp_path)
    window._result = None
    destination = tmp_path / "new-project"
    destination.mkdir()
    window.project_edit = QLineEdit(str(destination), window)
    assert rec._context() == destination.resolve()
    window.project_edit.setText(str(tmp_path / "not-created"))
    assert rec._context() is None
    stop(application, window, rec)
