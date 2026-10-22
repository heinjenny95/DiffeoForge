"""Interactive method preference, refinement and coverage; preparation never fits."""

from __future__ import annotations

from pathlib import Path

from diffeoforge import reference_calibration_study as study
from diffeoforge import reference_guided_pilot as guided
from diffeoforge.mesh import sha256_file
from diffeoforge.pilot_recovery import DESCRIPTIONS, capture, proposal


def _candidate(snapshot, identifier, *, allow_unreviewed=False):
    from diffeoforge.guided_feedback import inspected

    candidate = next(c for c in snapshot.candidates if c.candidate_id == identifier)
    metrics = candidate.metrics or {}
    if (candidate.status != "completed"
            or (not allow_unreviewed and not inspected(snapshot, identifier))
            or metrics.get("completed") is not True
            or type(metrics.get("invalid_face_count")) is not int
            or metrics["invalid_face_count"] != 0
            or metrics.get("subject_reconstruction_count") != snapshot.plan.pilot_subject_count):
        raise ValueError("Inspect this complete, valid fit before choosing a starting method")
    return candidate


def starting_allowed(snapshot, identifier):
    try:
        _candidate(snapshot, identifier)
        return True
    except ValueError:
        return False


def _target(snapshot, identifier):
    info = guided.record(snapshot)
    decisions = snapshot.subject_decisions.get(identifier, {})
    return info["target"] or next(
        (n for n, result in decisions.items() if result in {"fail", "uncertain"}),
        snapshot.plan.selected_pilot_subjects[0].filename)


def _reference(snapshot, identifier, target=None):
    candidate = _candidate(snapshot, identifier)
    return dict(
        directory=str(snapshot.study_directory), candidate_id=identifier,
        manifest_sha256=sha256_file(snapshot.study_directory / study.STUDY_MANIFEST),
        binding=study._candidate_review_binding(candidate),
        method=snapshot.attachment_comparison["methods"][identifier],
        values=next(c.values for c in snapshot.current_stage.candidates
                    if c.candidate_id == identifier),
        target=target or _target(snapshot, identifier),
    )


def _verify_reference(reference):
    root = Path(reference["directory"])
    if sha256_file(root / study.STUDY_MANIFEST) != reference["manifest_sha256"]:
        raise ValueError("Starting-method source manifest changed")
    parent = study.load_reference_calibration_study(root)
    if _reference(parent, reference["candidate_id"], reference["target"]) != reference:
        raise ValueError("Starting-method fit, review or settings binding changed")
    return parent


def _preference(snapshot):
    for event in reversed(study._load_events(snapshot.study_directory)):
        if event["event"] == "guided_method_preference":
            reference = event["preference"]
            if reference != _reference(snapshot, reference["candidate_id"], reference["target"]):
                raise ValueError("The saved starting-method preference no longer matches this fit")
            return reference
    return (guided.record(snapshot).get("strategy") or {}).get("preference")


def _compatible(snapshot, method, values, cases=()):
    rows = [*guided.record(snapshot)["approved"],
            *(c["approval"] for c in cases if c.get("approval"))]
    return list({(r["directory"], r["candidate_id"]): r for r in rows
                 if r["method"] == method and r["values"] == values}.values())


def _context(snapshot):
    """Read historical cases in background; avoid repeating unchanged finished trials."""
    with study.calibration_verification_scope():
        return _read_context(snapshot)


def _read_context(snapshot):
    cases, goals = [], []
    for row in [*guided.record(snapshot)["history"], None]:
        other = snapshot
        if row:
            root = Path(row["directory"])
            if sha256_file(root / study.STUDY_MANIFEST) != row["manifest_sha256"]:
                raise ValueError("Saved pilot history changed")
            other = study.load_reference_calibration_study(root)
        info = guided.record(other)
        if not info or info["phase"] == "joint":
            continue
        if info["origin"] != guided.record(snapshot)["origin"]:
            raise ValueError("Saved pilot history belongs to another source cohort")
        if info.get("goal") in set(DESCRIPTIONS) - {"other_method"}:
            goals.append(info["goal"])
        for candidate in other.candidates:
            if candidate.status == "completed":
                cases.append(dict(method=other.attachment_comparison["methods"][candidate.candidate_id],
                    values=next(c.values for c in other.current_stage.candidates
                                if c.candidate_id == candidate.candidate_id),
                    target=info["target"],
                    approval=guided._approved_record(other, candidate.candidate_id)
                    if other.visual_reviews.get(candidate.candidate_id) is True else None))
    return cases, goals[-1] if goals else None


