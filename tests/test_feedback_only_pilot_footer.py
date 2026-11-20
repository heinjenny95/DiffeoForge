"""Feedback-inspected individual fields can reach their qualified visible repair."""

import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from pilot_view_helpers import wait_pilot_view
from test_guided_feedback import decision
from test_pilot_journey_invariants import METHOD, _finer_successor, _new_mark, _synthetic_frame

from diffeoforge import guided_feedback
from diffeoforge import reference_calibration_study as study
from diffeoforge import reference_guided_pilot as guided
from diffeoforge.config import load_config
from diffeoforge.desktop.pilot_review_target import choose


@pytest.mark.parametrize("red_mark", [False, True])
def test_feedback_only_better_footer_prepares_exact_repair_without_running(
    tmp_path, monkeypatch, red_mark,
):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from diffeoforge.desktop.reference_calibration_dialog import ReferenceCalibrationDialog

    base, current, reports = _finer_successor(tmp_path, monkeypatch, formal_review=False)
    target = guided.record(current)["target"]
    marks = [_new_mark(current)] if red_mark else []
    current = guided_feedback.save_feedback(current.study_directory, METHOD,
        decision(base, current, "better") | dict(symptom="unsure",
                                                problem_regions={target: marks} if marks else {}))
    assert METHOD not in current.visual_reviews
    exact = guided_feedback.reference(current, METHOD)
    previous_reviews = dict(current.visual_reviews)
    previous_config = load_config(current.candidates[0].config_path)
    if red_mark:
        _synthetic_frame(current, reports, monkeypatch)
    monkeypatch.setattr(study.ReferenceCalibrationStudyRunner, "run_current_stage",
                        lambda *_a, **_k: pytest.fail("Preparation dispatched fitting"))
    application = QApplication.instance() or QApplication([])
    dialog = ReferenceCalibrationDialog(current.study_directory)
    dialog.show()
    try:
        wait_pilot_view(dialog)
        review = dialog._guided_review_target
        assert review["pending"] is False
        assert "Reopen inspected individual" in review["label"]
        assert "Suitable fit is a separate decision" in review["explanation"]
        footer = dialog.next_step_button
        assert footer.isVisible() and footer.isEnabled()
        assert footer.objectName() == "primary"
        assert not dialog.review_next_button.objectName() == "primary"
        assert dialog._guided_footer_action[1] in {"adaptive_recover", "adaptive_recover_start"}
        goal = dialog._guided_footer_goal
        assert goal["reference"] == exact
        assert goal["goal"] == ("regional" if red_mark else "optimize")
        assert goal["regions"] == marks
        assert "Compare" not in footer.text()
        assert ("Improve marked areas" in footer.text() if red_mark
                else "Continue saved fit" in footer.text())
        footer.click()
        deadline = time.monotonic() + 20
        while dialog._worker is not None and time.monotonic() < deadline:
            application.processEvents()
            time.sleep(.002)
        assert dialog._worker is None
        wait_pilot_view(dialog)
        prepared = dialog._snapshot
        assert prepared.study_directory != current.study_directory
        assert prepared.attachment_comparison["refinement"]["reference"] == exact
        assert all(c.attempts == 0 and c.status == "pending" for c in prepared.candidates)
        assert not prepared.visual_reviews
        if red_mark:
            assert prepared.attachment_comparison["regional_objective"]
            assert guided.record(prepared)["feedback"]["regions"] == marks
        else:
            config = load_config(prepared.candidates[0].config_path)
            assert config["optimization"] == dict(previous_config["optimization"],
                max_iterations=goal["optimization_iterations"])
        assert study.load_reference_calibration_study(current.study_directory).visual_reviews == (
            previous_reviews)
    finally:
        dialog.close()
        application.processEvents()


@pytest.mark.parametrize("phase,goal,count", [
    ("joint", "", 1), ("refine", "shared_check", 1), ("refine", "", 4),
])
def test_feedback_does_not_clear_joint_common_or_cohort_review_boundary(phase, goal, count):
    candidate = SimpleNamespace(candidate_id="guided-varifold", label="Varifold",
                                status="completed")
    snapshot = SimpleNamespace(study_directory=Path("synthetic-pilot"),
                               candidates=[candidate], visual_reviews={},
                               plan=SimpleNamespace(pilot_subject_count=count),
                               attachment_comparison={})
    guidance = dict(fit_direction=dict(mode="trial", identifier=candidate.candidate_id),
                    allowed={candidate.candidate_id: True}, feedback={candidate.candidate_id: dict(
                        current_inspected=True)})
    info = dict(phase=phase, goal=goal, target="public.vtk", screen_trials_spent=3,
                strategy={})
    assert choose(snapshot, guidance, info)["pending"] is True


@pytest.mark.parametrize("mode,inspected,allowed", [
    ("compare", True, True), ("trial", False, True), ("trial", True, False),
])
def test_passive_comparison_or_unqualified_field_keeps_review_pending(mode, inspected, allowed):
    candidate = SimpleNamespace(candidate_id="guided-varifold", label="Varifold",
                                status="completed")
    snapshot = SimpleNamespace(study_directory=Path("synthetic-pilot"),
                               candidates=[candidate], visual_reviews={},
                               plan=SimpleNamespace(pilot_subject_count=1),
                               attachment_comparison={})
    guidance = dict(fit_direction=dict(mode=mode, identifier=candidate.candidate_id),
                    allowed={candidate.candidate_id: allowed},
                    feedback={candidate.candidate_id: dict(current_inspected=inspected)})
    info = dict(phase="refine", goal="", target="public.vtk", screen_trials_spent=3,
                strategy={})
    assert choose(snapshot, guidance, info)["pending"] is True
