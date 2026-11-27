import threading
import time
from concurrent.futures import Future
from pathlib import Path

import pytest

pytest.importorskip("PySide6")


@pytest.fixture
def qapp(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_optional_cache_permission_failure_never_fails_measurement(tmp_path, monkeypatch):
    from diffeoforge import measurement_cache as cache

    def denied(*args, **kwargs):
        raise PermissionError("Cache storage is unavailable")

    monkeypatch.setattr(cache.os, "replace", denied)
    monkeypatch.setattr(Path, "unlink", denied)
    cache.write_measurement(tmp_path, {"key": "synthetic"}, {"scalar": 1.0})


def test_new_study_cannot_display_report_from_previous_study(qapp, monkeypatch, tmp_path):
    from PySide6.QtWidgets import QAbstractItemView

    from diffeoforge.desktop import mesh_resolution_dialog as module

    pending = Future()
    monkeypatch.setattr(module._WORK, "submit", lambda _: pending)
    dialog = module.MeshResolutionDialog()
    dialog.report = tmp_path / "previous-report.html"
    dialog.show_report.setEnabled(True)
    dialog._start(lambda: None, "Loading a different study", "study")
    assert dialog.report is None and not dialog.show_report.isEnabled()
    assert dialog.table.editTriggers() == QAbstractItemView.EditTrigger.NoEditTriggers
    pending.set_exception(ValueError("fixture complete"))
    dialog._poll()
    dialog.close()
    qapp.processEvents()


def test_method_export_keeps_event_loop_live_and_rejects_duplicate_start(
    qapp, monkeypatch, tmp_path
):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QWidget

    from diffeoforge.desktop import media_export as module
    from diffeoforge.desktop.activity import ActivityIndicator

    gate, entered = threading.Event(), threading.Event()
    gui_thread = threading.get_ident()
    worker_threads, completed, active, ticks = [], [], [], []

    def slow_export(path, **kwargs):
        worker_threads.append(threading.get_ident())
        entered.set()
        assert gate.wait(5)
        return path

    monkeypatch.setattr(module, "export_media", slow_export)
    owner = QWidget()
    indicator = ActivityIndicator(owner)
    controller = module.MediaExportController(owner)
    controller.finished.connect(lambda path: completed.append((path, threading.get_ident())))
    controller.active_changed.connect(active.append)
    target = tmp_path / "synthetic.png"
    try:
        assert controller.start(target)
        assert indicator.tasks
        assert not controller.start(tmp_path / "duplicate.png")
        QTimer.singleShot(0, lambda: ticks.append(True))
        deadline = time.monotonic() + 3
        while (not ticks or not entered.is_set()) and time.monotonic() < deadline:
            qapp.processEvents()
            time.sleep(0.005)
        assert ticks and entered.is_set() and not completed
        assert worker_threads == [worker_threads[0]] and worker_threads[0] != gui_thread
        gate.set()
        while not completed and time.monotonic() < deadline:
            qapp.processEvents()
            time.sleep(0.005)
        assert completed == [(target, gui_thread)] and active == [True, False]
        assert not indicator.tasks
    finally:
        gate.set()
        owner.close()
        qapp.processEvents()


def test_old_media_export_completion_does_not_replace_new_result_status(qapp, tmp_path):
    from diffeoforge.desktop.visualization_panel import VisualizationPanel

    panel = VisualizationPanel()
    panel.directory = tmp_path / "new-result-media"
    panel._export_source = tmp_path / "old-result-media"
    panel.status.setText("New result media ready")
    future = Future()
    future.set_result(tmp_path / "old-result-view.png")
    panel._export_future = future
    panel._export_finished()
    assert panel.status.text() == "New result media ready"
    panel.clear()
    panel.close()
    qapp.processEvents()


def test_closing_export_view_cannot_leave_recording_in_busy_mode(qapp, monkeypatch, tmp_path):
    from PySide6.QtWidgets import QWidget
    from shiboken6 import delete

    from diffeoforge.desktop import media_export as module
    from diffeoforge.desktop.activity import ActivityIndicator

    gate = threading.Event()

    def slow_export(path, **kwargs):
        assert gate.wait(5)
        return path

    monkeypatch.setattr(module, "export_media", slow_export)
    owner = QWidget()
    indicator = ActivityIndicator(owner)
    controller = module.MediaExportController(owner)
    try:
        controller.start(tmp_path / "explicitly-requested.png")
        future = controller.future
        assert indicator.tasks
        delete(controller)
        assert not indicator.tasks
        gate.set()
        assert future.result(timeout=3).name == "explicitly-requested.png"
    finally:
        gate.set()
        owner.close()
        qapp.processEvents()


@pytest.mark.parametrize("width,height", [(850, 650), (1140, 900)])
@pytest.mark.parametrize("maximum", [500, None])
def test_convergence_advice_cannot_squeeze_qc_footer(qapp, monkeypatch, width, height, maximum):
    from PySide6.QtWidgets import QHBoxLayout, QPushButton, QVBoxLayout, QWidget

    from diffeoforge.desktop import convergence_advice as module

    page, footer = QWidget(), QWidget()
    page.resize(width, height)
    vertical = QVBoxLayout(page)
    vertical.addStretch()
    row = QHBoxLayout(footer)
    button = QPushButton("Continue +300 iterations")
    row.addWidget(QPushButton("Back"))
    row.addWidget(button)
    row.addWidget(QPushButton("Open Results"))
    vertical.addWidget(footer)
    future = Future()
    future.set_result((maximum, "Recent objective improvement is still measurable. " * 10, None))
    monkeypatch.setattr(module._POOL, "submit", lambda *args: future)
    controller = module.ConvergenceAdviceController(page, (button,))
    controller.load(Path("synthetic-capped-run"))
    controller._poll()
    page.show()
    qapp.processEvents()
    label = controller.labels[0]
    assert label.parentWidget() is page
    assert label.width() >= width - 80
    assert label.geometry().bottom() < footer.geometry().top()
    assert footer.height() < 100
    page.close()
    qapp.processEvents()


def test_convergence_advice_ignores_a_previous_run_and_reuses_selected_result(qapp, monkeypatch):
    from PySide6.QtWidgets import QPushButton, QVBoxLayout, QWidget

    from diffeoforge.desktop import convergence_advice as module

    page = QWidget()
    layout = QVBoxLayout(page)
    button = QPushButton("Continue +300 iterations")
    layout.addWidget(button)
    previous, selected = Path("old-cap-run"), Path("selected-tolerance-run")
    previous_future, selected_future = Future(), Future()
    assert previous_future.set_running_or_notify_cancel()
    requests = []

    def submit(worker, source):
        requests.append(source)
        return {previous: previous_future, selected: selected_future}[source]

    monkeypatch.setattr(module._POOL, "submit", submit)
    controller = module.ConvergenceAdviceController(page, (button,))
    controller.load(previous)
    controller.load(selected)
    controller.load(selected)
    previous_future.set_result((500, "Old advice", None))
    controller._poll()
    assert button.isHidden() and controller.labels[0].isHidden()

    selected_future.set_result((None, "Selected advice", None))
    controller._poll()
    controller.load(selected)
    assert requests == [previous, selected]
    assert controller.labels[0].text() == "Selected advice"
    assert not controller.labels[0].isHidden()
    assert button.isHidden() and page._iteration_extension_source is None
    page.close()
    qapp.processEvents()