def state(snapshot):
    """Prepared in the background together with the evidence presentation."""
    info = guided.record(snapshot)
    preference = _preference(snapshot)
    preferred = preference["method"] if preference else info.get("selected_method")
    cases, last = _context(snapshot)
    values = snapshot.plan.effective_values
    approved = _compatible(snapshot, preferred, values, cases) if preferred else []
    covered = {r["filename"] for r in approved}
    for candidate in snapshot.candidates:
        if (snapshot.visual_reviews.get(candidate.candidate_id) is True
                and snapshot.attachment_comparison["methods"][candidate.candidate_id] == preferred
                and info["target"]):
            covered.add(info["target"])
    from diffeoforge.guided_feedback import presentation

    return dict(preferred=preferred, checked=len(covered), total=len(info["pilot_order"]),
                phase=info["phase"], preference=preference, cases=cases, last_adjustment=last,
                feedback={c.candidate_id: presentation(snapshot, c.candidate_id)
                          for c in snapshot.candidates if c.status == "completed"},
                allowed={c.candidate_id: starting_allowed(snapshot, c.candidate_id)
                         for c in snapshot.candidates if c.status == "completed"})


def remaining_forms(snapshot, identifier, *, context):
    method = snapshot.attachment_comparison["methods"][identifier]
    values = next(c.values for c in snapshot.current_stage.candidates
                  if c.candidate_id == identifier)
    rows = _compatible(snapshot, method, values, context["cases"])
    covered = {r["filename"] for r in rows} | {guided.record(snapshot)["target"]}
    return [n for n in guided.record(snapshot)["pilot_order"] if n not in covered]


def trial_proposal(snapshot, identifier, symptom, *, context=None):
    """Explain one hypothesis and its downstream checks; no global trial cap."""
    from diffeoforge.guided_feedback import regions, selection

    anchor = selection(snapshot, identifier)
    _candidate(snapshot, identifier, allow_unreviewed=bool(anchor))
    marked = regions(snapshot, identifier, _target(snapshot, identifier))
    proposed = proposal(snapshot, identifier, "unsure" if ":" in symptom else symptom,
                        adaptive=True, starting_from_saved=bool(anchor),
                        regions_override=marked)
    info = guided.record(snapshot)
    strategy = info.get("strategy") or {}
    baseline = strategy.get("baseline")
    cases, last = (context["cases"], context["last_adjustment"]) if context else _context(snapshot)
    from_base = symptom.startswith("base:")
    if from_base and not baseline:
        raise ValueError("No earlier settings are bound to this test")
    if ":" in symptom:
        goal = symptom.split(":", 1)[1]
        if goal not in DESCRIPTIONS:
            raise ValueError("Unknown targeted adjustment")
        proposed.update(goal=goal, title=DESCRIPTIONS[goal][0], reason=DESCRIPTIONS[goal][1])
    elif symptom == "detail" and last in {"detail", "local_motion"}:
        next_goal = "local_motion" if last == "detail" else "weight"
        proposed.update(goal=next_goal, title=DESCRIPTIONS[next_goal][0],
                        reason=DESCRIPTIONS[next_goal][1])
    base_values = baseline["values"] if from_base else snapshot.plan.effective_values
    base_method = (baseline["method"] if from_base
                   else snapshot.attachment_comparison["methods"][identifier])
    goal = proposed["goal"]
    target = baseline["target"] if from_base else _target(snapshot, identifier)
    if anchor and not from_base:
        base_values, base_method, target = anchor["values"], anchor["method"], anchor["target"]

    def choice(key):
        method = ("varifold" if base_method == "current" else "current") \
            if key == "other_method" else base_method
        values = base_values if key == "other_method" else guided.adjusted_values(base_values, key)
        seen = any(r["method"] == method and r["target"] == target and r["values"] == values
                   for r in cases)
        return method, values, seen

    method, values, seen = choice(goal)
    if seen and ":" not in symptom and symptom != "other_method":
        for alternative in ("local_motion", "detail", "weight", "motion", "smooth"):
            method, values, seen = choice(alternative)
            if not seen:
                goal = alternative
                break
    proposed.update(goal=goal, title=DESCRIPTIONS[goal][0], reason=DESCRIPTIONS[goal][1])
    approved = _compatible(snapshot, method, values, cases)
    covered = {r["filename"] for r in approved} | {target}
    proposed.update(method=method, values=values, target=target, from_base=from_base,
                    anchor=anchor if not from_base else baseline,
                    remaining_checks=len(set(info["pilot_order"]) - covered),
                    available=not seen, hypothesis_count=strategy.get("hypothesis_count", 0))
    return proposed


