"""Public receipt-controller journey, separate from native mathematical qualification.

Only field tensors/quality are synthetic here. Study creation, protected files,
two-stage dispatch, review/adoption, next-form and joint setup use production code.
"""

from copy import deepcopy

import numpy as np
from test_guided_pilot import approve, run_batch
from test_reviewed_start_progress import selected_local_after_common_failure

from diffeoforge import pilot_multiscale as support
from diffeoforge import pilot_multiscale_study as pipeline
from diffeoforge import reference_calibration_study as study
from diffeoforge import reference_guided_pilot as guided
from diffeoforge.config import load_config
from diffeoforge.mesh import sha256_file
from diffeoforge.pilot_form_progress import marker


def synthetic_inputs(monkeypatch):
    from diffeoforge.guided_feedback import verify_reference
    from diffeoforge.pilot_common_capacity import demand
    from diffeoforge.surface_io import load_surface_mesh

    def sites(snapshot, value):
        parent = verify_reference(value["protocol"]["reference"])
        manifest = study._verify_manifest(parent.study_directory)
        row = manifest["inputs"]["template"]
        path = parent.study_directory / row["copy"]
        cp = parent.attachment_comparison["controls"]
        cp_path = parent.study_directory / cp["copy"]
        candidate = parent.candidates[0]
        cfg = load_config(candidate.config_path)
        spec = support.specification(
            value["protocol"]["reference"]["values"],
            precision=cfg["runtime"]["precision"],
            tolerance=cfg["optimization"]["convergence_tolerance"],
            required_controls=max(demand(value).values()),
        )
        proof = dict(
            specification=spec,
            template=dict(path=str(path), sha256=row["sha256"]),
            prefix=dict(
                path=str(cp_path),
                sha256=cp["sha256"],
                study_directory=str(parent.study_directory),
                study_manifest_sha256=sha256_file(parent.study_directory / study.STUDY_MANIFEST),
            ),
            blocks=[],
        )
        return np.loadtxt(cp_path, ndmin=2), load_surface_mesh(path).geometry, proof

    monkeypatch.setattr(support, "retained_support", sites)

    def field(snapshot):
        from guided_field_fixture import field_fixture

        c = snapshot.candidates[0]
        assert c.status == "completed"
        run = study.calibration_candidate_run_directory(c)
        manifest = run / "manifest.json"
        if not manifest.exists():
            manifest.write_text('{"public_synthetic_controller_checkpoint":true}\n')
        result = field_fixture(run)
        result.run_directory = run
        return result

    monkeypatch.setattr(pipeline, "_capture_field", field)


def test_capture_detail_review_adoption_next_forms_and_original_joint_choices(
    tmp_path, monkeypatch
):
    from diffeoforge import guided_strategy

    local, previous = selected_local_after_common_failure(tmp_path, monkeypatch)
    value = marker(previous)
    individual = deepcopy(value["reviews"])
    original_reviews = dict(local.visual_reviews)
    source, _ = guided._origin(previous.study_directory)
    source_config = load_config(
        source.study_directory
        / study._verify_manifest(source.study_directory)["source_config"]["copy"]
    )
    synthetic_inputs(monkeypatch)
    info = guided.record(previous)
    state = dict(form_progress=value, previous=pipeline.binding(previous), preference=None)
    plan = dict(
        source=source,
        previous=previous,
        phase="validate",
        target=info["target"],
        methods=("varifold",),
        values=value["protocol"]["reference"]["values"],
        approved=[],
        history=[*info["history"], dict(pipeline.binding(previous), outcome="explicit_new_test")],
        spent=info["screen_trials_spent"],
        strategy=state,
        goal="form_model_check",
        feedback=None,
    )
    plan = pipeline.apply(plan, previous, value)
    capture = guided._batch(**plan)
    assert pipeline.marker(capture.attachment_comparison)["stage"] == "capture"
    assert capture.candidates[0].attempts == 0
    cfg = load_config(capture.candidates[0].config_path)
    assert "initial_momenta" not in cfg["model"]["deformation"]
    assert cfg["optimization"]["max_iterations"] == 120
    detail = run_batch(capture, monkeypatch, capped=True)
    assert detail.study_directory != capture.study_directory
    assert pipeline.marker(detail.attachment_comparison)["stage"] == "detail"
    assert (
        not detail.visual_reviews
        and not study.load_reference_calibration_study(capture.study_directory).visual_reviews
    )
    assert detail.candidates[0].metrics["objective_stages"]["stage_number"] == 2
    assert detail.candidates[0].metrics["iteration_accounting"]["total_iterations"] == 240
    assert detail.attachment_comparison["controls"] == capture.attachment_comparison["controls"]
    # Reopening the earlier stage follows its direct detail pointer, even once
    # later next-form successors exist. It never repeats the capture.
    assert (
        pipeline.prepare_detail(
            study.load_reference_calibration_study(capture.study_directory)
        ).study_directory
        == detail.study_directory
    )
    from diffeoforge.guided_feedback import presentation

    comparison = presentation(detail, "guided-varifold")["comparison"]
    original = next(r for r in individual if r["filename"] == guided.record(detail)["target"])
    assert comparison["directory"] == original["directory"]
    assert comparison["candidate_id"] == original["candidate_id"]
    assert marker(detail)["reviews"] == individual
    assert (
        len(
            [
                e
                for e in study._load_events(capture.study_directory)
                if e["event"] == "candidate_started"
            ]
        )
        == 1
    )
    detail = approve(detail)
    assert guided_strategy.state(detail)["common_recovery"]["mode"] == "adopt"
    current = guided.next_action(
        detail.study_directory, "adaptive_adopt_common_model", "guided-varifold"
    )
    assert marker(current)["reviews"] == individual
    assert guided.record(current)["target"] != guided.record(detail)["target"]
    assert current.attachment_comparison["controls"] == capture.attachment_comparison["controls"]
    for _ in range(len(individual) - 1):
        assert (
            "initial_momenta"
            not in load_config(current.candidates[0].config_path)["model"]["deformation"]
        )
        current = approve(run_batch(current, monkeypatch, capped=True))
        current = guided.next_action(
            current.study_directory, "adaptive_form_model_check", "guided-varifold"
        )
        assert marker(current)["reviews"] == individual
    assert guided.record(current)["phase"] == "joint"
    joint = load_config(current.candidates[0].config_path)
    for key in ("method", "freeze_template", "freeze_control_points"):
        assert joint["optimization"][key] == source_config["optimization"][key]
    assert "finite_accepted_guard" not in joint["project"]["parameter_provenance"]
    assert len(current.attachment_comparison["joint_initialization"]["subjects"]) == len(individual)
    from diffeoforge.cohort_field_quality import VERSION as JOINT_QUALITY

    assert current.attachment_comparison["joint_initialization"]["field_quality"] == JOINT_QUALITY
    assert (
        pipeline.prepare_detail(
            study.load_reference_calibration_study(capture.study_directory)
        ).study_directory
        == detail.study_directory
    )
    assert study.load_reference_calibration_study(local.study_directory).visual_reviews == (
        original_reviews
    )
    # Continue beyond joint preparation: retaining the reviewed joint result must
    # reach the existing final numerical stage without restarting the singles.
    joint_result = approve(run_batch(current, monkeypatch, capped=True))
    final = guided.next_action(joint_result.study_directory, "finish_joint", "guided-varifold")
    assert final.current_stage.order == 4
    assert any(c.status == "completed" for c in final.candidates)
    assert not any(c.attempts for c in final.candidates if c.status == "pending")
    assert study.load_reference_calibration_study(local.study_directory).visual_reviews == (
        original_reviews
    )
