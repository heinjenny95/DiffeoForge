from types import SimpleNamespace

import pytest
from test_guided_suitable_dialog import panel as _panel

panel = _panel


def test_cancelled_checks_offer_resume_without_a_new_fit(panel):
    panel.candidate.status = 'interrupted'
    panel.candidate.metrics = None
    panel.candidate.error = 'Surface checks cancelled; saved fit retained'
    panel.snapshot.visual_reviews.clear()
    panel.guidance['qualification_pending'] = {panel.candidate.candidate_id: {}}
    panel.window.layout().addWidget(panel.window.start_button)
    panel.window.start_button.clicked.connect(panel.window._start_pilot)
    panel.render()
    assert panel.window.start_button.isEnabled()
    assert 'Resume checks' in panel.window.start_button.text()
    assert 'no new fitting' in panel.window.start_button.text()
    assert 'failed' not in panel.window.status.text()
    from PySide6.QtWidgets import QLabel

    texts = [w.text() for w in panel.window.content.findChildren(QLabel)]
    assert 'Fit saved · checks incomplete' in texts
    assert not any('Optimize longer with the same settings' in text for text in texts)
    panel.window.start_button.click()
    assert len(panel.invoked) == 1 and not panel.snapshot.visual_reviews


def test_scope_and_failed_checks_are_visible_without_a_technical_disclosure(panel):
    from PySide6.QtWidgets import QLabel

    panel.guidance['regional_scope'] = dict(text='This trial: improve C; keep B in place.')
    metrics = panel.candidate.metrics
    metrics.update(runtime_seconds=2076, pipeline_wall_seconds=2604,
                   maximum_iterations=600, final_iteration=600)
    quality = metrics["attachment_comparison"]["subjects"]["specimen.vtk"]["regional_quality"]
    quality.update(local_improved=True, baseline_surface_p95=0.218, active_surface_p95=0.039,
                   explicit_fixed_preserved=True, qualification_wall_seconds=426)
    panel.snapshot.attachment_comparison["iterations"] = 600
    panel.render()
    scope = panel.window.content.findChild(QLabel, 'regionalTrialScope')
    assert scope.isVisible() and 'improve C' in scope.text()
    assert any('Numerical checks did not pass' in w.text()
               for w in panel.window.content.findChildren(QLabel) if w.isVisible())
    result = panel.window.content.findChild(QLabel, "regionalCheckOutcome")
    assert result.isVisible()
    assert "Marked-area P95 distance fell by 82.1%" in result.text()
    assert "new surface intersection flags, source geometry refinement limit" in result.text()
    assert "Review these checks before spending more iterations" in result.text()
    assert "fixed marked areas" not in result.text()
    assert any(
        "43.4 min total · 34.6 min fit run" in row.text() and "7.1 min checks" in row.text()
        for row in panel.window.content.findChildren(QLabel)
        if row.isVisible()
    )


def test_prepared_single_regional_fit_names_its_own_iteration_allowance(panel):
    from PySide6.QtWidgets import QLabel

    panel.candidate.status = "pending"
    panel.candidate.metrics = None
    panel.snapshot.visual_reviews.clear()
    panel.snapshot.attachment_comparison["iterations"] = 600
    panel.window.layout().addWidget(panel.window.start_button)
    panel.render()
    assert panel.window.start_button.text() == "Run single protected local fit"
    effort = panel.window.content.findChild(QLabel, "singleRegionalEffort")
    assert effort.isVisible()
    assert "up to 600 iterations, then surface checks" in effort.text()
    assert not panel.invoked


