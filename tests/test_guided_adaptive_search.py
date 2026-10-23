"""Adaptive response and responsive selectors; no native optimization is executed."""

from types import SimpleNamespace

import pytest

from diffeoforge import guided_search, guided_strategy
from diffeoforge import reference_guided_pilot as guided
from diffeoforge.guided_progress import next_hypothesis


def model(monkeypatch, *, cases=(), outcome=None, goal="detail", capped=False):
    values = dict(attachment_kernel_width=.1, deformation_kernel_width=.4,
                  noise_std=.02, initial_control_point_spacing=.5)
    reference = dict(directory="retained", candidate_id="fit", target="form.vtk",
                     method="current", values=values)
    current_reference = dict(reference, directory="latest")
    metrics = dict(completed=True, converged=not capped, final_iteration=120,
                   maximum_iterations=120, optimizer_stop_signal="maximum_iterations"
                   if capped else "converged")
    current = SimpleNamespace(candidate_id="fit", status="completed", metrics=metrics)
    parent = SimpleNamespace(candidates=[current], plan=SimpleNamespace(pilot_subject_count=1),
                             attachment_comparison={"controls": {"count": 100}})
    snapshot = SimpleNamespace(candidates=[current], visual_reviews={"fit": False},
        plan=SimpleNamespace(selected_pilot_subjects=[SimpleNamespace(filename="form.vtk")],
                             effective_values=values),
        subject_decisions={}, attachment_comparison={"methods": {"fit": "current"}})
    info = dict(target="form.vtk", goal=goal, strategy={}, pilot_order=["form.vtk", "other.vtk"],
                screen_trial_limit=None, screen_trials_spent=2)
    monkeypatch.setattr(guided, "record", lambda _: info)
    data = dict(anchor=reference, current=current, current_reference=current_reference,
                references={"retained": parent}, regions=[], severe=False,
                context=dict(cases=list(cases), feedback={"fit": {"feedback":
                    dict(outcome=outcome) if outcome else None}}))
    return snapshot, data, reference


def test_same_increases_contrast_on_same_retained_field(monkeypatch):
    snapshot, data, reference = model(monkeypatch, outcome="same")
    first = guided_search.propose(snapshot, "fit", "goal:detail", data)
    data["context"]["cases"] = [dict(method="current", target="form.vtk", goal="detail",
        outcome="same", reference=reference, values=first["values"])]
    follow = guided_search.propose(snapshot, "fit", "detail", data)
    assert follow["goal"] == "detail" and follow["available"]
    assert follow["values"]["attachment_kernel_width"] == pytest.approx(.063)
    assert follow["values"]["deformation_kernel_width"] == .4
    assert follow["anchor"] == follow["initialization_reference"] == reference
    assert "no useful change" in follow["reason"]
    assert follow["initialization"] == "learned"


def test_all_families_can_be_revisited_and_worse_changes_direction(monkeypatch):
    snapshot, data, reference = model(monkeypatch, outcome="worse")
    for goal in ("detail", "weight", "local_motion", "density"):
        row = guided_search.propose(snapshot, "fit", "goal:" + goal, data)
        data["context"]["cases"].append(dict(method="current", target="form.vtk", goal=goal,
            reference=reference, values=row["values"], outcome="worse"))
    again = guided_search.propose(snapshot, "fit", "detail", data)
    assert again["available"] and again["goal"] == "detail"
    assert again["contrast_level"] == 1
    assert again["anchor"] == reference
    assert "last result was worse" in again["reason"]
    for _ in range(20):
        goal, _reason = next_hypothesis(data["context"]["cases"], "current", "form.vtk", "detail")
        assert goal is not None
        data["context"]["cases"].append(dict(method="current", target="form.vtk", goal=goal,
            reference=reference, values={}, outcome="same"))


def test_marked_scale_changes_explanation_without_local_objective_claim(monkeypatch):
    snapshot, data, reference = model(monkeypatch)
    data["regions"] = [dict(radius=.4, symptom="detail")]
    row = guided_search.propose(snapshot, "fit", "unsure", data)
    assert row["goal"] == "weight"  # matching scale is already finer than this patch
    assert "1 marked area" in row["reason"]
    assert row["anchor"] == reference


def test_capped_new_field_keeps_old_comparison_and_cannot_loop_unchanged(monkeypatch):
    snapshot, data, reference = model(monkeypatch, outcome="same", goal="density", capped=True)
    snapshot.plan.pilot_subject_count = 1
    row = guided_search.propose(snapshot, "fit", "detail", data)
    assert row["goal"] == "optimize" and row["optimization_iterations"] == 240
    assert row["anchor"] == reference
    assert row["initialization_reference"] == data["current_reference"]
    data["context"]["cases"].append(dict(goal="optimize", reference=data["current_reference"],
        method="current", target="form.vtk", values=reference["values"]))
    retry = guided_search.propose(snapshot, "fit", "goal:optimize", data)
    assert not retry["available"]
    alternative = guided_search.propose(snapshot, "fit", "goal:weight", data)
    assert alternative["available"] and alternative["anchor"] == reference


def test_selector_callbacks_perform_no_verification_or_file_reads(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QComboBox
    from pilot_view_helpers import wait_pilot_view
    from test_guided_feedback import attempted, decision

    from diffeoforge import guided_feedback, reference_calibration_study as study
    from diffeoforge.desktop.reference_calibration_dialog import ReferenceCalibrationDialog

    app = QApplication.instance() or QApplication([])
    base, trial = attempted(tmp_path, monkeypatch)
    trial = guided_feedback.save_feedback(trial.study_directory, "guided-varifold",
                                          decision(base, trial, "same"))
    dialog = ReferenceCalibrationDialog(trial.study_directory)
    dialog.show()
    try:
        wait_pilot_view(dialog)
        ticks = []
        timer = QTimer()
        timer.timeout.connect(lambda: ticks.append(1))
        timer.start(0)
        combos = [c for c in dialog.content.findChildren(QComboBox)
                  if c.accessibleName().startswith(("What is wrong", "Alternative adjustment"))]
        assert len(combos) == 2
        def forbid(*_a, **_k):
            pytest.fail("Selector performed scientific verification/file I/O on Qt thread")
        with monkeypatch.context() as guard:
            guard.setattr(guided_strategy, "trial_proposal", forbid)
            guard.setattr(study, "load_reference_calibration_study", forbid)
            guard.setattr(study, "_verify_manifest", forbid)
            guard.setattr("diffeoforge.mesh.sha256_file", forbid)
            for combo in combos:
                for index in range(combo.count()):
                    combo.setCurrentIndex(index)
                    app.processEvents()
        assert ticks
        timer.stop()
    finally:
        dialog.close()
        app.processEvents()
