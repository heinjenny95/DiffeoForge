"""A visible continuation is grounded in a capped saved field, not an ETA or approval."""

import time
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from diffeoforge import pilot_capped_direction as capped


def _case(monkeypatch):
    from diffeoforge import reference_guided_pilot

    identifier, target = "guided-varifold", "example.vtk"
    reference = dict(directory="saved", candidate_id=identifier, method="varifold", target=target)
    metrics = dict(completed=True, converged=False, maximum_iterations=600, final_iteration=600,
                   optimizer_stop_signal="maximum_iterations")
    candidate = SimpleNamespace(candidate_id=identifier, status="completed", metrics=metrics)
    snapshot = SimpleNamespace(study_directory=Path("saved"), candidates=[candidate],
        visual_reviews={identifier: False}, plan=SimpleNamespace(pilot_subject_count=1),
        attachment_comparison=dict(methods={identifier: "varifold"}))
    monkeypatch.setattr(reference_guided_pilot, "record", lambda _: dict(
        phase="refine", target=target, strategy={}))
    proposal = dict(available=True, goal="optimize", numerical_extension=True, target=target,
                    initialization_reference=reference, optimization_iterations=1200, values={})
    feedback = dict(choices=[dict(reference=reference, label="Varifold · Test 4 · 270 CP")],
                    feedback={})
    context = dict(allowed={identifier: True}, feedback={identifier: feedback},
        working_proposals={}, proposals={identifier: {"goal:optimize": proposal}},
        preferred="varifold")
    monkeypatch.setattr(capped, "_objective_tail", lambda _: ((595, -150.), (600, -145.)))
    return snapshot, context, candidate, proposal, feedback, reference


def test_objective_only_progress_is_named_separately_and_preserves_recorded_budget(monkeypatch):
    snapshot, context, _, proposal, _, reference = _case(monkeypatch)
    result = capped.preview(snapshot, context, None)
    assert result["continuation"] and result["request"]["reference"] == reference
    assert result["request"]["optimization_iterations"] == 1200
    assert "up to 1,200 more" in result["title"]
    assert "-150 → -145" in result["reason"]
    assert "improved surface fit is not established" in result["reason"]
    assert "new optimizer history" in result["reason"]
    assert proposal["optimization_iterations"] == 1200


@pytest.mark.parametrize("change", [
    "failed", "unknown_stop", "converged", "short", "unreviewed", "suitable",
    "uninspected", "needs_direction", "other_seed", "earlier_chosen", "wrong_budget",
    "global_regression", "marked_regression", "green_regression", "alignment",
    "new_marks", "worse_review", "no_objective_progress",
])
def test_ineligible_results_do_not_get_a_primary_continuation(monkeypatch, change):
    snapshot, context, candidate, proposal, feedback, reference = _case(monkeypatch)
    identifier = candidate.candidate_id
    chosen = None
    if change == "failed":
        candidate.status = "failed"
    elif change == "unknown_stop":
        candidate.metrics["optimizer_stop_signal"] = "unknown"
    elif change == "converged":
        candidate.metrics["converged"] = True
    elif change == "short":
        candidate.metrics["final_iteration"] = 599
    elif change in {"unreviewed", "suitable"}:
        snapshot.visual_reviews[identifier] = None if change == "unreviewed" else True
        if change == "unreviewed":
            context["allowed"][identifier] = False  # No inspection, including feedback-only review.
    elif change == "uninspected":
        context["allowed"][identifier] = False
    elif change == "needs_direction":
        feedback["needs_direction"] = True
    elif change == "other_seed":
        proposal["initialization_reference"] = dict(reference, directory="older")
    elif change == "earlier_chosen":
        chosen = dict(editing_candidate_id=identifier, reference=dict(reference, directory="older"))
    elif change == "wrong_budget":
        proposal["optimization_iterations"] = True
    elif change in {"global_regression", "marked_regression", "green_regression"}:
        key, value = {
            "global_regression": ("refinement_guard", dict(severe=False, outcome="regression")),
            "marked_regression": ("marked_regions", dict(outcome="regression")),
            "green_regression": ("regional_quality", dict(explicit_fixed_preserved=False)),
        }[change]
        candidate.metrics["attachment_comparison"] = dict(
            subjects={reference["target"]: {key: value}})
    elif change == "alignment":
        feedback["feedback"] = dict(symptom="alignment")
    elif change == "new_marks":
        feedback["problem_regions"] = {reference["target"]: [dict(symptom="detail")]}
    elif change == "worse_review":
        feedback["feedback"] = dict(outcome="worse")
    else:
        monkeypatch.setattr(capped, "_objective_tail", lambda _: None)
    assert capped.preview(snapshot, context, chosen) is None


