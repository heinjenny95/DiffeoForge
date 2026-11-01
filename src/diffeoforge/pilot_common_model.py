"""Keep common-model work on one protocol and reuse the same form's saved field."""
from copy import deepcopy
from pathlib import Path

from diffeoforge import reference_calibration_study as study
from diffeoforge import reference_guided_pilot as guided
from diffeoforge.config import load_config
from diffeoforge.mesh import sha256_file

VERSION = "common-model-warm-step-v1"


def approvals(snapshot, context, value):
    from diffeoforge.pilot_form_progress import compatible

    rows = [*guided.record(snapshot)["approved"],
            *(case["approval"] for case in context["cases"] if case.get("approval"))]
    for candidate in snapshot.candidates:
        if snapshot.visual_reviews.get(candidate.candidate_id) is True:
            rows.append(guided._approved_record(snapshot, candidate.candidate_id))
    return list({row["filename"]: row for row in rows
                 if compatible(row, value["protocol"])}.values())


def _saved(snapshot, target, protocol):
    from diffeoforge.guided_feedback import inspected, reference
    from diffeoforge.pilot_form_progress import compatible

    info = guided.record(snapshot)
    result, seen = [], set()
    for entry in [*info["history"], None]:
        if entry and sha256_file(Path(entry["directory"]) / study.STUDY_MANIFEST) != entry[
                "manifest_sha256"]:
            raise ValueError("Saved common-model history changed")
        parent = (study.load_reference_calibration_study(Path(entry["directory"]))
                  if entry else snapshot)
        if parent.study_directory in seen:
            continue
        seen.add(parent.study_directory)
        other = guided.record(parent)
        if (other["origin"] != info["origin"] or other["target"] != target
                or parent.attachment_comparison.get("regional_objective")):
            continue
        for candidate in parent.candidates:
            try:
                ref = reference(parent, candidate.candidate_id)
            except ValueError:
                continue
            row = dict(ref)
            row["filename"] = row.pop("target")
            if compatible(row, protocol):
                result.append((parent, candidate, ref, inspected(parent, candidate.candidate_id)))
    return result


def preview(snapshot, context, target, *, value=None):
    from diffeoforge.guided_progress import iteration_limited
    from diffeoforge.pilot_form_progress import marker
    from diffeoforge.reference_attachment_comparison import ITERATIONS

    value = value or marker(snapshot)
    if not value or value["stage"] != "model" or not target:
        return None
    saved = _saved(snapshot, target, value["protocol"])
    if not saved:
        return dict(mode="fresh", available=True, target=target,
                    label="Prepare first common-model check · " + target)
    parent, candidate, ref, inspected = saved[-1]
    label = f"Test {guided.record(parent)['screen_trials_spent']}"
    if parent.visual_reviews.get(candidate.candidate_id) is True:
        return dict(mode="approved", available=False, target=target, reference=ref,
                    label="Common-model fit already approved · " + target,
                    reason="This matching result is already approved. Continue to the next "
                    "missing common-model check; no repeat is needed.")
    if not inspected:
        return dict(mode="review", available=True, target=target, reference=ref,
                    label="Review saved common-model fit · " + target,
                    reason="This matching result already exists. Review it before another fit.")
    feedback = [event for event in study._load_events(parent.study_directory)
                if event["event"] == "guided_fit_feedback"
                and event["current"]["candidate_id"] == candidate.candidate_id]
    step = (guided.record(parent).get("strategy") or {}).get("common_model_step")
    if step and not feedback:
        return dict(mode="feedback", available=False, target=target, reference=ref,
                    label="Compare with the previous common-model fit · " + target,
                    reason="Tell us whether this continuation improved the shape before "
                    "another continuation. Your earlier suitable individual fit stays saved.")
    stalled = bool(step and feedback and feedback[-1]["outcome"] in {"same", "worse"})
    if not iteration_limited(candidate) or stalled:
        return dict(mode="stalled", available=False, target=target, reference=ref,
                    label="Review the shared model · " + target,
                    reason="This shared-model result stopped or did not improve. Keep your "
                    "suitable local fit; revise the shared model explicitly rather than "
                    "repeating the same fit or returning to a local-repair loop.")
    from diffeoforge.pilot_iteration_accounting import total

    previous = total(candidate.metrics)
    return dict(mode="continue", available=True, target=target, reference=ref,
                additional_iterations=ITERATIONS, previous_iterations=previous,
                label=f"Continue common-model fit from {label} · +{ITERATIONS} · {target}",
                reason=f"Keep the saved field and common settings. Up to {ITERATIONS} new "
                f"iterations ({previous} already recorded); optimizer history restarts. "
                "Earlier suitable fits and common approvals remain saved.")


def apply_plan(snapshot, proposed, plan, context):
    """Change initialization only; never transfer a regional field to the common model."""
    choice = preview(snapshot, context, proposed["target"], value=proposed["marker"])
    if not choice or choice["mode"] == "fresh":
        return plan
    if choice["mode"] != "continue":
        raise ValueError(choice["reason"])
    state = plan["strategy"]
    state.update(baseline=choice["reference"], anchor=choice["reference"],
                 common_model_step=dict(version=VERSION, reference=choice["reference"],
                     protocol=deepcopy(proposed["marker"]["protocol"]),
                     additional_iterations=choice["additional_iterations"],
                     previous_iterations=choice["previous_iterations"],
                     approval_transferred=False))
    plan.update(phase="refine", goal="common_continue")
    return plan


def physics(config):
    model, optimization = deepcopy(config["model"]), deepcopy(config["optimization"])
    for key in ("initial_control_points", "initial_momenta", "initial_momenta_subjects"):
        model["deformation"].pop(key, None)
    optimization.pop("max_iterations", None)
    return dict(model=model, optimization=optimization, runtime=config["runtime"])


def verify(info, record, manifest, root):
    from diffeoforge.guided_feedback import verify_reference
    from diffeoforge.guided_progress import iteration_limited
    from diffeoforge.pilot_form_progress import compatible
    from diffeoforge.pilot_iteration_accounting import total
    from diffeoforge.reference_attachment_comparison import ITERATIONS

    marker = info["strategy"]["common_model_step"]
    ref = marker["reference"]
    parent = verify_reference(ref)
    candidate = next(c for c in parent.candidates if c.candidate_id == ref["candidate_id"])
    row = dict(ref)
    row["filename"] = row.pop("target")
    config = load_config(study._safe_study_path(root, manifest["source_config"]["copy"]))
    if (marker["version"] != VERSION or marker["approval_transferred"] is not False
            or marker["protocol"] != info["strategy"]["form_progress"]["protocol"]
            or not compatible(row, marker["protocol"]) or not iteration_limited(candidate)
            or marker["previous_iterations"] != total(candidate.metrics)
            or marker["additional_iterations"] != ITERATIONS or record["iterations"] != ITERATIONS
            or config["optimization"]["max_iterations"] != ITERATIONS
            or info["goal"] != "common_continue" or info["phase"] != "refine"
            or info["target"] != ref["target"] or parent.plan.pilot_subject_count != 1
            or guided.record(parent)["origin"] != info["origin"]
            or record.get("regional_objective") or info["strategy"].get("regional_recipe")
            or record["refinement"].get("initialization") != "learned"
            or record["refinement"]["reference"] != ref
            or info["strategy"].get("baseline") != ref
            or manifest["plan"]["baseline_effective_values"] != ref["values"]
            or physics(config) != physics(load_config(candidate.config_path))):
        raise ValueError("Common-model successor must retain the exact saved field and protocol")
