"""Independent hook journeys; synthetic files only, with no native dispatch."""

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_pilot_adaptive_run import action as action

from diffeoforge import guided_feedback as feedback
from diffeoforge import guided_working_fit
from diffeoforge import pilot_adaptive_native as native
from diffeoforge import pilot_adaptive_run as adaptive
from diffeoforge import reference_calibration_study as study
from diffeoforge import reference_guided_pilot as guided
from diffeoforge.mesh import sha256_file


@pytest.fixture
def inspection(monkeypatch, tmp_path):
    identifier = "guided-varifold"
    target = "target.vtk"
    current_ref = dict(
        directory=str(tmp_path / "current"),
        candidate_id=identifier,
        target=target,
        method="varifold",
        binding={"hash": "current"},
    )
    previous_ref = dict(
        current_ref, directory=str(tmp_path / "previous"), binding={"hash": "previous"}
    )
    internal_ref = dict(
        current_ref, directory=str(tmp_path / "internal"), binding={"hash": "internal"}
    )
    quality = dict(numerical_selection_suitable=False, no_new_intersection_flags=False)
    candidate = SimpleNamespace(
        candidate_id=identifier,
        status="completed",
        metrics=dict(attachment_comparison=dict(subjects={target: dict(regional_quality=quality)})),
    )
    current = SimpleNamespace(
        study_directory=Path(current_ref["directory"]),
        candidates=[candidate],
        visual_reviews={},
        attachment_comparison={},
    )
    previous = SimpleNamespace(study_directory=Path(previous_ref["directory"]), visual_reviews={})
    internal = SimpleNamespace(
        study_directory=Path(internal_ref["directory"]),
        visual_reviews={},
        attachment_comparison=dict(guided=dict(strategy=dict(adaptive_fit={"version": "fixture"}))),
    )
    parents = {
        r["directory"]: p
        for r, p in ((current_ref, current), (previous_ref, previous), (internal_ref, internal))
    }
    events = [
        dict(
            event="guided_fit_feedback",
            sequence=0,
            current=current_ref,
            comparison=previous_ref,
            outcome="better",
            problem_regions={},
        )
    ]
    monkeypatch.setattr(study, "_load_events", lambda *_: copy.deepcopy(events))
    monkeypatch.setattr(study, "load_reference_calibration_study", lambda _: current)
    monkeypatch.setattr(
        study,
        "_verify_manifest",
        lambda _: dict(inputs=dict(subjects=[dict(filename=target, sha256="0" * 64)])),
    )
    monkeypatch.setattr(feedback, "_same_source", lambda _s, r: parents[r["directory"]])
    monkeypatch.setattr(feedback, "inspected", lambda parent, _id: parent is not internal)
    monkeypatch.setattr(
        feedback,
        "choices",
        lambda *_: [dict(reference=r) for r in (current_ref, previous_ref, internal_ref)],
    )
    monkeypatch.setattr(feedback, "_local_events", lambda *_: iter(events[:1]))
    from diffeoforge import retained_mark_source

    monkeypatch.setattr(retained_mark_source, "context", lambda *_: None)
    monkeypatch.setattr(
        guided,
        "record",
        lambda s: dict(
            target=target, screen_trials_spent=4 if s is current else 3, history=[], strategy={}
        ),
    )

    def append(_root, event, payload):
        row = dict(event=event, sequence=len(events), **payload)
        events.append(row)
        return row

    monkeypatch.setattr(study, "_append_event", append)
    return SimpleNamespace(
        current=current,
        previous=previous,
        internal=internal,
        current_ref=current_ref,
        previous_ref=previous_ref,
        internal_ref=internal_ref,
        events=events,
        identifier=identifier,
        target=target,
    )


def test_viewable_internal_field_cannot_be_directly_selected_as_inspected(inspection):
    c = inspection
    before = copy.deepcopy(c.events)
    with pytest.raises(ValueError, match="Inspect this saved field"):
        feedback.select(c.current.study_directory, c.identifier, c.internal_ref)
    assert c.events == before and c.internal.visual_reviews == {}