def test_unchanged_bound_marks_distinguish_measured_local_gain(monkeypatch):
    snapshot, context, candidate, _, feedback, reference = _case(monkeypatch)
    marks = [dict(symptom="detail", purpose="problem", center=[0., 0., 0.])]
    feedback["problem_regions"] = {reference["target"]: marks}
    candidate.metrics["attachment_comparison"] = dict(subjects={reference["target"]: dict(
        marked_regions=dict(outcome="improved", measurements=[dict(region=marks[0])]),
        regional_quality=dict(outside_preserved=True, shape_preserved=True),
    )})
    before = deepcopy(candidate.metrics)
    result = capped.preview(snapshot, context, None)
    assert "surface measurements improved" in result["reason"]
    assert result["request"]["regions"] == marks
    assert candidate.metrics == before


def test_guarded_regional_proposal_exposes_its_exact_field_and_allowance(tmp_path, monkeypatch):
    from test_regional_continuation import case as regional_fixture

    from diffeoforge import regional_continuation
    from diffeoforge.mesh import sha256_file

    # Build the sealed synthetic checkpoint/field-chain fixture; no solver runs.
    case = regional_fixture.__wrapped__(tmp_path, monkeypatch, SimpleNamespace())
    snapshot, identifier = case.snapshot, case.identifier
    case.info.update(phase="refine", target=case.ref["target"])
    snapshot.study_directory = Path(case.ref["directory"])
    snapshot.visual_reviews = {identifier: False}
    snapshot.attachment_comparison = dict(methods={identifier: "varifold"}, regional_objective={})
    proposal = regional_continuation.proposal(snapshot, identifier, case.data)
    assert proposal is not None and proposal["regional_continuation"]
    feedback = dict(feedback=dict(outcome="same"), problem_regions={case.ref["target"]: case.marks},
                    choices=[dict(reference=case.ref, label="Varifold · Test 8 · 270 CP")])
    context = dict(allowed={identifier: True}, preferred="varifold",
                   feedback={identifier: feedback},
                   working_proposals={}, proposals={identifier: {"goal:optimize": proposal}})
    monkeypatch.setattr(capped, "_objective_tail", lambda _: ((3, -3.), (4, -2.)))
    before = {p: sha256_file(p) for p in tmp_path.rglob("*") if p.is_file()}
    result = capped.preview(snapshot, context, None)
    assert result["request"]["optimization_iterations"] == 4
    assert result["request"]["reference"] == case.ref
    assert result["request"]["regions"] == case.marks
    assert "surface fit is not established" in result["reason"]
    assert all(sha256_file(p) == digest for p, digest in before.items())


