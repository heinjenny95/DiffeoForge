"""Persistent, bounded feedback search for an existing pilot stage.

Searches the same complete cohort; it neither approves anatomy nor launches the
full atlas. Completed candidates and the immutable extension lineage are reused.
"""

from __future__ import annotations

import copy
import json
import os
from dataclasses import asdict, replace
from pathlib import Path

from diffeoforge.adaptive_calibration import (
    FIT_PARAMETERS,
    AdaptiveSearchPolicy,
    FitObservation,
    adaptive_fit_decision,
)
from diffeoforge.config import validate_schema
from diffeoforge.mesh import sha256_file
from diffeoforge.reference_calibration import (
    CalibrationCandidate,
    CalibrationSearchExtensionProposal,
    _canonical_hash,
)


def decide_context(context):
    return adaptive_fit_decision(
        [FitObservation(**row) for row in context["observations"]],
        expected_subjects=context["expected_subjects"],
        policy=AdaptiveSearchPolicy(**context["policy"]),
        bounds={name: tuple(pair) for name, pair in context["bounds"].items()},
        round_index=context["round_index"],
        new_runs_used=context["new_runs_used"],
        previous_center_id=context["previous_center_id"],
        tested_trial_keys=context["tested_trial_keys"],
    )


def propose_adaptive_fit(plan, assessment, context):
    if assessment.plan_fingerprint != plan.fingerprint:
        raise ValueError("Adaptive assessment belongs to another plan")
    stage = next(s for s in plan.stages if s.stage_id == assessment.stage_id)
    if stage.kind == "integration_accuracy":
        raise ValueError("Integration accuracy retains its separate comparison stage")
    if {row["candidate_id"] for row in context["observations"]} != {
        c.candidate_id for c in stage.candidates
    }:
        raise ValueError("Adaptive observations differ from the declared candidate set")
    decision = decide_context(context)
    if not decision.trials:
        raise ValueError(f"Adaptive search stopped: {decision.stop_reason}")
    proposal = CalibrationSearchExtensionProposal(
        version="0.3-adaptive",
        fingerprint="",
        plan_fingerprint=plan.fingerprint,
        assessment_fingerprint=assessment.fingerprint,
        stage_id=stage.stage_id,
        source_candidate_id=decision.center_id,
        outward_steps=1,
        boundary_parameters=tuple(f"{name}:adaptive" for name in FIT_PARAMETERS),
        candidates=tuple(
            CalibrationCandidate(
                candidate_id=trial.trial_id,
                label=trial.label.replace("-", " ").capitalize(),
                parameter_values=tuple(sorted(trial.values.items())),
                rationale=trial.reason,
            )
            for trial in decision.trials
        ),
        limitations=(
            "Bounded relative search, not a globally optimal or anatomically validated fit.",
            "Worst specimen first; recentering cannot worsen another measured specimen.",
            "Fit distances are sampled bidirectional nearest-vertex p95, normalized per specimen.",
            "Iteration-limit results can seed more work but cannot pass the stage gate.",
        ),
        adaptive_context=json.dumps(context, sort_keys=True, allow_nan=False),
    )
    payload = proposal.as_manifest()
    payload.pop("fingerprint")
    return replace(proposal, fingerprint=_canonical_hash(payload))


