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
            "optimizer_convergence_tolerance": 1e-6,
            "log_likelihood": -10., "attachment": -8., "regularity": -2.,
            "elapsed_seconds": 3., "eta_to_iteration_cap_seconds": None,
            "seconds_per_iteration": None, "estimate_status": "warming_up",
        },
    )
    window._reference_atlas_event(event)
    assert not window.run_stop_rule_label.isHidden()
    assert window.run_stop_rule_label.text() == "Optimizer convergence tolerance 1e-06"
    assert window.run_live_optimizer_plot.samples[0].iteration == 300
    assert not window.run_live_optimizer_plot.isHidden()
    source = tmp_path / "finished"
    from diffeoforge.desktop import convergence_advice

    monkeypatch.setattr(convergence_advice, "run_advice", lambda path: (300, "Advice"))
    window._refresh_convergence_advice(source)
    window._convergence_advice.future.result(timeout=5)
    window._convergence_advice._poll()
    assert "300 → 600" in window.run_more_iterations_button.text()
    assert not window.result_more_iterations_button.isHidden()
    assert not window.qc_more_iterations_button.isHidden()
    # Reopened capped results first enter QC. Continuing must not require its release.
    monkeypatch.setattr(window, "_registration_results_released", lambda: False)
    window.page_stack.setCurrentIndex(4)
    window.show()
    app.processEvents()
    assert window.qc_more_iterations_button.isVisible()
    assert window.qc_more_iterations_button.isEnabled()
    assert not window._step_is_unlocked(5)
    request = replace(_request(tmp_path), resume_source=source.resolve(), additional_iterations=300)
    result = widgets.ResumableReferenceRun(
        run_directory=source, project_name="synthetic", subject_count=2,
        terminal_status="completed", checkpoint_bytes=123,
        source_config_path=request.config_path, source_config_sha256=request.expected_config_sha256,
        convergence_origin_iteration=0,
    )
    from test_desktop_reference_prelaunch import _review

    window._review = _review(request.config_path)
    queued = []

    class QueueOnlyPool:
        def start(self, worker):
            queued.append(worker)

    window._thread_pool = QueueOnlyPool()
    window.qc_more_iterations_button.click()
    assert len(queued) == 1
    assert isinstance(queued[0], widgets._IterationExtensionWorker)
    assert queued[0].source == source
    assert window._worker is queued[0]
    assert not request.destination.exists()
    window._iteration_extension_ready((request, result, 300))
    assert "keeps the objective from iteration 0" in window.run_boundary_label.text()
    assert "300 → 600" in window.run_summary_label.text()
    assert "Start +300" in window.start_atlas_button.text()
    window._sync_ready_state()
    assert "Start +300" in window.start_atlas_button.text()
    assert not request.destination.exists()
    assert not window.run_live_optimizer_plot.samples
    window._clear_engine_project_state()
    assert window.run_stop_rule_label.isHidden()
    assert window._iteration_extension_source is None
    assert window.run_more_iterations_button.isHidden()
    assert window.run_live_optimizer_plot.isHidden()
    window.close()


def test_tolerance_stop_shows_diagnosis_without_continuation_on_every_page(
    app, monkeypatch, tmp_path
):
    from diffeoforge.desktop import convergence_advice, widgets

    source = tmp_path / "completed"
    advice = "Native stop: tolerance reached.\nLast 50 logged iterations: objective improved."
    monkeypatch.setattr(convergence_advice, "run_advice", lambda path: (None, advice))

    window = widgets.DiffeoForgeWindow()
    window._refresh_convergence_advice(source)
    controller = window._convergence_advice
    controller.future.result(timeout=5)
    controller._poll()
    assert [label.text() for label in controller.labels] == [advice] * 3
    assert all(not label.isHidden() for label in controller.labels)
    assert all(button.isHidden() for button in controller.buttons)
    assert window._iteration_extension_source is None
    window._clear_engine_project_state()
    assert all(label.isHidden() for label in controller.labels)
    window.close()


