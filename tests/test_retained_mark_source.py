"""Retain follows the inspected marked field, including legacy feedback journals."""

from copy import deepcopy
from types import SimpleNamespace

from test_guided_feedback import attempted, decision
from test_pilot_region_feedback import patch

from diffeoforge import guided_feedback as feedback
from diffeoforge import reference_calibration_study as study
from diffeoforge import reference_guided_pilot as guided
from diffeoforge.mesh import sha256_file
from diffeoforge.retained_mark_source import context


def marked(base, trial):
    payload = decision(base, trial, "better")
    form = trial.plan.selected_pilot_subjects[0]
    payload["problem_regions"] = {form.filename: [
        dict(patch(form.sha256), purpose="problem", version="surface-region-v2"),
        dict(patch(form.sha256), purpose="fixed", version="surface-region-v2",
             center=[.5, .5, .5]),
    ]}
    return payload


def test_better_retain_uses_displayed_fit_despite_outside_regression(tmp_path, monkeypatch):
    base, trial = attempted(tmp_path, monkeypatch)
    monkeypatch.setattr(feedback, "severe_regression", lambda *_: True)
    saved = feedback.save_feedback(trial.study_directory, "guided-varifold", marked(base, trial))
    before = (saved.study_directory / study.STUDY_EVENTS).read_bytes()
    reference = feedback.reference(saved, "guided-varifold")
    result = context(saved, "guided-varifold")
    assert result["reference"] == reference and result["automatic_start_allowed"]
    assert feedback.selection(saved, "guided-varifold") == reference
    assert (saved.study_directory / study.STUDY_EVENTS).read_bytes() == before
    assert not saved.visual_reviews and result["anatomical_approval"] is False


def test_newer_explicit_saved_fit_choice_overrides_mark_origin(tmp_path, monkeypatch):
    base, trial = attempted(tmp_path, monkeypatch)
    saved = feedback.save_feedback(trial.study_directory, "guided-varifold", marked(base, trial))
    ref = feedback.reference(base, "guided-varifold")
    selected = feedback.select(saved.study_directory, "guided-varifold", ref)
    assert context(selected, "guided-varifold")["reference"] == ref
    assert feedback.selection(selected, "guided-varifold") == ref


def test_unchanged_retained_area_does_not_rebind_to_later_worse_view(tmp_path, monkeypatch):
    base, trial = attempted(tmp_path, monkeypatch)
    payload = marked(base, trial)
    saved = feedback.save_feedback(trial.study_directory, "guided-varifold", payload)
    original = feedback.reference(saved, "guided-varifold")
    # Same field/region, later feedback changes the whole-fit opinion, not the
    # reference at which its already-saved Retain instruction was introduced.
    payload = deepcopy(payload)
    payload["outcome"] = "worse"
    saved = feedback.save_feedback(saved.study_directory, "guided-varifold", payload)
    assert context(saved, "guided-varifold")["reference"] == original
    assert feedback.selection(saved, "guided-varifold") == original


def test_clear_removes_retention_preference_without_rewriting_original_fit(tmp_path, monkeypatch):
    base, trial = attempted(tmp_path, monkeypatch)
    original = {p: sha256_file(p) for p in base.study_directory.rglob("*") if p.is_file()}
    payload = marked(base, trial)
    saved = feedback.save_feedback(trial.study_directory, "guided-varifold", payload)
    payload.update(outcome="worse", problem_regions={},
                   cleared_region_subjects=[guided.record(saved)["target"]])
    cleared = feedback.save_feedback(saved.study_directory, "guided-varifold", payload)
    assert context(cleared, "guided-varifold") is None
    assert feedback.selection(cleared, "guided-varifold") == feedback.reference(
        base, "guided-varifold")
    assert all(sha256_file(p) == digest for p, digest in original.items())


def test_unpreferred_new_retention_needs_explicit_working_fit_choice(tmp_path, monkeypatch):
    base, trial = attempted(tmp_path, monkeypatch)
    payload = marked(base, trial)
    payload["outcome"] = "worse"
    saved = feedback.save_feedback(trial.study_directory, "guided-varifold", payload)
    result = context(saved, "guided-varifold")
    assert result["available"] and not result["automatic_start_allowed"]
    assert "working-fit" in result["reason"]
    assert feedback.selection(saved, "guided-varifold") == feedback.reference(
        base, "guided-varifold")


