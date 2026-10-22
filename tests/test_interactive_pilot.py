"""Interactive pilot journeys; all controller receipts are synthetic, never native fits."""

import shutil
from types import SimpleNamespace

import pytest
from test_guided_pilot import approve, origin, run_batch
from test_pilot_budget_transition import exhausted_snapshot
from test_pilot_region_feedback import reject

from diffeoforge import guided_strategy as strategy
from diffeoforge import reference_calibration_study as study
from diffeoforge import reference_guided_pilot as guided
from diffeoforge.mesh import sha256_file


def initial(tmp_path):
    parent = origin(tmp_path)
    return guided._batch(parent, None, phase="screen", target=guided._pilot_order(parent.plan)[0],
                         methods=("current", "varifold"), values=parent.plan.effective_values,
                         approved=(), history=(), spent=0, strategy={})


def geometry_receipt(snapshot, identifier, monkeypatch):
    from diffeoforge import result_report

    candidate = next(c for c in snapshot.candidates if c.candidate_id == identifier)
    target = strategy._target(snapshot, identifier)
    manifest = study._verify_manifest(snapshot.study_directory)
    source = next(r for r in manifest["inputs"]["subjects"] if r["filename"] == target)
    output = candidate.run_directory / "output"
    output.mkdir(exist_ok=True)
    name = "Fixture__Reconstruction__subject_" + target + ".vtk"
    shutil.copyfile(snapshot.study_directory / source["copy"], output / name)
    monkeypatch.setattr(result_report, "collect_run_report", lambda _root: SimpleNamespace(
        inventory=[dict(path=name, sha256=sha256_file(output / name))]))


def test_rejected_method_can_be_preferred_without_granting_approval(tmp_path, monkeypatch):
    snapshot = run_batch(initial(tmp_path), monkeypatch)
    snapshot = reject(reject(snapshot, "guided-current"), "guided-varifold")
    before = {p: sha256_file(p) for p in snapshot.study_directory.rglob("*") if p.is_file()}
    with monkeypatch.context() as guard:
        guard.setattr(study.ReferenceCalibrationStudyRunner, "run_current_stage",
                      lambda *_a, **_k: pytest.fail("Preference started a fit"))
        preferred = guided.next_action(
            snapshot.study_directory, "adaptive_prefer", "guided-varifold")
    assert preferred.study_directory == snapshot.study_directory
    assert strategy.state(preferred)["preferred"] == "varifold"
    assert preferred.visual_reviews == {"guided-current": False, "guided-varifold": False}
    assert not preferred.selected_candidate_ids
    assert all(c.attempts == 1 for c in preferred.candidates)
    with pytest.raises(ValueError, match="approve"):
        guided.next_action(preferred.study_directory, "adaptive_confirm", "guided-varifold")
    assert all(sha256_file(p) == digest for p, digest in before.items()
               if p.name != study.STUDY_EVENTS)
    follow = guided.next_action(preferred.study_directory, "adaptive_recover", "guided-varifold",
                               goal="detail")
    assert guided.record(follow)["phase"] == "refine"
    assert guided.record(follow)["screen_trial_limit"] is None
    assert len(follow.candidates) == follow.plan.pilot_subject_count == 1
    assert not follow.visual_reviews and not guided.record(follow)["approved"]
    assert all(c.attempts == 0 for c in follow.candidates)


def test_saved_exhausted_rejection_keeps_regions_and_can_refine_again(tmp_path, monkeypatch):
    snapshot = exhausted_snapshot(tmp_path, monkeypatch)
    last = guided.next_action(snapshot.study_directory, "extend_coverage", "guided-varifold")
    last = reject(run_batch(last, monkeypatch), marked=True)
    geometry_receipt(last, "guided-varifold", monkeypatch)
    before = {p: sha256_file(p) for p in last.study_directory.rglob("*") if p.is_file()}
    proposed = strategy.trial_proposal(last, "guided-varifold", "detail")
    assert proposed["available"] and proposed["remaining_checks"] == 2
    follow = guided.next_action(last.study_directory, "adaptive_recover", "guided-varifold",
                               goal="detail")
    info = guided.record(follow)
    assert info["version"] == guided.ADAPTIVE_VERSION
    assert info["screen_trials_spent"] == 14 and info["screen_trial_limit"] is None
    assert not info["approved"] and not info.get("coverage_extension")
    assert info["feedback"]["regions"] == last.problem_regions["guided-varifold"][info["target"]]
    assert all(c.attempts == 0 for c in follow.candidates)
    assert all(sha256_file(p) == digest for p, digest in before.items()
               if p.name != study.STUDY_EVENTS)
    follow = reject(run_batch(follow, monkeypatch))
    next_proposal = strategy.trial_proposal(follow, "guided-varifold", "detail")
    assert next_proposal["goal"] == (
        "weight" if info["goal"] == "local_motion" else "local_motion")
    second = guided.next_action(follow.study_directory, "adaptive_recover", "guided-varifold",
                               goal="detail")
    assert guided.record(second)["screen_trials_spent"] == 15
    assert second.plan.pilot_subject_count == 1 and not second.visual_reviews