def propose_selected_continuation(plan, assessment, context):
    """A single researcher-selected warm continuation, without a parameter grid."""
    if assessment.plan_fingerprint != plan.fingerprint:
        raise ValueError("Continuation assessment belongs to another plan")
    expected_keys = {"candidate_id", "iterations", "values"}
    if context.get("finer_surface") is True:
        expected_keys.add("finer_surface")
    if context.get("confirm_full_targets") is True:
        expected_keys.add("confirm_full_targets")
    if set(context) != expected_keys:
        raise ValueError("Invalid continuation context")
    iterations = context["iterations"]
    if type(iterations) is not int or not 1 <= iterations <= 20_000:
        raise ValueError("Additional iteration budget must be between 1 and 20000")
    stage = next(s for s in plan.stages if s.stage_id == assessment.stage_id)
    center = next(c for c in stage.candidates if c.candidate_id == context["candidate_id"])
    if context["values"] != {k: context["values"][k] for k in FIT_PARAMETERS}:
        raise ValueError("Continuation must retain all spatial and matching settings")
    identity = _canonical_hash(dict(context, plan_fingerprint=plan.fingerprint))
    proposal = CalibrationSearchExtensionProposal(
        version="0.4-selected-continuation",
        fingerprint="",
        plan_fingerprint=plan.fingerprint,
        assessment_fingerprint=assessment.fingerprint,
        stage_id=stage.stage_id,
        source_candidate_id=center.candidate_id,
        outward_steps=1,
        boundary_parameters=tuple(f"{name}:continue" for name in FIT_PARAMETERS),
        candidates=(
            CalibrationCandidate(
                candidate_id="continue-" + identity[:16],
                label=(
                    "Full target confirmation"
                    if context.get("confirm_full_targets")
                    else "Refine surface fit"
                    if context.get("finer_surface")
                    else "Continue selected fit"
                ),
                parameter_values=tuple(sorted(context["values"].items())),
                rationale=(
                    "Finer attachment and stronger fit; compatible learned deformation."
                    if context.get("finer_surface")
                    else "Same model and learned state; additional optimizer iterations only."
                ),
            ),
        ),
        limitations=(
            "Warm state, restarted optimizer step history; convergence remains unproven.",
        ),
        continuation_context=json.dumps(context, sort_keys=True, allow_nan=False),
    )
    payload = proposal.as_manifest()
    payload.pop("fingerprint")
    return replace(proposal, fingerprint=_canonical_hash(payload))


def create_selected_continuation(source, destination, *, candidate_id, iterations):
    from diffeoforge import reference_calibration_study as study

    snapshot = study.load_reference_calibration_study(source)
    if snapshot.current_stage is None:
        raise ValueError("The pilot is already complete")
    planned = next(c for c in snapshot.current_stage.candidates if c.candidate_id == candidate_id)
    values = {**snapshot.plan.effective_values, **snapshot.selected_values, **planned.values}
    context = dict(
        candidate_id=candidate_id,
        iterations=iterations,
        values={k: values[k] for k in FIT_PARAMETERS},
    )
    limits = snapshot.search_extension_safety_limits or {
        k: (values[k] / 8, values[k] * 8) for k in FIT_PARAMETERS
    }
    return study.create_reference_calibration_search_extension_study(
        source,
        destination,
        safety_limits={k: limits[k] for k in FIT_PARAMETERS},
        continuation_context=context,
    )


def study_context(snapshot, policy=None):
    from diffeoforge import reference_calibration_study as study

    if snapshot.current_stage is None:
        raise ValueError("The pilot is already complete")
    manifest = study._verify_manifest(snapshot.study_directory)
    extension = manifest.get("search_extension_source", {}).get("proposal", {})
    previous = extension.get("adaptive_context")
    if extension.get("stage_id") != snapshot.current_stage.stage_id:
        previous = None
    if previous:
        policy = AdaptiveSearchPolicy(**previous["policy"])
        old_decision = decide_context(previous)
        round_index = previous["round_index"] + 1
        used = previous["new_runs_used"] + len(old_decision.trials)
        center = old_decision.center_id
        tested = previous["tested_trial_keys"] + [t.trial_id for t in old_decision.trials]
        bounds = previous["bounds"]
    else:
        policy = policy or AdaptiveSearchPolicy()
        round_index, used, center, tested = 0, 0, None, []
        inherited = snapshot.search_extension_safety_limits or {}
        values = {**snapshot.plan.effective_values, **snapshot.selected_values}
        # Finite, recorded computational limits, not biological thresholds.
        bounds = {
            name: list(inherited.get(name, (values[name] / 8, values[name] * 8)))
            for name in FIT_PARAMETERS
        }
    definitions = {c.candidate_id: c for c in snapshot.current_stage.candidates}
    observations = []
    for candidate in snapshot.candidates:
        values = {
            **snapshot.plan.effective_values,
            **snapshot.selected_values,
            **definitions[candidate.candidate_id].values,
        }
        metrics = candidate.metrics or {}
        fit = study.normalized_candidate_subject_fit(snapshot, candidate) if metrics else {}
        observations.append(
            asdict(
                FitObservation(
                    candidate_id=candidate.candidate_id,
                    values={name: values[name] for name in FIT_PARAMETERS},
                    subject_fit=fit,
                    completed=candidate.status == "completed",
                    invalid_faces=metrics.get("invalid_face_count", -1),
                    converged=metrics.get("converged") is True,
                    review_approved=snapshot.visual_reviews.get(candidate.candidate_id),
                )
            )
        )
    return {
        "policy": asdict(policy),
        "bounds": bounds,
        "round_index": round_index,
        "new_runs_used": used,
        "previous_center_id": center,
        "tested_trial_keys": tested,
        "expected_subjects": [r["filename"] for r in manifest["inputs"]["subjects"]],
        "observations": observations,
    }