@pytest.mark.parametrize(("limit", "continuation"), [(120, False), (480, True)])
def test_prepared_early_review_uses_the_shared_budget_and_waits_for_run(panel, limit, continuation):
    from PySide6.QtWidgets import QLabel

    panel.candidate.status = "pending"
    panel.candidate.metrics = None
    panel.snapshot.visual_reviews.clear()
    record = panel.snapshot.attachment_comparison
    record["iterations"] = limit
    strategy = panel.info["strategy"] = dict(regional_recipe=dict(review_checkpoint=dict(
        version="regional-review-checkpoint-v1", first_iterations=120, total_iterations=600)))
    if continuation:
        strategy["optimization"] = dict(reference={})
    panel.window.layout().addWidget(panel.window.start_button)
    panel.render()
    effort = panel.window.content.findChild(QLabel, "singleRegionalEffort")
    assert effort.isVisible()
    assert "600" in effort.text() and str(limit) in effort.text()
    assert panel.window.start_button.text().startswith(
        "Run local continuation" if continuation else "Run first local check"
    )
    assert not panel.invoked


def test_directional_distances_reveal_tradeoffs_per_exact_mark(panel):
    from PySide6.QtWidgets import QLabel

    def row(region, forward, reverse):
        return dict(region=region, diagonal=10., repeats=[
            dict(original_to_fit_p95=forward, fit_to_original_p95=reverse)
        ] * 2)

    problem = dict(purpose="problem", center=[0, 0, 0])
    fixed = dict(purpose="fixed", center=[1, 0, 0])
    extra = dict(purpose="problem", center=[2, 0, 0])
    panel.info["feedback"] = dict(baseline=[
        row(problem, .4, .2), row(fixed, .1, .1), row(extra, .4, .2),
    ])
    target = panel.candidate.metrics["attachment_comparison"]["subjects"]["specimen.vtk"]
    target["marked_regions"] = dict(outcome="regression", measurements=[
        row(problem, .2, .3), row(fixed, .1, .1), row(extra, None, .1),
    ])
    panel.render()
    changes = panel.window.content.findChild(QLabel, "markedAreaP95Changes")
    assert changes.isVisible()
    assert "A · -2.00 pp / +1.00 pp" in changes.text()
    assert "C · unavailable / -1.00 pp" in changes.text()
    assert "B ·" not in changes.text()


@pytest.fixture
def qualification_receiver(panel):
    from PySide6.QtCore import QObject
    from PySide6.QtWidgets import QLabel

    from diffeoforge.desktop.reference_calibration_dialog import (
        ReferenceCalibrationDialog,
        _CalibrationSignals,
    )

    class Receiver(QObject):
        _event = ReferenceCalibrationDialog._event
        _current_worker_signal = ReferenceCalibrationDialog._current_worker_signal

    window = Receiver(panel.window)
    window.status = QLabel(panel.window)
    window._view_closed = False
    window._thread_pool = SimpleNamespace(indicator=SimpleNamespace(label=QLabel(panel.window)))
    window._worker = SimpleNamespace(
        signals=_CalibrationSignals(window),
        runner=SimpleNamespace(_cancel_requested=False),
    )
    window._worker.signals.event.connect(window._event)
    return window


@pytest.mark.parametrize('phase', [None, 'fixed_shooting'])
def test_check_clock_uses_whole_qualification_not_the_restarted_internal_batch(
    qualification_receiver, phase
):
    from diffeoforge.desktop.reference_calibration_dialog import _CalibrationSignals

    window = qualification_receiver
    event = dict(event='qualification_progress', timepoints=577, elapsed_seconds=2.,
                 completed_subjects=0, total_subjects=1, qualification_elapsed_seconds=720.)
    if phase is not None:
        event['phase'] = phase
    retired = _CalibrationSignals(window)
    retired.event.connect(window._event)
    retired.event.emit(event)
    assert not window.status.text()

    window._worker.signals.event.emit(event)
    assert '12.0 min checking' in window.status.text()
    assert '0.0 min' not in window.status.text()


@pytest.mark.parametrize('event', ['qualification_phase', 'qualification_progress'])
def test_late_qualification_events_cannot_hide_a_cancel_request(qualification_receiver, event):
    window = qualification_receiver
    window._worker.runner._cancel_requested = True
    window._worker.signals.event.emit(dict(event=event, message='Refining pass 8'))
    assert 'Stopping the current surface check' in window.status.text()
