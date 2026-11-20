"""Completed fitting with incomplete checks must not suggest a new native trial."""

from types import SimpleNamespace

import pytest
from test_failed_parent_recovery import route as _route
from test_guided_suitable_dialog import panel as _panel

panel = _panel
route = _route


def test_failed_postfit_checks_have_one_primary_resume_action(panel, monkeypatch):
    from PySide6.QtWidgets import QLabel, QPushButton

    from diffeoforge.desktop import guided_failed_parent

    candidate = panel.candidate
    candidate.status = "failed"
    candidate.metrics = None
    candidate.error = "The marked reconstruction material connectivity changed"
    panel.snapshot.visual_reviews.clear()
    panel.guidance["feedback"].clear()
    panel.guidance["allowed"].clear()
    panel.guidance["qualification_pending"] = {candidate.candidate_id: {}}
    # An older prepared view can still carry the numerical-recovery explanation.
    # It must not be presented as the cause of these incomplete surface checks.
    panel.guidance["failed_parents"] = {candidate.candidate_id: dict(
        reason="The failed backend has no matching normal terminal shutdown",
        reference={"directory": "synthetic-earlier-fit"},
    )}

    def forbidden(*_):
        raise AssertionError("Incomplete checks were routed to numerical-failure recovery")

    monkeypatch.setattr(guided_failed_parent, "render", forbidden)
    panel.window.layout().addWidget(panel.window.start_button)
    panel.window.start_button.clicked.connect(panel.window._start_pilot)
    panel.render()
    assert not panel.invoked and not panel.snapshot.visual_reviews
    active = [b for b in panel.window.findChildren(QPushButton)
              if b.isVisible() and b.isEnabled() and b.objectName() == "primary"]
    assert active == [panel.window.start_button]
    assert "Resume checks on saved fit" in active[0].text()
    assert "no new fitting" in active[0].text()
    assert "Resume checks" in panel.window.status.text()
    labels = [label.text() for label in panel.window.content.findChildren(QLabel)]
    assert "Fit saved · checks incomplete" in labels
    assert not any("normal terminal shutdown" in label for label in labels)
    panel.window.start_button.click()
    assert len(panel.invoked) == 1 and not panel.snapshot.visual_reviews


def test_completed_native_checks_skip_failed_field_proposals(route, monkeypatch):
    from diffeoforge import (
        guided_failed_parent,
        guided_strategy,
        pilot_multiscale_failure,
        reference_qualification_resume,
    )

    identifier = route.identifier
    binding = {identifier: {"version": "synthetic-verified-native-binding"}}
    monkeypatch.setattr(reference_qualification_resume, "pending", lambda _: binding)

    def forbidden(*_):
        raise AssertionError("A completed native fit was treated as failed coefficients")

    monkeypatch.setattr(guided_failed_parent, "preview", forbidden)
    checks = []

    def diagnose(snapshot, candidate, *, checks_available=None, **_):
        checks.append((candidate.candidate_id, checks_available))
        return None

    monkeypatch.setattr(pilot_multiscale_failure, "diagnose", diagnose)
    context = guided_strategy.state(route.failed)
    assert context["qualification_pending"] == binding
    assert context["failed_parents"] == {}
    assert (identifier, True) in checks
    prepared = guided_strategy.prepare_proposals(route.failed, context)
    assert prepared["failed_proposals"] == {}


def test_shared_stage_checks_keep_the_resume_action_visible(panel):
    candidate = panel.candidate
    candidate.status = "failed"
    candidate.metrics = None
    candidate.error = "Surface checks did not finish"
    panel.snapshot.visual_reviews.clear()
    panel.guidance["feedback"].clear()
    panel.guidance["allowed"].clear()
    panel.guidance["qualification_pending"] = {candidate.candidate_id: {}}
    panel.guidance["common_stage_failures"] = {candidate.candidate_id: dict(
        action="checks", title="Capture fitting completed",
        label="Resume saved capture checks",
        message="The saved native result passed verification. Resume its surface checks.",
        detail=candidate.error, candidate_id=candidate.candidate_id,
        directory=panel.snapshot.study_directory, reference=None,
    )}
    panel.window.layout().addWidget(panel.window.start_button)
    panel.render()
    assert panel.window.start_button.isVisible() and panel.window.start_button.isEnabled()
    assert panel.window.start_button.text() == "Resume saved capture checks"
    assert panel.window.next_step_button.isHidden()
    assert not panel.invoked and not panel.snapshot.visual_reviews


@pytest.mark.parametrize("kind", ["candidate_failed", "candidate_interrupted"])
def test_bound_postfit_event_banner_keeps_native_success_clear(panel, kind):
    from PySide6.QtWidgets import QLabel

    from diffeoforge.desktop.reference_calibration_dialog import ReferenceCalibrationDialog

    cleared = []
    window = SimpleNamespace(_worker=None, status=QLabel(),
        _live_fit_preview=SimpleNamespace(clear=lambda: cleared.append(True)))
    event = dict(event=kind, candidate_id="synthetic-fit", phase="qualification",
                 completed_native_fit=dict(optimizer_restart=False),
                 error="The marked reconstruction material connectivity changed")
    ReferenceCalibrationDialog._event(window, event)
    assert cleared == [True]
    assert "fit saved; checks incomplete" in window.status.text()
    assert "without fitting again" in window.status.text()


def test_native_failure_banner_does_not_claim_a_saved_completed_fit(panel):
    from PySide6.QtWidgets import QLabel

    from diffeoforge.desktop.reference_calibration_dialog import ReferenceCalibrationDialog

    window = SimpleNamespace(_worker=None, status=QLabel(),
        _live_fit_preview=SimpleNamespace(clear=lambda: None))
    event = dict(event="candidate_failed", candidate_id="synthetic-fit",
                 error="Native consistency guard stopped this fit")
    ReferenceCalibrationDialog._event(window, event)
    assert window.status.text() == "synthetic-fit: Native consistency guard stopped this fit"
    assert "checks incomplete" not in window.status.text()
