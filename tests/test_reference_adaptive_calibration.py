from __future__ import annotations

import copy
import json
from dataclasses import replace
from pathlib import Path

import pytest
from test_reference_calibration_study import _metrics, _review_ready_stage

import diffeoforge.reference_adaptive_calibration as adaptive
import diffeoforge.reference_calibration_study as study
from diffeoforge.adaptive_calibration import AdaptiveSearchPolicy
from diffeoforge.config import load_config, validate_input_paths
from diffeoforge.mesh import sha256_file


def seed_stub(snapshot, center_id, destination):
    candidate = next(c for c in snapshot.candidates if c.candidate_id == center_id)
    config = load_config(candidate.config_path)
    files = {}
    names = sorted(s.filename for s in snapshot.plan.selected_pilot_subjects)
    template = next((snapshot.study_directory / "inputs/template").glob("*.vtk"))
    for role, filename, data in (
        ("template", "template.vtk", template.read_bytes()),
        ("control_points", "controls.txt", b"0 0 0\n1 1 1\n"),
        ("momenta", "momenta.txt", (f"{len(names)} 2 3\n" + "0 0 0\n" * len(names) * 2).encode()),
    ):
        path = destination / "adaptive-seed" / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        files[role] = {
            "copy": path.relative_to(destination).as_posix(),
            "sha256": sha256_file(path),
        }
    return {
        "candidate_id": center_id,
        "files": files,
        "subject_labels": names,
        "optimization": config["optimization"],
        "model": config["model"],
        "deformation": config["model"]["deformation"],
        "source_manifest_sha256": "a" * 64,
        "source_run_directory": str(study.calibration_candidate_run_directory(candidate)),
    }


def setup_search(tmp_path, monkeypatch):
    runner, original = _review_ready_stage(tmp_path, monkeypatch)
    monkeypatch.setattr(adaptive, "bind_learned_seed", seed_stub)
    return runner, original


def test_feedback_loop_preserves_old_runs_stops_at_plateau_and_reopens_budget(
    tmp_path, monkeypatch
):
    runner, original = setup_search(tmp_path, monkeypatch)
    old_bytes = (original.study_directory / "events.jsonl").read_bytes()
    result = adaptive.run_adaptive_stage(runner)
    assert result.study_directory != original.study_directory
    assert result.status == "awaiting_review"
    assert len(result.candidates) == len(original.candidates) + 7
    assert result.adaptive_search_status["stop_reason"] == "fit_plateau"
    assert not result.visual_reviews and not result.selected_candidate_ids
    assert (original.study_directory / "events.jsonl").read_bytes().startswith(old_bytes)
    source_digest = sha256_file(original.study_directory / "events.jsonl")
    context = adaptive.study_context(result)
    assert context["new_runs_used"] == 7
    assert context["round_index"] == 1
    attempts = {c.candidate_id: c.attempts for c in result.candidates}
    rerun = adaptive.run_adaptive_stage(
        study.ReferenceCalibrationStudyRunner(
            result.study_directory,
            controller_factory=runner._controller_factory,
        )
    )
    assert {c.candidate_id: c.attempts for c in rerun.candidates} == attempts
    assert sha256_file(original.study_directory / "events.jsonl") == source_digest
    assert (
        study.latest_reference_calibration_search_extension_directory(original.study_directory)
        == result.study_directory
    )


def test_improvement_creates_next_round_and_stops_at_persisted_run_budget(tmp_path, monkeypatch):
    runner, original = setup_search(tmp_path, monkeypatch)

    def collect(run):
        atlas = run / "atlas.vtk"
        atlas.write_text("placeholder")
        # New results improve all subjects, so the search must react and recenter.
        return replace(_metrics(atlas, -0.1))

    monkeypatch.setattr(study, "collect_reference_calibration_run_metrics", collect)
    result = adaptive.run_adaptive_stage(runner, policy=AdaptiveSearchPolicy(maximum_new_runs=8))
    assert len(result.candidates) == len(original.candidates) + 8
    assert result.search_extension_round == 2
    assert result.adaptive_search_status["stop_reason"] == "budget_reached"
    assert result.adaptive_search_status["center_id"].startswith("adaptive-")
    assert not result.selected_candidate_ids


