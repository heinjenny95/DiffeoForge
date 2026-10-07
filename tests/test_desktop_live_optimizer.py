from __future__ import annotations

import math
from dataclasses import replace
from types import SimpleNamespace

import pytest

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication

from diffeoforge.desktop.live_optimizer_plot import MAX_LIVE_SAMPLES, LiveOptimizerPlot


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication(["live-optimizer-test"])


def test_plot_accepts_resumed_history_and_rejects_invalid_or_stale_values(app):
    plot = LiveOptimizerPlot()
    assert plot.add_sample(300, -100.0, -90.0, -10.0)
    assert plot.add_sample(301, -95.0, -86.0, -9.0)
    for row in [(301, -90, -80, -10), (299, -90, -80, -10), (True, -1, -1, 0),
                (302, math.nan, -1, -1), (302, -1, math.inf, -1), (302, True, -1, -1)]:
        assert not plot.add_sample(*row)
    assert [sample.iteration for sample in plot.samples] == [300, 301]
    assert "300–301" in plot.status_label.text()
    plot.clear()
    assert not plot.samples
    assert plot.add_sample(0, -20, -18, -2)
    plot.close()


def test_render_empty_single_flat_extreme_and_bounded_series(app):
    plot = LiveOptimizerPlot()
    plot.resize(840, 450)
    plot.show()
    app.processEvents()
    assert not plot.grab().isNull()
    for values in [(-10., -8., -2.), (1.7e308, -1.7e308, 0.)]:
        plot.clear()
        plot.add_sample(10, *values)
        app.processEvents()
        assert not plot.grab().isNull()
        plot.add_sample(11, *values)
        plot.attachment_checkbox.setChecked(True)
        plot.regularity_checkbox.setChecked(True)
        assert plot.canvas.height() == 360
        app.processEvents()
        assert not plot.grab().isNull()
    plot.clear()
    for iteration in range(MAX_LIVE_SAMPLES + 5):
        plot.add_sample(iteration, -10., -8., -2.)
    assert len(plot.samples) == MAX_LIVE_SAMPLES
    assert plot.samples[0].iteration == 5
    app.processEvents()
    assert not plot.grab().isNull()
    plot.close()


def test_run_window_observes_progress_and_clears_engine_bound_history(app, monkeypatch, tmp_path):
    from test_desktop_reference_execution_worker import _request

    from diffeoforge.desktop import widgets
    from diffeoforge.desktop.project_setup import DesktopEngine
    from diffeoforge.desktop.reference_worker_protocol import DesktopReferenceWorkerEvent

    window = widgets.DiffeoForgeWindow()
    window._review = SimpleNamespace(engine=DesktopEngine.DEFORMETRICA_REFERENCE)
    event = DesktopReferenceWorkerEvent(
        request_id="plot-test", sequence=1, kind="progress", payload={
            "iteration": 300, "maximum_iterations": 600,
            "log_likelihood": -10., "attachment": -8., "regularity": -2.,
            "elapsed_seconds": 3., "eta_to_iteration_cap_seconds": None,
            "seconds_per_iteration": None, "estimate_status": "warming_up",
        },
    )
    window._reference_atlas_event(event)
    assert window.run_live_optimizer_plot.samples[0].iteration == 300
    assert not window.run_live_optimizer_plot.isHidden()
    source = tmp_path / "finished"
    monkeypatch.setattr(widgets, "iteration_extension_limit", lambda path: 300)
    window._refresh_iteration_extension(source)
    assert "300 → 600" in window.run_more_iterations_button.text()
    assert not window.result_more_iterations_button.isHidden()
    request = replace(_request(tmp_path), resume_source=source.resolve(), additional_iterations=300)
    result = widgets.ResumableReferenceRun(
        run_directory=source, project_name="synthetic", subject_count=2,
        terminal_status="completed", checkpoint_bytes=123,
        source_config_path=request.config_path, source_config_sha256=request.expected_config_sha256,
    )
    from test_desktop_reference_prelaunch import _review

    window._review = _review(request.config_path)
    queued = []

    class QueueOnlyPool:
        def start(self, worker):
            queued.append(worker)

    window._thread_pool = QueueOnlyPool()
    window.run_more_iterations_button.click()
    assert len(queued) == 1
    assert isinstance(queued[0], widgets._IterationExtensionWorker)
    assert queued[0].source == source
    assert window._worker is queued[0]
    assert not request.destination.exists()
    window._iteration_extension_ready((request, result, 300))
    assert "300 → 600" in window.run_summary_label.text()
    assert "Start +300" in window.start_atlas_button.text()
    window._sync_ready_state()
    assert "Start +300" in window.start_atlas_button.text()
    assert not request.destination.exists()
    assert not window.run_live_optimizer_plot.samples
    window._clear_engine_project_state()
    assert window._iteration_extension_source is None
    assert window.run_more_iterations_button.isHidden()
    assert window.run_live_optimizer_plot.isHidden()
    window.close()
