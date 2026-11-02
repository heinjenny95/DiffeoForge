"""Refine a reviewed shared-capacity candidate before adopting or approving it."""
from copy import deepcopy
from pathlib import Path

VERSION = "common-candidate-refinement-v1"
KINDS = {"iterations", "detail", "weight"}


def decide(diagnosis, *, capped, counts, outcome=None):
    """A finite experiment policy; better feedback never becomes suitability."""
    if diagnosis and diagnosis.get("warnings"):
        return None
    if (diagnosis and diagnosis["gap"] and diagnosis["trend"] == "improving"
            and capped and outcome not in {"same", "worse"}
            and counts.get("iterations", 0) < 2):
        return "iterations"
    return next((kind for kind in ("detail", "weight") if not counts.get(kind)), None)


def family(snapshot, origin):
    from diffeoforge import reference_calibration_study as study
    from diffeoforge import reference_guided_pilot as guided
    from diffeoforge.mesh import sha256_file

    result, seen = [], set()
    for entry in [*guided.record(snapshot)["history"], None]:
        parent = snapshot
        if entry:
            root = Path(entry["directory"])
            if sha256_file(root / study.STUDY_MANIFEST) != entry["manifest_sha256"]:
                raise ValueError("Common-candidate history changed")
            parent = study.load_reference_calibration_study(root)
        if parent.study_directory in seen:
            continue
        seen.add(parent.study_directory)
        marker = (guided.record(parent).get("strategy") or {}).get("common_candidate_step")
        if marker and marker["capacity_origin"] == origin:
            result.append((parent, marker))
    return result


def preview(snapshot, tested, target, value):
    from diffeoforge import reference_calibration_study as study
    from diffeoforge import reference_guided_pilot as guided
    from diffeoforge.guided_feedback import inspected, reference, verify_reference
    from diffeoforge.guided_progress import iteration_limited
    from diffeoforge.pilot_common_diagnosis import diagnose
    from diffeoforge.pilot_iteration_accounting import branch_total

    def pending():
        return dict(mode="prepared", available=False, target=target,
            label="Complete the prepared common candidate · " + target,
            reason="A separate common candidate is prepared or running. Use its normal "
                   "Run/check controls; no duplicate or approval is created.")
    if tested.candidates[0].status != "completed":
        return pending()
    try:
        origin = reference(tested, tested.candidates[0].candidate_id)
    except ValueError:
        return dict(mode="stalled", available=False, target=target,
            label="Inspect the retained candidate and its failed checks · " + target,
            reason="The capacity test has no complete valid field. Keep the accepted "
                   "individual shapes and inspect its failure before another numerical test.")
    trials = family(snapshot, origin)
    latest = trials[-1][0] if trials else tested
    candidate = latest.candidates[0]
    if candidate.status in {"pending", "running"}:
        return pending()
    try:
        ref = reference(latest, candidate.candidate_id)
    except ValueError:
        return dict(mode="stalled", available=False, target=target,
            label="Inspect the failed common-candidate refinement · " + target,
            reason="The latest candidate has no valid completed field. It is not restarted "
                   "automatically; accepted fields and the old protocol remain saved.")
    base = dict(target=target, reference=ref, review_reference=ref,
                test_number=guided.record(latest)["screen_trials_spent"],
                comparison_kind="capacity", candidate_origin=origin)
    if candidate.candidate_id not in latest.visual_reviews or not inspected(
            latest, candidate.candidate_id):
        return dict(base, mode="review", available=True,
            label="Review saved common-model candidate · " + target,
            reason="Inspect this exact candidate. Better agreement is separate from "
                   "suitability; approval and model adoption are explicit decisions.")
    verify_reference(ref)
    if latest.visual_reviews[candidate.candidate_id] is True:
        return dict(base, mode="adopt", available=False,
            label="Use the approved candidate as the common model · " + target,
            reason="This candidate has your suitability review. Explicitly adopt its "
                   "settings as the common model to check the other forms. "
                   "Old decisions stay saved.")
    strategy = guided.record(latest).get("strategy") or {}
    step = strategy.get("common_candidate_step")
    previous = step["reference"] if step else strategy.get("baseline")
    measured = diagnose(snapshot, value, ref, previous)
    feedback = [event for event in study._load_events(latest.study_directory)
        if event["event"] == "guided_fit_feedback"
        and event["current"]["candidate_id"] == candidate.candidate_id]
    outcome = feedback[-1]["outcome"] if feedback else None
    counts = {kind: sum(m["kind"] == kind for _, m in trials) for kind in KINDS}
    kind = decide(measured, capped=iteration_limited(candidate), counts=counts, outcome=outcome)
    if kind is None:
        return dict(base, mode="stalled", available=False, diagnosis=measured,
            label="Review the remaining candidate mismatch · " + target,
            reason="This candidate remains unsuitable. Its bounded iteration and surface-scale "
                   "contrasts are exhausted or checks need attention. Reopen this exact result "
                   "and its comparison or choose a saved field for a different hypothesis. "
                   "No approval, restart or identical repeat is required.")
    # An unsuccessful parameter contrast does not silently become the next seed.
    seed = (step["reference"] if step and (outcome == "worse" or measured
            and measured["trend"] == "worse") else ref)
    parent = verify_reference(seed)
    retained = next(c for c in parent.candidates if c.candidate_id == seed["candidate_id"])
    values = (dict(seed["values"]) if kind == "iterations" else
              guided.adjusted_values(seed["values"], kind, conservative=True))
    count = parent.attachment_comparison["controls"]["count"]
    title = {"iterations": "Continue this common candidate",
             "detail": "Refine surface matching on this common candidate",
             "weight": "Test stronger surface matching on this common candidate"}[kind]
    reason = ("The saved candidate is improving toward the accepted shape without a measured "
              "local regression. " if kind == "iterations" else
              "The candidate is still unsuitable or shows a local trade-off. Test a different "
              "surface-matching setting instead of repeating unchanged iterations. ")
    reason += (f"Start from its saved {count}-control field; retain every control and momentum. "
               "The old common model, good individual fits and all approvals stay saved. "
               "Prepare at most 120 steps with fresh optimizer history; adoption is separate.")
    return dict(base, mode="candidate_refine", available=True, diagnosis=measured, kind=kind,
        reference=seed, values=values, candidate_controls=count, additional_iterations=120,
        previous_iterations=branch_total(parent, retained), counts=counts,
        label=f"{title} · {count} CP · up to +120 · {target}", reason=reason)