def verify_strategy(info, record, manifest):
    """A new protocol has per-action scope, provenance and QC gates, not a total cap."""
    strategy = info.get("strategy")
    if (not isinstance(strategy, dict) or info.get("coverage_extension")
            or info["screen_trial_limit"] is not None
            or type(info["screen_trials_spent"]) is not int or info["screen_trials_spent"] < 2):
        return False
    previous = strategy.get("previous")
    if previous:
        root = Path(previous["directory"])
        if sha256_file(root / study.STUDY_MANIFEST) != previous["manifest_sha256"]:
            raise ValueError("Interactive pilot predecessor changed")
        parent = study._verify_manifest(root)["attachment_comparison"]["guided"]
        if (parent["origin"] != info["origin"] or info["screen_trials_spent"] !=
                parent["screen_trials_spent"] + (0 if info["phase"] == "joint"
                                                  else len(record["methods"]))):
            return False
    elif info["phase"] != "screen" or info["screen_trials_spent"] != 2 or info["approved"]:
        return False
    if (len(record["methods"]) != (2 if info["phase"] == "screen" else 1)
            or not set(strategy.get("difficult_targets", [])) <= set(info["pilot_order"])):
        return False
    for key in ("preference", "baseline"):
        if strategy.get(key):
            _verify_reference(strategy[key])
    if strategy.get("anchor"):
        from diffeoforge.guided_feedback import verify_reference

        verify_reference(strategy["anchor"])
    values = manifest["plan"]["baseline_effective_values"]
    if info["phase"] in {"validate", "joint"} and any(
            r["values"] != values or r["method"] not in record["methods"].values()
            for r in info["approved"]):
        return False
    return True