def bind_learned_seed(snapshot, center_id, destination):
    """Copy verified full-resolution learned geometry and the exact ordered field."""
    from diffeoforge import reference_calibration_study as study
    from diffeoforge.reference_holdout_study import _trained_model_artifacts
    from diffeoforge.reference_pca import load_reference_momenta

    candidate = next(c for c in snapshot.candidates if c.candidate_id == center_id)
    run = study.calibration_candidate_run_directory(candidate)
    inputs = load_reference_momenta(run)
    manifest = study._verify_manifest(snapshot.study_directory)
    subjects = manifest["inputs"]["subjects"]
    # Match validate_input_paths' platform path ordering, including mixed case.
    expected = tuple(r["filename"] for r in sorted(subjects, key=lambda r: Path(r["filename"])))
    if inputs.subject_labels != expected:
        raise ValueError("Seed momenta subject order differs from the pilot cohort")
    source_subjects = {
        Path(r["staged_path"]).name: r["geometry"]["sha256"]
        for r in inputs.run_report.manifest["inputs"]
        if r["role"] == "subject"
    }
    expected_hashes = {r["filename"]: r["sha256"] for r in subjects}
    if manifest.get("fit_search"):
        from diffeoforge.reference_fit_search import verify_search

        verify_search(snapshot.study_directory, manifest)
        working_hashes = {
            r["filename"]: r["sha256"] for r in manifest["fit_search"]["working_targets"]
        }
    else:
        working_hashes = expected_hashes
    if source_subjects not in (expected_hashes, working_hashes):
        raise ValueError("Seed subject geometry differs from the bound pilot cohort")
    template, template_hash, controls, controls_hash, *_ = _trained_model_artifacts(run)
    files = {}
    for role, path, digest in (
        ("template", template, template_hash),
        ("control_points", controls, controls_hash),
        ("momenta", inputs.momenta_path, str(inputs.momenta_record["sha256"])),
    ):
        target = destination / "adaptive-seed" / (role + path.suffix)
        study._copy_bound(path, target, digest)
        files[role] = {"copy": study._relative_path(destination, target), "sha256": digest}
    effective = inputs.run_report.manifest["effective_config"]
    return {
        "candidate_id": center_id,
        "source_run_directory": str(run),
        "source_manifest_sha256": sha256_file(run / "manifest.json"),
        "subject_labels": list(expected),
        "files": files,
        "optimization": copy.deepcopy(effective["optimization"]),
        "model": copy.deepcopy(effective["model"]),
        "deformation": copy.deepcopy(effective["model"]["deformation"]),
    }


def apply_seed(
    config, *, root, candidate_directory, seed, initialization, regenerate_controls=False
):
    def relative(role):
        path = root / seed["files"][role]["copy"]
        return os.path.relpath(path, candidate_directory).replace("\\", "/")

    config["input"]["template"] = relative("template")
    deformation = config["model"]["deformation"]
    for name in ("initial_control_points", "initial_momenta", "initial_momenta_subjects"):
        deformation.pop(name, None)
    if not regenerate_controls:
        deformation["initial_control_points"] = relative("control_points")
    if initialization == "warm":
        if regenerate_controls:
            raise ValueError("A regenerated control grid cannot reuse momenta")
        deformation["initial_momenta"] = relative("momenta")
        deformation["initial_momenta_subjects"] = seed["subject_labels"]


