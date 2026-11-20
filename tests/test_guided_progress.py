"""Cap-aware saved-field preparation; controllers are synthetic, never native fits."""

import copy
from dataclasses import replace
from types import SimpleNamespace

import pytest
import test_guided_pilot as fixtures
from test_guided_feedback import decision
from test_interactive_pilot import initial
from test_pilot_region_feedback import reject

from diffeoforge import guided_feedback, guided_strategy
from diffeoforge import reference_calibration_study as study
from diffeoforge import reference_guided_pilot as guided
from diffeoforge.config import load_config
from diffeoforge.guided_progress import iteration_limited, next_hypothesis
from diffeoforge.mesh import sha256_file


def limited(snapshot, monkeypatch):
    fixtures._stub_learned_seed(monkeypatch)
    original = fixtures._metrics
    cap = snapshot.attachment_comparison["iterations"]
    with monkeypatch.context() as patch:
        patch.setattr(fixtures, "_metrics", lambda *a, **k: replace(
            original(*a, **k), converged=False, final_iteration=cap, maximum_iterations=cap,
            optimizer_stop_signal="maximum_iterations"))
        return fixtures.run_batch(snapshot, patch)


def test_cap_stop_requires_explicit_native_evidence():
    good = dict(completed=True, converged=False, optimizer_stop_signal="maximum_iterations",
                final_iteration=120, maximum_iterations=120)
    assert iteration_limited(SimpleNamespace(status="completed", metrics=good))
    for change in (dict(converged=True), dict(optimizer_stop_signal="unknown"),
                   dict(final_iteration=119), dict(maximum_iterations=True)):
        assert not iteration_limited(SimpleNamespace(status="completed", metrics=good | change))
    assert not iteration_limited(SimpleNamespace(status="failed", metrics=good))


def test_cap_first_prepares_same_physics_with_nonzero_saved_field(tmp_path, monkeypatch):
    base = reject(limited(initial(tmp_path), monkeypatch), "guided-varifold")
    before = {p: sha256_file(p) for p in base.study_directory.rglob("*") if p.is_file()}
    plan = guided_strategy.trial_proposal(base, "guided-varifold", "detail")
    assert plan["goal"] == "optimize" and plan["optimization_iterations"] == 240
    assert plan["values"] == base.plan.effective_values
    with monkeypatch.context() as guard:
        guard.setattr(study.ReferenceCalibrationStudyRunner, "run_current_stage",
                      lambda *_a, **_k: pytest.fail("Preparation dispatched a fit"))
        child = guided.next_action(base.study_directory, "adaptive_recover", "guided-varifold",
                                   goal="detail")
    config = load_config(child.candidates[0].config_path)
    assert child.attachment_comparison["iterations"] == 240
    assert config["optimization"]["max_iterations"] == 240
    original = load_config(next(c for c in base.candidates
                                if c.candidate_id == "guided-varifold").config_path)
    assert config["optimization"] == dict(original["optimization"], max_iterations=240)
    assert config["model"]["attachment"] == original["model"]["attachment"]
    assert child.plan.effective_values == base.plan.effective_values
    assert child.attachment_comparison["refinement"]["initialization"] == "learned"
    assert config["model"]["deformation"]["initial_momenta"]
    assert child.candidates[0].attempts == 0 and not child.visual_reviews
    assert all(sha256_file(p) == digest for p, digest in before.items()
               if p.name != study.STUDY_EVENTS)
    reopened = study.load_reference_calibration_study(child.study_directory)
    assert reopened.attachment_comparison["guided"]["goal"] == "optimize"
    manifest = study._verify_manifest(child.study_directory)
    for change in ("method", "initialization", "iterations"):
        tampered = copy.deepcopy(manifest["attachment_comparison"])
        if change == "method":
            tampered["methods"] = {"guided-varifold": "current"}
        elif change == "initialization":
            tampered["refinement"]["initialization"] = "fresh"
        else:
            tampered["iterations"] += 1
        assert not guided_strategy.verify_strategy(tampered["guided"], tampered, manifest)


def test_worse_extension_cannot_repeat_from_same_retained_field(tmp_path, monkeypatch):
    base = reject(limited(initial(tmp_path), monkeypatch), "guided-varifold")
    child = guided.next_action(base.study_directory, "adaptive_recover", "guided-varifold",
                               goal="detail")
    child = limited(child, monkeypatch)
    child = guided_feedback.save_feedback(child.study_directory, "guided-varifold",
                                          decision(base, child, "worse"))
    plan = guided_strategy.trial_proposal(child, "guided-varifold", "detail")
    assert plan["goal"] != "optimize"
    blocked = guided_strategy.trial_proposal(child, "guided-varifold", "goal:optimize")
    assert not blocked["available"] and "already had" in blocked["blocked_reason"]


