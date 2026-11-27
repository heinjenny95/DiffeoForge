from concurrent.futures import Future
from types import SimpleNamespace

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon, QWidget

from diffeoforge.desktop import activity, notifications, widgets


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


def test_banner_keeps_window_minimized_until_clicked(app, monkeypatch):
    window = QWidget()
    window.showMaximized()
    window.showMinimized()
    banners = []
    monkeypatch.setattr(QSystemTrayIcon, "isSystemTrayAvailable", lambda: True)
    monkeypatch.setattr(QSystemTrayIcon, "supportsMessages", lambda: True)
    monkeypatch.setattr(QSystemTrayIcon, "show", lambda self: None)
    monkeypatch.setattr(QSystemTrayIcon, "showMessage", lambda self, *args: banners.append(args))
    notifications.notify(window, "Atlas finished", "Review the result.")
    assert window.isMinimized()
    assert len(banners) == 1 and banners[0][:2] == ("DiffeoForge · Atlas finished",
                                                     "Review the result.")
    window._task_notification_tray.messageClicked.emit()
    assert window.isMaximized() and not window.isMinimized()
    window.close()


def test_modal_decision_notifies_once_and_waits_for_user(app, monkeypatch):
    notices = []
    monkeypatch.setattr(notifications, "notify", lambda *args: notices.append(args))
    notifications.install_decision_notifications(app)
    notifications.install_decision_notifications(app)
    box = QMessageBox(QMessageBox.Icon.Question, "Confirm workload", "Start the selected run?",
                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    box.open()
    app.processEvents()
    assert notices == [(box, "Decision needed", "Confirm workload")]
    assert box.isVisible() and box.clickedButton() is None
    box.reject()


@pytest.mark.parametrize(("outcome", "early", "title"), [
    ("completed", False, "Atlas finished"),
    ("interrupted", True, "Atlas review needed"),
    ("interrupted", False, "Atlas interrupted"),
    ("prepared_not_executed", False, "Atlas start cancelled"),
])
def test_reference_atlas_waits_for_controller_outcome(app, monkeypatch, tmp_path,
                                                     outcome, early, title):
    from diffeoforge.desktop.reference_execution_controller import (
        ReferenceExecutionControllerResult,
    )
    from diffeoforge.desktop.reference_worker_protocol import DesktopReferenceWorkerEvent
    from diffeoforge.reference_atlas_handoff import EARLY_CHECK

    notices = []
    window = widgets.DiffeoForgeWindow()
    monkeypatch.setattr(widgets, "notify", lambda _w, title, _msg, **kw: notices.append(title))
    monkeypatch.setattr(window, "_refresh_convergence_advice", lambda _source: None)
    monkeypatch.setattr(window, "_review_run_result", lambda: None)
    if early:
        (tmp_path / "output").mkdir()
        (tmp_path / "output" / EARLY_CHECK).write_text("{}")
    terminal = DesktopReferenceWorkerEvent(
        request_id="notifications", sequence=1, kind="terminal", payload={
            "outcome": outcome, "destination": str(tmp_path), "destination_exists": True,
            "result_sha256": None if outcome == "prepared_not_executed" else "e" * 64,
            "message": "Worker ended",
        },
    )
    window._reference_atlas_event(terminal)
    assert notices == []
    result = ReferenceExecutionControllerResult(
        request_id="notifications", exit_code=0, terminal_event=terminal,
        events=(terminal,), stderr="",
    )
    window._atlas_succeeded(result)
    assert notices == [title]
    window._atlas_failed("Synthetic verification failure")
    assert notices[-1] == "Atlas needs attention"
    window.close()


def test_export_and_measurement_notify_only_when_the_task_finishes(app, monkeypatch, tmp_path):
    from diffeoforge.desktop import mesh_resolution_dialog, r_export_dialog

    notices = []
    for module in (mesh_resolution_dialog, r_export_dialog):
        monkeypatch.setattr(module, "notify", lambda _w, title, _msg, **kw: notices.append(title))
    resolution = mesh_resolution_dialog.MeshResolutionDialog()
    resolution.action = "report"
    resolution.future = Future()
    export = r_export_dialog.RExportDialog()
    export.future = Future()
    resolution._poll()
    export._finished()
    assert notices == []
    resolution.future.set_result(tmp_path)
    export.future.set_exception(OSError("Destination unavailable"))
    resolution._poll()
    export._finished()
    resolution._poll()
    export._finished()
    assert notices == ["Mesh resolution assessment finished", "R export needs attention"]
    resolution.close()
    export.close()


def test_holdout_preparation_notifies_when_next_action_is_available(app, monkeypatch, tmp_path):
    from diffeoforge.desktop import pilot_holdout_check_dialog as holdout

    notices = []
    monkeypatch.setattr(holdout, "notify", lambda _w, title, _msg: notices.append(title))
    monkeypatch.setattr(holdout.PreviewMeshLoader, "request_operation", lambda *args: None)
    window = holdout.PilotHoldoutCheckDialog(tmp_path / "atlas.yaml")
    assert notices == []
    window._prepared(None, SimpleNamespace(run_directory=tmp_path, specimens=["A", "B"],
                                           maximum_iterations=10))
    assert notices == ["Held-out check prepared"] and not window.command.isHidden()
    window.close()


def test_background_ticket_reports_outcome_once(app, monkeypatch):
    class Signals(QObject):
        succeeded = Signal(object)
        failed = Signal(str)
        finished = Signal(object)

    class _ScientificReportWorker:
        def __init__(self):
            self.signals = Signals()

    window = QWidget()
    pool = activity.ActivityPool(window, pool=SimpleNamespace(start=lambda worker: None))
    notices = []
    monkeypatch.setattr(activity, "notify", lambda *args, **kw: notices.append((args[1], kw)))
    for success in (True, False):
        worker = _ScientificReportWorker()
        pool.start(worker)
        if success:
            worker.signals.succeeded.emit(None)
        else:
            worker.signals.failed.emit("Failed")
        worker.signals.finished.emit(worker)
    assert notices == [("Task finished", {"warning": False}),
                       ("Task needs attention", {"warning": True})]
    window.close()
