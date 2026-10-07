"""Slow saved evidence must not block navigation or supply action authorization."""

import hashlib
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

import diffeoforge.desktop.widgets as module
from diffeoforge.desktop.project_setup import DesktopEngine
from diffeoforge.reference_calibration_study import create_reference_calibration_study


def _wait(app, predicate):
    deadline = time.monotonic() + 10
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.002)
    app.processEvents()
    assert predicate()


@pytest.fixture
def pilot_window(monkeypatch, tmp_path):
    from test_reference_calibration_study import _project

    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    config = _project(tmp_path)
    snapshot = create_reference_calibration_study(config, tmp_path / "study")
    window = module.DiffeoForgeWindow()
    window._review = SimpleNamespace(
        engine=DesktopEngine.DEFORMETRICA_REFERENCE,
        config_path=config, config_sha256=hashlib.sha256(config.read_bytes()).hexdigest(),
    )
    window._reference_readiness = SimpleNamespace(ready=True)
    window._reference_calibration_study_directory = snapshot.study_directory
    monkeypatch.setattr(
        window, "_reference_calibration_context", lambda: (snapshot.plan, snapshot.study_directory)
    )
    # These tests exercise pilot status/open transitions independently of project creation.
    monkeypatch.setattr(window, "_sync_ready_state", lambda: None)
    yield app, window, snapshot
    window._worker = None
    window._reference_calibration_dialog = None
    window.close()
    _wait(app, lambda: window._pilot_status_loader._active is None)
    window.deleteLater()
    app.processEvents()


def test_slow_pilot_status_keeps_event_loop_live_and_is_not_repeated(
    pilot_window, monkeypatch,
):
    app, window, snapshot = pilot_window
    real_load = module.load_reference_calibration_study
    started, release = threading.Event(), threading.Event()
    calls = []
    gui_thread = threading.get_ident()

    def slow_load(directory):
        calls.append(threading.get_ident())
        started.set()
        assert release.wait(5)
        return real_load(directory)

    monkeypatch.setattr(module, "load_reference_calibration_study", slow_load)
    ticks = []
    timer = QTimer()
    timer.timeout.connect(lambda: ticks.append(time.monotonic()))
    timer.start(2)
    try:
        assert window._reference_calibration_pending()
        _wait(app, started.is_set)
        for _ in range(20):
            assert window._reference_calibration_action_text() == "Checking saved pilot…"
            assert window._reference_calibration_pending()
            app.processEvents()
            time.sleep(0.003)
        assert len(ticks) >= 5
        assert calls == [calls[0]] and calls[0] != gui_thread
    finally:
        release.set()
        timer.stop()
    _wait(app, lambda: not window._pilot_status_loading)
    assert window._pilot_status_snapshot.status == snapshot.status
    for _ in range(20):
        window._reference_calibration_action_text()
    assert len(calls) == 1

    # A changed record invalidates status; a failed verification is cached as an error,
    # not retried every time the interface updates.
    manifest = snapshot.study_directory / "study.json"
    original = manifest.read_bytes()
    manifest.write_bytes(original + b" ")
    assert window._saved_pilot_status(window._reference_calibration_context()) is None
    _wait(app, lambda: not window._pilot_status_loading)
    assert window._pilot_status_snapshot is None
    assert window._pilot_status_error
    assert window._reference_calibration_action_text() == "Inspect pilot calibration issue"
    for _ in range(20):
        window._saved_pilot_status(window._reference_calibration_context())
    assert len(calls) == 2


def test_old_status_cannot_follow_a_project_switch(pilot_window):
    _app, window, snapshot = pilot_window
    old_key = window._pilot_status_context_key(window._reference_calibration_context())
    window._review = None
    window._pilot_status_loaded(old_key, (snapshot, ()))
    window._pilot_status_failed(old_key, "Old project failed")
    assert window._pilot_status_snapshot is None
    assert window._pilot_status_error is None


def test_explicit_open_reverifies_tampered_evidence_despite_cached_status(
    pilot_window, monkeypatch,
):
    app, window, snapshot = pilot_window
    window._saved_pilot_status(window._reference_calibration_context())
    _wait(app, lambda: not window._pilot_status_loading)
    assert window._pilot_status_snapshot is not None
    (snapshot.study_directory / "study.json").write_text("{}", encoding="utf-8")
    failures, finished, threads = [], [], []
    real_load = module.load_reference_calibration_study

    def load(directory):
        threads.append(threading.get_ident())
        return real_load(directory)

    monkeypatch.setattr(module, "load_reference_calibration_study", load)
    monkeypatch.setattr(module.QMessageBox, "warning", lambda *args: failures.append(args[2]))
    monkeypatch.setattr(window, "_finish_reference_calibration", finished.append)
    window._open_reference_calibration()
    assert window._worker is not None
    _wait(app, lambda: window._worker is None)
    assert failures and not finished
    assert threads and threading.get_ident() not in threads
    assert window._reference_calibration_dialog is None
    assert window._reference_calibrated_config_path is None


@pytest.mark.parametrize("close_requested", [False, True])
def test_open_does_not_apply_after_project_change_or_close(
    pilot_window, monkeypatch, close_requested,
):
    _app, window, snapshot = pilot_window
    queued, applied = [], []
    window._thread_pool = SimpleNamespace(start=queued.append)
    monkeypatch.setattr(window, "_finish_reference_calibration", applied.append)
    window._open_reference_calibration()
    assert len(queued) == 1
    if close_requested:
        window._close_after_worker = True
    else:
        window._review = None
    window._reference_calibration_opened(snapshot)
    assert not applied and window._reference_calibration_dialog is None
    assert window._worker is None


def test_dialog_reuses_fresh_worker_snapshot_without_loading_again(
    pilot_window, monkeypatch, tmp_path: Path,
):
    import diffeoforge.desktop.reference_calibration_dialog as dialog_module

    app, _window, snapshot = pilot_window

    def unexpected_load(_directory):
        pytest.fail("A freshly verified worker snapshot must not be verified twice on the GUI")

    monkeypatch.setattr(dialog_module, "load_reference_calibration_study", unexpected_load)
    dialog = dialog_module.ReferenceCalibrationDialog(
        snapshot.study_directory, verified_snapshot=snapshot
    )
    assert dialog.snapshot is snapshot
    dialog.close()
    app.processEvents()
    with pytest.raises(ValueError, match="different study"):
        dialog_module.ReferenceCalibrationDialog(tmp_path / "different", verified_snapshot=snapshot)
