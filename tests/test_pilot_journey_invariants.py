"""Outcome-driven pilot journeys, using synthetic controllers and bound geometry.

These tests do not mock the direction/selection functions. The numerical
controller supplies explicit synthetic receipts rather than running an optimizer;
surface readers and the source/feedback/transition machinery remain real.
"""

import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_guided_feedback import decision
from test_guided_pilot import approve, run_batch
from test_interactive_pilot import initial
from test_pilot_region_feedback import patch, reject
from test_reference_calibration_study import _CompletedController

from diffeoforge import guided_feedback, guided_strategy
from diffeoforge import reference_calibration_study as study
from diffeoforge import reference_guided_pilot as guided
from diffeoforge.config import load_config
from diffeoforge.mesh import sha256_file
from diffeoforge.surface_io import load_surface_mesh

METHOD = "guided-varifold"


def _state(snapshot):
    return guided_strategy.prepare_proposals(snapshot, guided_strategy.state(snapshot))


def _register_geometry(snapshot, reports):
    """Supply real same-topology meshes for the receipt-only controller's output."""
    manifest = study._verify_manifest(snapshot.study_directory)
    template = snapshot.study_directory / manifest["inputs"]["template"]["copy"]
    for candidate in snapshot.candidates:
        config = load_config(candidate.config_path)
        output = candidate.run_directory / "output"
        output.mkdir(exist_ok=True)
        inventory = []
        for row in manifest["inputs"]["subjects"]:
            name = (f"Fixture__Reconstruction__{config['model']['object_id']}__subject_"
                    + row["filename"] + ".vtk")
            path = output / name
            shutil.copyfile(template, path)
            inventory.append(dict(path=name, bytes=path.stat().st_size, sha256=sha256_file(path)))
        final = candidate.metrics["final_iteration"]
        reports[candidate.run_directory] = SimpleNamespace(
            manifest=dict(effective_config=config), inventory=inventory,
            result=dict(status="completed", return_code=0),
            convergence=tuple(SimpleNamespace(iteration=i, log_likelihood=value,
                attachment=value, regularity=0.) for i, value in ((final - 1, -10.), (final, -9.))),
        )


def _surface_controller(monkeypatch, *, finer=False, tradeoff=False):
    from diffeoforge import reference_attachment_comparison as comparison

    class Controller(_CompletedController):
        def run(self, *, event_callback=None):
            result = super().run(event_callback=event_callback)
            measure = comparison.measure

            def measured(*args, **kwargs):
                values = measure(*args, **kwargs)
                for row in values["attachment_comparison"]["subjects"].values():
                    for repeat in row["repeats"]:
                        repeat["regions"] = {
                            "0:1": dict(count=16, tail=.015 if finer else .06),
                            "1:3": dict(count=16, tail=.03 if tradeoff and finer
                                        else .005 if finer else .01),
                        }
                return values

            monkeypatch.setattr(comparison, "measure", measured)
            return result

    return Controller


def _finer_successor(tmp_path, monkeypatch, *, formal_review=True, tradeoff=False):
    from diffeoforge import result_report

    reports = {}
    monkeypatch.setattr(result_report, "collect_run_report", lambda root: reports[Path(root)])
    screen = run_batch(initial(tmp_path), monkeypatch,
                       controller=_surface_controller(monkeypatch))
    screen = reject(reject(screen, "guided-current"), METHOD)
    _register_geometry(screen, reports)
    chosen = guided.next_action(screen.study_directory, "adaptive_working_start", "guided-current",
        goal=dict(reference=guided_feedback.reference(screen, METHOD),
            inspected_subjects=[guided.record(screen)["target"]],
            display_scopes={guided.record(screen)["target"]: "preview"}, problem_regions={}))
    direction = _state(chosen)["fit_direction"]
    assert direction["mode"] == "trial"
    assert direction["request"]["reference"] == guided_feedback.reference(screen, METHOD)
    prepared = guided.next_action(chosen.study_directory, direction["action"],
                                 direction["identifier"], goal=direction["request"])
    assert guided.record(prepared)["goal"] == "detail"
    assert prepared.attachment_comparison["refinement"]["reference"] == (
        guided_feedback.reference(screen, METHOD))
    assert prepared.plan.effective_values["attachment_kernel_width"] == pytest.approx(
        screen.plan.effective_values["attachment_kernel_width"] * .9)
    current = run_batch(prepared, monkeypatch, capped=True,
                        controller=_surface_controller(monkeypatch, finer=True, tradeoff=tradeoff))
    _register_geometry(current, reports)
    if formal_review:
        current = reject(current, METHOD)
    return screen, current, reports


