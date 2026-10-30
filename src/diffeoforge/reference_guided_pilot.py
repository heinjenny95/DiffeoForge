"""Small, user-gated method/parameter batches followed by a joint pilot check.

Every transition prepares immutable studies only. Only the ordinary explicit Run
action dispatches an optimizer. Legacy comparison studies retain their protocol.
"""

from __future__ import annotations

import copy
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from diffeoforge.config import load_config
from diffeoforge.mesh import sha256_file
from diffeoforge.reference_calibration import CalibrationCandidate

VERSION = "guided-pilot-v2"
ADAPTIVE_VERSION = "guided-pilot-v3"
MAX_SCREEN_TRIALS = 12


def screening_limit(plan):
    return max(MAX_SCREEN_TRIALS, plan.pilot_subject_count + 2)


def enabled(config):
    from diffeoforge.reference_attachment_comparison import selection

    return selection(config).get("workflow") in {VERSION, ADAPTIVE_VERSION}


def record(snapshot):
    return (snapshot.attachment_comparison or {}).get("guided")


def coverage_step(snapshot, identifier):
    """Describe accepted settings' remaining checks without preparing work."""
    info = record(snapshot)
    values = next(c.values for c in snapshot.current_stage.candidates
                  if c.candidate_id == identifier)
    method = snapshot.attachment_comparison["methods"][identifier]
    covered = {r["filename"] for r in info["approved"]
               if r["method"] == method and r["values"] == values}
    covered.add(info["target"])
    remaining = [n for n in info["pilot_order"] if n not in covered]
    return dict(remaining=remaining, method=method, values=values,
                extra_trials=max(0, info["screen_trials_spent"] + len(remaining)
                                 - info["screen_trial_limit"]))


def verify_coverage_extension(info, source_manifest, methods, values):
    """Verify one explicit allowance reserved for unchanged coverage checks."""
    from diffeoforge import reference_calibration_study as study

    base = max(MAX_SCREEN_TRIALS, len(source_manifest["inputs"]["subjects"]) + 2)
    extension = info.get("coverage_extension")
    if not extension:
        return info["screen_trial_limit"] == base
    parent_root = Path(extension["directory"])
    if sha256_file(parent_root / study.STUDY_MANIFEST) != extension["manifest_sha256"]:
        raise ValueError("Coverage allowance source changed")
    parent = study.load_reference_calibration_study(parent_root)
    previous = record(parent)
    row = _approved_record(parent, extension["candidate_id"])
    step = coverage_step(parent, extension["candidate_id"])
    return bool(
        previous and not previous.get("coverage_extension")
        and previous["origin"] == info["origin"]
        and step["extra_trials"] > 0
        and extension["added_trials"] == step["extra_trials"]
        and info["screen_trial_limit"] == base + step["extra_trials"]
        and set(methods.values()) == {row["method"]}
        and values == row["values"] and row in info["approved"]
        and info["phase"] in {"validate", "joint"}
        and (info["phase"] == "joint" or info["target"] in step["remaining"])
    )


def _pilot_order(plan):
    subjects = plan.selected_pilot_subjects
    representative = next(
        (s.filename for s in subjects if "medoid" in s.selection_role), subjects[0].filename
    )
    return [representative, *(s.filename for s in subjects if s.filename != representative)]