def test_prepared_trials_bind_momenta_and_reinitialize_changed_grid(tmp_path, monkeypatch):
    runner, original = setup_search(tmp_path, monkeypatch)
    context = adaptive.study_context(original)
    child = study.create_reference_calibration_search_extension_study(
        original.study_directory,
        tmp_path / "successor",
        safety_limits={k: tuple(v) for k, v in context["bounds"].items()},
        adaptive_context=context,
    )
    trials = {t.trial_id: t for t in adaptive.decide_context(context).trials}
    for candidate in child.candidates:
        if candidate.candidate_id not in trials:
            continue
        trial = trials[candidate.candidate_id]
        config = load_config(candidate.config_path)
        inputs = validate_input_paths(config, candidate.config_path)
        assert (
            inputs.initial_momenta is not None
            if trial.initialization == "warm"
            else (inputs.initial_momenta is None)
        )
        assert config["optimization"]["max_iterations"] == 300
        if trial.label == "denser-controls":
            assert inputs.initial_control_points is None
        if trial.label == "continue":
            old = load_config(original.candidates[0].config_path)
            assert config["optimization"]["convergence_tolerance"] == pytest.approx(
                old["optimization"]["convergence_tolerance"] / 10
            )
    seed = child.study_directory / "adaptive-seed/momenta.txt"
    seed.write_text("changed")
    with pytest.raises(study.ReferenceCalibrationStudyError, match="input changed"):
        study.load_reference_calibration_study(child.study_directory)


def test_forged_scores_cannot_create_a_successor(tmp_path, monkeypatch):
    _, original = setup_search(tmp_path, monkeypatch)
    context = adaptive.study_context(original)
    context["observations"][0]["subject_fit"] = dict.fromkeys(context["expected_subjects"], 0.0)
    with pytest.raises(study.ReferenceCalibrationStudyError, match="differs from bound evidence"):
        study.create_reference_calibration_search_extension_study(
            original.study_directory,
            tmp_path / "forged",
            safety_limits={k: tuple(v) for k, v in context["bounds"].items()},
            adaptive_context=context,
        )
    assert not (tmp_path / "forged").exists()


def test_cancellation_at_decision_starts_no_successor(tmp_path, monkeypatch):
    runner, original = setup_search(tmp_path, monkeypatch)

    def cancel(event):
        if event["event"] == "adaptive_search_decision":
            runner.request_cancel()

    result = adaptive.run_adaptive_stage(runner, event_callback=cancel)
    assert result.study_directory == original.study_directory
    assert result.search_extension_round == 0


def test_final_cohort_uses_selected_geometry_but_never_pilot_momenta(tmp_path, monkeypatch):
    _, snapshot = setup_search(tmp_path, monkeypatch)
    manifest = study._verify_manifest(snapshot.study_directory)
    selected = {"attachment": snapshot.candidates[0].candidate_id}
    # Test export without pretending the synthetic fixture was visually approved.
    manifest = copy.deepcopy(manifest)
    # A broad glob must keep excluding the original template after a learned
    # template outside the cohort replaces it as the atlas initialization.
    manifest["inputs"]["full_cohort"]["subject_pattern"] = "*.vtk"
    path = study._final_configuration(
        snapshot.study_directory,
        manifest,
        {**snapshot.plan.effective_values, "timepoints": 10},
        {**selected, "deformation": "test", "noise": "test", "timepoints": "test"},
        dict.fromkeys(["attachment", "deformation", "noise", "timepoints"], "researcher_manual"),
        "a" * 64,
        continuation_source=snapshot,
    )
    config = load_config(path)
    inputs = validate_input_paths(config, path)
    assert inputs.initial_momenta is None
    assert inputs.initial_control_points is not None
    assert "selected-seed" in str(inputs.template)
    original_template = Path(manifest["inputs"]["full_cohort"]["template"])
    assert inputs.cohort_template == original_template
    assert inputs.subject_count == snapshot.plan.subject_count
    assert original_template not in inputs.subjects
    assert (
        config["project"]["parameter_provenance"]["recommendation"]["calibration_result"][
            "full_cohort_confirmation_required"
        ]
        is True
    )


