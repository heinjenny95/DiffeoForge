"""Carry accepted single-form control demand into a separate common-basis test."""
from copy import deepcopy
from functools import wraps

VERSION = "accepted-control-demand-v1"


def _scoped(function):
    @wraps(function)
    def read(*args, **kwargs):
        from diffeoforge.reference_calibration_study import calibration_verification_scope

        with calibration_verification_scope():
            return function(*args, **kwargs)
    return read


@_scoped
def count(reference, *, seen=None):
    """Count a complete composed field, not only its last local residual."""
    from diffeoforge.guided_feedback import verify_reference

    seen = set() if seen is None else seen
    key = reference["directory"], reference["candidate_id"]
    if key in seen:
        raise ValueError("Cyclic accepted control-demand history")
    seen.add(key)
    parent = verify_reference(reference)
    record = parent.attachment_comparison
    total = record["controls"]["count"]
    refinement = record.get("refinement") or {}
    if refinement.get("initialization") == "residual":
        total += count(refinement["reference"], seen=seen)
    elif record.get("regional_objective") and refinement.get("initialization") == "learned":
        # A continuation refines the last field while retaining its prefix; it
        # does not append that field for every batch of extra iterations.
        ref = refinement["reference"]
        previous = verify_reference(ref)
        total += count(ref, seen=seen) - previous.attachment_comparison["controls"]["count"]
    return total


@_scoped
def demand(value):
    from diffeoforge import reference_guided_pilot as guided
    from diffeoforge.guided_feedback import verify_reference

    base = verify_reference(value["protocol"]["reference"])
    result = {}
    for row in value["reviews"]:
        ref = dict(row)
        ref["target"] = ref.pop("filename")
        parent = verify_reference(ref)
        if (parent.visual_reviews.get(ref["candidate_id"]) is not True
                or guided.record(parent)["origin"] != guided.record(base)["origin"]):
            raise ValueError("Control demand needs this cohort's accepted individual fit")
        result[ref["target"]] = count(ref)
    return result


@_scoped
def describe(value, *, grow=False):
    import math

    from diffeoforge.guided_feedback import verify_reference

    base = verify_reference(value["protocol"]["reference"])
    current = base.attachment_comparison["controls"]["count"]
    counts = demand(value)
    required = max(counts.values(), default=current)
    proposed = max(required, math.ceil(current * 1.5) if grow else current)
    return dict(version=VERSION, protocol=deepcopy(value["protocol"]),
        reviews=deepcopy(value["reviews"]), grow=grow, current_controls=current,
        required_controls=required, target_count=proposed, demand=counts,
        available=current < proposed <= 2000)


def validate(request, value):
    if (type(request.get("grow")) is not bool
            or request != describe(value, grow=request["grow"]) or not request["available"]):
        raise ValueError("Common capacity must include the bound accepted single-form demand")


def choice(value, target, *, grow=False, reference=None, diagnosis=None):
    request = describe(value, grow=grow)
    old, new = request["current_controls"], request["target_count"]
    return dict(mode="capacity" if reference else "fresh_capacity", target=target,
        available=request["available"], reference=reference, diagnosis=diagnosis,
        capacity_request=request, current_controls=old, proposed_controls=new,
        additional_iterations=120,
        label=f"Test shared controls for accepted shapes · {old} → {new} · {target}",
        reason=(f"Accepted individual fields used up to {request['required_controls']} controls, "
            "including preserved prefixes and local additions. Test at least that many on "
            "one shared basis before spending more steps on an undersized basis. "
            "Existing fields and approvals stay saved. This separate 120-step candidate "
            "needs review and explicit adoption as the common model."
            if request["available"] else
            "The accepted field demand exceeds the 2,000-control pilot guard. The count "
            "is not silently reduced; retain the accepted shapes and review the shared model."))


