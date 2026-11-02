"""Keep common-model work on one protocol and reuse the same form's saved field."""
from copy import deepcopy
from pathlib import Path

from diffeoforge import reference_calibration_study as study
from diffeoforge import reference_guided_pilot as guided
from diffeoforge.config import load_config
from diffeoforge.mesh import sha256_file

LEGACY_VERSION = "common-model-warm-step-v1"
PREVIOUS_VERSION = "common-model-warm-step-v2"
VERSION = "common-model-warm-step-v3"
EFFORT_VERSION = "guided-warm-effort-v1"


def optimization_context(snapshot, context, references):
    """Bind optional recovery to the same common-model stop as the primary route.

    Opening an older starting fit must not erase a newer no-improvement decision.
    This read-only result is computed with the other verified proposal inputs.
    """
    from diffeoforge.pilot_form_progress import compatible, marker
    from diffeoforge.reference_attachment_comparison import ITERATIONS

    choice = context.get("common_recovery")
    if not choice:
        return {}
    value = marker(snapshot)
    if not value or value["stage"] != "model":
        return {}
    result = {}
    for ref in references:
        if not ref or ref["target"] != choice["target"]:
            continue
        candidate_origin = choice.get("candidate_origin")
        if candidate_origin:
            from diffeoforge.guided_feedback import verify_reference

            parent = verify_reference(ref)
            step = (guided.record(parent).get("strategy") or {}).get("common_candidate_step")
            if ref == candidate_origin or step and step["capacity_origin"] == candidate_origin:
                result[(ref["directory"], ref["candidate_id"])] = dict(
                    additional_iterations=ITERATIONS,
                    blocked_reason="Use the bounded common-candidate action to retain its "
                                   "field, comparison, experiment budget and saved approvals.")
                continue
        row = dict(ref)
        row["filename"] = row.pop("target")
        if compatible(row, value["protocol"]):
            result[(ref["directory"], ref["candidate_id"])] = dict(
                additional_iterations=ITERATIONS,
                blocked_reason=choice.get("reason", "")
                if choice["mode"] in {"stalled", "feedback", "review", "approved",
                                      "capacity", "fresh_capacity", "prepared", "adopt",
                                      "candidate_refine"} else "")
    return result


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
    from diffeoforge.pilot_common_capacity import choice as capacity_choice
    from diffeoforge.pilot_common_capacity import describe

    capacity = describe(value)
    shortfall = capacity["target_count"] > capacity["current_controls"]
    if shortfall:
        target = max(capacity["demand"], key=capacity["demand"].get)
    tests = _diagnostic_tests(snapshot, target, value)
    if tests and tests[-1][1]["kind"] == "capacity":
        return _capacity_status(tests[-1][0], target, snapshot=snapshot, value=value)
    saved = _saved(snapshot, target, value["protocol"])
    if not saved:
        if shortfall:
            return capacity_choice(value, target)
        from diffeoforge.pilot_common_basis import preview as basis_preview

        transfer = basis_preview(snapshot, target, value["protocol"])
        if transfer:
            return transfer
        return dict(mode="fresh", available=True, target=target,
                    label="Prepare first common-model check · " + target)
    parent, candidate, ref, inspected = saved[-1]
    label = f"Test {guided.record(parent)['screen_trials_spent']}"
    if parent.visual_reviews.get(candidate.candidate_id) is True and not shortfall:
        return dict(mode="approved", available=False, target=target, reference=ref,
                    label="Common-model fit already approved · " + target,
                    reason="This matching result is already approved. Continue to the next "
                    "missing common-model check; no repeat is needed.")
    if not inspected:
        return dict(mode="review", available=True, target=target, reference=ref,
                    test_number=guided.record(parent)["screen_trials_spent"],
                    label="Review saved common-model fit · " + target,
                    reason="This matching result already exists. Review it before another fit.")
    from diffeoforge.pilot_common_diagnosis import diagnose, recommend

    earlier = [r for r in saved[:-1] if r[3]]
    diagnosis = diagnose(snapshot, value, ref, earlier[-1][2] if earlier else None)
    feedback = [event for event in study._load_events(parent.study_directory)
                if event["event"] == "guided_fit_feedback"
                and event["current"]["candidate_id"] == candidate.candidate_id]
    strategy = guided.record(parent).get("strategy") or {}
    optimization = strategy.get("optimization") or {}
    step = strategy.get("common_model_step") or (
        optimization if optimization.get("version") == EFFORT_VERSION
        and optimization.get("common_model") is True else None)
    if step and not feedback and not diagnosis:
        return dict(mode="feedback", available=True, target=target, reference=ref,
                    review_reference=ref,
                    label="Compare with the previous common-model fit · " + target,
                    reason="Tell us whether this continuation improved the shape before "
                    "another continuation. Your earlier suitable individual fit stays saved.")
    stalled = bool(step and feedback and feedback[-1]["outcome"] in {"same", "worse"})
    prior_steps = [(guided.record(p).get("strategy") or {}) for p, _, _, _ in saved]
    iteration_tests = sum(bool(s.get("common_model_step") or
        (s.get("optimization") or {}).get("common_model")) for s in prior_steps)
    recommendation = recommend(diagnosis, capped=iteration_limited(candidate),
        iteration_tests=iteration_tests,
        density_tested=any(t["kind"] == "capacity" for _, t in tests), veto=stalled)
    if shortfall or recommendation and recommendation["kind"] == "capacity":
        return capacity_choice(value, target, grow=not shortfall, reference=ref,
                               diagnosis=diagnosis)
    if recommendation and recommendation["kind"] in {"inspect", "stalled"}:
        return dict(mode="stalled", available=False, target=target, reference=ref,
                    diagnosis=diagnosis,
                    label="Compare with the accepted individual fit · " + target,
                    reason=recommendation["reason"])
    if not iteration_limited(candidate) or stalled:
        return dict(mode="stalled", available=False, target=target, reference=ref,
                    label="Review the shared model · " + target,
                    reason="This shared-model result stopped or did not improve. Keep your "
                    "suitable local fit; revise the shared model explicitly rather than "
                    "repeating the same fit or returning to a local-repair loop.")
    if not feedback or feedback[-1]['outcome'] != 'better' or not feedback[-1].get('event_hash'):
        return dict(mode="feedback", available=True, target=target, reference=ref,
                    review_reference=ref, diagnosis=diagnosis,
                    label="Compare this common fit · tell us what changed · " + target,
                    reason="Unchanged continuation needs your explicit Better feedback. "
                           "Choose Better, About the same or Worse in the saved comparison. "
                           "No extra iterations are prepared without that decision.")
    from diffeoforge.pilot_iteration_accounting import branch_total, total

    recorded = total(candidate.metrics)
    previous = branch_total(parent, candidate)
    return dict(mode="continue", available=True, target=target, reference=ref,
                diagnosis=diagnosis,
                additional_iterations=ITERATIONS, previous_iterations=previous,
                previous_recorded_iterations=recorded,
                human_feedback=dict(reference=ref, event_hash=feedback[-1]['event_hash'],
                                    outcome=feedback[-1]['outcome']),
                label=f"Continue common-model fit from {label} · +{ITERATIONS} · {target}",
                reason=(f"Saved-field branch: {previous} iterations; the last native counter "
                        f"is {candidate.metrics['final_iteration']} and the older branch "
                        f"summary recorded {recorded}. Historical counters remain unchanged. "
                        if previous != recorded else "")
                + ((recommendation["reason"] + " ") if recommendation else
                   "Accepted-shape comparison is unavailable; this is an optional capped "
                   "continuation, not an automatic diagnosis. ")
                + f"Keep the saved field and common settings. Up to {ITERATIONS} new "
                f"iterations ({previous} already recorded); optimizer history restarts. "
                "Earlier suitable fits and common approvals remain saved.")