def _plan_transition(snapshot, action, identifier, *, goal=None):
    """Read-only planning; the shared verification scope ends before any writes."""
    info = guided.record(snapshot)
    source, _ = guided._origin(snapshot.study_directory)
    approved = list(info["approved"])
    guided.verify_approvals(approved)
    strategy = dict(info.get("strategy") or {})
    strategy["previous"] = dict(directory=str(snapshot.study_directory),
        manifest_sha256=sha256_file(snapshot.study_directory / study.STUDY_MANIFEST))
    history = [*info["history"], dict(**strategy["previous"], outcome="adaptive_" + action)]
    values = snapshot.plan.effective_values
    cases, _last = _context(snapshot)
    feedback = None
    preference = _preference(snapshot)
    if action == "recover":
        proposed = trial_proposal(snapshot, identifier, goal or "unsure")
        if not proposed["available"]:
            raise ValueError("This unchanged combination was already tested. Inspect saved "
                             "alternatives or choose another adjustment; no fit was prepared.")
        baseline_snapshot, baseline_id = snapshot, identifier
        if proposed["anchor"]:
            from diffeoforge.guided_feedback import verify_reference

            reference = proposed["anchor"]
            baseline_snapshot = verify_reference(reference)
            baseline_id = reference["candidate_id"]
        target, values, methods = proposed["target"], proposed["values"], (proposed["method"],)
        from diffeoforge.guided_feedback import regions

        feedback = capture(baseline_snapshot, baseline_id, target,
                           regions=regions(snapshot, identifier, target))
        strategy["baseline"] = _reference(baseline_snapshot, baseline_id, target)
        if proposed["anchor"]:
            strategy["anchor"] = proposed["anchor"]
        strategy["difficult_targets"] = list(dict.fromkeys(
            [target, *strategy.get("difficult_targets", [])]))
        strategy["hypothesis_count"] = strategy.get("hypothesis_count", 0) + 1
        preference = preference if preference and preference["method"] == methods[0] else None
        approved = _compatible(snapshot, methods[0], values, cases)
        phase, goal = "refine", proposed["goal"]
    elif action in {"confirm", "confirm_start"}:
        accepted, accepted_id = snapshot, identifier
        if action == "confirm_start":
            from diffeoforge.guided_feedback import selection, verify_reference

            anchor = selection(snapshot, identifier)
            if not anchor:
                raise ValueError("Choose an inspected starting fit first")
            accepted, accepted_id = verify_reference(anchor), anchor["candidate_id"]
        row = guided._approved_record(accepted, accepted_id)
        preference = _reference(accepted, accepted_id)
        values, methods = row["values"], (row["method"],)
        approved = list({r["filename"]: r for r in
            [*_compatible(snapshot, methods[0], values, cases), row]}.values())
        covered = {r["filename"] for r in approved}
        order = list(dict.fromkeys([*strategy.get("difficult_targets", []), *info["pilot_order"]]))
        target = next((n for n in order if n not in covered), None)
        phase = "validate" if target else "joint"
    elif action == "tie":
        if len(snapshot.candidates) != 2:
            raise ValueError("A further method comparison needs two reviewed methods")
        approved.extend(guided._approved_record(snapshot, c.candidate_id)
                        for c in snapshot.candidates)
        covered = {r["filename"] for r in approved if r["values"] == values}
        target = next((n for n in info["pilot_order"] if n not in covered), None)
        if target is None:
            raise ValueError("All selected forms were compared; choose a starting method")
        methods, phase, preference = ("current", "varifold"), "screen", None
    else:
        raise ValueError("Unknown interactive pilot action")
    strategy["preference"] = preference
    return dict(source=source, previous=snapshot, phase=phase, target=target, methods=methods,
        values=values, approved=approved, history=history, spent=info["screen_trials_spent"],
        goal=goal, feedback=feedback, strategy=strategy)


def transition(snapshot, action, identifier, *, goal=None):
    """Called under the existing transition lock; never dispatch an optimizer."""
    if action in {"select_start", "feedback"}:
        from diffeoforge.guided_feedback import save_feedback, select

        return (select(snapshot.study_directory, identifier, goal) if action == "select_start"
                else save_feedback(snapshot.study_directory, identifier, goal))
    if action == "prefer":
        reference = _reference(snapshot, identifier)
        study._append_event(snapshot.study_directory, "guided_method_preference", dict(
            preference=reference, anatomical_approval_created=False, optimizer_started=False))
        return study.load_reference_calibration_study(snapshot.study_directory)
    if guided.record(snapshot)["phase"] == "joint" and action != "recover":
        raise ValueError("Review the joint fit, or refine a failed form before continuing")
    with study.calibration_verification_scope():
        verified = study.load_reference_calibration_study(snapshot.study_directory)
        plan = _plan_transition(verified, action, identifier, goal=goal)
    result = guided._batch(**plan)
    study._append_event(snapshot.study_directory, "guided_pilot_decision", dict(
        action="adaptive_" + action, candidate_id=identifier, goal=plan["goal"],
        next_directory=str(result.study_directory),
        next_manifest_sha256=sha256_file(result.study_directory / study.STUDY_MANIFEST),
        anatomical_approval_created=False, optimizer_started=False))
    return result
