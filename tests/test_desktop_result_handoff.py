"""Real signal/queue regressions for the atlas-to-result handoff."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from diffeoforge.desktop.activity import ActivityPool
from diffeoforge.desktop.widgets import DiffeoForgeWindow, _ResultReviewWorker


@pytest.fixture
def application(monkeypatch, tmp_path):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("DIFFEOFORGE_STATE_HOME", str(tmp_path / "state"))
    return QApplication.instance() or QApplication(["handoff-test"])


def test_real_queued_completions_can_dispatch_successors(application):
    class Signals(QObject):
        succeeded = Signal(object)
        failed = Signal(str)

    class Worker(QRunnable):
        def __init__(self, number):
            super().__init__()
            self.number = number
            self.signals = Signals()

        def run(self):
            self.signals.succeeded.emit(self.number)

    owner = QWidget()
    executor = QThreadPool()
    pool = ActivityPool(owner, pool=executor)

    class Receiver(QObject):
        def __init__(self):
            super().__init__()
            self.worker = None
            self.received = []

        def start(self, number):
            self.worker = Worker(number)
            # Same ordering as the GUI: app completion before activity cleanup.
            self.worker.signals.succeeded.connect(self.done)
            pool.start(self.worker)

        @Slot(object)
        def done(self, number):
            self.worker = None
            self.received.append(number)
            if number < 24:
                self.start(number + 1)

    receiver = Receiver()
    receiver.start(0)
    try:
        for _ in range(500):
            application.processEvents()
            if len(receiver.received) == 25 and not pool.indicator.tasks:
                break
            QTest.qWait(5)
        assert receiver.received == list(range(25))
        assert not pool.indicator.tasks
    finally:
        assert executor.waitForDone(5000)


@pytest.mark.parametrize("reference", [False, True])
def test_result_worker_reports_unexpected_exceptions(application, monkeypatch, tmp_path, reference):
    import diffeoforge.desktop.widgets as widgets

    def fail(*_args, **_kwargs):
        raise KeyError("unexpected importer key")

    monkeypatch.setattr(widgets, "review_reference_result", fail)
    monkeypatch.setattr(widgets, "review_modern_result", fail)
    worker = _ResultReviewWorker(tmp_path, reference=reference)
    errors, successes = [], []
    worker.signals.failed.connect(errors.append)
    worker.signals.succeeded.connect(successes.append)
    worker.run()
    assert errors == ["KeyError: 'unexpected importer key'"]
    assert not successes


def test_saved_result_progress_replaces_stale_backend_status(application, tmp_path):
    window = DiffeoForgeWindow()
    queued = []
    window._thread_pool = SimpleNamespace(start=queued.append)
    window.run_optimizer_label.setText("Old atlas resource reading")
    window._open_completed_result(SimpleNamespace(run_directory=tmp_path, reference=True))
    assert len(queued) == 1
    assert "no longer live" in window.run_optimizer_label.text()
    queued[0].signals.progress.emit((4, 21, "Checking registration surfaces"))
    assert "4 of 21" in window.run_stage_label.text()
    assert "Checking registration surfaces" in window.data_status_label.text()
    assert window.run_progress_bar.value() == 4
    assert window.run_progress_bar.maximum() == 21
    queued[0].signals.progress.emit((0, 0, "Assembling review"))
    assert window.run_progress_bar.maximum() == 0
    window._completed_result_review_failed("test cleanup")
    assert window.open_completed_run_button.isEnabled()
    window.close()


def test_saved_result_dispatch_failure_is_visible_and_retryable(application, tmp_path):
    window = DiffeoForgeWindow()

    def reject(_worker):
        raise RuntimeError("queue rejected")

    window._thread_pool = SimpleNamespace(start=reject)
    window._open_completed_result(SimpleNamespace(run_directory=tmp_path, reference=True))
    assert window._worker is None
    assert "queue rejected" in window.data_status_label.text()
    assert window.open_completed_run_button.isEnabled()
    window.close()
