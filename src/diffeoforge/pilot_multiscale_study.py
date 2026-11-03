"""Bound, finite full-target capture/detail studies; no approval or field splicing."""

from copy import deepcopy
from pathlib import Path

import numpy as np

from diffeoforge import reference_calibration_study as study
from diffeoforge import reference_guided_pilot as guided
from diffeoforge.config import load_config
from diffeoforge.mesh import sha256_file
from diffeoforge.pilot_multiscale import VERSION


def marker(record):
    return (record.get("guided", {}).get("strategy") or {}).get("common_multiscale")


def bound_snapshot(binding):
    root = Path(binding["directory"])
    if sha256_file(root / study.STUDY_MANIFEST) != binding["manifest_sha256"]:
        raise ValueError("The declared capture/detail family changed")
    return study.load_reference_calibration_study(root)


def binding(snapshot):
    return dict(
        directory=str(snapshot.study_directory),
        manifest_sha256=sha256_file(snapshot.study_directory / study.STUDY_MANIFEST),
    )


def family(snapshot):
    request = marker(snapshot.attachment_comparison)
    if not request:
        return None
    return bound_snapshot(request["family"]) if request["family"] else snapshot


def adopted_family(value):
    """An adopted detail protocol keeps the same prospectively declared model."""
    from diffeoforge.guided_feedback import verify_reference

    parent = verify_reference(value["protocol"]["reference"])
    request = marker(parent.attachment_comparison)
    if request and request["stage"] == "detail":
        return family(parent)
    return None


def request(snapshot, value, *, target, model=None, capture=None):
    """An explicit new hypothesis or another form on an already adopted one."""
    from diffeoforge.pilot_form_progress import verify_marker

    info = guided.record(snapshot)
    verify_marker(value, info["origin"], info["pilot_order"])
    if target not in info["pilot_order"]:
        raise ValueError("Capture/detail target is outside this pilot")
    if model is None and capture is None:
        from diffeoforge.pilot_common_capacity import demand
        from diffeoforge.pilot_multiscale import specification

        ref = value["protocol"]["reference"]
        from diffeoforge.guided_feedback import verify_reference

        parent = verify_reference(ref)
        c = next(c for c in parent.candidates if c.candidate_id == ref["candidate_id"])
        config = load_config(c.config_path)
        spec = specification(
            ref["values"],
            precision=config["runtime"]["precision"],
            tolerance=config["optimization"]["convergence_tolerance"],
            required_controls=max(demand(value).values()),
        )
        return dict(
            version=VERSION,
            stage="capture",
            target=target,
            family=None,
            support_source=binding(snapshot),
            accepted_marker=deepcopy(value),
            specification=spec,
            capture=None,
            approval_transferred=False,
        )
    base = family(capture) if capture else model
    original = marker(base.attachment_comparison)
    if not original or original["stage"] != "capture" or original["family"]:
        raise ValueError("A capture/detail family needs its original capture contract")
    if original["accepted_marker"]["reviews"] != value["reviews"]:
        raise ValueError("The retained individual approvals changed")
    return dict(
        version=VERSION,
        stage="detail" if capture else "capture",
        target=target,
        family=binding(base),
        support_source=original["support_source"],
        accepted_marker=deepcopy(original["accepted_marker"]),
        specification=deepcopy(original["specification"]),
        capture=binding(capture) if capture else None,
        approval_transferred=False,
    )


def configure_source(config, declaration):
    """Only a newly prepared singleton; never mutate a running contract."""
    from diffeoforge.reference_finite_accepted_guard import clear_runtime_markers
    from diffeoforge.reference_ordinary_guard import DECLARATION

    provenance = config["project"]["parameter_provenance"]
    for key in ("regional_fit", "regional_conditioning", "pilot_review", "surface_gather"):
        provenance.pop(key, None)
    clear_runtime_markers(config)
    provenance["finite_accepted_guard"] = dict(DECLARATION)
    spec = declaration["specification"]
    config["optimization"].update(
        method="lbfgs",
        freeze_template=True,
        freeze_control_points=True,
        max_iterations=120,
        convergence_tolerance=spec["tolerance"],
    )
    config["model"]["deformation"].update(timepoints=spec["timepoints"], use_rk2=spec["use_rk2"])
    config["runtime"]["precision"] = spec["precision"]


def stage_values(declaration):
    return next(
        s["values"]
        for s in declaration["specification"]["stages"]
        if s["name"] == declaration["stage"]
    )