def upgrade(directory, *, cache_directory=None):
    """Explicitly prepare a separately bound guided successor of a legacy pilot."""
    from diffeoforge import reference_calibration_study as study
    from diffeoforge.config import validate_input_paths
    from diffeoforge.pilot_design import coverage_suggestion
    from diffeoforge.reference_calibration import build_reference_calibration_plan
    from diffeoforge.reference_recommendation import recommend_reference_parameters
    from diffeoforge.reference_sequential_fit import _fingerprint

    old = study.load_reference_calibration_study(directory)
    if (
        record(old)
        or old.selected_candidate_ids
        or any(c.status in {"running", "orphaned"} for c in old.candidates)
        or (old.study_directory / "fit-search-latest.json").exists()
    ):
        raise ValueError("Reopen the current idle, unselected pilot before preparing a successor")
    manifest = study._verify_manifest(old.study_directory)
    config = copy.deepcopy(load_config(old.study_directory / manifest["source_config"]["copy"]))
    cohort = manifest["inputs"]["full_cohort"]
    config["input"].update(
        directory=cohort["directory"],
        template=cohort["template"],
        subject_pattern=cohort["subject_pattern"],
    )
    config["project"]["parameter_provenance"]["attachment_selection"] = dict(
        version="attachment-comparison-v1", mode="auto", state="pending", workflow=ADAPTIVE_VERSION
    )
    source_path = old.study_directory.parent / ("guided-source-" + uuid4().hex[:12] + ".yaml")
    inputs = validate_input_paths(config, source_path)
    if sha256_file(inputs.template) != old.plan.template_sha256:
        raise ValueError("Original template changed; prepare a new project explicitly")
    recommendation = recommend_reference_parameters(
        (inputs.template, *inputs.subjects),
        alignment_basis="declared_gpa",
        surface_detail_intent="balanced",
        deformation_scale_intent="balanced",
        cache_directory=cache_directory,
    )
    suggestion = coverage_suggestion(
        recommendation,
        required=old.plan.required_subject_filenames,
        declarations=old.plan.pilot_subject_declarations,
    )
    suggestion["legacy_source_manifest_sha256"] = sha256_file(
        old.study_directory / study.STUDY_MANIFEST
    )
    plan = build_reference_calibration_plan(
        recommendation,
        coordinate_unit=old.plan.coordinate_unit,
        requested_pilot_subject_count=suggestion["recommended_count"],
        required_subject_filenames=old.plan.required_subject_filenames,
        pilot_subject_declarations=old.plan.pilot_subject_declarations,
    )
    plan = _fingerprint(replace(plan, design_suggestion=suggestion))
    config["project"]["parameter_provenance"]["recommendation"] = dict(
        recommendation.provenance, calibration_plan=plan.provenance
    )
    study._write_yaml(source_path, config, overwrite=False)
    origin = study.create_reference_calibration_study(
        source_path, source_path.with_suffix(""), plan_override=plan
    )
    child = prepare(origin.study_directory)
    _pointer(origin.study_directory, child.study_directory)
    _pointer(old.study_directory, origin.study_directory)
    return child


def _origin(directory):
    from diffeoforge import reference_calibration_study as study

    snapshot = study.load_reference_calibration_study(directory)
    info = record(snapshot)
    root = Path(info["origin"]) if info else snapshot.study_directory
    return study.load_reference_calibration_study(root), info


def prepare(directory):
    source, _ = _origin(directory)
    from diffeoforge import reference_calibration_study as study
    from diffeoforge.reference_attachment_comparison import pending

    manifest = study._verify_manifest(source.study_directory)
    config = load_config(source.study_directory / manifest["source_config"]["copy"])
    if (
        source.study_directory != Path(directory).resolve()
        or not enabled(config)
        or not pending(config)
        or source.selected_candidate_ids
        or source.attachment_comparison
        or any(c.attempts for c in source.candidates)
        or (source.study_directory / "fit-search-latest.json").exists()
    ):
        raise ValueError("A guided comparison needs a new, unstarted pilot; reopen existing work")
    return _batch(
        source,
        None,
        phase="screen",
        target=_pilot_order(source.plan)[0],
        methods=("current", "varifold"),
        values=source.plan.effective_values,
        approved=(),
        history=(),
        spent=0,
        strategy={} if config["project"]["parameter_provenance"]["attachment_selection"].get(
            "workflow") == ADAPTIVE_VERSION else None,
    )


