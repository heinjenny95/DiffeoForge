from __future__ import annotations

import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from diffeoforge.validation_progress import (
    backend_status,
    ledger_start,
    validation_progress,
    wall_seconds,
)


def state(
    name: str, status: str = "pending", backend: str = "unknown", terminal: str | None = None
) -> NS:
    return NS(
        run_id=name,
        status=status,
        backend_status=backend,
        terminal_event=terminal,
        evidence=object() if status == "completed" else None,
    )


def training(*runs: NS, status: str = "ready") -> NS:
    return NS(runs=runs, plan=NS(finalists=("a", "b", "c")), status=status)


def test_count_frozen_slots_including_unprepared_holdout() -> None:
    snapshot = training(
        state("done", "completed"),
        state("post", "failed", "completed"),
        state("crash", "failed"),
        state("cancel", "failed", terminal="run_interrupted"),
        state("orphan", "orphaned"),
        state("active"),
        state("pending"),
    )
    p = validation_progress(snapshot, active_mode="training", active_run_id="active")
    assert (p.verified, p.total, p.backend_finished) == (1, 10, 2)
    assert (p.evidence_failed, p.execution_failed, p.interrupted, p.active, p.pending) == (
        1,
        1,
        2,
        1,
        4,
    )
    assert not p.reports_complete


def test_backend_finish_is_not_verified_or_full_validation_complete() -> None:
    t = training(state("first"))
    p = validation_progress(
        t, active_mode="training", active_run_id="first", evidence_run_id="first"
    )
    assert (p.backend_finished, p.evidence_pending, p.verified, p.active) == (1, 1, 0, 0)
    t = training(state("first", "completed"), status="completed")
    held = NS(runs=tuple(state(str(i), "completed") for i in range(3)), status="awaiting_report")
    p = validation_progress(t, held)
    assert p.verified == p.total == 4
    assert not p.reports_complete
    held.status = "completed"
    assert validation_progress(t, held).reports_complete


def test_reopened_backend_receipt_never_promotes_evidence(tmp_path: Path) -> None:
    assert backend_status(tmp_path, verified=False) == "unknown"
    (tmp_path / "result.json").write_text('{"status":"completed","return_code":0}')
    observed = backend_status(tmp_path, verified=False)
    p = validation_progress(training(state("orphan", "orphaned", observed)))
    assert (p.backend_finished, p.evidence_pending, p.verified) == (1, 1, 0)


def test_original_wall_clock_includes_reopen_pause_and_freezes_at_completion() -> None:
    events = [
        {"event": "study_created", "recorded_at": "2026-09-01T00:00:00+00:00"},
        {"event": "run_started", "recorded_at": "2026-09-02T00:00:00+00:00"},
        {"event": "run_started", "recorded_at": "2026-09-03T00:00:00+00:00"},
    ]
    now = datetime(2026, 9, 4, tzinfo=UTC)
    assert wall_seconds(ledger_start(events), now=now) == 2 * 86400
    assert wall_seconds(ledger_start(events), end=events[-1]["recorded_at"], now=now) == 86400
    del events[1]["recorded_at"]
    assert ledger_start(events) is None
    assert wall_seconds(None, now=now) is None
    assert wall_seconds("invalid", now=now) is None
    assert (
        ledger_start([{"event": "run_inherited", "recorded_at": "2026-09-03T00:00:00+00:00"}])
        is None
    )


def test_completed_holdout_backend_is_not_relaunched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import diffeoforge.reference_holdout_study as module

    run = state("finished-engine", "failed", "completed")
    snapshot = NS(status="ready_to_retry", runs=(run,))
    monkeypatch.setattr(module, "load_reference_holdout_study", lambda directory: snapshot)
    monkeypatch.setattr(module, "_verify_manifest", lambda directory: {})
    runner = module.ReferenceHoldoutStudyRunner(
        tmp_path, controller_factory=lambda request: pytest.fail("Must not rerun completed backend")
    )
    with pytest.raises(module.ReferenceHoldoutStudyError, match="evidence requires"):
        runner.run_all()


def pump(app: object, until: object) -> None:
    deadline = time.monotonic() + 10
    while not until() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    assert until()


def test_preparation_keeps_ui_alive_and_cancel_discards_late_result(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from diffeoforge.desktop.reference_validation_dialog import ReferenceValidationDialog

    app = QApplication.instance() or QApplication([])
    entered, release = threading.Event(), threading.Event()
    worker_threads: list[int] = []
    ticks: list[bool] = []

    def prepare(cancelled: object, phase: object) -> Path:
        worker_threads.append(threading.get_ident())
        entered.set()
        assert release.wait(5)
        return tmp_path

    dialog = ReferenceValidationDialog(tmp_path, prepare=prepare)
    dialog.show()
    timer = QTimer(dialog)
    timer.timeout.connect(lambda: ticks.append(True))
    timer.start(1)
    try:
        pump(app, lambda: entered.is_set() and len(ticks) >= 3)
        assert len(worker_threads) == 1
        assert worker_threads[0] != threading.get_ident()
        assert not dialog.run_button.isEnabled()
        original_worker = dialog._worker
        dialog._run()
        assert dialog._worker is original_worker
        dialog._cancel()
        release.set()
        pump(app, lambda: dialog._worker is None)
        assert dialog._snapshot is None
        assert "cancelled" in dialog.status_label.text().lower()
        assert not any(tmp_path.iterdir())
    finally:
        release.set()
        pump(app, lambda: dialog._worker is None)
        dialog.close()


def test_cancel_after_worker_success_queued_never_launches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QMessageBox

    from diffeoforge.desktop.reference_validation_dialog import ReferenceValidationDialog

    app = QApplication.instance() or QApplication([])
    dialog = ReferenceValidationDialog(tmp_path)
    monkeypatch.setattr(QMessageBox, "critical", lambda *args: None)
    pump(app, lambda: dialog._worker is None)
    monkeypatch.setattr(QMessageBox, "question", lambda *args: pytest.fail("Must not confirm"))
    dialog._cancel_requested = True
    dialog._prepared((None, None, (object(), "training", "Start?")))
    assert dialog._worker is None
    assert "cancelled" in dialog.status_label.text().lower()
    dialog.close()