def _capture_field(snapshot):
    """Computational checkpoint, deliberately independent of human inspection."""
    from diffeoforge.guided_refinement import load_field
    from diffeoforge.regional_evaluation import endpoint

    declaration = marker(snapshot.attachment_comparison)
    if not declaration or declaration["stage"] != "capture" or len(snapshot.candidates) != 1:
        raise ValueError("Detail requires the declared same-form capture")
    candidate = snapshot.candidates[0]
    subjects = (candidate.metrics or {}).get("attachment_comparison", {}).get("subjects", {})
    row = subjects.get(declaration["target"], {})
    quality = row.get("ordinary_quality") or {}
    if (
        candidate.status != "completed"
        or quality.get("passed") is not True
        or endpoint(candidate) is None
        or not row.get("repeats")
        or row.get("warnings")
        or not np.isfinite(row.get("diagonal", np.nan))
        or row["diagonal"] <= 0
        or any(
            not np.isfinite(r["p95"]) or r["p95"] > 0.15 * row["diagonal"] for r in row["repeats"]
        )
    ):
        raise ValueError("Capture checks did not pass; no detail stage or recovery was started")
    field = load_field(study.calibration_candidate_run_directory(candidate))
    if field.subject_labels != (declaration["target"],):
        raise ValueError("Capture coefficients belong to another form")
    return field


def bind(root, manifest, record):
    declaration = marker(record)
    if not declaration:
        return None
    from diffeoforge.pilot_multiscale import retained_support, source_supported_sites

    if declaration["family"]:
        base = bound_snapshot(declaration["family"])
        prior = base.attachment_comparison
        controls = prior["controls"]
        source = study._safe_study_path(base.study_directory, controls["copy"])
        path = root / "multiscale-controls.txt"
        study._copy_bound(source, path, controls["sha256"])
        support = deepcopy(prior["multiscale"]["support"])
    else:
        parent = bound_snapshot(declaration["support_source"])
        union, geometry, proof = retained_support(parent, declaration["accepted_marker"])
        if (
            proof["specification"] != declaration["specification"]
            or proof["template"]["sha256"] != manifest["inputs"]["template"]["sha256"]
        ):
            raise ValueError("New common support must retain the original template and model")
        points, recipe = source_supported_sites(union, geometry.vertices, geometry.triangles)
        path = root / "multiscale-controls.txt"
        np.savetxt(path, points, fmt="%.17g")
        support = dict(inputs=proof, sampling=recipe)
    if declaration["family"] and (
        study._verify_manifest(base.study_directory)["inputs"]["template"]["sha256"]
        != manifest["inputs"]["template"]["sha256"]
    ):
        raise ValueError("Common capture/detail template changed")
    details = dict(version=VERSION, support=support, initial_momenta=None)
    if declaration["capture"]:
        capture = bound_snapshot(declaration["capture"])
        old = study._verify_manifest(capture.study_directory)
        if (
            old["inputs"]["subjects"] != manifest["inputs"]["subjects"]
            or capture.attachment_comparison["controls"]["sha256"] != sha256_file(path)
            or marker(capture.attachment_comparison)["specification"]
            != declaration["specification"]
        ):
            raise ValueError("Detail needs the same original form, physics and control basis")
        field = _capture_field(capture)
        momentum = root / "multiscale-capture-momenta.txt"
        study._copy_bound(field.momenta_path, momentum, sha256_file(field.momenta_path))
        details["initial_momenta"] = dict(
            copy=momentum.name,
            sha256=sha256_file(momentum),
            source_run=str(field.run_directory),
            source_manifest_sha256=sha256_file(field.run_directory / "manifest.json"),
            source_sha256=sha256_file(field.momenta_path),
            optimizer_history_restored=False,
        )
    return dict(
        record,
        multiscale=details,
        controls=dict(
            copy=path.name,
            sha256=sha256_file(path),
            count=declaration["specification"]["controls"],
            spacing=stage_values(declaration)["initial_control_point_spacing"],
        ),
    )


def configure_candidate(config, root, record):
    declaration = marker(record)
    if not declaration:
        return
    configure_source(config, declaration)
    deformation = config["model"]["deformation"]
    initial = record["multiscale"]["initial_momenta"]
    if initial:
        deformation.update(
            initial_momenta=str(root / initial["copy"]),
            initial_momenta_subjects=[declaration["target"]],
        )
    from diffeoforge.reference_ordinary_guard import mark

    mark(config)