def _batch(
    source, previous, *, phase, target, methods, values, approved, history, spent, goal=None,
    feedback=None, coverage_extension=None, strategy=None,
):
    from diffeoforge import reference_calibration_study as study
    from diffeoforge.guided_joint_initialization import references as joint_references
    from diffeoforge.reference_attachment_comparison import ITERATIONS
    from diffeoforge.reference_attachment_comparison import VERSION as METRIC_VERSION
    from diffeoforge.reference_fit_search import control_grid
    from diffeoforge.reference_sequential_fit import _fingerprint
    from diffeoforge.surface_io import load_surface_mesh

    manifest = study._verify_manifest(source.study_directory)
    config = copy.deepcopy(load_config(source.study_directory / manifest["source_config"]["copy"]))
    cohort_method = config["optimization"]["method"]
    iterations = (max(ITERATIONS, previous.attachment_comparison["iterations"])
                  if strategy is not None and previous else ITERATIONS)
    if goal in {"shared_check", "next_form", "form_model_check"}:
        iterations = ITERATIONS
    optimization = (strategy or {}).get("optimization")
    if optimization:
        from diffeoforge.guided_feedback import verify_reference

        parent = verify_reference(optimization["reference"])
        retained = next(c for c in parent.candidates
                        if c.candidate_id == optimization["reference"]["candidate_id"])
        config = copy.deepcopy(load_config(retained.config_path))
        iterations = optimization["iterations"]
    if (strategy or {}).get("form_progress") and not optimization:
        from diffeoforge.pilot_form_progress import configure

        configure(config, strategy["form_progress"], cohort_method)
    if ((strategy or {}).get("regional_recipe")
            and not (strategy or {}).get("regional_continuation")):
        from diffeoforge.regional_pilot import configure_numerics

        configure_numerics(config)
        from diffeoforge.pilot_iteration_effort import regional_allowance

        effort = regional_allowance(strategy["regional_recipe"], feedback["regions"], iterations)
        iterations = effort["maximum_iterations"]
    cohort = manifest["inputs"]["full_cohort"]
    config["input"].update(
        directory=cohort["directory"],
        template=cohort["template"],
        subject_pattern=cohort["subject_pattern"],
    )
    config["project"]["parameter_provenance"]["attachment_selection"].update(state="comparing")
    if strategy is not None:
        config["project"]["parameter_provenance"]["attachment_selection"]["workflow"] = (
            ADAPTIVE_VERSION)
    for key in ("initial_momenta", "initial_momenta_subjects", "initial_control_points"):
        config["model"]["deformation"].pop(key, None)
    if ((strategy or {}).get("shared_model_check")
            and not strategy.get("regional_recipe")
            and not strategy.get("regional_continuation")):
        from diffeoforge.guided_shared_check import configure

        configure(config, strategy["shared_model_check"], cohort_method)
    if (strategy or {}).get("regional_continuation"):
        # The transitional source config still describes the full input cohort;
        # only its selected singleton receives the copied regional objective in
        # prepare_controls/configure. Never expose old specimen-specific terms
        # as a shared cohort objective during initial source-path validation.
        provenance = config["project"]["parameter_provenance"]
        provenance.pop("regional_fit", None)
        from diffeoforge.reference_finite_accepted_guard import clear_runtime_markers

        clear_runtime_markers(config)
        config["optimization"]["method"] = cohort_method
    template = load_surface_mesh(source.study_directory / manifest["inputs"]["template"]["copy"])
    _, spacing = control_grid(template.metadata.bounds)
    center = dict(values)
    refinement = (strategy or {}).get("baseline") if phase == "refine" else None
    if not refinement and not (strategy or {}).get("control_basis"):
        center["initial_control_point_spacing"] = spacing
    selected = (
        source.plan.selected_pilot_subjects
        if phase == "joint"
        else tuple(s for s in source.plan.selected_pilot_subjects if s.filename == target)
    )
    if not selected or (phase != "joint" and len(selected) != 1):
        raise ValueError("A screening batch must bind exactly one independent pilot target")
    methods = tuple(methods)
    if not methods or not set(methods) <= {"current", "varifold"}:
        raise ValueError("Unknown matching method")
    limit = (screening_limit(source.plan) + (
        coverage_extension["added_trials"] if coverage_extension else 0)
        if strategy is None else None)
    if limit is not None and spent + len(methods) > limit and phase != "joint":
        raise ValueError(
            f"The {limit}-trial screening budget is exhausted. Revisit inputs/template "
            "or explicitly prepare a new pilot; all earlier results remain saved."
        )
    candidates = tuple(
        CalibrationCandidate(
            "guided-" + method,
            method.title() + (" · joint confirmation" if phase == "joint" else
                              " · protected local fit" if goal == "regional" else
                              " · atlas-model check" if goal == "shared_check" else ""),
            tuple(sorted(center.items())),
            "One bounded original-surface trial; explicit visual review",
        )
        for method in methods
    )
    stages = (
        replace(
            source.plan.stages[0],
            candidates=candidates,
            title="Joint pilot confirmation" if phase == "joint" else "Compare matching methods",
        ),
        *tuple(replace(s, candidates=(s.candidates[0],)) for s in source.plan.stages[1:]),
    )
    names = {s.filename for s in selected}
    plan = _fingerprint(
        replace(
            source.plan,
            stages=stages,
            selected_pilot_subjects=selected,
            requested_pilot_subject_count=len(selected),
            pilot_subject_declarations=tuple(
                d for d in source.plan.pilot_subject_declarations if d.filename in names
            ),
            required_subject_filenames=tuple(sorted(names)),
            version="0.5"
            if any(d.filename in names for d in source.plan.pilot_subject_declarations)
            else "0.3",
            execution_scope="joint_fit_confirmation"
            if phase == "joint"
            else "single_specimen_probe",
            baseline_effective_values=tuple(sorted(center.items())),
            baseline_parameter_ratios=tuple(
                sorted((k, v / manifest["template_diagonal"]) for k, v in center.items())
            ),
        )
    )
    config["project"]["parameter_provenance"]["recommendation"]["calibration_plan"] = (
        plan.provenance
    )
    destination = source.study_directory.parent / ("guided-pilot-" + uuid4().hex[:12])
    config_path = destination.with_suffix(".yaml")
    study._write_yaml(config_path, config, overwrite=False)
    result = study.create_reference_calibration_study(
        config_path,
        destination,
        plan_override=plan,
        pilot_max_iterations=iterations,
        attachment_comparison=dict(
            version=METRIC_VERSION,
            methods={c.candidate_id: m for c, m in zip(candidates, methods, strict=True)},
            source_directory=str(source.study_directory),
            source_manifest_sha256=sha256_file(source.study_directory / study.STUDY_MANIFEST),
            iterations=iterations,
            samples_per_repeat=8192,
            repeats=2,
            region_grid=4,
            shrink_warning_fraction=0.1,
            confirmation_freeze_settings={
                k: config["optimization"][k] for k in ("freeze_template", "freeze_control_points")
            },
            scope="All original pilot targets" if phase == "joint" else "One original target only",
            **({"joint_initialization": dict(version="accepted-singletons-v1",
                references=joint_references(approved))}
               if phase == "joint" and strategy is not None else {}),
            **({"refinement": dict(version="guided-refinement-v1", reference=refinement)}
               if refinement else {}),
            guided=dict(
                version=ADAPTIVE_VERSION if strategy is not None else VERSION,
                origin=str(source.study_directory),
                phase=phase,
                target=target,
                pilot_order=_pilot_order(source.plan),
                approved=list(approved),
                history=list(history),
                goal=goal,
                feedback=feedback,
                screen_trials_spent=spent + (len(methods) if phase != "joint" else 0),
                screen_trial_limit=limit,
                selected_method=methods[0] if len(methods) == 1 else None,
                **({"coverage_extension": coverage_extension} if coverage_extension else {}),
                **({"strategy": strategy} if strategy is not None else {}),
            ),
        ),
    )
    if previous is not None:
        _pointer(previous.study_directory, result.study_directory)
    return result