def _capacity_status(tested, target, diagnosis=None, *, snapshot=None, value=None):
    from diffeoforge.guided_feedback import reference

    if snapshot is not None and value is not None:
        from diffeoforge.pilot_common_candidate import preview

        return preview(snapshot, tested, target, value)
    other = tested.candidates[0]
    if other.status != "completed":
        return dict(mode="prepared", available=False, target=target, diagnosis=diagnosis,
            label="Complete the prepared control-point comparison · " + target,
            reason="A separate capacity test is already prepared or running. Use its "
                   "normal Run/check controls; another test is not prepared automatically.")
    try:
        tested_ref = reference(tested, other.candidate_id)
    except ValueError:
        return dict(mode="stalled", available=False, target=target, diagnosis=diagnosis,
            label="Inspect the saved control-point comparison · " + target,
            reason="The saved capacity test has no complete technically valid field. "
                   "Inspect its retained result and checks; it is not repeated automatically.")
    return dict(mode="review" if other.candidate_id not in tested.visual_reviews else "stalled",
        available=other.candidate_id not in tested.visual_reviews, target=target,
        reference=tested_ref, diagnosis=diagnosis, comparison_kind="capacity",
        test_number=guided.record(tested)["screen_trials_spent"],
        label="Review saved control-point comparison · " + target,
        reason="This separate capacity test already exists. Inspect it and, if suitable, "
               "explicitly adopt its settings as a shared-model revision. Earlier shape "
               "and common-model approvals stay saved under their original protocol.")