def _new_mark(snapshot):
    source = snapshot.plan.selected_pilot_subjects[0]
    manifest = study._verify_manifest(snapshot.study_directory)
    path = snapshot.study_directory / manifest["inputs"]["subjects"][0]["copy"]
    vertices = load_surface_mesh(path).geometry.vertices
    return patch(source.sha256, center=list(max(vertices, key=lambda p: p[0])),
                 radius=.35, symptom="detail")


def _synthetic_frame(snapshot, reports, monkeypatch):
    """Supply the separate frame qualification receipt, not a shooting computation."""
    from guided_field_fixture import field_fixture

    from diffeoforge import regional_frame

    candidate = snapshot.candidates[0]
    run = candidate.run_directory
    manifest = study._verify_manifest(snapshot.study_directory)
    config = load_config(candidate.config_path)
    template = snapshot.study_directory / manifest["inputs"]["template"]["copy"]
    endpoint = run / "output" / reports[run].inventory[0]["path"]
    field = field_fixture(run)
    controls = Path(config["model"]["deformation"]["initial_control_points"])
    if not controls.is_absolute():
        controls = candidate.config_path.parent / controls
    receipt = dict(source_run=str(run), source_manifest_sha256=sha256_file(run / "manifest.json"),
        endpoint=dict(path=str(endpoint), sha256=sha256_file(endpoint)),
        reference_source=dict(path=str(template), sha256=sha256_file(template)),
        timepoints=73, precision="float64", integrator="rk2",
        starting_frame_qualification=dict(temporal_stable=True),
        field_paths=dict(control_points=str(controls), momenta=str(field.momenta_path)),
        controls_sha256=sha256_file(controls), momenta_sha256=sha256_file(field.momenta_path))
    monkeypatch.setattr(regional_frame, "qualify", lambda *_a, **_k: receipt)


@pytest.mark.parametrize("formal_review", [True, False])
def test_better_capped_successor_with_new_red_mark_offers_current_local_correction(
    tmp_path, monkeypatch, formal_review,
):
    screen, current, reports = _finer_successor(tmp_path, monkeypatch, formal_review=formal_review,
                                               tradeoff=True)
    target = guided.record(current)["target"]
    mark = _new_mark(current)
    payload = decision(screen, current, "better") | dict(symptom="unsure",
        problem_regions={target: [mark]})
    current = guided_feedback.save_feedback(current.study_directory, METHOD, payload)
    exact = guided_feedback.reference(current, METHOD)
    assert guided_feedback.selection(current, METHOD) == exact
    approvals = dict(current.visual_reviews)
    journal = current.study_directory / study.STUDY_EVENTS
    prefix = journal.read_bytes()
    for _ in range(2):
        state = _state(study.load_reference_calibration_study(current.study_directory))
        direction = state["fit_direction"]
        assert direction["mode"] == "trial", direction
        assert direction["request"]["goal"] == "regional", direction
        assert direction["request"]["reference"] == exact
        assert direction["request"]["regions"] == [mark]
        assert not direction.get("continuation")
        assert "surface measurements improved" not in direction["reason"].lower()
    assert journal.read_bytes() == prefix
    assert study.load_reference_calibration_study(current.study_directory).visual_reviews == (
        approvals)
    if not formal_review:
        assert METHOD not in approvals  # Better never creates anatomical approval/rejection.
    _synthetic_frame(current, reports, monkeypatch)
    prepared = guided.next_action(current.study_directory, direction["action"],
                                 direction["identifier"], goal=direction["request"])
    assert prepared.attachment_comparison["regional_objective"]
    assert prepared.attachment_comparison["refinement"]["reference"] == exact
    assert guided.record(prepared)["feedback"]["regions"] == [mark]
    assert prepared.plan.pilot_subject_count == 1
    assert all(c.attempts == 0 for c in prepared.candidates) and not prepared.visual_reviews
    assert study.load_reference_calibration_study(current.study_directory).visual_reviews == (
        approvals)


