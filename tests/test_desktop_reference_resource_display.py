from __future__ import annotations

import os

import pytest


def test_resource_only_update_preserves_optimizer_progress_and_event_log(monkeypatch):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from diffeoforge.desktop.reference_worker_protocol import DesktopReferenceWorkerEvent
    from diffeoforge.desktop.widgets import DiffeoForgeWindow
    from diffeoforge.resource_monitor import ProcessResourceMonitor

    app = QApplication.instance() or QApplication(["resource-display-test"])
    window = DiffeoForgeWindow()
    try:
        window.run_progress_bar.setRange(0, 100)
        window.run_progress_bar.setValue(5)
        window.run_state_label.setText("Optimizing at iteration 5")
        window.run_optimizer_label.setText("Iteration 5\nLive resources: previous sample")
        window.run_event_log.setPlainText("Iteration 5 observed")
        resources = ProcessResourceMonitor(os.getpid(), requested_device="cpu").sample()
        window._reference_atlas_event(DesktopReferenceWorkerEvent(
            request_id="resources-test", sequence=8, kind="resources", payload=resources,
        ))
        assert window.run_event_log.toPlainText() == "Iteration 5 observed"
        assert window.run_progress_bar.value() == 5
        assert window.run_progress_bar.maximum() == 100
        assert window.run_state_label.text() == "Optimizing at iteration 5"
        assert window.run_optimizer_label.text().startswith("Iteration 5\nLive resources:")
        assert "previous sample" not in window.run_optimizer_label.text()
    finally:
        window.close()
        app.processEvents()
