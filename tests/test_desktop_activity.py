from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from diffeoforge.desktop.activity import ActivityIndicator, ActivityPool
from diffeoforge.desktop.preview_mesh_loader import PreviewMeshLoader


@pytest.fixture
def application(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication(["activity-test"])


class Signals(QObject):
    succeeded = Signal(object)
    failed = Signal(str)
    progress = Signal(object)


def test_activity_tracks_overlap_duplicates_failures_and_existing_cursor(application):
    owner = QWidget()
    owner.setCursor(Qt.CursorShape.CrossCursor)
    queued = []
    pool = ActivityPool(owner, pool=SimpleNamespace(start=queued.append))
    first, second = SimpleNamespace(signals=Signals()), SimpleNamespace(signals=Signals())
    pool.start(first)
    pool.start(first)
    pool.start(second)
    assert len(queued) == 2
    assert len(pool.indicator.tasks) == 2
    assert "other task" in pool.indicator.label.text()
    assert owner.cursor().shape() == Qt.CursorShape.BusyCursor
    first.signals.progress.emit((2, 5, "subject.vtk"))
    assert "2 of 5: subject.vtk" in pool.indicator.label.text()
    first.signals.succeeded.emit(None)
    assert len(pool.indicator.tasks) == 1
    assert owner.cursor().shape() == Qt.CursorShape.BusyCursor
    second.signals.failed.emit("explicit failure")
    assert pool.indicator.isHidden()
    assert owner.cursor().shape() == Qt.CursorShape.CrossCursor
    assert QApplication.overrideCursor() is None


def test_queue_failure_clears_indicator_and_does_not_change_other_window(application):
    owner, other = QWidget(), QWidget()
    previous_shape = owner.cursor().shape()
    other.setCursor(Qt.CursorShape.PointingHandCursor)

    def reject(worker):
        raise RuntimeError("queue failed")

    pool = ActivityPool(owner, pool=SimpleNamespace(start=reject))
    with pytest.raises(RuntimeError, match="queue failed"):
        pool.start(SimpleNamespace(signals=Signals()))
    assert not pool.indicator.tasks
    assert owner.cursor().shape() == previous_shape
    assert other.cursor().shape() == Qt.CursorShape.PointingHandCursor


def test_worker_completion_is_queued_to_gui_and_interface_keeps_processing(application):
    owner = QWidget()
    executor = QThreadPool()
    pool = ActivityPool(owner, pool=executor)
    release = threading.Event()

    class Delayed(QRunnable):
        def __init__(self):
            super().__init__()
            self.signals = Signals()

        def run(self):
            release.wait(5)
            self.signals.succeeded.emit(None)

    pool.start(Delayed())
    try:
        QTest.qWait(20)
        assert pool.indicator.tasks
        assert not pool.indicator.isHidden()
    finally:
        release.set()
        assert executor.waitForDone(5000)
    for _ in range(30):
        application.processEvents()
        if not pool.indicator.tasks:
            break
        QTest.qWait(5)
    assert not pool.indicator.tasks


def test_cancelled_loader_stays_busy_until_real_exit_and_discards_stale_result(application):
    owner = QWidget()
    indicator = ActivityIndicator(owner)
    loader = PreviewMeshLoader(owner)
    indicator.bind_loader(loader, "Loading mesh")
    release = threading.Event()
    received = []
    loader.loaded.connect(lambda *args: received.append(args))
    loader.request_operation("old", lambda: release.wait(5))
    loader.request_operation("queued", lambda: "must not run")
    loader.cancel()
    assert indicator.tasks
    release.set()
    for _ in range(200):
        application.processEvents()
        if not indicator.tasks:
            break
        QTest.qWait(5)
    assert not indicator.tasks
    assert received == []


def test_owner_destroyed_before_completion_disconnects_activity_slots(application):
    from PySide6.QtCore import QCoreApplication, QEvent
    from shiboken6 import isValid

    owner = QWidget()
    pool = ActivityPool(owner, pool=SimpleNamespace(start=lambda worker: None))
    worker = SimpleNamespace(signals=Signals())
    pool.start(worker)
    owner.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert not isValid(owner)
    worker.signals.progress.emit((1, 1, "finished after close"))
    worker.signals.succeeded.emit(None)
    application.processEvents()


def test_project_summary_collapses_paths_but_retains_warnings(application, tmp_path):
    from diffeoforge.desktop.project_setup import DesktopEngine, ProjectSetupResult
    from diffeoforge.desktop.widgets import DiffeoForgeWindow

    window = DiffeoForgeWindow()
    result = ProjectSetupResult(
        engine=DesktopEngine.DEFORMETRICA_REFERENCE,
        config_path=tmp_path / "atlas.yaml", template_path=tmp_path / "template.vtk",
        subject_count=4, report_path=None, notices=("Routine preparation detail",),
        warnings=("Open surface needs review",),
    )
    window._project_succeeded(result)
    assert "4 subjects" in window.result_label.text()
    assert "Atlas not started" in window.result_label.text()
    assert "Open surface needs review" in window.result_label.text()
    assert str(tmp_path) not in window.result_label.text()
    assert str(tmp_path) in window.result_details_label.text()
    assert "Routine preparation detail" in window.result_details_label.text()
    assert window.result_details.panel.isHidden()
    assert window._result is result
    window.close()


@pytest.mark.parametrize("width", [900, 1120, 1440])
@pytest.mark.parametrize("engine_index", [0, 1])
def test_narrow_pages_never_silently_clip_overwide_controls(application, width, engine_index):
    from PySide6.QtWidgets import QFormLayout, QScrollArea

    from diffeoforge.desktop.widgets import DiffeoForgeWindow

    window = DiffeoForgeWindow()
    window.resize(width, 780)
    window.engine_combo.setCurrentIndex(engine_index)
    window.procrustes_box.show()
    window.show()
    application.processEvents()
    pages = [scroll for scroll in window.findChildren(QScrollArea) if scroll.widget() is not None]
    assert len(pages) >= 6
    for scroll in pages:
        assert scroll.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAsNeeded
        if scroll.isVisible():
            assert (scroll.widget().width() <= scroll.viewport().width()
                    or scroll.horizontalScrollBar().maximum() > 0)
    forms = window.procrustes_box.findChildren(QFormLayout)
    assert forms and all(
        form.rowWrapPolicy() == QFormLayout.RowWrapPolicy.WrapLongRows for form in forms
    )
    assert "CSV" in window.landmarks_button.toolTip()
    assert "planned landmarks" in window.landmark_auto_advance_check.toolTip()
    window.close()
    application.processEvents()