def test_refine_then_coverage_and_joint_rejection_return_to_failing_form(tmp_path, monkeypatch):
    snapshot = reject(run_batch(initial(tmp_path), monkeypatch), "guided-varifold")
    follow = guided.next_action(snapshot.study_directory, "adaptive_recover", "guided-varifold",
                               goal="detail")
    checked = approve(run_batch(follow, monkeypatch), "guided-varifold")
    while guided.record(checked)["phase"] != "joint":
        checked = guided.next_action(checked.study_directory, "adaptive_confirm", "guided-varifold")
        assert not checked.visual_reviews and all(c.attempts == 0 for c in checked.candidates)
        checked = approve(run_batch(checked, monkeypatch), "guided-varifold")
    names = [s.filename for s in checked.plan.selected_pilot_subjects]
    failed = names[-1]
    checked = study.record_reference_calibration_candidate_review(
        checked.study_directory, candidate_id="guided-varifold", approved=False,
        reviewed_subjects=names,
        subject_decisions={name: "fail" if name == failed else "pass" for name in names})
    with pytest.raises(ValueError, match="approve"):
        guided.next_action(checked.study_directory, "finish_joint", "guided-varifold")
    recovery = guided.next_action(checked.study_directory, "adaptive_recover", "guided-varifold",
                                 goal="detail")
    assert guided.record(recovery)["target"] == failed
    assert guided.record(recovery)["phase"] == "refine"
    assert not guided.record(recovery)["approved"] and recovery.plan.pilot_subject_count == 1


def test_previous_settings_can_fund_different_hypothesis_but_no_duplicate_fit(
    tmp_path, monkeypatch,
):
    snapshot = reject(run_batch(initial(tmp_path), monkeypatch), "guided-varifold")
    follow = guided.next_action(snapshot.study_directory, "adaptive_recover", "guided-varifold",
                               goal="goal:detail")
    follow = reject(run_batch(follow, monkeypatch))
    duplicate = strategy.trial_proposal(follow, "guided-varifold", "base:detail")
    assert not duplicate["available"]
    with pytest.raises(ValueError, match="already tested"):
        guided.next_action(follow.study_directory, "adaptive_recover", "guided-varifold",
                           goal="base:detail")
    alternative = guided.next_action(follow.study_directory, "adaptive_recover", "guided-varifold",
                                    goal="base:local_motion")
    assert alternative.plan.effective_values["attachment_kernel_width"] == (
        snapshot.plan.effective_values["attachment_kernel_width"])
    assert alternative.plan.effective_values["deformation_kernel_width"] == (
        snapshot.plan.effective_values["deformation_kernel_width"] / 2)
    assert not alternative.visual_reviews and all(c.attempts == 0 for c in alternative.candidates)


def test_actual_rejected_method_buttons_and_repeat_click_guard(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from pilot_view_helpers import wait_pilot_view
    from PySide6.QtWidgets import QApplication, QLabel, QPushButton

    from diffeoforge.desktop.reference_calibration_dialog import ReferenceCalibrationDialog

    app = QApplication.instance() or QApplication([])
    snapshot = reject(reject(run_batch(initial(tmp_path), monkeypatch), "guided-current"),
                      "guided-varifold")
    dialog = ReferenceCalibrationDialog(snapshot.study_directory)
    dialog.show()
    try:
        wait_pilot_view(dialog)
        scope = dialog.content.findChild(QLabel, "pilotScope")
        assert scope.text().splitlines()[0] == guided.record(snapshot)["target"]
        button = next(b for b in dialog.content.findChildren(QPushButton)
                      if b.text().startswith("Use Varifold as starting method"))
        queued = []
        monkeypatch.setattr(dialog._thread_pool, "start", queued.append)
        for _ in range(10):
            button.click()
        assert len(queued) == 1
        queued.pop().run()
        wait_pilot_view(dialog)
        assert dialog._snapshot.visual_reviews["guided-varifold"] is False
        prepare = next(b for b in dialog.content.findChildren(QPushButton)
                       if "prepare 1 trial on 1 specimen" in b.text())
        assert prepare.isEnabled() and not prepare.isHidden()
        assert dialog.start_button.isHidden()
    finally:
        dialog._worker = None
        dialog.close()
        app.processEvents()