def _pointer(origin, destination):
    from diffeoforge import reference_calibration_study as study

    study._write_json(
        origin / "fit-search-latest.json",
        dict(
            directory=str(destination),
            manifest_sha256=sha256_file(destination / study.STUDY_MANIFEST),
        ),
        overwrite=False,
    )


def _approved_record(snapshot, identifier):
    from diffeoforge import reference_calibration_study as study

    candidate = next(c for c in snapshot.candidates if c.candidate_id == identifier)
    if candidate.status != "completed" or snapshot.visual_reviews.get(identifier) is not True:
        raise ValueError("Inspect and explicitly approve the complete fit first")
    metrics = candidate.metrics or {}
    if (
        type(metrics.get("invalid_face_count")) is not int
        or metrics["invalid_face_count"] != 0
        or metrics.get("completed") is not True
        or metrics.get("subject_reconstruction_count") != snapshot.plan.pilot_subject_count
    ):
        raise ValueError("A complete, valid reconstruction is required")
    return dict(
        directory=str(snapshot.study_directory),
        candidate_id=identifier,
        manifest_sha256=sha256_file(snapshot.study_directory / study.STUDY_MANIFEST),
        binding=study._candidate_review_binding(candidate),
        filename=snapshot.plan.selected_pilot_subjects[0].filename,
        method=snapshot.attachment_comparison["methods"][identifier],
        values=next(
            c.values for c in snapshot.current_stage.candidates if c.candidate_id == identifier
        ),
    )