def _precision_guard_case(tmp_path, monkeypatch):
    import json

    import numpy as np

    from diffeoforge import reference_calibration_study
    from diffeoforge.mesh import sha256_file
    from diffeoforge.reference_guard_assets import C5_SOURCE

    run = tmp_path / "run"
    guard_path = run / "output/numerical-guard"
    guard_path.parent.mkdir(parents=True)
    namespace = {}
    exec(compile(C5_SOURCE, "finite-guard-test", "exec"), namespace)

    def snapshot(path, _parameters, _iteration):
        path.write_bytes(b"synthetic native serializer for read-only trace test")

    initial, final, gradient = np.zeros(3), np.ones(3), np.ones(3)
    guard = namespace["FiniteAcceptedGuard"](initial, guard_path, snapshot,
        provenance=dict(objective_fingerprint="precision-objective"))
    guard.observe_fg(initial, np.float64(1377.0002), gradient, 599)
    accepted = guard.observe_fg(final, np.float64(1377.0001), gradient, 600)
    guard.commit(accepted, 600)
    guard.validate_final_result(final, np.float64(1377.0001), gradient)
    guard.export_allowed(final)
    pointer = json.loads((guard_path / "best-latest.json").read_text())
    marker = dict(source_seals={str(p.resolve()): sha256_file(p)
        for p in guard_path.rglob("*") if p.is_file()},
        guard_objective_fingerprint="precision-objective",
        accepted_parameter_sha256=pointer["parameter_sha256"])
    candidate = SimpleNamespace(metrics=dict(final_iteration=600, maximum_iterations=600))
    monkeypatch.setattr(reference_calibration_study, "calibration_candidate_run_directory",
                        lambda _: run)
    return candidate, marker, guard_path


def test_exact_accepted_guard_improvement_survives_flat_rounded_log(tmp_path, monkeypatch):
    from diffeoforge import result_report

    candidate, marker, _ = _precision_guard_case(tmp_path, monkeypatch)
    monkeypatch.setattr(result_report, "collect_run_report", lambda _: SimpleNamespace(
        convergence=tuple(SimpleNamespace(iteration=i, log_likelihood=-1377.) for i in (599, 600))))
    assert capped._objective_tail(candidate) is None
    assert capped._guarded_tail(candidate, marker) == ((599, -1377.0002), (600, -1377.0001))


@pytest.mark.parametrize("change", ["stale_trace", "wrong_objective", "wrong_field",
                                    "false_final", "false_export", "violation"])
def test_guarded_progress_requires_the_exact_final_field_and_sealed_trace(
    tmp_path, monkeypatch, change,
):
    import json

    from diffeoforge.mesh import sha256_file

    candidate, marker, folder = _precision_guard_case(tmp_path, monkeypatch)
    if change == "stale_trace":
        with (folder / "events.jsonl").open("a") as handle:
            handle.write("\n")
    elif change == "wrong_objective":
        marker["guard_objective_fingerprint"] = "other-objective"
    elif change == "wrong_field":
        marker["accepted_parameter_sha256"] = "f" * 64
    elif change == "false_final":
        candidate.metrics["final_iteration"] = 601
    elif change == "false_export":
        path = folder / "events.jsonl"
        events = [json.loads(line) for line in path.read_text().splitlines()]
        event = next(row for row in events if row["kind"] == "native_export_parameter_binding")
        event["parameter_sha256"] = "f" * 64
        path.write_text("\n".join(json.dumps(row) for row in events) + "\n")
        marker["source_seals"][str(path.resolve())] = sha256_file(path)
    else:
        (folder / "violation.json").write_text("{}")
    assert capped._guarded_tail(candidate, marker) is None
    snapshot, context, offered_candidate, proposal, _, _ = _case(monkeypatch)
    offered_candidate.metrics.update(candidate.metrics)
    proposal["regional_continuation"] = marker
    # Even an apparently improving legacy log must not rescue stale guard data.
    assert capped.preview(snapshot, context, None) is None