def apply(plan, selected):
    """Prepare only; no optimizer, protocol replacement or approval transfer."""
    if not selected["available"]:
        raise ValueError(selected["reason"])
    request = selected["capacity_request"]
    state = plan["strategy"]
    plan["target"] = selected["target"]
    state["common_capacity_request"] = deepcopy(request)
    ref = request["protocol"]["reference"]
    state["control_basis"] = ref
    if selected.get("reference"):
        state.update(baseline=selected["reference"], anchor=selected["reference"],
                     initialization="nested")
        plan.update(phase="refine", goal="density")
    else:
        state.pop("baseline", None)
        state.pop("anchor", None)
        plan.update(phase="refine", goal="density")
    plan["values"] = dict(ref["values"], initial_control_point_spacing=
                           ref["values"]["initial_control_point_spacing"] * .8)
    return plan


def points(value):
    import numpy as np

    from diffeoforge import reference_calibration_study as study
    from diffeoforge.guided_feedback import verify_reference

    base = verify_reference(value["protocol"]["reference"])
    controls = base.attachment_comparison["controls"]
    return np.loadtxt(study._safe_study_path(base.study_directory, controls["copy"]), ndmin=2)


def verify(info, record, manifest, root):
    from pathlib import Path

    import numpy as np

    from diffeoforge import reference_calibration_study as study
    from diffeoforge import reference_guided_pilot as guided
    from diffeoforge.config import load_config
    from diffeoforge.guided_density import extend
    from diffeoforge.guided_feedback import verify_reference
    from diffeoforge.pilot_common_basis import _physics
    from diffeoforge.pilot_form_progress import compatible, configure

    request = info["strategy"]["common_capacity_request"]
    value = info["strategy"]["form_progress"]
    validate(request, value)
    base = verify_reference(value["protocol"]["reference"])
    candidate = next(c for c in base.candidates
                     if c.candidate_id == value["protocol"]["reference"]["candidate_id"])
    expected_config = load_config(candidate.config_path)
    configure(expected_config, value, expected_config["optimization"]["method"])
    spacing = value["protocol"]["reference"]["values"]["initial_control_point_spacing"] * .8
    expected_values = dict(value["protocol"]["reference"]["values"],
                           initial_control_point_spacing=spacing)
    cp = np.loadtxt(study._safe_study_path(root, record["controls"]["copy"]), ndmin=2)
    previous = info["strategy"]["previous"]
    parent_snapshot = study.load_reference_calibration_study(Path(previous["directory"]))
    parent = guided.record(parent_snapshot)
    prior = (parent.get("strategy") or {}).get("form_progress")
    reviews = {r["filename"]: r for r in (prior or value)["reviews"]}
    retained = {r["filename"]: r for r in parent["approved"]
                if compatible(r, value["protocol"])}
    first = prior and prior["stage"] == "forms" and value["stage"] == "model"
    if first:
        for c in parent_snapshot.candidates:
            if parent_snapshot.visual_reviews.get(c.candidate_id) is True:
                row = guided._approved_record(parent_snapshot, c.candidate_id)
                reviews[row["filename"]] = row
                if compatible(row, value["protocol"]):
                    retained[row["filename"]] = row
    if (record.get("regional_objective") or record["iterations"] != 120
            or info["goal"] not in {"density", "form_model_check"}
            or value["reviews"] != list(reviews.values())
            or (prior and not first and value != prior)
            or any(not compatible(r, value["protocol"]) for r in info["approved"])
            or any(r not in info["approved"] for r in retained.values())
            or record["controls"]["count"] != request["target_count"]
            or record["controls"]["spacing"] != spacing
            or manifest["plan"]["baseline_effective_values"] != expected_values
            or not np.array_equal(cp, extend(points(value), spacing,
                                             target_count=request["target_count"]))
            or _physics(expected_config) != _physics(load_config(
                study._safe_study_path(root, manifest["source_config"]["copy"])))):
        raise ValueError("Shared capacity must preserve its accepted demand, field and reviews")
