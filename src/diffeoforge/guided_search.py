"""Feedback-driven proposals from verified inputs; the search itself performs no I/O."""

from diffeoforge import reference_guided_pilot as guided
from diffeoforge.guided_progress import iteration_limited, next_hypothesis
from diffeoforge.pilot_recovery import DESCRIPTIONS, proposal


def inputs(snapshot, identifier, context, *, regions_override=None, allow_continuation=True):
    """Verify once in the background, shared by all selector previews for this fit."""
    from diffeoforge import reference_calibration_study as study
    from diffeoforge.guided_feedback import (
        local_strategy_reference,
        regions,
        selection,
        severe_regression,
        verify_reference,
    )
    from diffeoforge.guided_strategy import _candidate, _reference, _target

    anchor = selection(snapshot, identifier)
    current = _candidate(snapshot, identifier, allow_unreviewed=bool(anchor))
    target = _target(snapshot, identifier)
    marked = regions(snapshot, identifier, target) if regions_override is None else regions_override
    if regions_override is not None:
        from diffeoforge.pilot_regions import validate

        manifest = study._verify_manifest(snapshot.study_directory)
        validate(
            {target: marked} if marked else {},
            {r["filename"]: r["sha256"] for r in manifest["inputs"]["subjects"]},
        )
    baseline = local_strategy_reference(snapshot, "baseline")
    references = {}
    for ref in (anchor, baseline):
        if ref and ref["directory"] not in references:
            references[ref["directory"]] = verify_reference(ref)
    for comparison in (anchor, baseline):
        latest_density = next((r for r in reversed(context["cases"])
                               if r.get("family", r.get("goal")) == "density"
                               and (r.get("comparison") or r.get("reference")) == comparison
                               and r.get("fit") and r.get("outcome") in {"same", "better"}
                               and not r.get("severe")), None)
        if latest_density:
            ref = latest_density["fit"]
            references[ref["directory"]] = verify_reference(ref)
    inspected = context["allowed"].get(identifier, False)
    from diffeoforge.guided_response import history

    response_cases, response_evidence = history(context['cases'], anchor, marked)
    current_reference = _reference(snapshot, identifier, target) if inspected else None
    capture_reference = anchor or current_reference
    regional_capture = None
    if (marked and capture_reference
            and any(r.get('purpose', 'problem') == 'problem' for r in marked)):
        from diffeoforge.regional_search import capture

        regional_capture = capture(references.get(capture_reference['directory'], snapshot),
            capture_reference,
            [r for r in marked if r.get('purpose', 'problem') == 'problem'])
    verified = dict(anchor=anchor, baseline=baseline, current=current, target=target,
                regions=marked,
                current_reference=current_reference,
                severe=severe_regression(snapshot, identifier), references=references,
                context=context, response_cases=response_cases, response_evidence=response_evidence,
                regional_capture=regional_capture,
                spatial_diagonal=study._verify_manifest(snapshot.study_directory)['template_diagonal'])
    from diffeoforge.regional_continuation import prepare_preview

    if allow_continuation:
        verified["_regional_continuation_preview"] = prepare_preview(snapshot, identifier, verified)
    return verified


