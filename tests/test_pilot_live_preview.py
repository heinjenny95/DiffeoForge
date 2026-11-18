"""Exercise the running pilot UI with synthetic preview frames and no optimizer."""

from dataclasses import replace
from threading import Event
from time import monotonic, sleep
from types import ModuleType, SimpleNamespace

import numpy as np
import pytest
from pilot_view_helpers import wait_pilot_view
from test_reference_calibration_dialog import _model
from test_reference_calibration_study import _project


@pytest.fixture
def app(monkeypatch):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def wait(app, predicate):
    deadline = monotonic() + 5
    while not predicate() and monotonic() < deadline:
        app.processEvents()
        sleep(0.002)
    assert predicate()


def host(monkeypatch, *, prepare, read_frame, release):
    import sys

    module = ModuleType("diffeoforge.pilot_live_frames")
    module.prepare = prepare
    module.read_frame = read_frame
    module.release = release
    monkeypatch.setitem(sys.modules, module.__name__, module)


def test_live_preview_uses_blank_pilot_area_and_exact_frame_iteration(app, tmp_path, monkeypatch):
    from diffeoforge.desktop.reference_calibration_dialog import ReferenceCalibrationDialog
    from diffeoforge.reference_calibration_study import create_reference_calibration_study

    snapshot = create_reference_calibration_study(_project(tmp_path), tmp_path / "pilot")
    dialog = ReferenceCalibrationDialog(snapshot.study_directory)
    dialog.resize(920, 680)
    dialog.show()
    wait_pilot_view(dialog)
    panel = dialog._live_fit_preview
    panel_layout = panel.parentWidget().layout()
    assert panel_layout.indexOf(panel) == panel_layout.indexOf(dialog.pilot_tools) + 1
    assert panel.isHidden()
    # Supply tiny models and two genuine generations, with a fixed target and
    # distinct fit objects. This test never starts the scientific worker.
    target = _model(tmp_path / "target.vtk")
    fit = replace(target, path=tmp_path / "first-fit.vtk")
    second = replace(fit, path=tmp_path / "later-fit.vtk",
                     vertices=((0.0, 0.0, 0.1), *fit.vertices[1:]))
    cp = np.array([[0.0, 0.0, 0.0]])
    buffer = [SimpleNamespace(iteration=12, target=target, fit=fit, controls=cp)]
    reads, released = [], []

    def read_frame(binding, after):
        reads.append((binding.request_id, after))
        return buffer.pop(0) if buffer else None

    host(monkeypatch, prepare=lambda _run, request, **_: SimpleNamespace(request_id=request),
         read_frame=read_frame, release=lambda binding: released.append(binding.request_id))
    worker = SimpleNamespace(runner=SimpleNamespace(_cancel_requested=False))
    worker.request_cancel = lambda: True
    dialog._worker = worker
    candidate = snapshot.candidates[0].candidate_id
    try:
        start = dict(event="candidate_started", candidate_id=candidate, run_directory="runs/test",
                     request_id="fit-1", iteration_offset=30)
        dialog._event(dict(start, qualification_only=True))
        assert panel.isHidden()
        dialog._event(start)
        display_id = panel._attempt.display_id
        dialog.scroll.ensureWidgetVisible(panel, 0, 0)
        panel.poll()
        wait(app, lambda: panel.status.text().startswith("Accepted iteration 42"))
        assert panel.canvas.reconstruction_model is fit
        assert panel.control_points.isEnabled() and not panel.control_points.isChecked()
        assert panel.canvas._control_points is None
        assert reads == [(display_id, -1)]
        panel.control_points.click()
        assert panel.canvas._control_points is cp
        assert not panel.canvas.grab().isNull()
        assert reads == [(display_id, -1)]
        dialog.showMinimized()
        app.processEvents()
        panel.poll()
        assert not panel._busy
        assert reads == [(display_id, -1)]
        dialog.showNormal()
        app.processEvents()
        dialog._event(dict(event="candidate_worker_event", candidate_id=candidate,
                           worker_event=dict(kind="progress", payload=dict(
                               iteration=50, maximum_iterations=100))))
        assert "Accepted iteration 42" in panel.status.text()
        # A tick with a pending/newly-rendering frame keeps the old frame alive.
        buffer.append(SimpleNamespace(iteration=23, target=target, fit=second, controls=cp))
        panel.poll()
        assert panel.canvas.reconstruction_model is fit
        wait(app, lambda: panel.status.text().startswith("Accepted iteration 53"))
        assert panel.canvas.reconstruction_model is second
        assert reads == [(display_id, -1), (display_id, 12)]
        dialog._cancel()
        assert panel.isHidden()
        assert panel.canvas.reconstruction_model is None
        wait(app, lambda: released == [display_id])
    finally:
        dialog._worker = None
        dialog.close()
        app.processEvents()


