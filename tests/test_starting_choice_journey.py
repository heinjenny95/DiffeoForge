"""A better but provisional three-tip repair cannot silently restart its old seed."""

from copy import deepcopy

import pytest
from test_guided_direction_flow import _complete_with_regions, _regional_trial
from test_guided_feedback import decision

from diffeoforge import guided_feedback as feedback
from diffeoforge import guided_fit_direction as direction
from diffeoforge import guided_search, guided_strategy, guided_working_fit
from diffeoforge import reference_calibration_study as study
from diffeoforge import reference_guided_pilot as guided
from diffeoforge.mesh import sha256_file


def narrowed_better(tmp_path, monkeypatch):
    base, trial, identifier = _regional_trial(tmp_path, monkeypatch, mark_count=3)
    old_marks = deepcopy(guided.record(trial)["feedback"]["regions"])
    trial = _complete_with_regions(trial, monkeypatch, "improved", failed_guard=True)
    target = guided.record(trial)["target"]
    remaining = dict(old_marks[-1], radius=old_marks[-1]["radius"] * 1.01)
    payload = decision(base, trial, "better")
    payload["problem_regions"] = {target: [remaining]}
    trial = feedback.save_feedback(trial.study_directory, identifier, payload)
    return base, trial, identifier, target, old_marks, remaining


def test_narrowed_better_requires_choice_and_drafts_green_without_writing(tmp_path, monkeypatch):
    _, trial, identifier, target, old_marks, remaining = narrowed_better(tmp_path, monkeypatch)
    witnesses = {p: sha256_file(p) for p in trial.study_directory.rglob("*") if p.is_file()}
    assert not trial.visual_reviews
    assert feedback.regions(trial, identifier, target) == [remaining]
    pending = feedback.starting_fit_choice(trial, identifier)
    assert pending and pending["latest"] == feedback.reference(trial, identifier)
    assert feedback.selection(trial, identifier) is None
    prepared = guided_strategy.prepare_proposals(trial, guided_strategy.state(trial))
    assert prepared["fit_direction"]["mode"] == "choose_start"
    assert identifier not in prepared["proposals"]
    assert identifier not in prepared["working_proposals"]
    draft = direction.partial_mark_draft(trial, pending["latest"])
    assert draft["suggested"] == 2 and draft["remaining"] == 1
    assert draft["skipped_overlap"] == 0  # The remaining red point is not a removed area.
    assert draft["marks"][0] == remaining
    assert [row.get("purpose", "problem") for row in draft["marks"]] == [
        "problem", "fixed", "fixed"]
    assert [row["center"] for row in draft["marks"][1:]] == [m["center"] for m in old_marks[:2]]
    assert feedback.regions(trial, identifier, target) == [remaining]
    assert all(sha256_file(p) == digest for p, digest in witnesses.items())


@pytest.mark.parametrize("route", ["recover", "recover_start", "prefer_next_form", "inputs",
                                    "working_inputs", "direct_transition"])
def test_pending_choice_blocks_fresh_preparation_without_a_study_write(
    tmp_path, monkeypatch, route,
):
    _, trial, identifier, _, _, _ = narrowed_better(tmp_path, monkeypatch)
    before = {p: sha256_file(p) for p in trial.study_directory.rglob("*") if p.is_file()}
    before_dirs = {p for p in trial.study_directory.parent.iterdir() if p.is_dir()}
    monkeypatch.setattr(study.ReferenceCalibrationStudyRunner, "run_current_stage",
                        lambda *_a, **_k: pytest.fail("Preparation ran a native optimizer"))
    with pytest.raises(ValueError, match="Choose.*starting fit|starting.fit.*choice"):
        if route in {"recover", "recover_start", "prefer_next_form"}:
            action = "next_form" if route == "prefer_next_form" else route
            guided.next_action(trial.study_directory, "adaptive_" + action, identifier,
                               goal="regional:detail")
        elif route == "inputs":
            guided_search.inputs(trial, identifier, guided_strategy.state(trial))
        elif route == "working_inputs":
            guided_working_fit.inputs(trial, identifier, {}, verified={})
        else:
            guided_strategy.transition(trial, "recover_start", identifier,
                                       goal="regional:detail")
    assert before == {p: sha256_file(p) for p in before}
    assert before_dirs == {p for p in trial.study_directory.parent.iterdir() if p.is_dir()}
    assert not (trial.study_directory / "guided-transition-active.lock").exists()


