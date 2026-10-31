"""Separate cumulative warm-fit effort from a restarted native iteration counter."""

from pathlib import Path


def total(metrics):
    return metrics.get("iteration_accounting", {}).get("total_iterations",
                                                       metrics.get("final_iteration"))


def source(manifest, candidate_id):
    extension = manifest.get("search_extension_source", {})
    proposal = extension.get("proposal", {})
    context = proposal.get("continuation_context")
    if (context and not context.get("finer_surface")
            and candidate_id in {c["candidate_id"] for c in proposal["candidates"]}):
        return Path(extension["study_directory"]), context["candidate_id"]
    search = manifest.get("fit_search", {})
    first_ids = {c["candidate_id"] for c in manifest["plan"]["stages"][0]["candidates"]}
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
    count = total(candidate.metrics or {})
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
