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
    assert 'Fit saved · checks cancelled' in texts
    assert not any('Optimize longer with the same settings' in text for text in texts)
    panel.window.start_button.click()
    assert len(panel.invoked) == 1 and not panel.snapshot.visual_reviews


def test_scope_and_failed_checks_are_visible_without_a_technical_disclosure(panel):
    from PySide6.QtWidgets import QLabel


    panel.guidance['regional_scope'] = dict(text='This trial: improve C; keep B in place.')
    panel.render()
    scope = panel.window.content.findChild(QLabel, 'regionalTrialScope')
    assert scope.isVisible() and 'improve C' in scope.text()
    assert any('Numerical checks did not pass' in w.text()
               for w in panel.window.content.findChildren(QLabel) if w.isVisible())


@pytest.mark.parametrize('phase', [None, 'fixed_shooting'])
def test_check_clock_uses_whole_qualification_not_the_restarted_internal_batch(panel, phase):
    from PySide6.QtWidgets import QLabel

    from diffeoforge.desktop.reference_calibration_dialog import ReferenceCalibrationDialog

    window = SimpleNamespace(_worker=None, status=QLabel(),
        _thread_pool=SimpleNamespace(indicator=SimpleNamespace(label=QLabel())))
    event = dict(event='qualification_progress', timepoints=577, elapsed_seconds=2.,
                 completed_subjects=0, total_subjects=1, qualification_elapsed_seconds=720.)
    if phase is not None:
        event['phase'] = phase
    ReferenceCalibrationDialog._event(window, event)
    assert '12.0 min checking' in window.status.text()
    assert '0.0 min' not in window.status.text()


@pytest.mark.parametrize('event', ['qualification_phase', 'qualification_progress'])
def test_late_qualification_events_cannot_hide_a_cancel_request(panel, event):
    from PySide6.QtWidgets import QLabel

    from diffeoforge.desktop.reference_calibration_dialog import ReferenceCalibrationDialog

    window = SimpleNamespace(
        _worker=SimpleNamespace(runner=SimpleNamespace(_cancel_requested=True)),
        status=QLabel())
    ReferenceCalibrationDialog._event(window, dict(event=event, message='Refining pass 8'))
    assert 'Stopping the current surface check' in window.status.text()