def verify_approvals(rows):
    from diffeoforge import reference_calibration_study as study

    with study.calibration_verification_scope():
        for row in rows:
            root = Path(row["directory"])
            if sha256_file(root / study.STUDY_MANIFEST) != row["manifest_sha256"]:
                raise ValueError("Guided pilot source manifest changed")
            snapshot = study.load_reference_calibration_study(root)
            actual = _approved_record(snapshot, row["candidate_id"])
            if actual != row:
                raise ValueError("An earlier visual approval, run or settings binding changed")


def next_action(directory, action, candidate_id=None, *, goal=None):
    """Serialize preparation; an abandoned lock needs explicit recovery."""
    lock = Path(directory) / "guided-transition-active.lock"
    try:
        lock.mkdir()
    except FileExistsError as error:
        raise ValueError("A guided transition is active or needs explicit recovery") from error
    try:
        return _next_action(directory, action, candidate_id, goal=goal)
    finally:
        lock.rmdir()


def _next_action(directory, action, candidate_id=None, *, goal=None):
    """Prepare one next batch; never execute it or choose an anatomical winner."""
    from diffeoforge import reference_calibration_study as study

    snapshot = study.load_reference_calibration_study(directory)
    info = record(snapshot)
    if info is None or snapshot.current_stage.order != 1:
        raise ValueError("This is not an active guided comparison")
    if (snapshot.study_directory / "fit-search-latest.json").exists():
        raise ValueError("A newer prepared batch exists; reopen the current pilot")
    if any(c.status not in {"completed", "failed", "interrupted"} for c in snapshot.candidates):
        raise ValueError("Complete or resolve the current batch before preparing more work")
    if action == "finish_joint":
        return finish_joint(snapshot, candidate_id)
    if action.startswith("adaptive_") or info["version"] == ADAPTIVE_VERSION:
        from diffeoforge.guided_strategy import transition

        return transition(snapshot, action.removeprefix("adaptive_"), candidate_id, goal=goal)
    if info.get("coverage_extension") and action not in {"choose", "approve"}:
        raise ValueError(
            "The extra allowance is reserved for unchanged coverage checks. "
            "Revisit inputs/template if this configuration fails; earlier fits remain saved.")
    source, _ = _origin(directory)
    approved = list(info["approved"])
    verify_approvals(approved)
    values = snapshot.plan.effective_values
    methods = tuple(snapshot.attachment_comparison["methods"].values())
    phase, target = info["phase"], info["target"]
    feedback = None
    coverage_extension = info.get("coverage_extension")
    history = [
        *info["history"],
        dict(
            directory=str(snapshot.study_directory),
            manifest_sha256=sha256_file(snapshot.study_directory / study.STUDY_MANIFEST),
            outcome=action,
        ),
    ]
    if action == "recover":
        from diffeoforge.pilot_recovery import capture, proposal

        proposed = proposal(snapshot, candidate_id, goal)
        if not proposed["available"]:
            raise ValueError(
                "Screening budget exhausted. Revisit alignment, mesh quality or template; "
                "all results remain saved. No extra trials have been prepared.")
        goal, target = proposed["goal"], proposed["target"]
        feedback = capture(snapshot, candidate_id, target)
        methods = (proposed["method"],)
        if goal == "other_method":
            approved = [r for r in approved if r["method"] == methods[0] and r["values"] == values]
        else:
            values = adjusted_values(values, goal)
            approved = []
        phase = "validate"
    elif action == "both_good":
        if len(methods) != 2:
            raise ValueError("Both-good requires two methods")
        approved.extend(_approved_record(snapshot, c.candidate_id) for c in snapshot.candidates)
        covered = {r["filename"] for r in approved if r["values"] == values}
        target = next((n for n in info["pilot_order"] if n not in covered), None)
        if target is None:
            raise ValueError(
                "Both methods remain visually acceptable across the pilot. "
                "Choose an approved method explicitly; runtime is available as context."
            )
        reserved = len(info["pilot_order"]) - len(covered) - 1
        if info["screen_trials_spent"] + 2 + max(0, reserved) > info["screen_trial_limit"]:
            raise ValueError(
                "Another method pair would consume the remaining cross-check "
                "budget. Choose an approved method or prepare a new pilot explicitly."
            )
        phase = "screen"
    elif action == "both_bad":
        if len(methods) != 2 or any(
            snapshot.visual_reviews.get(c.candidate_id) is not False for c in snapshot.candidates
        ):
            raise ValueError("Record both fits as unfit before a shared-cause follow-up")
        if goal not in {"detail", "motion", "weight"}:
            raise ValueError(
                "Check alignment, mesh quality and template, then choose one "
                "targeted change: detail, motion or weight"
            )
        values = adjusted_values(values, goal)
        approved = []  # New settings require fresh coverage; prior results stay in history.
    elif action == "adjust":
        if goal not in {"detail", "motion", "weight"}:
            raise ValueError("Choose the observed mismatch before adjusting a parameter")
        values = adjusted_values(values, goal)
        approved = []
    elif action in {"choose", "approve", "extend_coverage"}:
        row = _approved_record(snapshot, candidate_id)
        step = coverage_step(snapshot, candidate_id)
        if action == "extend_coverage":
            if coverage_extension or step["extra_trials"] <= 0:
                raise ValueError("No additional coverage allowance is needed or available")
            coverage_extension = dict(
                directory=str(snapshot.study_directory),
                manifest_sha256=sha256_file(snapshot.study_directory / study.STUDY_MANIFEST),
                candidate_id=candidate_id, added_trials=step["extra_trials"],
            )
        elif step["extra_trials"]:
            raise ValueError(
                f"Coverage needs {step['extra_trials']} additional trial(s). "
                "Use the explicit coverage allowance; no new fit has started.")
        approved.append(row)
        values, methods = row["values"], (row["method"],)
        approved = [r for r in approved if r["method"] == methods[0] and r["values"] == values]
        covered = {r["filename"] for r in approved}
        target = next((n for n in info["pilot_order"] if n not in covered), None)
        phase = "validate" if target else "joint"
    else:
        raise ValueError("Unknown guided-pilot action")
    result = _batch(
        source,
        snapshot,
        phase=phase,
        target=target,
        methods=methods,
        values=values,
        approved=approved,
        history=history,
        spent=info["screen_trials_spent"],
        goal=goal,
        feedback=feedback,
        coverage_extension=coverage_extension,
    )
    study._append_event(
        snapshot.study_directory,
        "guided_pilot_decision",
        dict(
            action=action,
            candidate_id=candidate_id,
            goal=goal,
            next_directory=str(result.study_directory),
            next_manifest_sha256=sha256_file(result.study_directory / study.STUDY_MANIFEST),
            anatomical_approval_created=False,
            optimizer_started=False,
        ),
    )
    return result


