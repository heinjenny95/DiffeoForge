"""Recovery must preserve accepted fields and never dispatch another optimizer."""

from copy import deepcopy

import pytest
from test_guided_pilot import approve, run_batch
from test_guided_suitable_dialog import panel as panel
from test_interactive_pilot import initial

from diffeoforge import guided_accepted_fit as recovery
from diffeoforge import guided_feedback as feedback
from diffeoforge import guided_strategy as strategy
from diffeoforge import reference_calibration_study as study
from diffeoforge import reference_guided_pilot as guided
from diffeoforge.mesh import sha256_file


def rejected_joint(tmp_path, monkeypatch):
    snapshot = approve(run_batch(initial(tmp_path), monkeypatch), "guided-varifold")
    while guided.record(snapshot)["phase"] != "joint":
        snapshot = guided.next_action(
            snapshot.study_directory, "adaptive_confirm", "guided-varifold")
        snapshot = run_batch(snapshot, monkeypatch)
        if guided.record(snapshot)["phase"] != "joint":
            snapshot = approve(snapshot, "guided-varifold")
    names = [s.filename for s in snapshot.plan.selected_pilot_subjects]
    return study.record_reference_calibration_candidate_review(
        snapshot.study_directory, candidate_id="guided-varifold", approved=False,
        reviewed_subjects=names, subject_decisions={n: "fail" for n in names})


def test_return_from_joint_preserves_results_and_binds_actual_single_form_field(
        tmp_path, monkeypatch):
    joint = rejected_joint(tmp_path, monkeypatch)
    before = {p: sha256_file(p) for p in joint.study_directory.parent.rglob("*") if p.is_file()}
    context = strategy.state(joint)
    offered = context["accepted_fits"]["guided-varifold"]
    assert offered and not offered["selected"]
    accepted = feedback.verify_reference(offered["reference"])
    assert accepted.plan.pilot_subject_count == 1
    assert accepted.visual_reviews["guided-varifold"] is True
    monkeypatch.setattr(study.ReferenceCalibrationStudyRunner, "run_current_stage",
                        lambda *_a, **_k: pytest.fail("Recovery dispatched an optimizer"))
    restored = guided.next_action(joint.study_directory, "adaptive_restore_accepted",
                                 "guided-varifold", goal=offered["reference"])
    assert restored.study_directory == joint.study_directory
    assert restored.visual_reviews == joint.visual_reviews == {"guided-varifold": False}
    assert restored.selected_candidate_ids == joint.selected_candidate_ids
    assert feedback.selection(restored, "guided-varifold") == offered["reference"]
    proposal = strategy.trial_proposal(restored, "guided-varifold", "goal:weight")
    assert proposal["initialization_reference"] == offered["reference"]
    assert proposal["initialization"] == "learned"
    assert strategy.state(restored)["accepted_fits"]["guided-varifold"]["selected"]
    assert all(sha256_file(p) == h for p, h in before.items()
               if p != joint.study_directory / study.STUDY_EVENTS)
    event = study._load_events(restored.study_directory)[-1]
    bad = deepcopy(event)
    bad["reference"]["target"] = "another-form.vtk"
    with pytest.raises((ValueError, KeyError)):
        recovery.verify_selection(restored, "guided-varifold", bad)
    bad = deepcopy(event)
    bad["anatomical_approval_created"] = True
    with pytest.raises(ValueError):
        recovery.verify_selection(restored, "guided-varifold", bad)


def test_joint_field_is_blocked_before_local_preparation_and_accepted_return_fixes_seed(
        tmp_path, monkeypatch):
    from test_pilot_region_feedback import patch

    joint = rejected_joint(tmp_path, monkeypatch)
    target = next(s for s in joint.plan.selected_pilot_subjects
                  if s.filename == strategy._target(joint, "guided-varifold"))
    context = strategy.state(joint)
    from diffeoforge.guided_search import inputs, propose
    monkeypatch.setattr("diffeoforge.regional_search.capture",
                        lambda *_a, **_k: dict(original_to_fit_p95=.2))

    data = inputs(joint, "guided-varifold", context,
                  regions_override=[patch(target.sha256)], allow_continuation=False)
    blocked = propose(joint, "guided-varifold", "regional:detail", data)
    assert not blocked["available"]
    assert "accepted single-form fit" in blocked["blocked_reason"]
    offered = context["accepted_fits"]["guided-varifold"]
    selected = guided.next_action(joint.study_directory, "adaptive_restore_accepted",
                                 "guided-varifold", goal=offered["reference"])
    # No fresh joint run is a valid shortcut merely because the old single fit
    # was selected. The preparation guard is independent of disabled GUI controls.
    assert recovery.rejected_joint(selected, offered["reference"])


