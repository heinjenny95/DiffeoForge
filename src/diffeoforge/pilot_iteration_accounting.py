"""Separate cumulative warm-fit effort from a restarted native iteration counter."""

from pathlib import Path


def total(metrics):
    return metrics.get("iteration_accounting", {}).get("total_iterations",
                                                       metrics.get("final_iteration"))


def branch_total(snapshot, candidate, *, _seen=None):
    """Count verified warm-field ancestry without rewriting historical counters.

    Older optional optimizations recorded only their restarted local counter.
    Prospective successors can include the separately recorded seed's effort.
    Other historical continuation protocols retain their existing accounting.
    """
    from diffeoforge.guided_feedback import verify_reference
    from diffeoforge.pilot_common_model import EFFORT_VERSION, LEGACY_VERSION, VERSION
    from diffeoforge.reference_guided_pilot import record

    metrics = candidate.metrics or {}
    count = total(metrics)
    if candidate.status != "completed" or type(count) is not int or count < 0:
        raise ValueError("A saved-field branch needs verified completed iteration counts")
    seen = set() if _seen is None else _seen
    key = str(snapshot.study_directory), candidate.candidate_id
    if key in seen:
        raise ValueError("Cyclic saved-field iteration history")
    seen.add(key)
    if candidate.candidate_id not in (snapshot.attachment_comparison or {}).get("methods", {}):
        return count
    strategy = (record(snapshot) or {}).get("strategy") or {}
    diagnostic = strategy.get("common_diagnosis_test")
    capacity = (dict(reference=strategy["baseline"])
                if strategy.get("common_capacity_request") and strategy.get("baseline") else None)
    step = (strategy.get("common_model_step") or strategy.get("optimization") or diagnostic
            or strategy.get("common_basis_step")
            or strategy.get("common_candidate_step") or capacity)
    if not step:
        return count
    if strategy.get("common_model_step") and step.get("version") not in {LEGACY_VERSION, VERSION}:
        raise ValueError("Unknown common-model effort version")
    if strategy.get("optimization") and step.get("version") not in {None, EFFORT_VERSION}:
        raise ValueError("Unknown saved-field effort version")
    local = metrics.get("final_iteration")
    if type(local) is not int or local < 0:
        raise ValueError("The saved field has no recorded local native iteration count")
    ref = step["seed"] if step is diagnostic else step["reference"]
    parent = verify_reference(ref)
    source_candidate = next(c for c in parent.candidates if c.candidate_id == ref["candidate_id"])
    return branch_total(parent, source_candidate, _seen=seen) + local


def source(manifest, candidate_id):
    first_ids = {c["candidate_id"] for c in manifest["plan"]["stages"][0]["candidates"]}
    strategy = manifest.get("attachment_comparison", {}).get("guided", {}).get("strategy") or {}
    if strategy.get("common_candidate_step") and candidate_id in first_ids:
        ref = strategy["common_candidate_step"]["reference"]
        return Path(ref["directory"]), ref["candidate_id"]
    if (strategy.get("common_capacity_request") and strategy.get("baseline")
            and candidate_id in first_ids):
        ref = strategy["baseline"]
        return Path(ref["directory"]), ref["candidate_id"]
    diagnostic = ((manifest.get("attachment_comparison", {}).get("guided", {}).get(
        "strategy") or {}).get("common_diagnosis_test"))
    if diagnostic and candidate_id in first_ids:
        ref = diagnostic["seed"]
        return Path(ref["directory"]), ref["candidate_id"]
    transfer = ((manifest.get("attachment_comparison", {}).get("guided", {}).get(
        "strategy") or {}).get("common_basis_step"))
    if transfer and candidate_id in first_ids:
        ref = transfer["reference"]
        return Path(ref["directory"]), ref["candidate_id"]
    common = ((manifest.get("attachment_comparison", {}).get("guided", {}).get(
        "strategy") or {}).get("common_model_step"))
    if common and candidate_id in first_ids:
        ref = common["reference"]
        return Path(ref["directory"]), ref["candidate_id"]
    optimization = ((manifest.get("attachment_comparison", {}).get("guided", {}).get(
        "strategy") or {}).get("optimization"))
    from diffeoforge.pilot_common_model import EFFORT_VERSION

    if (optimization and optimization.get("version") == EFFORT_VERSION
            and candidate_id in first_ids):
        ref = optimization["reference"]
        return Path(ref["directory"]), ref["candidate_id"]
    extension = manifest.get("search_extension_source", {})
    proposal = extension.get("proposal", {})
    context = proposal.get("continuation_context")
    if (context and not context.get("finer_surface")
            and candidate_id in {c["candidate_id"] for c in proposal["candidates"]}):
        return Path(extension["study_directory"]), context["candidate_id"]
    search = manifest.get("fit_search", {})
    if (candidate_id in first_ids and (search.get("progressive") or {}).get("phase") == "continue"
            and search.get("warm_seed")):
        seed = search["warm_seed"]
        return Path(seed["source_study"]), seed["candidate_id"]
    return None


def offset(manifest, candidate_id):
    from diffeoforge import reference_calibration_study as study

    binding = source(manifest, candidate_id)
    if binding is None:
        return 0
    snapshot = study.load_reference_calibration_study(binding[0])
    candidate = next(c for c in snapshot.candidates if c.candidate_id == binding[1])
    common = ((manifest.get("attachment_comparison", {}).get("guided", {}).get(
        "strategy") or {}).get("common_model_step"))
    from diffeoforge.pilot_common_model import LEGACY_VERSION

    count = (common["previous_iterations"] if common and common["version"] == LEGACY_VERSION
             else branch_total(snapshot, candidate))
    if candidate.status != "completed" or type(count) is not int or count < 0:
        raise ValueError("Continuation source has no verified completed iteration count")
    return count


def annotate(metrics, initial):
    if not initial:
        return
    metrics["iteration_accounting"] = dict(
        initial_iterations=initial,
        additional_iterations=metrics["final_iteration"],
        total_iterations=initial + metrics["final_iteration"],
        maximum_total=initial + metrics["maximum_iterations"],
        history="Saved field retained; native optimizer history and local counter restart. "
        "Cumulative effort does not imply uninterrupted numerical trajectory.",
    )


def text(metrics):
    record = metrics.get("iteration_accounting")
    if not record:
        return ""
    return (f"Cumulative iterations on this saved-fit branch: {record['total_iterations']} "
            f"of {record['maximum_total']} "
            f"({record['initial_iterations']} earlier + {record['additional_iterations']} new).\n"
            + record["history"] + "\n")