def configure_adaptive_trial(config, *, root, candidate_directory, manifest, candidate_id):
    continuation = (
        manifest.get("search_extension_source", {}).get("proposal", {}).get("continuation_context")
    )
    if continuation:
        additions = manifest["search_extension_source"]["proposal"]["candidates"]
        if candidate_id in {row["candidate_id"] for row in additions}:
            seed = manifest["adaptive_seed"]
            config["model"] = copy.deepcopy(seed["model"])
            if continuation.get("finer_surface"):
                config["model"]["attachment"]["kernel_width"] = continuation["values"][
                    "attachment_kernel_width"
                ]
                config["model"]["noise_std"] = continuation["values"]["noise_std"]
            apply_seed(
                config,
                root=root,
                candidate_directory=candidate_directory,
                seed=seed,
                initialization="warm",
            )
            config["optimization"] = copy.deepcopy(seed["optimization"])
            config["optimization"]["max_iterations"] = continuation["iterations"]
            validate_schema(config)
        return
    context = (
        manifest.get("search_extension_source", {}).get("proposal", {}).get("adaptive_context")
    )
    if not context:
        return
    trial = next((t for t in decide_context(context).trials if t.trial_id == candidate_id), None)
    if trial is None:
        return
    seed = manifest["adaptive_seed"]
    apply_seed(
        config,
        root=root,
        candidate_directory=candidate_directory,
        seed=seed,
        initialization=trial.initialization,
        regenerate_controls=trial.label == "denser-controls",
    )
    config["optimization"] = copy.deepcopy(seed["optimization"])
    config["optimization"]["max_iterations"] = trial.iterations
    if trial.label == "continue":
        # A tolerance-stopped run needs a tighter stopping criterion for this probe.
        config["optimization"]["convergence_tolerance"] = max(
            1e-10, float(seed["optimization"]["convergence_tolerance"]) / 10
        )
    validate_schema(config)


def run_adaptive_stage(runner, *, event_callback=None, policy=None):
    """Use the same cancellable controller and persist every automatic decision."""
    from diffeoforge import reference_calibration_study as study

    snapshot = runner.run_current_stage(event_callback=event_callback)
    while not runner._cancel_requested:
        if snapshot.current_stage is None or snapshot.current_stage.kind == "integration_accuracy":
            return snapshot
        if any(c.status != "completed" for c in snapshot.candidates):
            return snapshot  # Failed/interrupted work needs an explicit retry, never a spin loop.
        context = study_context(snapshot, policy=policy)
        decision = decide_context(context)
        event = study._append_event(
            snapshot.study_directory,
            "adaptive_search_decision",
            {
                "stage_id": snapshot.current_stage.stage_id,
                "center_id": decision.center_id,
                "stop_reason": decision.stop_reason,
                "rationale": decision.rationale,
                "regressions": dict(decision.regressions),
                "context_sha256": _canonical_hash(context),
                "new_runs_used": context["new_runs_used"],
                "round_index": context["round_index"],
            },
        )
        if event_callback:
            event_callback(event)
        if not decision.trials or runner._cancel_requested:
            return study.load_reference_calibration_study(snapshot.study_directory)
        destination = study.next_reference_calibration_search_extension_destination(
            snapshot.study_directory
        )
        snapshot = study.create_reference_calibration_search_extension_study(
            snapshot.study_directory,
            destination,
            safety_limits={n: tuple(b) for n, b in context["bounds"].items()},
            adaptive_context=context,
        )
        runner.study_directory = snapshot.study_directory
        if event_callback:
            event_callback(
                {
                    "event": "adaptive_search_extended",
                    "study_directory": str(snapshot.study_directory),
                    "round_index": context["round_index"] + 1,
                    "new_runs": len(decision.trials),
                    "maximum_new_runs": context["policy"]["maximum_new_runs"],
                }
            )
        if runner._cancel_requested:
            return snapshot
        snapshot = runner.run_current_stage(event_callback=event_callback)
    return snapshot
