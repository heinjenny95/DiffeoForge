from __future__ import annotations

import json
import threading
import time
from types import SimpleNamespace

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("imageio_ffmpeg")
from PySide6.QtCore import QSettings, Slot
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QVBoxLayout, QWidget

from diffeoforge.desktop.activity import ActivityIndicator
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


def test_real_qt_capture_auto_exports_each_computation_and_restarts(application, tmp_path):
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
        worker = type("_AtlasWorker", (), {})()
        indicator.task_finished.emit(worker)
        wait(application, lambda: rec.current is not first and rec.last_output is not None)
        assert rec.current is not None
        data = json.loads(rec.last_output.with_suffix(".json").read_text(encoding="utf-8"))
        assert data["finish_reason"] == "computation_finished"
        assert data["capture_samples"] >= 3
        assert all(thread == gui_thread for thread, _value in deliveries)
        assert settings.value("enabled", type=bool) is True
        second = rec.current
        QTest.qWait(400)
        rec._computation_finished(worker)
        wait(application, lambda: rec.current is not second and len(deliveries) == 2)
        assert len(list((tmp_path / "project" / "recordings").glob("*.mp4"))) == 2
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
        rec.last_input = time.monotonic() - 31
        rec._capture(force=True)
        assert rec.last_mode == "waiting"
        rec.last_input = time.monotonic()
        rec._capture(force=True)
        assert rec.last_mode == "active"
    finally:
        foreign.close()
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