@pytest.mark.parametrize("values,iterations,expected", [
    ((-20., -19., -18.), (598, 599, 600), True),
    ((-18., -18., -18.), (598, 599, 600), False),
    ((-20., -19., -19.5), (598, 599, 600), False),
    ((-20., float("nan"), -18.), (598, 599, 600), False),
    ((-20., -19., -18.), (598, 599, 599), False),
    ((-20., -19., -18.), (597, 598, 599), False),
])
def test_objective_recommendation_requires_finite_ordered_tail_at_recorded_stop(
    monkeypatch, values, iterations, expected,
):
    from diffeoforge import reference_calibration_study, result_report

    candidate = SimpleNamespace(metrics=dict(final_iteration=600))
    monkeypatch.setattr(reference_calibration_study, "calibration_candidate_run_directory",
                        lambda _: Path("saved-run"))
    report = SimpleNamespace(convergence=tuple(SimpleNamespace(iteration=i, log_likelihood=v)
        for i, v in zip(iterations, values, strict=True)))
    monkeypatch.setattr(result_report, "collect_run_report", lambda _: report)
    assert (capped._objective_tail(candidate) is not None) is expected


def test_fixed_footer_prepares_exact_capped_field_without_running_or_losing_approval(
    tmp_path, monkeypatch,
):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from pilot_view_helpers import wait_pilot_view
    from PySide6.QtWidgets import QApplication, QPushButton
    from test_guided_progress import limited
    from test_interactive_pilot import initial
    from test_pilot_region_feedback import reject

    from diffeoforge import guided_feedback
    from diffeoforge import reference_calibration_study as study
    from diffeoforge import reference_guided_pilot as guided
    from diffeoforge.desktop.reference_calibration_dialog import ReferenceCalibrationDialog
    from diffeoforge.mesh import sha256_file

    app = QApplication.instance() or QApplication([])
    base = reject(reject(limited(initial(tmp_path), monkeypatch), "guided-current"),
                  "guided-varifold")
    base = guided.next_action(base.study_directory, "adaptive_prefer", "guided-varifold")
    monkeypatch.setattr(capped, "_objective_tail", lambda _: ((115, -150.), (120, -145.)))
    prefix = (base.study_directory / study.STUDY_EVENTS).read_bytes()
    preserved = {p: sha256_file(p) for p in base.study_directory.rglob("*")
                 if p.is_file() and p.name != study.STUDY_EVENTS}
    monkeypatch.setattr(study.ReferenceCalibrationStudyRunner, "run_current_stage",
                        lambda *_a, **_k: pytest.fail("Preparation dispatched a fit"))
    dialog = ReferenceCalibrationDialog(base.study_directory)
    dialog.show()
    try:
        wait_pilot_view(dialog)
        footer = dialog.next_step_button
        assert footer.isVisible() and footer.isEnabled()
        assert footer.text().startswith("Continue saved fit · up to 240 more")
        assert footer.objectName() == "primary"
        assert "Native log-likelihood still improves" in dialog.status.text()
        assert [button for button in dialog.findChildren(QPushButton, "primary")
                if button.isVisible() and button.isEnabled()] == [footer]
        goal = deepcopy(dialog._guided_footer_goal)
        assert goal["reference"] == guided_feedback.reference(base, "guided-varifold")
        with pytest.raises(ValueError, match="iteration allowance changed"):
            guided.next_action(base.study_directory, "adaptive_recover", "guided-varifold",
                               goal=goal | dict(optimization_iterations=241))
        footer.click()
        deadline = time.monotonic() + 20
        while dialog._worker and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(.002)
        assert dialog._worker is None
        wait_pilot_view(dialog)
        prepared = dialog._snapshot
        assert prepared.study_directory != base.study_directory
        assert prepared.attachment_comparison["iterations"] == 240
        assert prepared.attachment_comparison["refinement"]["reference"] == goal["reference"]
        assert all(c.status == "pending" and c.attempts == 0 for c in prepared.candidates)
        assert not prepared.visual_reviews
        assert all(sha256_file(p) == digest for p, digest in preserved.items())
        assert (base.study_directory / study.STUDY_EVENTS).read_bytes().startswith(prefix)
        assert study.load_reference_calibration_study(base.study_directory).visual_reviews == (
            base.visual_reviews)
    finally:
        dialog.close()
        app.processEvents()