def test_clearing_during_prepare_releases_only_the_late_attempt(app, tmp_path, monkeypatch):
    from diffeoforge.desktop.pilot_live_preview import PilotLivePreviewPanel

    preparing, unblock, released = Event(), Event(), Event()
    reads = []

    def prepare(_run, request, **_):
        preparing.set()
        assert unblock.wait(5)
        return request

    host(monkeypatch, prepare=prepare, read_frame=lambda *args: reads.append(args),
         release=lambda binding: released.set())
    panel = PilotLivePreviewPanel()
    panel.set_run(tmp_path, "old")
    panel.resize(600, 300)
    panel.poll()
    try:
        wait(app, preparing.is_set)
        panel.clear()
        assert panel.isHidden() and not released.is_set()
        unblock.set()
        wait(app, released.is_set)
        assert reads == []
        assert panel.canvas.reconstruction_model is None
    finally:
        unblock.set()
        panel.clear()
        panel.close()
        app.processEvents()


def test_missing_preview_on_published_run_stops_waiting(app, tmp_path, monkeypatch):
    from diffeoforge.desktop.pilot_live_preview import PilotLivePreviewPanel

    prepare_calls = []
    host(monkeypatch, prepare=lambda *_, **__: prepare_calls.append(None),
         read_frame=lambda *_: pytest.fail("No preview binding exists"),
         release=lambda *_: pytest.fail("No preview request exists"))
    panel = PilotLivePreviewPanel()
    panel.resize(600, 300)
    panel.set_run(tmp_path, "old")
    try:
        wait(app, lambda: bool(prepare_calls) and not panel._busy)
        assert panel._timer.isActive()
        assert "Waiting" in panel.status.text()
        (tmp_path / "manifest.json").write_text("{}", encoding="utf-8")
        panel.poll()
        wait(app, lambda: not panel._timer.isActive())
        assert "unavailable" in panel.status.text()
        assert not panel.control_points.isEnabled()
    finally:
        panel.clear()
        panel.close()
        app.processEvents()


def test_resolution_switch_accepts_same_iteration_and_retains_last_snapshot(app, tmp_path,
                                                                          monkeypatch):
    from diffeoforge.desktop.pilot_live_preview import PilotLivePreviewPanel

    prepared, reads, released = [], [], []
    target = _model(tmp_path / "target.vtk")
    fit = replace(target, path=tmp_path / "fit.vtk")
    detailed = replace(fit, path=tmp_path / "detailed.vtk")
    cp = np.array([[0., 0., 0.]])
    allow_detailed = Event()

    def prepare(run, identifier, *, face_budget):
        binding = SimpleNamespace(request_id=identifier, face_budget=face_budget)
        prepared.append(binding)
        return binding

    def read(binding, after):
        reads.append((binding.request_id, after))
        if after >= 7 or binding.face_budget == 16_000 and not allow_detailed.is_set():
            return None
        return SimpleNamespace(iteration=7, target=target,
                               fit=detailed if binding.face_budget == 16_000 else fit,
                               controls=cp)

    host(monkeypatch, prepare=prepare, read_frame=read,
         release=lambda binding: released.append(binding.request_id))
    panel = PilotLivePreviewPanel()
    panel.resize(920, 500)
    panel.set_run(tmp_path, "same-native-worker", iteration_offset=30)
    try:
        wait(app, lambda: panel.status.text().startswith("Accepted iteration 37"))
        old_attempt = panel._attempt
        assert panel.resolution.currentData() == 6_000
        panel.canvas._zoom = 1.8
        panel.control_points.click()
        assert len(prepared) == 1  # CP display has no publisher side effects.
        panel.resolution.setCurrentIndex(2)
        new_attempt = panel._attempt
        assert new_attempt.display_id != old_attempt.display_id
        assert new_attempt.request_id == old_attempt.request_id
        assert panel.canvas.reconstruction_model is fit
        assert "Last snapshot: accepted iteration 37" in panel.status.text()
        panel.set_run(tmp_path, "same-native-worker", iteration_offset=30)
        assert panel._attempt is new_attempt
        wait(app, lambda: len(prepared) == 2 and not panel._busy)
        panel._loaded(old_attempt, SimpleNamespace(iteration=99, target=target,
                                                  fit=fit, controls=cp))
        assert panel.canvas.reconstruction_model is fit
        allow_detailed.set()
        panel.poll()
        wait(app, lambda: panel.canvas.reconstruction_model is detailed)
        wait(app, lambda: panel.status.text().startswith("Accepted iteration 37"))
        assert reads[-1] == (new_attempt.display_id, -1)
        assert panel.canvas._zoom == 1.8
        assert panel.canvas._control_points is cp
        assert "triangles (fit / target)" in panel.status.text()
        wait(app, lambda: old_attempt.display_id in released)
        assert new_attempt.display_id not in released
    finally:
        panel.clear()
        panel.close()
        app.processEvents()