def test_numerical_seed_must_bind_the_exact_retained_field(tmp_path, monkeypatch):
    from diffeoforge import config, regional_fit
    from diffeoforge.retained_mark_source import current_is_bound

    manifest = tmp_path / "manifest.json"
    manifest.write_text("immutable numerical source")
    reference = dict(directory="chosen", candidate_id="field")
    data = dict(current_reference=dict(directory="new"),
        current=SimpleNamespace(config_path="new.yaml"),
        retention_context=dict(available=True, automatic_start_allowed=True,
                               reference=reference),
        references={"chosen": SimpleNamespace(candidates=[
            SimpleNamespace(candidate_id="field")])})
    plan = dict(retained_run=dict(path=str(tmp_path),
        manifest_sha256=sha256_file(manifest)), fixed_protection=dict(version="dense"))
    monkeypatch.setattr(config, "load_config", lambda _: {})
    monkeypatch.setattr(regional_fit, "read_plan", lambda _: plan)
    monkeypatch.setattr(study, "calibration_candidate_run_directory", lambda _: tmp_path)
    assert current_is_bound(data)
    plan["retained_run"]["path"] = str(tmp_path / "older-fallback")
    assert not current_is_bound(data)
    plan["retained_run"]["path"] = str(tmp_path)
    manifest.write_text("changed source")
    assert not current_is_bound(data)
    plan.pop("fixed_protection")
    assert not current_is_bound(data)
    data["current_reference"] = reference
    assert current_is_bound(data)
    data["retention_context"]["automatic_start_allowed"] = False
    assert not current_is_bound(data)
    assert current_is_bound({})


def test_mixed_retained_fields_have_one_explicit_working_fit_escape(tmp_path, monkeypatch):
    form = "shape.vtk"
    a = dict(patch("a" * 64), purpose="fixed")
    b = dict(a, center=[2, 0, 0])
    references = [dict(target=form, directory=name) for name in ("first", "second", "chosen")]
    events = [dict(event="guided_fit_feedback", current=reference, outcome="better",
        problem_regions={form: rows}, inspected_subjects=[form],
        display_scopes={form: "settled-preview"}, anatomical_approval_created=False)
        for reference, rows in zip(references, ([a], [a, b]), strict=False)]
    monkeypatch.setattr(guided, "record", lambda _: dict(target=form, phase="regional"))
    monkeypatch.setattr(study, "_load_events", lambda _: events)
    monkeypatch.setattr(feedback, "_same_source", lambda *_: None)
    snapshot = SimpleNamespace(study_directory=tmp_path)
    result = context(snapshot, "field", rows=[a, b])
    assert not result["available"] and "different saved fits" in result["reason"]
    events.append(dict(event="guided_starting_fit_selected", reference=references[2]))
    result = context(snapshot, "field", rows=[a, b])
    assert result["available"] and result["automatic_start_allowed"]
    assert result["reference"] == references[2] and not result["anatomical_approval"]


def test_unknown_retained_source_has_actionable_preparation_block(monkeypatch):
    from test_regional_fit import proposal_data

    from diffeoforge import regional_pilot

    monkeypatch.setattr(guided, "record", lambda _: dict(goal="regional", pilot_order=[1, 2]))
    data = proposal_data()
    data["retention_context"] = dict(available=False, automatic_start_allowed=False,
        reason="Choose one inspected working fit and confirm these areas together.")
    result = regional_pilot.proposal(None, "field", data, symptom="gap")
    assert not result["available"]
    assert result["blocked_reason"] == data["retention_context"]["reason"]
    assert result["initialization_reference"] == data["anchor"]


def test_good_outside_metrics_cannot_reuse_seed_protecting_a_different_field(monkeypatch):
    from test_regional_fit import proposal_data

    from diffeoforge import regional_pilot, retained_mark_source

    monkeypatch.setattr(guided, "record", lambda _: dict(goal="regional", pilot_order=[1, 2]))
    monkeypatch.setattr(retained_mark_source, "current_is_bound", lambda _: False)
    data = proposal_data()
    data["retention_context"] = dict(available=True, automatic_start_allowed=True,
                                    reference=data["anchor"])
    data["current"].metrics = dict(attachment_comparison=dict(subjects={"shape.vtk": dict(
        regional_quality=dict(marked_regions=data["regions"], outside_preserved=True,
                              shape_preserved=True))}))
    result = regional_pilot.proposal(None, "field", data, symptom="gap")
    assert result["available"] and result["initialization_reference"] == data["anchor"]
