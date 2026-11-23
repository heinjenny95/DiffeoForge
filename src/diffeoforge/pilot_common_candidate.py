"""Refine a reviewed shared-capacity candidate before adopting or approving it."""
from copy import deepcopy
from pathlib import Path

from diffeoforge.guided_density import controls_for

LEGACY_VERSION = "common-candidate-refinement-v1"
VERSION = "common-candidate-refinement-v2"
ORDINARY_BASIS_VERSION = "common-candidate-refinement-v3"
KINDS = {"iterations", "detail", "weight"}


def decide(diagnosis, *, capped, counts, outcome=None):
    """A finite experiment policy; better feedback never becomes suitability."""
    from diffeoforge.pilot_common_diagnosis import detail_evidence

    if not diagnosis or not diagnosis["gap"] or diagnosis.get("warnings"):
        return None
    progress = diagnosis.get("marked_progress")
    if ((diagnosis["trend"] == "improving" or diagnosis["trend"] == "plateau" and progress is True)
            and progress is not False
            and capped and outcome == "better"
            and counts.get("iterations", 0) < 2):
        return "iterations"
    broad = diagnosis.get("whole_gap") and not detail_evidence(diagnosis)
    if broad and not diagnosis.get("accepted_local"):
        # A broad discrepancy provides a reason to test weight, while a width
        # contrast needs evidence at the scale of a specific feature.
        return "weight" if not counts.get("weight") else None
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


def preview(snapshot, tested, target, value, *, ordinary_basis=False):
    from diffeoforge import reference_calibration_study as study
    from diffeoforge import reference_guided_pilot as guided
    from diffeoforge.guided_feedback import inspected, reference, verify_reference
    from diffeoforge.guided_progress import iteration_limited
    from diffeoforge.pilot_common_diagnosis import alignment_advice, diagnose, experiment
    from diffeoforge.pilot_common_review import seed_outcome
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
        retained = trials[-1][1]["reference"] if trials else origin
        retained_number = guided.record(verify_reference(retained))["screen_trials_spent"]
        return dict(mode="stalled", available=False, target=target,
            retained_reference=retained, retained_test_number=retained_number,
            bounded_exhausted=True,
            label=f"Inspect retained common fit · Test {retained_number} · {target}",
            reason="The latest candidate has no valid completed field. Inspect the retained "
                   "starting fit and its remaining mismatch.")
    base = dict(target=target, reference=ref, review_reference=ref,
                test_number=guided.record(latest)["screen_trials_spent"],
                comparison_kind="surface" if ordinary_basis else "capacity",
                candidate_origin=origin, ordinary_basis=ordinary_basis)
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
    feedback = [event for event in study._load_events(latest.study_directory)
        if event["event"] == "guided_fit_feedback"
        and event["current"]["candidate_id"] == candidate.candidate_id]
    alignment = alignment_advice(snapshot, latest, ref, feedback, value)
    if alignment:
        return dict(base, **alignment)
    measured = diagnose(snapshot, value, ref, previous)
    if not feedback or not feedback[-1].get("event_hash"):
        return dict(base, mode="feedback", available=True, diagnosis=measured,
            label="Compare this common fit · tell us what changed · " + target,
            reason="Compare the common fit with the fit shown on the right. Choose Better, "
                   "About the same, Worse or Unsure for this pair.")
    event = feedback[-1]
    progress = seed_outcome(event)
    counts = {kind: sum(m["kind"] == kind for _, m in trials) for kind in KINDS}
    kind = ("detail" if ordinary_basis and not trials else decide(
        measured, capped=iteration_limited(candidate), counts=counts, outcome=progress))
    # A rating against an individual fit does not rank two common fields. For
    # such ratings retain a newer common field only with a measured positive trend.
    useful = progress == "better" or (progress is None and measured
                                      and measured["trend"] == "improving"
                                      and measured.get("marked_progress") is not False)
    seed = (step["reference"] if step and (not useful or not measured
            or measured["trend"] == "worse" or measured.get("warnings")) else ref)
    parent = verify_reference(seed)
    retained_number = guided.record(parent)["screen_trials_spent"]
    base.update(retained_reference=seed, retained_test_number=retained_number)
    if kind is None:
        return dict(base, mode="stalled", available=False, diagnosis=measured,
            bounded_exhausted=True,
            label=f"Inspect retained common fit · Test {retained_number} · " + target,
            reason="The available shape checks give no reason for another bounded test. "
            + f"Return to retained Test {retained_number} to inspect the remaining mismatch.")
    retained = next(c for c in parent.candidates if c.candidate_id == seed["candidate_id"])
    values = (dict(seed["values"]) if kind == "iterations" else
              guided.adjusted_values(seed["values"], kind, conservative=True))
    count = controls_for(parent.attachment_comparison, seed["candidate_id"])["count"]
    title = {"iterations": "Continue this common candidate",
             "detail": "Refine surface matching on this common candidate",
             "weight": "Test stronger surface matching on this common candidate"}[kind]
    explanation = experiment(kind, measured or {})
    explanation["reason"] += (f" Start from Test {retained_number} with {count} control points. "
                              "The optimizer starts fresh with a 120-iteration cap.")
    return dict(base, mode="candidate_refine", available=True, diagnosis=measured, kind=kind,
        reference=seed, values=values, candidate_controls=count, additional_iterations=120,
        previous_iterations=branch_total(parent, retained), counts=counts,
        human_feedback=dict(reference=ref, event_hash=event["event_hash"],
                            outcome=event["outcome"]),
        seed_outcome=progress,
        label=f"{title} · {count} CP · " + (
            "up to +120 · " if kind == "iterations" else "1 setting test · ") + target,
        **explanation)