def test_newly_better_cap_limited_field_can_get_more_headroom(tmp_path, monkeypatch):
    base = reject(limited(initial(tmp_path), monkeypatch), "guided-varifold")
    child = guided.next_action(base.study_directory, "adaptive_recover", "guided-varifold",
                               goal="detail")
    child = limited(child, monkeypatch)
    child = guided_feedback.save_feedback(child.study_directory, "guided-varifold",
                                          decision(base, child, "better"))
    plan = guided_strategy.trial_proposal(child, "guided-varifold", "detail")
    assert plan["goal"] == "optimize" and plan["optimization_iterations"] == 480
    assert plan["anchor"] == guided_feedback.reference(child, "guided-varifold")


def test_capped_new_density_field_is_seed_without_replacing_good_comparison(tmp_path, monkeypatch):
    base = reject(fixtures.run_batch(initial(tmp_path), monkeypatch), "guided-varifold")
    child = guided.next_action(base.study_directory, "adaptive_recover", "guided-varifold",
                               goal="goal:density")
    child = limited(child, monkeypatch)
    child = guided_feedback.save_feedback(child.study_directory, "guided-varifold",
                                          decision(base, child, "same"))
    proposed = guided_strategy.trial_proposal(child, "guided-varifold", "detail")
    assert proposed["goal"] == "optimize"
    assert proposed["anchor"] == guided_feedback.reference(base, "guided-varifold")
    assert proposed["initialization_reference"] == guided_feedback.reference(
        child, "guided-varifold")
    longer = guided.next_action(child.study_directory, "adaptive_recover", "guided-varifold",
                                goal="detail")
    info = guided.record(longer)
    assert info["strategy"]["anchor"] == proposed["anchor"]
    assert info["strategy"]["baseline"] == proposed["initialization_reference"]
    assert info["strategy"]["search_family"] == "density"
    assert info["feedback"]["directory"] == str(base.study_directory)
    assert longer.plan.effective_values == child.plan.effective_values
    assert longer.attachment_comparison["controls"]["sha256"] == child.attachment_comparison[
        "controls"]["sha256"]
    assert longer.attachment_comparison["refinement"]["initialization"] == "learned"
    assert longer.candidates[0].attempts == 0 and not longer.visual_reviews
    assert study.load_reference_calibration_study(longer.study_directory)


def test_repeated_detail_switches_explanation_and_ignores_other_targets():
    case = dict(method="current", target="form.vtk", goal="detail", outcome="better")
    assert next_hypothesis([case], "current", "form.vtk", "detail")[0] == "detail"
    assert next_hypothesis([case, case], "current", "form.vtk", "detail")[0] == "detail"
    rejected = case | dict(outcome="worse")
    assert next_hypothesis([rejected], "current", "form.vtk", "detail")[0] == "weight"
    assert next_hypothesis([rejected], "varifold", "form.vtk", "detail")[0] == "detail"
    approved = case | dict(approval={"explicit": True})
    assert next_hypothesis([approved, approved], "current", "form.vtk", "detail")[0] == "detail"
    cases = [rejected, rejected, rejected | dict(goal="weight")]
    assert next_hypothesis(cases, "current", "form.vtk", "detail")[0] == "local_motion"
    assert next_hypothesis(cases + [rejected | dict(goal="local_motion")],
                           "current", "form.vtk", "detail")[0] == "density"
    assert next_hypothesis(
        cases + [rejected | dict(goal="local_motion"), rejected | dict(goal="density")],
        "current", "form.vtk", "detail",
    )[0] == "weight"


def test_actual_cap_button_prepares_only_one_successor(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from pilot_view_helpers import wait_pilot_view
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication, QLabel, QPushButton

    from diffeoforge.desktop.reference_calibration_dialog import ReferenceCalibrationDialog

    app = QApplication.instance() or QApplication([])
    base = reject(limited(initial(tmp_path), monkeypatch), "guided-varifold")
    base = guided.next_action(base.study_directory, "adaptive_prefer", "guided-varifold")
    dialog = ReferenceCalibrationDialog(base.study_directory)
    dialog.show()
    try:
        wait_pilot_view(dialog)
        button = next(b for b in dialog.content.findChildren(QPushButton)
                      if b.text().startswith("Optimize longer with the same settings"))
        assert button.isEnabled() and button.isVisible()
        for width, size in ((1080, 10), (850, 14), (1280, 10)):
            dialog.setFont(QFont("Segoe UI", size))
            dialog.resize(width, 820)
            for _ in range(6):
                app.processEvents()
            for label in dialog.content.findChildren(QLabel):
                if label.isVisible() and label.wordWrap() and label.hasHeightForWidth():
                    assert label.height() >= label.heightForWidth(label.width()), label.text()
        queued = []
        monkeypatch.setattr(dialog._thread_pool, "start", queued.append)
        for _ in range(8):
            button.click()
        assert len(queued) == 1
        queued.pop().run()
        wait_pilot_view(dialog)
        assert dialog._snapshot.attachment_comparison["iterations"] == 240
        assert all(c.attempts == 0 for c in dialog._snapshot.candidates)
        assert not dialog._snapshot.visual_reviews
    finally:
        dialog._worker = None
        dialog.close()
        app.processEvents()
