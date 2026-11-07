"""Coverage changes the animal, retaining shared settings, never another fit's field."""
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

import pytest
from test_guided_pilot import approve, run_batch
from test_interactive_pilot import initial

from diffeoforge import guided_feedback as feedback
from diffeoforge import guided_search
from diffeoforge import guided_strategy as strategy
from diffeoforge import reference_guided_pilot as guided
from diffeoforge.mesh import sha256_file


@pytest.mark.parametrize("phase", ["screen", "validate", "joint"])
def test_nonlocal_history_is_not_a_local_reference(phase, monkeypatch, tmp_path):
    ref = {"target": "previous.vtk"}
    origin = str(tmp_path / "cohort")
    parent = SimpleNamespace(attachment_comparison={"guided": {"origin": origin}})
    snapshot = SimpleNamespace(attachment_comparison={"guided": {
        "origin": origin, "phase": phase, "target": None if phase == "joint" else "next.vtk",
        "strategy": {"baseline": ref},
    }})
    verified = []
    monkeypatch.setattr(feedback, "verify_reference", lambda row: verified.append(row) or parent)
    assert feedback.local_strategy_reference(snapshot, "baseline") is None
    assert verified == [ref]


def test_joint_recovery_keeps_the_new_explicit_single_form_field(tmp_path, monkeypatch):
    # Exercise actual transition planning, without geometry/optimizer activity.
    # Recovery from a cohort target (None) binds a fresh, valid individual role;
    # that role must survive the same target-change boundary as coverage.
    (tmp_path / "study.json").write_text("{}", encoding="utf-8")
    values = dict(attachment_kernel_width=.1, deformation_kernel_width=.4,
                  noise_std=.02, initial_control_point_spacing=.5)
    ref = dict(directory=str(tmp_path), candidate_id="joint", target="one.vtk",
               method="current", values=values)
    snapshot = SimpleNamespace(study_directory=tmp_path,
        plan=SimpleNamespace(effective_values=values),
        attachment_comparison={"guided": dict(origin=str(tmp_path), phase="joint", target=None,
            approved=[], history=[], strategy={}, screen_trials_spent=4)})
    proposed = dict(available=True, initialization_reference=ref, target="one.vtk", values=values,
                    method="current", anchor=ref, numerical_extension=False, goal="detail")
    monkeypatch.setattr(guided, "_origin", lambda _: (snapshot, None))
    monkeypatch.setattr(guided, "verify_approvals", lambda _: None)
    monkeypatch.setattr(strategy, "_context", lambda _: ([], None))
    monkeypatch.setattr(strategy, "_preference", lambda _: None)
    monkeypatch.setattr(strategy, "trial_proposal", lambda *_a, **_k: proposed)
    monkeypatch.setattr(strategy, "_reference", lambda *_a, **_k: ref)
    monkeypatch.setattr(strategy, "_compatible", lambda *_a: [])
    monkeypatch.setattr(strategy, "capture", lambda *_a, **_k: {})
    monkeypatch.setattr(feedback, "verify_reference", lambda _: snapshot)
    monkeypatch.setattr(feedback, "region_state", lambda *_a: ([], False))
    plan = strategy._plan_transition(snapshot, "recover", "joint")
    assert plan["phase"] == "refine" and plan["target"] == "one.vtk"
    assert plan["strategy"]["baseline"] == plan["strategy"]["anchor"] == ref
    assert plan["strategy"]["search_family"] == "detail"
    assert plan["strategy"]["control_basis"] == ref
    assert not plan["approved"]


def legacy_coverage(tmp_path, monkeypatch):
    base = approve(run_batch(initial(tmp_path), monkeypatch), "guided-varifold")
    next_form = guided.next_action(base.study_directory, "adaptive_confirm", "guided-varifold")
    current = approve(run_batch(next_form, monkeypatch), "guided-varifold")
    # Older manifests are immutable. Represent their retained historical roles
    # in memory; the real saved-manifest read-only regression is separate.
    comparison = deepcopy(current.attachment_comparison)
    reference = feedback.reference(base, "guided-varifold")
    comparison["guided"]["strategy"].update(baseline=reference, anchor=reference)
    return base, replace(current, attachment_comparison=comparison)


def test_existing_coverage_history_cannot_be_a_cross_form_comparison_or_seed(
    tmp_path, monkeypatch,
):
    base, current = legacy_coverage(tmp_path, monkeypatch)
    protected = {p: sha256_file(p) for root in (base.study_directory, current.study_directory)
                 for p in root.rglob("*") if p.is_file()}
    context = strategy.state(current)
    data = context["feedback"]["guided-varifold"]
    assert data["comparison"] is None and data["selected"] is None
    assert all(row["reference"]["target"] == guided.record(current)["target"]
               for row in data["choices"])
    assert not data["needs_direction"]
    verified = guided_search.inputs(current, "guided-varifold", context)
    assert verified["baseline"] is None and verified["anchor"] is None
    assert verified["current_reference"]["target"] == guided.record(current)["target"]
    with pytest.raises(ValueError, match="No earlier settings"):
        guided_search.propose(current, "guided-varifold", "base:detail", verified)
    strategy.prepare_proposals(current, context)
    assert all(row.get("target", guided.record(current)["target"])
               == guided.record(current)["target"]
               for row in context["proposals"]["guided-varifold"].values())
    assert {p: sha256_file(p) for p in protected} == protected


@pytest.mark.parametrize("invalid", ["another_cohort", "refinement", "regional_objective"])
def test_coverage_compatibility_never_weakens_reference_identity(
    tmp_path, monkeypatch, invalid,
):
    _base, current = legacy_coverage(tmp_path / "one", monkeypatch)
    if invalid == "another_cohort":
        foreign = approve(run_batch(initial(tmp_path / "two"), monkeypatch), "guided-varifold")
        guided.record(current)["strategy"]["baseline"] = feedback.reference(
            foreign, "guided-varifold"
        )
    elif invalid == "refinement":
        guided.record(current)["phase"] = "refine"
    else:
        current.attachment_comparison["regional_objective"] = {"version": "not-coverage"}
    with pytest.raises(ValueError, match="same cohort and original form"):
        feedback.presentation(current, "guided-varifold")