@pytest.mark.parametrize("formal_review", [True, False])
def test_better_capped_successor_without_new_marks_offers_exact_continuation(
    tmp_path, monkeypatch, formal_review,
):
    screen, current, _ = _finer_successor(tmp_path, monkeypatch, formal_review=formal_review)
    current = guided_feedback.save_feedback(current.study_directory, METHOD,
        decision(screen, current, "better") | dict(symptom="unsure"))
    exact = guided_feedback.reference(current, METHOD)
    original = load_config(current.candidates[0].config_path)
    before = {p: sha256_file(p) for p in current.study_directory.rglob("*") if p.is_file()}
    state = _state(current)
    direction = state["fit_direction"]
    assert direction["mode"] == "trial" and direction.get("continuation"), direction
    assert direction["request"]["reference"] == exact
    assert direction["request"]["goal"] == "optimize"
    assert direction["request"]["values"] == exact["values"]
    allowance = direction["request"]["optimization_iterations"]
    assert type(allowance) is int and allowance > 0
    assert "native log-likelihood" in direction["reason"].lower()
    assert "improvement is not established" in direction["reason"].lower()
    prepared = guided.next_action(current.study_directory, direction["action"],
                                 direction["identifier"], goal=direction["request"])
    config = load_config(prepared.candidates[0].config_path)
    assert prepared.attachment_comparison["refinement"]["reference"] == exact
    assert config["optimization"] == dict(original["optimization"], max_iterations=allowance)
    assert prepared.plan.effective_values == current.plan.effective_values
    assert all(c.attempts == 0 for c in prepared.candidates) and not prepared.visual_reviews
    assert all(sha256_file(path) == digest for path, digest in before.items()
               if path.name != study.STUDY_EVENTS)


@pytest.mark.parametrize("outcome", ["worse", "unsure"])
def test_nonpreferred_successor_never_silently_becomes_the_next_start(
    tmp_path, monkeypatch, outcome,
):
    screen, current, _ = _finer_successor(tmp_path, monkeypatch)
    earlier = guided_feedback.reference(screen, METHOD)
    payload = decision(screen, current, outcome) | dict(symptom="unsure")
    current = guided_feedback.save_feedback(current.study_directory, METHOD, payload)
    assert guided_feedback.selection(current, METHOD) == earlier
    approvals = dict(current.visual_reviews)
    state = _state(current)
    direction = state["fit_direction"]
    assert direction is not None
    assert direction["mode"] != "compare", direction
    if direction["mode"] == "trial":
        assert direction["request"]["reference"] == earlier
    elif direction["mode"] == "return":
        assert direction["current"] == earlier
    else:
        assert "review" in direction["reason"].lower(), direction
    assert not any(current.visual_reviews.values()) and current.visual_reviews == approvals


def test_suitable_successor_advances_coverage_without_reopening_method_comparison(
    tmp_path, monkeypatch,
):
    screen, current, _ = _finer_successor(tmp_path, monkeypatch)
    current = guided_feedback.save_feedback(current.study_directory, METHOD,
        decision(screen, current, "better") | dict(symptom="unsure"))
    current = approve(current, METHOD)
    before = {p: sha256_file(p) for p in current.study_directory.rglob("*") if p.is_file()}
    state = _state(current)
    assert not state.get("fit_direction") or state["fit_direction"]["mode"] != "compare"
    # Use the same public next-step transition as the suitable-fit flow.
    following = guided.next_action(current.study_directory, "adaptive_confirm", METHOD)
    assert guided.record(following)["target"] != guided.record(current)["target"]
    assert following.plan.pilot_subject_count == 1
    assert not following.visual_reviews and all(c.attempts == 0 for c in following.candidates)
    assert study.load_reference_calibration_study(current.study_directory).visual_reviews[METHOD]
    assert all(sha256_file(path) == digest for path, digest in before.items()
               if path.name != study.STUDY_EVENTS)