def apply_plan(snapshot, proposed, plan, context):
    """Change initialization only; never transfer a regional field to the common model."""
    choice = preview(snapshot, context, proposed["target"], value=proposed["marker"])
    if not choice or choice["mode"] == "fresh":
        return plan
    if choice["mode"] == "basis":
        from diffeoforge.pilot_common_basis import apply

        return apply(plan, choice, proposed["marker"]["protocol"])
    if choice["mode"] == "candidate_refine":
        from diffeoforge.pilot_common_candidate import apply

        return apply(plan, choice)
    if choice["mode"] not in {"continue", "capacity", "fresh_capacity"}:
        raise ValueError(choice["reason"])
    if choice.get("capacity_request"):
        from diffeoforge.pilot_common_capacity import apply

        return apply(plan, choice)
    state = plan["strategy"]
    if choice.get("diagnosis"):
        state["common_diagnosis_test"] = dict(version="accepted-shape-common-test-v1",
            kind="capacity" if choice["mode"] == "capacity" else "iterations",
            accepted=choice["diagnosis"]["accepted"], seed=choice["reference"],
            protocol=deepcopy(proposed["marker"]["protocol"]), additional_iterations=120,
            approval_transferred=False)
    if choice["mode"] == "capacity":
        state.update(baseline=choice["reference"], anchor=choice["reference"],
                     control_basis=choice["reference"], initialization="nested")
        plan.update(phase="refine", goal="density", values=dict(choice["reference"]["values"],
            initial_control_point_spacing=choice["reference"]["values"][
                "initial_control_point_spacing"] * .8))
        return plan
    state.update(baseline=choice["reference"], anchor=choice["reference"],
                 common_model_step=dict(version=VERSION, reference=choice["reference"],
                     protocol=deepcopy(proposed["marker"]["protocol"]),
                     additional_iterations=choice["additional_iterations"],
                     previous_iterations=choice["previous_iterations"],
                     human_feedback=deepcopy(choice['human_feedback']),
                     approval_transferred=False))
    plan.update(phase="refine", goal="common_continue")
    return plan


def _diagnostic_tests(snapshot, target, value):
    """Read bound history; navigating to an earlier fit cannot reset the experiment budget."""
    result, seen = [], set()
    for entry in [*guided.record(snapshot)["history"], None]:
        parent = snapshot
        if entry:
            root = Path(entry["directory"])
            if sha256_file(root / study.STUDY_MANIFEST) != entry["manifest_sha256"]:
                raise ValueError("Common diagnostic history changed")
            parent = study.load_reference_calibration_study(root)
        if parent.study_directory in seen:
            continue
        seen.add(parent.study_directory)
        info = guided.record(parent)
        strategy = info.get("strategy") or {}
        marker = strategy.get("common_diagnosis_test")
        capacity = strategy.get("common_capacity_request")
        if capacity:
            marker = dict(kind="capacity", protocol=capacity["protocol"], accepted=next(
                (dict(r, target=r["filename"]) for r in capacity["reviews"]
                 if r["filename"] == target), {}))
        accepted = next((r for r in value["reviews"] if r["filename"] == target), None)
        if (marker and info["target"] == target and marker["protocol"] == value["protocol"]
                and marker["accepted"]["directory"] == (accepted or {}).get("directory")):
            result.append((parent, marker))
    return result