def apply(plan, choice):
    marker = dict(version=VERSION, kind=choice["kind"], reference=choice["reference"],
        capacity_origin=choice["candidate_origin"], protocol=deepcopy(plan["strategy"][
            "form_progress"]["protocol"]), additional_iterations=120,
        previous_iterations=choice["previous_iterations"], approval_transferred=False)
    plan["strategy"].update(common_candidate_step=marker, baseline=choice["reference"],
                            anchor=choice["reference"], control_basis=choice["reference"])
    plan.update(target=choice["target"], phase="refine", goal="common_candidate",
                values=choice["values"])
    return plan


def verify(info, record, manifest, root):
    from diffeoforge import reference_calibration_study as study
    from diffeoforge import reference_guided_pilot as guided
    from diffeoforge.config import load_config
    from diffeoforge.guided_feedback import reference, verify_reference
    from diffeoforge.guided_progress import iteration_limited
    from diffeoforge.guided_refinement import load_field
    from diffeoforge.mesh import sha256_file
    from diffeoforge.pilot_common_model import physics
    from diffeoforge.pilot_iteration_accounting import branch_total

    marker = info["strategy"]["common_candidate_step"]
    origin = verify_reference(marker["capacity_origin"])
    parent = study.load_reference_calibration_study(info["strategy"]["previous"]["directory"])
    seed = verify_reference(marker["reference"])
    value = info["strategy"]["form_progress"]
    trials = family(parent, marker["capacity_origin"])
    allowed = [origin, *(p for p, _ in trials)]
    refs = [reference(p, p.candidates[0].candidate_id) for p in allowed
            if p.candidates[0].status == "completed"]
    counts = {kind: sum(m["kind"] == kind for _, m in trials) for kind in KINDS}
    kind = marker["kind"]
    if kind not in KINDS:
        raise ValueError("Unknown common-candidate hypothesis")
    expected = (marker["reference"]["values"] if kind == "iterations" else
                guided.adjusted_values(marker["reference"]["values"], kind, conservative=True))
    candidate = next(c for c in seed.candidates
                     if c.candidate_id == marker["reference"]["candidate_id"])
    seed_run = study.calibration_candidate_run_directory(candidate)
    seed_field = load_field(seed_run)
    declared = (guided.record(origin).get("strategy") or {})
    capacity = declared.get("common_capacity_request") or declared.get("common_diagnosis_test")
    if (marker["version"] != VERSION or kind not in KINDS or not capacity
            or marker["reference"] not in refs or marker["approval_transferred"] is not False
            or counts[kind] >= (2 if kind == "iterations" else 1)
            or kind == "iterations" and not iteration_limited(candidate)
            or info["goal"] != "common_candidate" or record["iterations"] != 120
            or marker["additional_iterations"] != 120
            or marker["previous_iterations"] != branch_total(seed, candidate)
            or info["target"] != marker["capacity_origin"]["target"]
            or any(guided.record(p)["origin"] != info["origin"] for p in (origin, seed))
            or value != guided.record(parent)["strategy"]["form_progress"]
            or value["protocol"] != marker["protocol"]
            or info["approved"] != guided.record(parent)["approved"]
            or record.get("regional_objective")
            or record["controls"]["sha256"] != origin.attachment_comparison["controls"]["sha256"]
            or record["controls"]["sha256"] != seed.attachment_comparison["controls"]["sha256"]
            or record["refinement"]["initialization"] != "learned"
            or record["refinement"]["reference"] != marker["reference"]
            or record["refinement"]["momenta"]["sha256"] != sha256_file(seed_field.momenta_path)
            or manifest["plan"]["baseline_effective_values"] != expected
            or physics(load_config(candidate.config_path)) != physics(load_config(
                study._safe_study_path(root, manifest["source_config"]["copy"])))):
        raise ValueError("Common-candidate refinement must keep its field, approvals and budget")