def verify(info, record, manifest, root):
    declaration = marker(record)
    if not declaration:
        return
    spec = declaration["specification"]
    from diffeoforge.pilot_multiscale import specification

    expected = specification(
        spec["baseline"],
        precision=spec["precision"],
        tolerance=spec["tolerance"],
        required_controls=spec["required_controls"],
    )
    if (
        declaration["version"] != VERSION
        or spec != expected
        or declaration["stage"] not in {"capture", "detail"}
        or declaration["target"] != info["target"]
        or info["phase"] != "validate"
        or info["goal"] != "common_multiscale"
        or record["iterations"] != 120
        or set(record["methods"].values()) != {"varifold"}
        or declaration["approval_transferred"] is not False
        or record["controls"]["count"] != spec["controls"]
        or record["controls"]["spacing"]
        != stage_values(declaration)["initial_control_point_spacing"]
        or manifest["plan"]["baseline_effective_values"] != stage_values(declaration)
        or any(k in record for k in ("refinement", "regional_objective", "joint_initialization"))
        or declaration["accepted_marker"]["reviews"] != info["strategy"]["form_progress"]["reviews"]
    ):
        raise ValueError("Finite common capture/detail contract changed")
    for key in ("support_source", "family", "capture"):
        if declaration.get(key) and Path(declaration[key]["directory"]).resolve() == root.resolve():
            raise ValueError("A capture/detail dependency cannot reference itself")
    parent = bound_snapshot(declaration["support_source"])
    if (
        guided.record(parent)["origin"] != info["origin"]
        or guided.record(parent)["pilot_order"] != info["pilot_order"]
    ):
        raise ValueError("Capture/detail support belongs to another cohort")
    points = np.loadtxt(study._safe_study_path(root, record["controls"]["copy"]), ndmin=2)
    if points.shape != (spec["controls"], 3) or not np.isfinite(points).all():
        raise ValueError("Common control support changed")
    config = load_config(root / manifest["source_config"]["copy"])
    if (
        config["optimization"]["method"] != "lbfgs"
        or not all(config["optimization"][k] for k in ("freeze_template", "freeze_control_points"))
        or config["optimization"]["convergence_tolerance"] != spec["tolerance"]
        or config["runtime"]["precision"] != spec["precision"]
        or any(config["model"]["deformation"][k] != spec[k] for k in ("timepoints", "use_rk2"))
    ):
        raise ValueError("Capture/detail numerical contract changed")
    details = record["multiscale"]
    if declaration["family"]:
        base = bound_snapshot(declaration["family"])
        if (
            base.attachment_comparison["controls"]["sha256"] != record["controls"]["sha256"]
            or base.attachment_comparison["multiscale"]["support"] != details["support"]
        ):
            raise ValueError("Capture/detail family support changed")
    support = details["support"]["inputs"]
    if (
        support["specification"] != spec
        or sha256_file(Path(support["template"]["path"])) != support["template"]["sha256"]
        or support["template"]["sha256"] != manifest["inputs"]["template"]["sha256"]
    ):
        raise ValueError("Original source support binding changed")
    prefix = support["prefix"]
    if (
        sha256_file(Path(prefix["path"])) != prefix["sha256"]
        or sha256_file(Path(prefix["study_directory"]) / study.STUDY_MANIFEST)
        != prefix["study_manifest_sha256"]
    ):
        raise ValueError("Original control-site provenance changed")
    for block in support["blocks"]:
        if (
            sha256_file(Path(block["run"]) / "manifest.json") != block["manifest_sha256"]
            or sha256_file(Path(block["control_points"])) != block["control_points_sha256"]
        ):
            raise ValueError("Retained individual control-site evidence changed")
    initial = details["initial_momenta"]
    if declaration["stage"] == "capture":
        if declaration["capture"] or initial:
            raise ValueError("Each common capture must start from native zero coefficients")
    else:
        capture = bound_snapshot(declaration["capture"])
        field = _capture_field(capture)
        old = study._verify_manifest(capture.study_directory)
        if (
            old["inputs"]["subjects"] != manifest["inputs"]["subjects"]
            or old["inputs"]["template"]["sha256"] != manifest["inputs"]["template"]["sha256"]
            or field.subject_labels != (info["target"],)
            or initial["optimizer_history_restored"] is not False
            or sha256_file(study._safe_study_path(root, initial["copy"])) != initial["sha256"]
            or sha256_file(field.momenta_path) != initial["sha256"]
            or sha256_file(field.run_directory / "manifest.json")
            != initial["source_manifest_sha256"]
        ):
            raise ValueError("Same-form complete capture checkpoint changed")