@pytest.mark.parametrize(("stability", "unlimited"), [(False, False), (True, False), (True, True)])
def test_reopened_advice_shows_thresholds_only_for_stability(tmp_path, stability, unlimited):
    from test_reference_morphospace_stopping import _retained_report

    from diffeoforge.desktop.convergence_advice import _review_advice

    run, _ = _retained_report(
        tmp_path, full_window=True if stability else None, unlimited=unlimited,
        reason="morphospace_stable" if stability else "native_tolerance",
    )
    _, advice = _review_advice(run)
    assert "Weighted fit error, first to last checkpoint" in advice
    assert ("requires <1%" in advice) == stability
    assert ("requires <2%" in advice) == stability
    assert ("400/400" in advice) == stability


def test_atlas_live_checkpoint_shows_outlier_and_available_window(app):
    from diffeoforge.desktop import widgets
    from diffeoforge.desktop.reference_worker_protocol import DesktopReferenceWorkerEvent

    window = widgets.DiffeoForgeWindow()
    payload = {
        "iteration": 425, "previous_iteration": 225, "window_iterations": 200,
        "status": "measured", "cohort_percent": 0.4, "max_subject_percent": 3.0,
        "worst_subjects": ["outlier.vtk"], "weighted_fit_error": 0.08,
        "long_window": {
            "previous_iteration": 25, "window_iterations": 400, "status": "measured",
            "cohort_percent": 1.5, "max_subject_percent": 1.8, "worst_subjects": ["other.vtk"],
        },
    }
    window._reference_atlas_event(DesktopReferenceWorkerEvent(
        request_id="window", sequence=0, kind="morphospace_progress", payload=payload,
    ))
    preview = window.run_stop_rule_label.text()
    assert "225 → 425" in preview and "200/200" in preview
    assert "25 → 425" in preview and "400/400" in preview
    assert "Cohort 1.5% (requires <1%; above or at threshold)" in preview
    assert "Cohort 0.4% (requires <1%; within threshold)" in preview
    assert "Highest specimen 3% (requires <2%; above or at threshold)" in preview
    assert "outlier.vtk" in preview and "Weighted fit error 0.08" in preview
    window._clear_engine_project_state()
    assert window.run_stop_rule_label.isHidden()
    window.close()


def test_atlas_progress_stays_indeterminate_without_limit(app):
    from diffeoforge.desktop import widgets
    from diffeoforge.desktop.reference_worker_protocol import DesktopReferenceWorkerEvent

    window = widgets.DiffeoForgeWindow()
    payload = {
        "iteration": 1290, "maximum_iterations": None,
        "log_likelihood": -12.0, "attachment": -9.0, "regularity": -3.0,
        "elapsed_seconds": 512.0, "seconds_per_iteration": 0.4,
        "eta_to_iteration_cap_seconds": None, "estimate_status": "no_iteration_limit",
    }
    window._reference_atlas_event(DesktopReferenceWorkerEvent(
        request_id="atlas", sequence=0, kind="progress", payload=payload,
    ))
    assert window.run_progress_bar.minimum() == window.run_progress_bar.maximum() == 0
    assert "1290" in window.run_state_label.text()
    assert "no iteration limit" in window.run_optimizer_label.text()
    assert "0.40 s/iteration" in window.run_optimizer_label.text()
    window.close()


def test_verified_tolerance_stop_shows_explicit_continuation(app, monkeypatch, tmp_path):
    from diffeoforge.desktop import convergence_advice, widgets
    from diffeoforge.runs import ToleranceContinuation

    source = tmp_path / "completed"
    plan = ToleranceContinuation(317, 1600, 300, 617, 1.e-6, 1.e-7, "a" * 64, "b" * 64)
    monkeypatch.setattr(convergence_advice, "run_advice", lambda path: (None, "Native stop"))
    monkeypatch.setattr(convergence_advice, "tolerance_extension_preview", lambda path: plan)
    window = widgets.DiffeoForgeWindow()
    window._refresh_convergence_advice(source)
    controller = window._convergence_advice
    controller.future.result(timeout=5)
    controller._poll()
    assert window._iteration_extension_after_tolerance
    assert not controller.buttons[0].isHidden()
    assert "+300 iterations with tighter tolerance" in controller.buttons[0].text()
    assert "317" in controller.buttons[0].toolTip()
    assert "617" in controller.buttons[0].toolTip()
    assert not source.exists()
    window.close()