@pytest.mark.parametrize("kind", ["guided_starting_fit_selected", "guided_method_preference"])
def test_bare_internal_preference_cannot_clear_explicit_inspection_gate(inspection, kind):
    c = inspection
    key = "reference" if kind == "guided_starting_fit_selected" else "preference"
    c.events.append(
        dict(
            event=kind,
            sequence=1,
            **{key: c.internal_ref},
            anatomical_approval_created=False,
            optimizer_started=False,
        )
    )
    with pytest.raises(ValueError, match="settled working-fit viewer"):
        feedback.starting_fit_choice(c.current, c.identifier)
    assert not c.internal.visual_reviews


def test_settled_working_editor_can_choose_internal_source_without_anatomical_approval(inspection):
    c = inspection
    pending = feedback.starting_fit_choice(c.current, c.identifier)
    assert pending
    result = guided_working_fit.save(
        c.current.study_directory,
        c.identifier,
        dict(
            reference=c.internal_ref,
            expected_starting_choice=pending,
            inspected_subjects=[c.target],
            display_scopes={c.target: "preview"},
            problem_regions={},
        ),
    )
    assert result is c.current
    assert feedback.starting_fit_choice(result, c.identifier) is None
    assert feedback.selection(result, c.identifier) == c.internal_ref
    event = c.events[-1]
    assert event["region_edit"]["version"] == 2 and event["inspected_subjects"] == [c.target]
    assert event["anatomical_approval_created"] is False and event["optimizer_started"] is False
    assert c.internal.visual_reviews == {} and not feedback.inspected(c.internal, c.identifier)


@pytest.mark.parametrize(
    "mutation",
    [
        "unknown_guard",
        "wrong_method",
        "joint",
        "moving_template",
        "wrong_precision",
        "regional_in_ordinary",
    ],
)
def test_ordinary_seed_metadata_scope_is_explicit_and_unknown_scope_never_bypasses(
    tmp_path,
    monkeypatch,
    mutation,
):
    from diffeoforge.reference_ordinary_guard import DECLARATION

    config = dict(
        project=dict(
            parameter_provenance=dict(
                finite_accepted_guard=copy.deepcopy(DECLARATION),
                recommendation=dict(calibration_plan=dict(execution_scope="single_specimen_probe")),
            )
        ),
        optimization=dict(method="lbfgs", freeze_template=True, freeze_control_points=True),
        model=dict(
            attachment=dict(type="varifold"),
            deformation=dict(initial_control_points="controls.txt"),
        ),
        runtime=dict(precision="float32"),
        output={},
    )
    path = tmp_path / "ordinary.json"
    path.write_text(json.dumps(config))
    snapshot = SimpleNamespace(
        plan=SimpleNamespace(pilot_subject_count=1),
        candidates=[SimpleNamespace(candidate_id="candidate", config_path=path)],
    )
    monkeypatch.setattr(feedback, "reference", lambda *_: dict(method="varifold"))
    import diffeoforge.config as configuration

    monkeypatch.setattr(configuration, "load_config", lambda p: json.loads(Path(p).read_text()))
    assert native.eligible_seed(snapshot, "candidate")
    if mutation == "unknown_guard":
        config["project"]["parameter_provenance"]["finite_accepted_guard"]["version"] = (
            "unknown-scope"
        )
    elif mutation == "wrong_method":
        config["model"]["attachment"]["type"] = "current"
    elif mutation == "joint":
        snapshot.plan.pilot_subject_count = 2
    elif mutation == "moving_template":
        config["optimization"]["freeze_template"] = False
    elif mutation == "wrong_precision":
        config["runtime"]["precision"] = "float64"
    else:
        config["project"]["parameter_provenance"]["regional_fit"] = {"manifest": "not-opened"}
    path.write_text(json.dumps(config))
    assert not native.eligible_seed(snapshot, "candidate")