def apply(plan, choice):
    version = ORDINARY_BASIS_VERSION if choice["ordinary_basis"] else VERSION
    marker = dict(version=version, kind=choice["kind"], reference=choice["reference"],
        capacity_origin=choice["candidate_origin"], protocol=deepcopy(plan["strategy"][
            "form_progress"]["protocol"]), additional_iterations=120,
        previous_iterations=choice["previous_iterations"], approval_transferred=False,
        human_feedback=deepcopy(choice["human_feedback"]))
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
    from diffeoforge.pilot_common_review import seed_outcome
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
    capacity = (declared.get("common_capacity_request") or
                (declared.get("common_diagnosis_test") or {}).get("kind") == "capacity")
    if marker["version"] == ORDINARY_BASIS_VERSION:
        from diffeoforge.pilot_common_model import _saved
        from diffeoforge.pilot_form_progress import is_common_check

        origin_id = marker["capacity_origin"]["candidate_id"]
        known = _saved(parent, info["target"], value["protocol"])
        valid_origin = (not capacity and is_common_check(guided.record(origin))
                        and origin.visual_reviews.get(origin_id) is False
                        and any(ref == marker["capacity_origin"] and inspected
                                for _, _, ref, inspected in known)
                        and (kind == "detail" or bool(trials)))
    else:
        valid_origin = bool(capacity)
    if marker["version"] in {VERSION, ORDINARY_BASIS_VERSION}:
        human = marker.get("human_feedback") or {}
        if not isinstance(human.get("reference"), dict) or not human.get("event_hash"):
            raise ValueError("A common-candidate step needs its bound human comparison")
        reviewed = verify_reference(human["reference"])
        event = next((e for e in study._load_events(reviewed.study_directory)
            if e.get("event_hash") == human.get("event_hash")
            and e["event"] == "guided_fit_feedback"), None)
        if (not event or event["current"] != human["reference"]
                or human["reference"] not in refs or event["outcome"] != human.get("outcome")
                or kind == "iterations" and seed_outcome(event) != "better"):
            raise ValueError("A common-candidate step needs its bound human comparison; "
                             "unchanged iterations require explicit Better feedback")
    if (marker["version"] not in {LEGACY_VERSION, VERSION, ORDINARY_BASIS_VERSION}
            or kind not in KINDS or not valid_origin
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
            or record["controls"]["sha256"] != controls_for(
                origin.attachment_comparison, marker["capacity_origin"]["candidate_id"])["sha256"]
            or record["controls"]["sha256"] != controls_for(
                seed.attachment_comparison, marker["reference"]["candidate_id"])["sha256"]
            or record["refinement"]["initialization"] != "learned"
            or record["refinement"]["reference"] != marker["reference"]
            or record["refinement"]["momenta"]["sha256"] != sha256_file(seed_field.momenta_path)
            or manifest["plan"]["baseline_effective_values"] != expected
            or physics(load_config(candidate.config_path)) != physics(load_config(
                study._safe_study_path(root, manifest["source_config"]["copy"])))):
        raise ValueError("Common-candidate refinement must keep its field, approvals and budget")