def test_explicit_latest_choice_keeps_marks_and_exact_field_in_new_preparation(tmp_path,
                                                                            monkeypatch):
    import shutil
    from pathlib import Path
    from types import SimpleNamespace

    from guided_field_fixture import field_fixture

    from diffeoforge import regional_evaluation, regional_frame, result_report
    from diffeoforge.config import load_config

    _, trial, identifier, target, _, _ = narrowed_better(tmp_path, monkeypatch)
    latest = feedback.reference(trial, identifier)
    pending = feedback.starting_fit_choice(trial, identifier)
    draft = direction.partial_mark_draft(trial, latest)
    chosen = guided.next_action(trial.study_directory, "adaptive_working_start", identifier,
        goal=dict(reference=latest, inspected_subjects=[target],
                  display_scopes={target: "preview"}, problem_regions={target: draft["marks"]},
                  expected_starting_choice=pending))
    assert feedback.starting_fit_choice(chosen, identifier) is None
    assert feedback.selection(chosen, identifier) == latest
    assert not chosen.visual_reviews
    assert feedback.regions(chosen, identifier, target) == draft["marks"]
    # The receipt-only controller does not export a real endpoint. Supply the
    # selected run's own synthetic geometry, rather than returning the old run's
    # endpoint from the earlier fixture. No native fitting is involved.
    candidate = chosen.candidates[0]
    config = load_config(candidate.config_path)
    manifest = study._verify_manifest(chosen.study_directory)
    endpoint = candidate.run_directory / "output" / (
        f"Fixture__Reconstruction__{config['model']['object_id']}__subject_{target}.vtk")
    endpoint.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(chosen.study_directory / manifest["inputs"]["template"]["copy"], endpoint)
    old_report = result_report.collect_run_report
    monkeypatch.setattr(result_report, "collect_run_report", lambda path: SimpleNamespace(
        inventory=[dict(path=endpoint.name, sha256=sha256_file(endpoint))],
        manifest=dict(effective_config=config),
    ) if path == candidate.run_directory else old_report(path))
    old_endpoint = regional_evaluation.endpoint
    monkeypatch.setattr(regional_evaluation, "endpoint", lambda current, subject=None:
        None if current.run_directory == candidate.run_directory
        else old_endpoint(current, subject))
    # This fixture has a native reconstruction but no dense QC evaluation in
    # its metrics. Bind a separate synthetic fixed-field qualification to the
    # selected run, using the existing completed-field fixture and real files.
    # Qualification algorithms have their own tests; no approval is invented.
    field = field_fixture(candidate.run_directory)
    controls = Path(config["model"]["deformation"]["initial_control_points"])
    if not controls.is_absolute():
        controls = candidate.config_path.parent / controls
    source = chosen.study_directory / manifest["inputs"]["template"]["copy"]
    receipt = dict(source_run=str(candidate.run_directory),
        source_manifest_sha256=sha256_file(candidate.run_directory / "manifest.json"),
        endpoint=dict(path=str(endpoint), sha256=sha256_file(endpoint)),
        reference_source=dict(path=str(source), sha256=sha256_file(source)),
        timepoints=73, precision="float64", integrator="rk2",
        starting_frame_qualification=dict(temporal_stable=True, optimizer_updates=0),
        field_paths=dict(control_points=str(controls), momenta=str(field.momenta_path)),
        controls_sha256=sha256_file(controls), momenta_sha256=sha256_file(field.momenta_path))
    old_qualify = regional_frame.qualify
    monkeypatch.setattr(regional_frame, "qualify", lambda run, *args, **kwargs:
        deepcopy(receipt) if Path(run).resolve() == candidate.run_directory.resolve()
        else old_qualify(run, *args, **kwargs))
    monkeypatch.setattr(study.ReferenceCalibrationStudyRunner, "run_current_stage",
                        lambda *_a, **_k: pytest.fail("Preparation ran a native optimizer"))
    result = guided.next_action(chosen.study_directory, "adaptive_recover_start", identifier,
                               goal="regional:detail")
    refinement = result.attachment_comparison["refinement"]
    assert refinement["reference"] == latest
    assert guided.record(result)["feedback"]["regions"] == draft["marks"]
    if refinement["initialization"] == "residual":
        assert refinement["parent_evaluation"]["source_run"] == str(candidate.run_directory)
        assert refinement["parent_evaluation"]["momenta_sha256"] == sha256_file(field.momenta_path)
    else:
        assert refinement["initialization"] == "learned"
        assert refinement["momenta"]["sha256"] == sha256_file(field.momenta_path)
    assert result.candidates[0].attempts == 0
    assert not result.visual_reviews


def test_delayed_choice_save_rejects_a_newer_feedback_decision(tmp_path, monkeypatch):
    base, trial, identifier, target, _, remaining = narrowed_better(tmp_path, monkeypatch)
    pending = feedback.starting_fit_choice(trial, identifier)
    selected = pending["latest"]
    payload = decision(base, trial, "same")
    payload["problem_regions"] = {target: [remaining]}
    newer = feedback.save_feedback(trial.study_directory, identifier, payload)
    before = (newer.study_directory / study.STUDY_EVENTS).read_bytes()
    with pytest.raises(ValueError, match="decision changed"):
        guided.next_action(newer.study_directory, "adaptive_working_start", identifier,
            goal=dict(reference=selected, inspected_subjects=[target],
                      display_scopes={target: "preview"},
                      problem_regions={target: [remaining]}, expected_starting_choice=pending))
    assert (newer.study_directory / study.STUDY_EVENTS).read_bytes() == before


def test_overlapping_removed_areas_are_explained_without_resizing_or_preservation(
    tmp_path, monkeypatch,
):
    base, trial, identifier, target, _, remaining = narrowed_better(tmp_path, monkeypatch)
    overlapping = dict(remaining, radius=10.)
    payload = decision(base, trial, "better")
    payload["problem_regions"] = {target: [overlapping]}
    updated = feedback.save_feedback(trial.study_directory, identifier, payload)
    journal = updated.study_directory / study.STUDY_EVENTS
    before = journal.read_bytes()
    draft = direction.partial_mark_draft(updated, feedback.reference(updated, identifier))
    assert draft["skipped_overlap"] == 2 and draft["suggested"] == 0
    assert draft["marks"] == [overlapping]
    assert feedback.regions(updated, identifier, target) == [overlapping]
    assert journal.read_bytes() == before