def test_primary_recovery_button_is_visible_and_starts_only_explicit_selection(panel):
    from PySide6.QtWidgets import QLabel, QPushButton

    ref = dict(directory="accepted-study", candidate_id="guided-varifold")
    panel.guidance["accepted_fits"] = {panel.candidate.candidate_id: dict(
        reference=ref, label="Test 3 · Varifold", target="specimen.vtk", selected=False)}
    panel.render()
    button = next(b for b in panel.window.findChildren(QPushButton)
                  if b.property("acceptedFitRecovery"))
    assert button.isVisible() and button.isEnabled()
    assert panel.window.findChild(QLabel, "acceptedFitRecovery").isVisible()
    assert not panel.invoked
    button.click()
    assert panel.invoked == [((), dict(adaptive=False, guided_action=(
        "adaptive_restore_accepted", panel.candidate.candidate_id, ref)))]


def test_joint_conditions_explain_moving_basis_and_fresh_initialization(panel, monkeypatch):
    from PySide6.QtWidgets import QLabel

    from diffeoforge.desktop import guided_pilot as ui

    monkeypatch.setattr(ui, "record", lambda _: dict(phase="joint", target=None,
        screen_trials_spent=6, approved=[], pilot_order=["specimen.vtk"]))
    panel.snapshot.attachment_comparison["confirmation_freeze_settings"] = dict(
        freeze_template=False, freeze_control_points=False)
    panel.render()
    note = panel.window.findChild(QLabel, "jointFitConditions")
    assert note.isVisible()
    assert "template and control points" in note.text()
    assert "new deformation fields" in note.text()
    assert not panel.invoked


def test_prepared_joint_explains_accepted_start_before_run(panel, monkeypatch):
    import os

    from PySide6.QtGui import QFont, QFontDatabase
    from PySide6.QtWidgets import QLabel

    from diffeoforge.desktop import guided_pilot as ui

    monkeypatch.setattr(ui, "record", lambda _: dict(phase="joint", target=None,
        screen_trials_spent=6, approved=[], pilot_order=["specimen.vtk"]))
    panel.snapshot.attachment_comparison.update(joint_initialization=dict(version="accepted-singletons-v1"),
        confirmation_freeze_settings=dict(freeze_template=False, freeze_control_points=False))
    panel.candidate.status, panel.candidate.metrics = "pending", None
    panel.guidance["feedback"].clear()
    panel.snapshot.visual_reviews.clear()
    panel.snapshot.plan.pilot_subject_count = 6
    panel.window.layout().addWidget(panel.window.start_button)
    panel.render()
    note = panel.window.findChild(QLabel, "jointFitConditions")
    assert note.isVisible() and "all accepted individual deformation fields" in note.text()
    assert "estimates the shared template and control points" in note.text()
    assert panel.window.start_button.isEnabled()
    assert panel.window.start_button.text() == "Run joint check · 6 specimens"
    assert not panel.invoked
    capture = os.environ.get("DF_JOINT_INIT_CAPTURE")
    if capture:
        from diffeoforge.desktop.appearance import Appearance, themed_style
        from diffeoforge.desktop.widgets import _STYLE

        font_id = QFontDatabase.addApplicationFont("C:/Windows/Fonts/segoeui.ttf")
        assert font_id >= 0
        panel.app.setFont(QFont(QFontDatabase.applicationFontFamilies(font_id)[0], 10))
        panel.window.setStyleSheet(themed_style(_STYLE, Appearance()))
        panel.window.setWindowTitle("Source UI preview · joint initialization · no fit running")
        panel.window.resize(1050, 650)
        for _ in range(15):
            panel.app.processEvents()
        assert panel.window.grab().save(capture)