def adjusted_values(values, goal, *, conservative=False, step=0):
    values = dict(values)
    parameter, factor = {
        "detail": ("attachment_kernel_width", 0.5),
        "motion": ("deformation_kernel_width", 2.0),
        "weight": ("noise_std", 0.5),
        "local_motion": ("deformation_kernel_width", 0.5),
        "smooth": ("noise_std", 2.0),
        "density": ("initial_control_point_spacing", 0.8),
    }[goal]
    if conservative and goal != "density":
        # SAME needs a larger contrast, not a sequence tending back to no change.
        # The first test stays gentle; successive tests are meaningfully separated.
        factor = (.9 * (.7 ** step)) if factor < 1 else (1.1 / (.7 ** step))
    values[parameter] *= factor
    return values


def finish_joint(snapshot, identifier):
    """Reuse exactly the reviewed joint model for final numerical qualification."""
    from diffeoforge import reference_calibration_study as study
    from diffeoforge.reference_stage_retention import keep_previous_fit, register_previous_fit

    info = record(snapshot)
    if info["phase"] != "joint":
        raise ValueError("A complete joint pilot check is required")
    verify_approvals(info["approved"])
    _approved_record(snapshot, identifier)
    if study.iteration_limit_selection_available(snapshot, identifier):
        result, _ = study.record_reference_calibration_iteration_limit_selection(
            snapshot.study_directory, selected_candidate_id=identifier
        )
    else:
        result, _ = study.record_reference_calibration_stage_review(
            snapshot.study_directory,
            selected_candidate_id=identifier,
            visual_approvals=snapshot.visual_reviews,
        )
    # These transitions retain the identical approved joint reconstruction and
    # its bound review. They do not grant QC to a new reconstruction or run grids.
    for _ in range(2):
        result = keep_previous_fit(result.study_directory)
    if result.current_stage.order != 4:
        raise ValueError("Joint model did not reach numerical qualification")
    return register_previous_fit(result, for_qualification=True)