def test_root_launch_hook_reserves_the_sealed_cap_before_constructing_request(action):
    snapshot = adaptive.prepare(action.arguments)
    candidate = snapshot.candidates[0]
    candidate.failure = None
    manifest = json.loads((snapshot.study_directory / "study.json").read_text())
    manifest["launcher"] = dict(type="native", executable="not-executed")
    request = study._launch_request(snapshot.study_directory, manifest, candidate)
    mark = adaptive.marker(snapshot.attachment_comparison)
    from diffeoforge import pilot_adaptive_fit as policy

    state = policy.load_ledger(mark["ledger"])
    assert state.held == 100 and state.active["binding"]["child_manifest_sha256"] == sha256_file(
        snapshot.study_directory / "study.json"
    )
    assert request.expected_config_sha256 == sha256_file(candidate.config_path)
    assert not request.destination.exists() and not action.launches
    assert not snapshot.visual_reviews


def test_unknown_marker_does_not_reach_ordinary_native_launch_hook(action):
    snapshot = adaptive.prepare(action.arguments)
    candidate = snapshot.candidates[0]
    candidate.failure = None
    manifest = json.loads((snapshot.study_directory / "study.json").read_text())
    manifest["attachment_comparison"]["guided"]["strategy"]["adaptive_fit"]["version"] = "unknown"
    with pytest.raises(ValueError, match="Unsupported adaptive child"):
        study._launch_request(snapshot.study_directory, manifest, candidate)
    assert not action.launches


def test_ordinary_regional_transition_keeps_legacy_allowance_and_no_adaptive_marker(
    tmp_path,
    monkeypatch,
):
    from test_guided_direction_flow import _marked_fit

    from diffeoforge.config import load_config

    base, identifier = _marked_fit(tmp_path, monkeypatch)
    before = {p: sha256_file(p) for p in base.study_directory.rglob("*") if p.is_file()}
    monkeypatch.setattr(adaptive, "prepare", lambda *_: pytest.fail("Legacy opted into new action"))
    child = guided.next_action(
        base.study_directory, "adaptive_recover", identifier, goal="regional:detail"
    )
    assert adaptive.marker(child.attachment_comparison) is None
    # This fixture's legacy initial-warm proposal has its existing 400-step cap.
    assert child.attachment_comparison["iterations"] == 400
    assert load_config(child.candidates[0].config_path)["optimization"]["max_iterations"] == 400
    assert child.candidates[0].attempts == 0 and not child.visual_reviews
    assert all(sha256_file(p) == digest for p, digest in before.items() if p.name != "events.jsonl")


def test_bounded_transition_uses_verified_normal_plan_and_preserves_seed_identity(
    tmp_path,
    monkeypatch,
):
    from test_guided_direction_flow import _marked_fit

    base, identifier = _marked_fit(tmp_path, monkeypatch)
    source = feedback.reference(base, identifier)
    captured = []
    child_root = tmp_path / "new-bounded-child"
    child_root.mkdir()
    (child_root / "study.json").write_text("{}")

    def prepare(arguments):
        captured.append(arguments)
        return SimpleNamespace(study_directory=child_root)

    monkeypatch.setattr(adaptive, "prepare", prepare)
    result = guided.next_action(
        base.study_directory,
        "adaptive_bounded_fit",
        identifier,
        goal=dict(bounded_action="adaptive_recover", goal="regional:detail"),
    )
    assert result.study_directory == child_root and len(captured) == 1
    assert captured[0]["strategy"]["baseline"] == source
    assert captured[0]["feedback"]["target"] == source["target"]
    assert captured[0]["methods"] == ("varifold",)
    assert not captured[0]["strategy"].get("adaptive_fit")
    final_event = study._load_events(base.study_directory)[-1]
    assert final_event["anatomical_approval_created"] is False
    assert final_event["optimizer_started"] is False