def test_explicit_choice_is_carried_into_successor_then_better_selects_the_new_field(
    tmp_path, monkeypatch,
):
    screen, current, _ = _finer_successor(tmp_path, monkeypatch)
    old = guided_feedback.reference(screen, METHOD)
    assert guided.record(current)["strategy"]["preference"] == old
    current = guided_feedback.save_feedback(current.study_directory, METHOD,
        decision(screen, current, "better") | dict(symptom="unsure"))
    exact = guided_feedback.reference(current, METHOD)
    assert exact != old and guided_feedback.selection(current, METHOD) == exact
    state = _state(current)
    direction = state["fit_direction"]
    assert direction is not None and direction["mode"] != "compare", direction
    if direction["mode"] == "trial":
        assert direction["request"]["reference"] == exact
    elif direction["mode"] == "return":
        assert direction["current"] == exact
    assert not any(current.visual_reviews.values())


@pytest.mark.parametrize("outcome", ["same", "worse", "unsure"])
@pytest.mark.parametrize("button", ["method", "working"])
def test_newer_other_arm_review_is_a_boundary_until_a_new_explicit_choice(
    tmp_path, monkeypatch, outcome, button,
):
    """Exercise journal ordering with verified metadata, without preparing fields."""
    references = [dict(directory=str(tmp_path), candidate_id=arm, target="example.vtk",
        method=method, manifest_sha256=digest * 64, binding={"verified": arm}, values={})
        for arm, method, digest in (("arm-a", "varifold", "a"), ("arm-b", "current", "b"))]
    first, other = references
    events = [dict(event="guided_fit_feedback", current=first, comparison=other, outcome="better")]
    snapshot = SimpleNamespace(study_directory=tmp_path,
                               plan=SimpleNamespace(pilot_subject_count=1))
    context = dict(feedback={reference["candidate_id"]: dict(selected=reference,
        choices=[dict(reference=row) for row in references]) for reference in references})
    verified = []

    def same_source(_snapshot, reference):
        assert reference in references and reference["target"] == "example.vtk"
        verified.append(reference)

    def local_events(_snapshot, identifier):
        return (event for event in events if event["event"] == "guided_fit_feedback"
                and event["current"]["candidate_id"] == identifier)

    monkeypatch.setattr(study, "_load_events", lambda _: events)
    monkeypatch.setattr(guided, "record", lambda _: dict(target="example.vtk", phase="refine"))
    monkeypatch.setattr(guided_feedback, "_same_source", same_source)
    monkeypatch.setattr(guided_feedback, "_local_events", local_events)
    assert guided_strategy._explicit_start(snapshot, context)["reference"] == first
    verified.clear()
    events.append(dict(event="guided_fit_feedback", current=other,
                       comparison=first, outcome=outcome))
    assert guided_strategy._explicit_start(snapshot, context) is None
    assert not verified  # The older Better must not be resurrected or prepared.
    if button == "method":
        events.append(dict(event="guided_method_preference", preference=first))
        identifier = first["candidate_id"]
    else:
        identifier = other["candidate_id"]
        context["feedback"][identifier]["selected"] = first
        events.append(dict(event="guided_starting_fit_selected", reference=first,
                           editing_candidate_id=identifier))
    selected = guided_strategy._explicit_start(snapshot, context)
    assert selected["reference"] == first and selected["editing_candidate_id"] == identifier
    assert verified == [first]


@pytest.mark.parametrize("phase,goal,strategy,count", [
    ("joint", "detail", {}, 1),
    ("refine", "form_model_check", {}, 1),
    ("refine", "detail", {"shared_model_check": {"verified": True}}, 1),
    ("refine", "detail", {}, 2),
])
def test_individual_feedback_normalization_leaves_other_review_protocols_alone(
    tmp_path, monkeypatch, phase, goal, strategy, count,
):
    snapshot = SimpleNamespace(study_directory=tmp_path,
                               plan=SimpleNamespace(pilot_subject_count=count))
    monkeypatch.setattr(guided, "record", lambda _: dict(
        target="example.vtk", phase=phase, goal=goal, strategy=strategy))
    monkeypatch.setattr(study, "_load_events", lambda _: [
        dict(event="guided_fit_feedback", outcome="better")])
    monkeypatch.setattr(guided_feedback, "_same_source", lambda *_:
                        pytest.fail("An individual preference crossed another review protocol"))
    assert guided_strategy._explicit_start(snapshot, dict(feedback={})) is None