def verify_diagnostic(info, record, manifest, root):
    from diffeoforge.guided_feedback import verify_reference

    marker = info["strategy"]["common_diagnosis_test"]
    accepted, seed = (verify_reference(marker[k]) for k in ("accepted", "seed"))
    expected_goal = "density" if marker["kind"] == "capacity" else "common_continue"
    old = guided.record(seed)
    value = info["strategy"]["form_progress"]
    approved_row = next((r for r in value["reviews"] if r["filename"] == info["target"]), {})
    approved_ref = dict(approved_row)
    if approved_ref:
        approved_ref["target"] = approved_ref.pop("filename")
    seed_row = dict(marker["seed"])
    seed_row["filename"] = seed_row.pop("target")
    from diffeoforge.pilot_form_progress import compatible

    if (marker["version"] != "accepted-shape-common-test-v1"
            or marker["kind"] not in {"iterations", "capacity"}
            or marker["additional_iterations"] != 120 or record["iterations"] != 120
            or marker["approval_transferred"] is not False or info["goal"] != expected_goal
            or accepted.visual_reviews.get(marker["accepted"]["candidate_id"]) is not True
            or marker["accepted"] != approved_ref
            or not compatible(seed_row, value["protocol"])
            or any(r["target"] != info["target"] for r in (marker["accepted"], marker["seed"]))
            or any(origin != info["origin"] for origin in
                   (guided.record(accepted)["origin"], old["origin"]))
            or value["protocol"] != marker["protocol"]
            or record.get("regional_objective")
            or record.get("refinement", {}).get("reference") != marker["seed"]):
        raise ValueError("Accepted-shape comparison must preserve its bound source and allowance")
    previous = info["strategy"]["previous"]
    parent = guided.record(study.load_reference_calibration_study(Path(previous["directory"])))
    parent_marker = (parent.get("strategy") or {}).get("form_progress")
    if value != parent_marker or info["approved"] != parent["approved"]:
        raise ValueError("Common diagnostic test changed saved approvals or protocol")
    current_config = physics(load_config(study._safe_study_path(
        root, manifest["source_config"]["copy"])))
    original_config = physics(load_config(next(c for c in seed.candidates
        if c.candidate_id == marker["seed"]["candidate_id"]).config_path))
    if marker["kind"] == "capacity":
        for config in (current_config, original_config):
            config["model"]["deformation"].pop("initial_control_point_spacing", None)
    if current_config != original_config:
        raise ValueError("Common diagnostic test changed unrelated model or numerical settings")


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
    from diffeoforge.pilot_iteration_accounting import branch_total, total
    from diffeoforge.reference_attachment_comparison import ITERATIONS

    marker = info["strategy"]["common_model_step"]
    ref = marker["reference"]
    parent = verify_reference(ref)
    candidate = next(c for c in parent.candidates if c.candidate_id == ref["candidate_id"])
    row = dict(ref)
    row["filename"] = row.pop("target")
    config = load_config(study._safe_study_path(root, manifest["source_config"]["copy"]))
    previous = (total(candidate.metrics) if marker["version"] == LEGACY_VERSION
                else branch_total(parent, candidate))
    if marker['version'] == VERSION:
        human = marker.get('human_feedback') or {}
        event = next((e for e in study._load_events(parent.study_directory)
            if e.get('event_hash') == human.get('event_hash')
            and e['event'] == 'guided_fit_feedback'), None)
        if (not event or human.get('reference') != ref or event['current'] != ref
                or human.get('outcome') != 'better' or event['outcome'] != 'better'):
            raise ValueError('A common continuation needs its bound explicit Better feedback')
    if (marker["version"] not in {LEGACY_VERSION, PREVIOUS_VERSION, VERSION}
            or marker["approval_transferred"] is not False
            or marker["protocol"] != info["strategy"]["form_progress"]["protocol"]
            or not compatible(row, marker["protocol"]) or not iteration_limited(candidate)
            or marker["previous_iterations"] != previous
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