def test_legacy_run_explains_light_limit_and_restores_choice_for_new_run(app, tmp_path,
                                                                     monkeypatch):
    from diffeoforge.desktop.pilot_live_preview import PilotLivePreviewPanel

    def prepare(run, identifier, *, face_budget):
        return SimpleNamespace(legacy_runtime=run.name == "legacy", request_id=identifier,
                               face_budget=1_600 if run.name == "legacy" else face_budget)

    host(monkeypatch, prepare=prepare, read_frame=lambda *_: None, release=lambda *_: None)
    panel = PilotLivePreviewPanel()
    panel.resize(920, 450)
    panel.resolution.setCurrentIndex(2)
    panel.set_run(tmp_path / "legacy", "old")
    try:
        wait(app, lambda: "supports Light only" in panel.resolution_note.text())
        assert panel.resolution.currentData() == 1_600
        assert not panel.resolution.model().item(1).isEnabled()
        assert not panel.resolution.model().item(2).isEnabled()
        assert panel._preferred_budget == 16_000
        panel.set_run(tmp_path / "new", "new")
        assert panel.resolution.currentData() == 16_000
        assert panel.resolution.model().item(2).isEnabled()
        assert panel._attempt.face_budget == 16_000
    finally:
        panel.clear()
        panel.close()
        app.processEvents()


def test_rapid_tier_changes_during_preparation_keep_only_latest_request(app, tmp_path,
                                                                    monkeypatch):
    from diffeoforge.desktop.pilot_live_preview import PilotLivePreviewPanel

    entered, unblock = Event(), Event()
    prepared, reads, released = [], [], []

    def prepare(run, identifier, *, face_budget):
        prepared.append((identifier, face_budget))
        if len(prepared) == 1:
            entered.set()
            assert unblock.wait(5)
        return SimpleNamespace(request_id=identifier, face_budget=face_budget)

    host(monkeypatch, prepare=prepare,
         read_frame=lambda binding, after: reads.append(binding.request_id),
         release=lambda binding: released.append(binding.request_id))
    panel = PilotLivePreviewPanel()
    panel.resize(920, 450)
    panel.set_run(tmp_path, "running-worker")
    try:
        wait(app, entered.is_set)
        first = panel._attempt.display_id
        panel.resolution.setCurrentIndex(2)
        skipped = panel._attempt.display_id
        panel.resolution.setCurrentIndex(0)
        latest = panel._attempt.display_id
        assert len({first, skipped, latest}) == 3
        assert panel._busy
        unblock.set()
        wait(app, lambda: not panel._busy and first in released)
        panel.poll()
        wait(app, lambda: latest in reads)
        assert prepared == [(first, 6_000), (latest, 1_600)]
        assert reads == [latest]
        assert latest not in released
        assert panel._attempt.request_id == "running-worker"
    finally:
        unblock.set()
        panel.clear()
        panel.close()
        app.processEvents()