def apply(plan, snapshot, value, *, model=None):
    """Prepare only. The normal Run action owns both native stages and cancellation."""
    declaration = request(snapshot, value, target=plan["target"], model=model)
    state = plan["strategy"]
    for key in (
        "baseline",
        "anchor",
        "control_basis",
        "common_model_step",
        "common_diagnosis_test",
        "common_capacity_request",
        "common_candidate_step",
        "common_basis_step",
        "regional_recipe",
        "regional_continuation",
        "optimization",
        "shared_model_check",
        "control_capacity_request",
        "failure_parent_recovery",
    ):
        state.pop(key, None)
    state["common_multiscale"] = declaration
    if plan.get("history"):
        plan["history"][-1] = dict(plan["history"][-1], outcome="common_multiscale_capture")
    plan.update(
        phase="validate",
        goal="common_multiscale",
        methods=("varifold",),
        approved=[],
        values=stage_values(declaration),
    )
    return plan


def _detail_plan(snapshot, cancelled):
    """Read each bound predecessor graph once; leave the scope before writes."""
    declaration = marker(snapshot.attachment_comparison)
    if not declaration or declaration["stage"] != "capture":
        raise ValueError("Select this family's completed capture before preparing detail")
    if cancelled():
        return snapshot
    _capture_field(snapshot)
    if cancelled():
        return snapshot
    pointer = snapshot.study_directory / "fit-search-latest.json"
    if pointer.exists():
        saved = study._read_json(pointer, "declared detail successor")
        result = bound_snapshot(
            dict(directory=saved["directory"], manifest_sha256=saved["manifest_sha256"])
        )
        child = marker(result.attachment_comparison)
        if not child or child["capture"] != binding(snapshot):
            raise ValueError("Existing next stage is not this capture's declared detail")
    else:
        info = guided.record(snapshot)
        state = deepcopy(info["strategy"])
        state["previous"] = binding(snapshot)
        state["common_multiscale"] = request(
            snapshot, state["form_progress"], target=info["target"], capture=snapshot
        )
        source, _ = guided._origin(snapshot.study_directory)
        return dict(
            source=source,
            previous=snapshot,
            phase="validate",
            target=info["target"],
            methods=("varifold",),
            values=stage_values(state["common_multiscale"]),
            approved=[],
            history=[
                *info["history"],
                dict(binding(snapshot), outcome="common_multiscale_capture_complete"),
            ],
            spent=info["screen_trials_spent"],
            goal="common_multiscale",
            strategy=state,
            destination_parent=snapshot.study_directory.parent,
        )
    return result


def prepare_detail(snapshot, *, cancelled=lambda: False):
    """Prepare/reopen the declared detail without dispatch or a suitability claim."""
    with study.calibration_verification_scope():
        planned = _detail_plan(snapshot, cancelled)
    if not isinstance(planned, dict):
        return planned
    if cancelled():
        return snapshot
    return guided._batch(**planned)


def followup(runner, snapshot, event_callback):
    """At most one detail stage. Never restart a completed native capture."""
    declaration = marker(snapshot.attachment_comparison)
    if not declaration or declaration["stage"] != "capture" or runner._cancel_requested:
        return snapshot
    if snapshot.candidates[0].status != "completed":
        return snapshot
    result = prepare_detail(snapshot, cancelled=lambda: runner._cancel_requested)
    runner.study_directory = result.study_directory
    if runner._cancel_requested:
        return result
    if event_callback:
        event_callback(dict(event="attachment_comparison_started", snapshot=result))
    # The enclosing capture lock retains its own path; the detail dispatch owns
    # a separate lock. Neither stage can be launched twice by re-entering Run.
    runner._method_comparison_dispatch = False
    return runner.run_current_stage(event_callback=event_callback)


def annotate_effort(metrics, manifest):
    declaration = marker(manifest.get("attachment_comparison", {}))
    if not declaration:
        return
    metrics["objective_stages"] = dict(
        version=VERSION,
        stage=declaration["stage"],
        stage_number=1 if declaration["stage"] == "capture" else 2,
        stages_declared=2,
        maximum_iterations_each=120,
        maximum_total_accepted_steps=240,
        optimizer_history_restored=False,
        unchanged_objective_continuation=False,
    )
    if declaration["stage"] == "detail":
        capture = bound_snapshot(declaration["capture"])
        old = capture.candidates[0].metrics or {}
        metrics["objective_stages"].update(
            capture_iterations=old.get("final_iteration"),
            capture_runtime_seconds=old.get("runtime_seconds"),
            capture_pipeline_wall_seconds=old.get("pipeline_wall_seconds"),
        )