def propose(snapshot, identifier, request, data):
    """One explicit, meaningful test, retaining human preference independently of its seed."""
    info = guided.record(snapshot)
    strategy = info.get("strategy") or {}
    context, marked = data["context"], data["regions"]
    baseline = data.get("baseline")
    from_base = request.startswith("base:")
    if from_base and not baseline:
        raise ValueError("No earlier settings are bound to this test")
    reference = baseline if from_base else data["anchor"] or data["current_reference"]
    parent = data["references"].get(reference["directory"], snapshot)
    retained = next(c for c in parent.candidates if c.candidate_id == reference["candidate_id"])
    base_values, base_method, target = reference["values"], reference["method"], reference["target"]
    explicit = ":" in request or request == "other_method"
    symptom = "unsure" if ":" in request else request
    # A concrete marked-patch symptom is more useful than an unchanged Unsure default.
    if symptom == "unsure" and marked:
        symptom = next((r["symptom"] for r in marked if r["symptom"] != "unsure"), symptom)
    if request.startswith("regional:"):
        symptom = request.split(":", 1)[1]
    if request == "goal:regional" or request.startswith("regional:") or symptom in {
            "gap", "thickness", "position", "curvature", "alignment", "topology", "view"}:
        from diffeoforge.regional_pilot import proposal as local_proposal

        return local_proposal(snapshot, identifier, data, symptom=symptom)
    if not explicit or request == "goal:optimize":
        from diffeoforge.regional_continuation import proposal as numerical_proposal

        numerical = numerical_proposal(snapshot, identifier, data)
        if numerical:
            return numerical
    result = proposal(snapshot, identifier, symptom, adaptive=True,
                      starting_from_saved=bool(reference), regions_override=marked)
    goal = request.split(":", 1)[1] if ":" in request else result["goal"]
    if goal not in DESCRIPTIONS:
        raise ValueError("Unknown targeted adjustment")
    cases = data.get('response_cases', context["cases"])
    relevant = [r for r in cases if r["method"] == base_method and r["target"] == target]
    # New human-preferred fields start a new local search. An exact old field/settings
    # combination does not become new merely because it is opened again.
    local = [r for r in relevant if (r.get("comparison") or r.get("reference")) == reference]
    seed, seed_parent, numerical = reference, parent, retained
    feedback = (context["feedback"].get(identifier) or {}).get("feedback") or {}
    if (data["current_reference"] and feedback.get("outcome") == "same"
            and not data["severe"] and info.get("goal") != "optimize"
            and iteration_limited(data["current"])):
        # A capped new field may need numerical completion, while the good comparison
        # remains the old field. This does not promote or approve the new anatomy.
        seed, seed_parent, numerical = data["current_reference"], snapshot, data["current"]
    extended = any(r.get("goal") == "optimize" and r.get("reference") == seed for r in cases)
    can_optimize = seed_parent.plan.pilot_subject_count == 1 and iteration_limited(numerical) \
        and not extended
    reason = ""
    if not explicit and can_optimize and symptom != "distortion":
        goal = "optimize"
    elif not explicit and symptom in {"detail", "unsure"}:
        fallback = "weight" if marked and base_values["attachment_kernel_width"] <= \
            min(r["radius"] for r in marked) / 2 else "detail"
        goal, reason = next_hypothesis(local, base_method, target, fallback)
        from diffeoforge.guided_response import choose

        response = choose(local, fallback)
        if response:
            goal, reason = response
    elif not explicit and goal != 'optimize':
        from diffeoforge.guided_response import choose

        response = choose(local, goal)
        if response:
            goal, reason = response
    elif goal != "optimize":
        seed, seed_parent = reference, parent
    available, blocked = True, ""
    step = 0
    if goal == "optimize":
        values, method = seed["values"], seed["method"]
        available = can_optimize
        blocked = ("This saved field has already had a longer optimization test. Choose "
                   "a different adjustment; parameter tests can continue."
                   if extended else "Longer optimization requires an inspected single-form "
                   "fit with an explicit iteration-limit stop.")
        if can_optimize:
            from diffeoforge.config import load_config
            from diffeoforge.regional_fit import declaration

            if declaration(load_config(numerical.config_path)):
                available = False
                blocked = ("Continue with Improve marked areas to preserve the full field "
                           "chain and local objective. A global extension cannot discard them.")
    elif goal == "other_method":
        seed, seed_parent = reference, parent
        values, method = base_values, "varifold" if base_method == "current" else "current"
        available = not any(r["method"] == method and r["target"] == target
                            and r["values"] == values for r in cases)
        blocked = "This method/settings pair has a saved result. Inspect it or change a parameter."
    elif goal == "density":
        seed, seed_parent = reference, parent
        # Repeat density on its most recent inspected, non-worse nested field; no
        # projection, no promotion of that field as the retained comparison.
        latest = next((r for r in reversed(local) if r.get("family", r.get("goal")) == "density"
                       and r.get("fit") and r.get("outcome") in {"same", "better"}
                       and not r.get("severe")
                       and r.get('response', {}).get('status') not in {'worse', 'tradeoff'}
                       and not r.get('response', {}).get('global_worse')), None)
        if latest:
            seed = latest["fit"]
            seed_parent = data["references"][seed["directory"]]
        values = guided.adjusted_values(seed["values"], goal, conservative=True)
        method = base_method
        available = seed_parent.plan.pilot_subject_count == 1 and \
            seed_parent.attachment_comparison["controls"]["count"] * 1.5 <= 2000
        blocked = ("This density test would exceed the 2,000-control resource guard or lacks "
                   "a single-form field. Other parameter tests and input checks remain available.")
        reason += ("Preserve the saved field and expand its controls; "
                   "compare against your retained fit. ")
    else:
        seed, seed_parent = reference, parent
        method = base_method
        # Increase contrast after SAME, rather than approaching the unchanged baseline.
        # Worsening tests retain the earlier field; the automatic family chooser moves on.
        for step in range(9):
            values = guided.adjusted_values(base_values, goal, conservative=True, step=step)
            if not any(r["values"] == values and r.get("reference") == reference
                       for r in relevant):
                break
        else:
            available = False
            blocked = ("This parameter has reached the guided scale guard relative to this "
                       "starting fit. Choose another adjustment or a different saved starting fit.")
        if step:
            reason += "Earlier tests at smaller contrasts did not resolve this area. "
    title, description = DESCRIPTIONS[goal]
    measured_rows = [r for r in local if r.get('response')]
    if measured_rows:
        counts = {status: sum(r['response']['status'] == status for r in measured_rows)
                  for status in ('improved', 'unchanged', 'worse', 'tradeoff')}
        reason = (f"Same marked areas, {len(measured_rows)} saved tests: "
                  f"{counts['improved']} with lower distances, "
                  f"{counts['unchanged']} similar, "
                  f"{counts['worse'] + counts['tradeoff']} worse or mixed. " + reason)
        prior = [r for r in measured_rows if r.get('family', r.get('goal')) == goal]
        if explicit and prior and (prior[-1]['response']['status'] in {'worse', 'tradeoff'}
                                  or prior[-1]['response']['global_worse']):
            reason += ("This direction previously worsened the marked area or whole shape. "
                       "This is an optional different-scale test, not the suggested next step. ")
    if goal not in {"density", "optimize", "other_method"}:
        key = next(k for k in values if values[k] != base_values[k])
        ratio = values[key] / base_values[key]
        label = {"attachment_kernel_width": "surface detail scale",
                 "deformation_kernel_width": "movement scale",
                 "noise_std": "tolerance for surface mismatch"}[key]
        reason += f"Test {label} at {ratio:.0%} of the retained fit's value " \
                  f"({base_values[key]:.5g} → {values[key]:.5g}). "
    if feedback.get("outcome") == "worse":
        reason = "Your last result was worse: keep the earlier starting fit. " + reason
    elif feedback.get("outcome") == "same" and goal != "optimize":
        reason = "You saw no useful change: test a stronger contrast or another cause. " + reason
    if marked:
        reason += f"Recheck {len(marked)} marked area(s) and the rest of the shape separately. "
    approved = [r["approval"] for r in cases if r.get("approval")
                and r["method"] == method and r["values"] == values]
    covered = {r["filename"] for r in approved} | {target}
    result.update(goal=goal, title=title, reason=reason + description, available=available,
                  blocked_reason=blocked, method=method, values=values, target=target,
                  anchor=reference, initialization_reference=seed, from_base=from_base,
                  remaining_checks=len(set(info["pilot_order"]) - covered),
                  hypothesis_count=strategy.get("hypothesis_count", 0),
                  contrast_level=step, numerical_extension=goal == "optimize",
                  response_evidence=data.get('response_evidence', []),
                  initialization="nested" if goal == "density" else
                  "learned" if goal in {"optimize", "detail", "weight", "smooth"}
                  and seed_parent.plan.pilot_subject_count == 1 else "fresh",
                  optimization_iterations=numerical.metrics["maximum_iterations"] * 2
                  if goal == "optimize" and can_optimize else None)
    if not available and not explicit:
        for alternative in ("detail", "weight", "local_motion", "density", "motion", "smooth"):
            if alternative == goal:
                continue
            follow = propose(snapshot, identifier, "goal:" + alternative, data)
            if follow["available"]:
                follow["reason"] = blocked + " " + follow["reason"]
                return follow
    return result