def test_seed_binding_uses_real_run_inventory_and_rejects_tampered_geometry(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from test_reference_pca import _completed_reference_run

    run = _completed_reference_run(tmp_path / "run")
    manifest = json.loads((run / "manifest.json").read_text())
    subjects = [
        {"filename": Path(r["staged_path"]).name, "sha256": r["geometry"]["sha256"]}
        for r in manifest["inputs"]
        if r["role"] == "subject"
    ]
    snapshot = SimpleNamespace(
        study_directory=tmp_path, candidates=[SimpleNamespace(candidate_id="seed")]
    )
    monkeypatch.setattr(study, "calibration_candidate_run_directory", lambda _: run)
    monkeypatch.setattr(study, "_verify_manifest", lambda _: {"inputs": {"subjects": subjects}})
    seed = adaptive.bind_learned_seed(snapshot, "seed", tmp_path / "copied")
    assert set(seed["files"]) == {"template", "control_points", "momenta"}
    (run / "output/DeterministicAtlas__EstimatedParameters__Momenta.txt").write_text("changed")
    with pytest.raises(RuntimeError, match="evidence failed|checksum|Momenta"):
        adaptive.bind_learned_seed(snapshot, "seed", tmp_path / "tampered")


def test_approved_adaptive_fit_carries_learned_state_into_next_stage(tmp_path, monkeypatch):
    from test_reference_calibration_study import _approve_for_test

    runner, _ = setup_search(tmp_path, monkeypatch)
    result = adaptive.run_adaptive_stage(runner)
    candidate = next(c for c in result.candidates if c.candidate_id.startswith("adaptive-"))
    _approve_for_test(result.study_directory, candidate.candidate_id)
    next_snapshot, _ = study.record_reference_calibration_stage_review(
        result.study_directory,
        selected_candidate_id=candidate.candidate_id,
        visual_approvals={candidate.candidate_id: True},
    )
    assert next_snapshot.current_stage.stage_id == "deformation"
    for c in next_snapshot.candidates:
        if c.candidate_id == "deformation-retained":
            assert study.calibration_candidate_run_directory(c) == candidate.run_directory
            assert next_snapshot.visual_reviews[c.candidate_id] is True
            continue
        config = load_config(c.config_path)
        summary = validate_input_paths(config, c.config_path)
        assert "stage-seeds" in str(summary.template)
        assert config["optimization"]["max_iterations"] == 300
    seed_event = next(
        e
        for e in reversed(study._load_events(result.study_directory))
        if e["event"] == "stage_prepared"
    )
    bound = seed_event["continuation_seed"]["files"]["template"]["copy"]
    (result.study_directory / bound).write_text("changed")
    with pytest.raises(study.ReferenceCalibrationStudyError, match="stage seed changed"):
        study.load_reference_calibration_study(result.study_directory)


def test_repeated_adaptive_extensions_preserve_stratified_plan_version():
    from test_reference_calibration import _recommendation

    from diffeoforge.reference_calibration import (
        CalibrationCandidateEvidence,
        PilotSubjectDeclaration,
        assess_calibration_stage,
        bind_calibration_search_extension_plan,
        build_reference_calibration_plan,
        reference_calibration_plan_from_provenance,
    )

    recommendation = _recommendation()
    declaration = PilotSubjectDeclaration(recommendation.observations[1].filename, "group", True)
    plan = build_reference_calibration_plan(
        recommendation,
        coordinate_unit="unitless",
        requested_pilot_subject_count=3,
        pilot_subject_declarations=(declaration,),
    )
    for _ in range(2):
        stage = plan.stages[0]
        names = [s.filename for s in plan.selected_pilot_subjects]
        evidence = [
            CalibrationCandidateEvidence(
                candidate_id=c.candidate_id,
                completed=True,
                converged=True,
                invalid_face_count=0,
                residual_p95=0.1,
                deformation_energy=1.0,
                distortion_p95=0.1,
                runtime_seconds=1.0,
                subject_normalized_residual_p95=tuple((name, 0.1) for name in names),
            )
            for c in stage.candidates
        ]
        assessment = assess_calibration_stage(plan, stage_id=stage.stage_id, evidence=evidence)
        context = {
            "policy": {"maximum_new_runs": 1},
            "bounds": {
                k: [v / 10, v * 10]
                for k, v in plan.effective_values.items()
                if k in adaptive.FIT_PARAMETERS
            },
            "round_index": 0,
            "new_runs_used": 0,
            "previous_center_id": None,
            "tested_trial_keys": [],
            "expected_subjects": names,
            "observations": [
                {
                    "candidate_id": c.candidate_id,
                    "values": {**plan.effective_values, **c.values},
                    "subject_fit": dict.fromkeys(names, 0.1),
                }
                for c in stage.candidates
            ],
        }
        proposal = adaptive.propose_adaptive_fit(plan, assessment, context)
        plan = bind_calibration_search_extension_plan(plan, assessment, proposal)
        assert plan.version == "0.6"
        assert reference_calibration_plan_from_provenance(plan.provenance) == plan
        assert plan.pilot_subject_declarations == (declaration,)
