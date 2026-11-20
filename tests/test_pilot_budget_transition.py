"""Bounded recovery of an accepted pilot at its test limit; no native execution."""

import copy
from pathlib import Path

import pytest
from test_guided_pilot import approve, origin, run_batch

from diffeoforge import reference_calibration_study as study
from diffeoforge import reference_guided_pilot as guided
from diffeoforge.mesh import sha256_file


def exhausted_snapshot(tmp_path, monkeypatch):
    parent = origin(tmp_path)
    first = guided._batch(
        parent, None, phase="validate", target=guided._pilot_order(parent.plan)[0],
        methods=("varifold",), values=parent.plan.effective_values,
        approved=(), history=(), spent=10)
    first = approve(run_batch(first, monkeypatch))
    # Reproduce the saved legacy transition, which spent the last slot despite
    # another required target remaining. New transitions reserve it earlier.
    second = guided._batch(
        parent, first, phase="validate", target=guided._pilot_order(parent.plan)[1],
        methods=("varifold",), values=first.plan.effective_values,
        approved=[guided._approved_record(first, "guided-varifold")], history=(), spent=11)
    return approve(run_batch(second, monkeypatch))


def test_explicit_minimal_allowance_preserves_reviews_and_requires_run_and_joint(
    tmp_path, monkeypatch,
):
    current = exhausted_snapshot(tmp_path, monkeypatch)
    step = guided.coverage_step(current, "guided-varifold")
    assert len(step["remaining"]) == step["extra_trials"] == 1
    protected = {p: sha256_file(p) for p in current.study_directory.rglob("*") if p.is_file()}
    with pytest.raises(ValueError, match="explicit coverage allowance"):
        guided.next_action(current.study_directory, "choose", "guided-varifold")
    assert {p: sha256_file(p) for p in protected} == protected
    with monkeypatch.context() as guard:
        guard.setattr(study.ReferenceCalibrationStudyRunner, "run_current_stage",
                      lambda *_a, **_k: pytest.fail("Preparation dispatched an optimizer"))
        following = guided.next_action(
            current.study_directory, "extend_coverage", "guided-varifold")
    info = guided.record(following)
    assert info["screen_trials_spent"] == info["screen_trial_limit"] == 13
    assert info["coverage_extension"]["added_trials"] == 1
    assert following.plan.pilot_subject_count == 1 and len(following.candidates) == 1
    assert info["target"] == step["remaining"][0]
    assert following.plan.effective_values == current.plan.effective_values
    assert not following.visual_reviews and all(c.attempts == 0 for c in following.candidates)
    with pytest.raises(ValueError, match="Complete or resolve"):
        guided.next_action(following.study_directory, "choose", "guided-varifold")
    done = approve(run_batch(following, monkeypatch))
    with pytest.raises(ValueError, match="reserved for unchanged"):
        guided.next_action(done.study_directory, "adjust", goal="detail")
    joint = guided.next_action(done.study_directory, "choose", "guided-varifold")
    assert guided.record(joint)["phase"] == "joint" and joint.plan.pilot_subject_count == 3
    assert guided.record(joint)["screen_trials_spent"] == 13
    assert not joint.visual_reviews and all(c.attempts == 0 for c in joint.candidates)
    with pytest.raises(ValueError, match="Complete or resolve"):
        guided.next_action(joint.study_directory, "finish_joint", "guided-varifold")
    joint = approve(run_batch(joint, monkeypatch))
    checked = guided.next_action(joint.study_directory, "finish_joint", "guided-varifold")
    assert checked.current_stage.order == 4
    for p, digest in protected.items():
        if p.name != "events.jsonl":  # Only the append-only transition journal changes.
            assert sha256_file(p) == digest


def test_allowance_is_bound_to_source_minimum_configuration_and_review(tmp_path, monkeypatch):
    current = exhausted_snapshot(tmp_path, monkeypatch)
    following = guided.next_action(current.study_directory, "extend_coverage", "guided-varifold")
    manifest = study._verify_manifest(following.study_directory)
    original = study._verify_manifest(Path(guided.record(current)["origin"]))
    info = guided.record(following)
    methods = following.attachment_comparison["methods"]
    values = manifest["plan"]["baseline_effective_values"]
    assert guided.verify_coverage_extension(info, original, methods, values)
    changed = copy.deepcopy(info)
    changed["coverage_extension"]["added_trials"] += 1
    changed["screen_trial_limit"] += 1
    assert not guided.verify_coverage_extension(changed, original, methods, values)
    assert not guided.verify_coverage_extension(
        info, original, {"guided-current": "current"}, values)
    assert not guided.verify_coverage_extension(
        info, original, methods, dict(values, noise_std=999))
    changed = copy.deepcopy(info)
    changed.pop("coverage_extension")
    assert not guided.verify_coverage_extension(changed, original, methods, values)
    names = [s.filename for s in current.plan.selected_pilot_subjects]
    study.record_reference_calibration_candidate_review(
        current.study_directory, candidate_id="guided-varifold", approved=False,
        reviewed_subjects=names, subject_decisions={n: "fail" for n in names})
    with pytest.raises(ValueError, match="approve"):
        study.load_reference_calibration_study(following.study_directory)


def test_actual_exhausted_button_prepares_one_test_and_errors_survive_async_render(
    tmp_path, monkeypatch,
):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from pilot_view_helpers import wait_pilot_view
    from PySide6.QtWidgets import QApplication, QPushButton

    from diffeoforge.desktop.reference_calibration_dialog import ReferenceCalibrationDialog

    current = exhausted_snapshot(tmp_path, monkeypatch)
    app = QApplication.instance() or QApplication([])
    dialog = ReferenceCalibrationDialog(current.study_directory)
    dialog.show()
    try:
        wait_pilot_view(dialog)
        button = next(b for b in dialog.content.findChildren(QPushButton)
                      if b.text().startswith("Use Varifold"))
        assert button.isVisible() and button.isEnabled() and button.objectName() == "primary"
        assert not any(b.isVisible() and b.text().startswith("Add 1 coverage")
                       for b in dialog.content.findChildren(QPushButton))
        monkeypatch.setattr(study.ReferenceCalibrationStudyRunner, "run_current_stage",
                            lambda *_a, **_k: pytest.fail("Preparation dispatched an optimizer"))
        button.click()
        import time
        deadline = time.monotonic() + 30
        while (dialog._worker is not None or dialog._view_loading) and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(.002)
        wait_pilot_view(dialog)
        assert dialog.study_directory != current.study_directory
        assert all(c.attempts == 0 for c in dialog._snapshot.candidates)
        assert dialog.start_button.isVisible() and dialog.start_button.isEnabled()
        dialog._failed("Synthetic transition failure")
        wait_pilot_view(dialog)
        dialog.resize(800, 650)
        dialog._render(prepared=dialog._prepared_view)
        app.processEvents()
        assert dialog.operation_error.isVisible()
        assert "Synthetic transition failure" in dialog.operation_error.text()
        from PySide6.QtWidgets import QMessageBox
        monkeypatch.setattr(QMessageBox, "critical", lambda *_a: None)
        def fail_dispatch(**_kwargs):
            raise ValueError("Synthetic start failure")
        monkeypatch.setattr(dialog, "_dispatch_pilot", fail_dispatch)
        dialog._start_pilot(adaptive=False)
        wait_pilot_view(dialog)
        assert dialog.operation_error.isVisible()
        assert "Synthetic start failure" in dialog.operation_error.text()
    finally:
        dialog.close()
        app.processEvents()
