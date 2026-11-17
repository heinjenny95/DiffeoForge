"""Interactive method preference, refinement and coverage; preparation never fits."""

from __future__ import annotations

from pathlib import Path

from diffeoforge import reference_calibration_study as study
from diffeoforge import reference_guided_pilot as guided
from diffeoforge.mesh import sha256_file
from diffeoforge.pilot_recovery import DESCRIPTIONS, capture


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
    def common_objective(row):
        manifest = study._verify_manifest(Path(row["directory"]))
        if manifest.get("attachment_comparison", {}).get("regional_objective"):
            return False
        marker = (guided.record(snapshot).get("strategy") or {}).get("shared_model_check")
        if marker:
            from diffeoforge.guided_shared_check import compatible

            parent = study.load_reference_calibration_study(Path(row["directory"]))
            candidate = next(c for c in parent.candidates
                             if c.candidate_id == row["candidate_id"])
            return compatible(marker, candidate)
        progress = (guided.record(snapshot).get("strategy") or {}).get("form_progress")
        if progress:
            from diffeoforge.pilot_form_progress import compatible

            return compatible(row, progress["protocol"])
        return True

    return list({(r["directory"], r["candidate_id"]): r for r in rows
                 if r["method"] == method and r["values"] == values
                 and common_objective(r)}.values())


def _context(snapshot):
    """Read historical cases in background; avoid repeating unchanged finished trials."""
    with study.calibration_verification_scope():
        return _read_context(snapshot)


def _read_context(snapshot):
    from diffeoforge.guided_density import controls_for
    from diffeoforge.pilot_form_progress import is_common_check

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
        individual = other.plan.pilot_subject_count == 1 and not is_common_check(info)
        for candidate in other.candidates:
            if candidate.status == "completed":
                feedback = [e for e in study._load_events(other.study_directory)
                            if e["event"] == "guided_fit_feedback"
                            and e["current"]["candidate_id"] == candidate.candidate_id]
                cases.append(dict(method=other.attachment_comparison["methods"][candidate.candidate_id],
                    values=next(c.values for c in other.current_stage.candidates
                                if c.candidate_id == candidate.candidate_id),
                    target=info["target"],
                    goal=info.get("goal"),
                    individual=individual,
                    early_density_comparison=bool(
                        other.attachment_comparison.get("early_density_comparison")),
                    reference=other.attachment_comparison.get("refinement", {}).get("reference"),
                    comparison=(info.get("strategy") or {}).get("anchor"),
                    family=(info.get("strategy") or {}).get("search_family", info.get("goal")),
                    regional_recipe=(info.get("strategy") or {}).get("regional_recipe"),
                    regions=(info.get("feedback") or {}).get("regions", []),
                    iterations=other.attachment_comparison["iterations"],
                    stop=(candidate.metrics or {}).get("optimizer_stop_signal"),
                    control_count=controls_for(
                        other.attachment_comparison, candidate.candidate_id)["count"],
                    severe=any(r.get("refinement_guard", {}).get("severe") is True for r in
                        (candidate.metrics or {}).get("attachment_comparison", {}).get(
                            "subjects", {}).values()),
                    fit=_reference(other, candidate.candidate_id)
                    if starting_allowed(other, candidate.candidate_id) else None,
                    region_outcomes=[r["marked_regions"]["outcome"] for r in
                        (candidate.metrics or {}).get("attachment_comparison", {}).get(
                            "subjects", {}).values() if r.get("marked_regions")],
                    outcome=feedback[-1]["outcome"] if feedback else
                    "rejected" if other.visual_reviews.get(candidate.candidate_id) is False
                    else None,
                    approval=guided._approved_record(other, candidate.candidate_id)
                    if other.visual_reviews.get(candidate.candidate_id) is True else None))
    return cases, goals[-1] if goals else None


def state(snapshot):
    """Prepared in the background together with the evidence presentation."""
    # Context, approvals and next-form previews traverse many of the same
    # ancestors. One read action must share verification across the WHOLE view,
    # not close its scope after _context and rebuild each lineage for every row.
    with study.calibration_verification_scope():
        return _read_state(snapshot)


def _read_state(snapshot):
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
                and info["target"]
                and not snapshot.attachment_comparison.get("regional_objective")):
            covered.add(info["target"])
    from diffeoforge.guided_feedback import presentation
    from diffeoforge.method_comparison_followup import provisional_comparison

    result = dict(preferred=preferred, checked=len(covered), total=len(info["pilot_order"]),
                phase=info["phase"], preference=preference, cases=cases, last_adjustment=last,
                feedback={c.candidate_id: presentation(snapshot, c.candidate_id)
                          for c in snapshot.candidates if c.status == "completed"},
                allowed={c.candidate_id: starting_allowed(snapshot, c.candidate_id)
                         for c in snapshot.candidates if c.status == "completed"})
    result["provisional_comparison"] = provisional_comparison(snapshot, context=result)
    from diffeoforge.guided_early_density import preview as density_comparison

    result["density_comparisons"] = {
        c.candidate_id: option for c in snapshot.candidates
        if (option := density_comparison(snapshot, c.candidate_id, result)) is not None
    }
    from diffeoforge.guided_failed_parent import preview
    from diffeoforge.pilot_multiscale_failure import diagnose as stage_failure
    from diffeoforge.pilot_multiscale_study import marker as multiscale_marker

    multiscale = multiscale_marker(snapshot.attachment_comparison)
    result["failed_parents"] = {
        c.candidate_id: preview(snapshot, c.candidate_id)
        for c in snapshot.candidates if c.status == "failed" and not multiscale
    }
    result["common_stage_failures"] = {
        c.candidate_id: failure for c in snapshot.candidates
        if (failure := stage_failure(snapshot, c)) is not None
    }
    from diffeoforge.guided_accepted_fit import preview as accepted_fit

    result["accepted_fits"] = {c.candidate_id: accepted_fit(snapshot, c.candidate_id, cases)
                               for c in snapshot.candidates
                               if result["allowed"].get(c.candidate_id)}
    if snapshot.attachment_comparison.get("regional_objective"):
        from diffeoforge.guided_shared_check import preview as shared_preview

        result["shared_model_checks"] = {
            c.candidate_id: shared_preview(snapshot, c.candidate_id) for c in snapshot.candidates
            if snapshot.visual_reviews.get(c.candidate_id) is True}
    if (snapshot.plan.pilot_subject_count == 1 and info["phase"] != "joint"
            and (snapshot.attachment_comparison.get("regional_objective")
                 or (info.get("strategy") or {}).get("form_progress"))):
        from diffeoforge.pilot_form_progress import preview

        result["next_forms"] = {c.candidate_id: preview(snapshot, c.candidate_id, result)
                                for c in snapshot.candidates
                                if snapshot.visual_reviews.get(c.candidate_id) is True}
    if (info.get("strategy") or {}).get("form_progress"):
        from diffeoforge.pilot_common_model import approvals
        from diffeoforge.pilot_common_model import preview as common_preview
        from diffeoforge.pilot_form_progress import individual_reviews, marker

        progress = marker(snapshot)
        result["checked"] = len(approvals(snapshot, result, progress))
        result["form_progress_summary"] = dict(
            shapes=len(individual_reviews(progress, result, info["pilot_order"])),
            checked=result["checked"], total=result["total"])
        result["common_recovery"] = common_preview(snapshot, result, info["target"])
        from diffeoforge.pilot_form_progress import compatible, proposal

        result["common_revision"] = {}
        failure = (result["common_recovery"] or {}).get("stage_failure")
        if failure and failure["directory"] == snapshot.study_directory:
            result["common_stage_failures"][failure["candidate_id"]] = failure
        if (snapshot.plan.pilot_subject_count == 1 and info["phase"] != "joint"
                and not snapshot.attachment_comparison.get("regional_objective")
                and not (multiscale and multiscale["stage"] == "capture")):
            for candidate in snapshot.candidates:
                if (snapshot.visual_reviews.get(candidate.candidate_id) is True
                        and not compatible(
                            guided._approved_record(snapshot, candidate.candidate_id),
                            progress["protocol"])):
                    result["common_revision"][candidate.candidate_id] = proposal(
                        snapshot, candidate.candidate_id, result, model=True, revise=True)
    from diffeoforge.pilot_form_progress import preview as starting_preview
    from diffeoforge.pilot_form_progress import uses_starting_progress

    for identifier, data in result["feedback"].items():
        if data and any(r["approved"] and not r["current"] and r["reference"] == data["selected"]
               for r in data["choices"]) and uses_starting_progress(snapshot, identifier):
            data["starting_form_progress"] = starting_preview(
                snapshot, identifier, result, starting_fit=True)
    return result


def remaining_forms(snapshot, identifier, *, context):
    method = snapshot.attachment_comparison["methods"][identifier]
    values = next(c.values for c in snapshot.current_stage.candidates
                  if c.candidate_id == identifier)
    rows = _compatible(snapshot, method, values, context["cases"])
    covered = {r["filename"] for r in rows} | {guided.record(snapshot)["target"]}
    return [n for n in guided.record(snapshot)["pilot_order"] if n not in covered]


def prepare_proposals(snapshot, context):
    """Verify every selectable preview in the background read scope, never in a Qt slot.

    These are presentation data only. Preparation/dispatch still recalculates the
    selected request against fresh bound evidence in its existing worker.
    """
    from diffeoforge.guided_search import inputs, propose
    from diffeoforge.pilot_regions import SYMPTOMS

    requests = [*SYMPTOMS, "other_method", *("goal:" + k for k in DESCRIPTIONS),
                *("regional:" + k for k in SYMPTOMS)]
    with study.calibration_verification_scope():
        context["proposals"] = {}
        context["working_proposals"] = {}
        context["failed_proposals"] = {}
        chosen = next((event for event in reversed(study._load_events(snapshot.study_directory))
                       if event["event"] == "guided_starting_fit_selected"), None)
        for candidate in snapshot.candidates:
            identifier = candidate.candidate_id
            if candidate.status == "failed":
                if (context.get("failed_parents", {}).get(identifier) or {}).get("available"):
                    from diffeoforge.guided_failed_parent import inputs as parent_inputs
                    from diffeoforge.guided_failed_parent import propose as parent_propose

                    verified = parent_inputs(snapshot, identifier, context)
                    context["failed_proposals"][identifier] = {
                        request: parent_propose(snapshot, identifier, request, verified)
                        for request in requests
                        if request.startswith(("goal:", "regional:"))
                        and request != "goal:optimize"
                        or request == "other_method"
                    }
                continue
            if not (context["allowed"].get(identifier)
                    or (context["feedback"].get(identifier) or {}).get("selected")):
                continue
            verified = inputs(snapshot, identifier, context)
            context["proposals"][identifier] = {
                request: propose(snapshot, identifier, request, verified) for request in requests}
            selected = (context["feedback"].get(identifier) or {}).get("selected")
            if selected and ((selected["directory"], selected["candidate_id"]) != (
                    str(snapshot.study_directory), identifier) or
                    (chosen and chosen.get("editing_candidate_id") == identifier
                     and chosen["reference"] == selected)):
                from diffeoforge import guided_working_fit as working

                parent, working_data = working.inputs(snapshot, identifier, context,
                                                      verified=verified)
                context["working_proposals"][identifier] = {
                    request: working.propose(parent, request, working_data) for request in requests}
        context["fit_direction"] = (_prepare_fit_direction(snapshot, context, chosen)
                                    or _marked_trial_direction(snapshot, context, chosen)
                                    or _default_trial_direction(snapshot, context, chosen))
    return context


def default_recovery_symptom(feedback):
    symptom = (feedback.get("feedback") or {}).get("symptom", "unsure")
    if symptom != "unsure":
        return symptom
    return next((row["symptom"] for rows in feedback.get("problem_regions", {}).values()
                 for row in rows if row.get("purpose", "problem") == "problem"), symptom)


def _default_trial_direction(snapshot, context, chosen):
    """Use the verified default adjustment for the reviewed starting method."""
    from diffeoforge.pilot_form_progress import is_common_check

    info = guided.record(snapshot)
    if (not info.get("target") or snapshot.plan.pilot_subject_count != 1
            or info["phase"] == "joint" or is_common_check(info)
            or snapshot.attachment_comparison.get("regional_objective")
            or any(c.status != "completed"
                   or snapshot.visual_reviews.get(c.candidate_id) is not False
                   for c in snapshot.candidates)):
        return None
    methods = snapshot.attachment_comparison["methods"]
    identifiers = ([chosen["editing_candidate_id"]] if chosen else
                   [key for key, method in methods.items() if method == context["preferred"]])
    if len(identifiers) != 1:
        return None
    identifier = identifiers[0]
    feedback = context["feedback"].get(identifier) or {}
    if (feedback.get("needs_direction") or any(feedback.get("problem_regions", {}).values())
            or not context["allowed"].get(identifier)):
        return None
    request = default_recovery_symptom(feedback)
    working = context["working_proposals"].get(identifier)
    proposal = (working or context["proposals"].get(identifier, {})).get(request)
    if (not proposal or not proposal["available"] or proposal["goal"] == "regional"
            or proposal["target"] != info["target"]):
        return None
    seed = proposal["initialization_reference"]
    if not seed or (chosen and seed != chosen["reference"]):
        return None
    choice = next((row for row in feedback["choices"] if row["reference"] == seed), None)
    if choice is None:
        return None
    option = context["density_comparisons"].get(identifier)
    # High disparity alone does not make the optional paired test a recommendation.
    paired = proposal["goal"] == "density" and option and option["reference"] == seed
    return dict(
        mode="density" if paired else "trial", identifier=identifier, current=seed,
        action="adaptive_recover_start" if working else "adaptive_recover",
        title=proposal["title"], start_label=choice["label"], reason=proposal["reason"],
        request=dict(request=request, reference=seed, values=proposal["values"],
                     goal=proposal["goal"], regions=[], reviewed_next=True),
    )


def _marked_trial_direction(snapshot, context, chosen):
    """Offer an already verified local repair from the fit the user just marked."""
    from diffeoforge.guided_feedback import local_region_edit
    from diffeoforge.pilot_form_progress import is_common_check

    info = guided.record(snapshot)
    target = info.get("target")
    if (not target or snapshot.plan.pilot_subject_count != 1 or info["phase"] == "joint"
            or is_common_check(info) or any(snapshot.visual_reviews.values())):
        return None
    choices = []
    for candidate in snapshot.candidates:
        identifier = candidate.candidate_id
        if (candidate.status != "completed" or snapshot.visual_reviews.get(identifier) is not False
                or not context["allowed"].get(identifier)
                or (chosen and chosen.get("editing_candidate_id") != identifier)):
            continue
        if (not chosen and context["preference"]
                and snapshot.attachment_comparison["methods"][identifier] != context["preferred"]):
            continue
        subject = ((candidate.metrics or {}).get("attachment_comparison", {})
                   .get("subjects", {}).get(target, {}))
        if (subject.get("regional_quality") or {}).get("numerical_selection_suitable") is False:
            continue  # A visually better result did not supersede its failed guard.
        feedback = context["feedback"].get(identifier) or {}
        regions = feedback.get("problem_regions", {}).get(target, [])
        edit = local_region_edit(snapshot, identifier, target)
        if (not edit or edit[1] != regions or edit[2] or feedback.get("needs_direction")
                or not any(row.get("purpose", "problem") == "problem" for row in regions)):
            continue
        symptom = default_recovery_symptom(feedback)
        if symptom in {"alignment", "topology", "view"}:
            continue
        request = "regional:" + symptom
        working = context["working_proposals"].get(identifier)
        proposal = (working or context["proposals"][identifier]).get(request)
        if (not proposal or not proposal["available"] or proposal["goal"] != "regional"
                or proposal["target"] != target):
            continue
        seed = proposal["initialization_reference"]
        if not seed or (chosen and seed != chosen["reference"]):
            continue
        choice = next((row for row in feedback["choices"] if row["reference"] == seed), None)
        if choice is None:
            continue
        choices.append((edit[0], dict(
            mode="trial", identifier=identifier, current=seed,
            action="adaptive_recover_start" if working else "adaptive_recover",
            title=proposal["title"], start_label=choice["label"],
            reason="You marked an area that needs work. Prepare one local test that protects "
                   "the surrounding shape, then compare it with this saved fit.",
            request=dict(request=request, reference=seed, values=proposal["values"],
                         goal=proposal["goal"], regions=regions, reviewed_next=True),
        )))
    choices.sort(key=lambda row: row[0], reverse=True)
    if choices and (len(choices) == 1 or choices[0][0] > choices[1][0]):
        return choices[0][1]
    return None


def _prepare_fit_direction(snapshot, context, chosen):
    from diffeoforge.guided_fit_direction import preview

    direction = preview(snapshot, context)
    if direction and direction["mode"] == "return":
        return _prepare_return_direction(context, direction, chosen)
    if not direction or direction["mode"] != "compare":
        return direction

    identifier = direction["identifier"]
    feedback = context["feedback"][identifier]
    selected = feedback["selected"]
    working = context["working_proposals"].get(identifier)
    if not working or selected not in (direction["current"], direction["alternative"]):
        return direction
    # Merely restoring a view or saving relative feedback is not an explicit
    # choice to proceed from one of the compared fields.
    if (not chosen or chosen.get("editing_candidate_id") != identifier
            or chosen["reference"] != selected or feedback["needs_direction"]):
        return direction

    regions = feedback["problem_regions"].get(selected["target"], [])
    symptoms = {row["symptom"] for row in regions if row.get("purpose", "problem") == "problem"}
    if symptoms and symptoms <= {"detail", "missing"}:
        request = "goal:detail"
    elif symptoms == {"distortion"}:
        request = "goal:smooth"
    else:
        request = None
    proposal = working.get(request)
    if proposal and proposal["available"] and proposal["initialization_reference"] == selected:
        choice = next(row for row in feedback["choices"] if row["reference"] == selected)
        count_key = "alternative_cp" if selected == direction["alternative"] else "current_cp"
        count = direction[count_key]
        label = f"{selected['method'].title()} · Test {choice['trial_index']} · {count:,} CP"
        return dict(
            direction, mode="trial", title=proposal["title"], start_label=label,
            reason="This test compares the same marked areas on the selected saved fit. "
                   "Review the affected areas and the rest of the shape after the test.",
            request=dict(request=request, reference=selected, values=proposal["values"],
                         goal=proposal["goal"], regions=regions),
        )
    if not symptoms or symptoms & {"alignment", "topology"}:
        return dict(direction, mode="inputs", current=selected,
                    reason="Inspect how the original template and specimen match before "
                           "choosing another test. This opens the saved input overlay.")
    # Leave refinements and history accessible for marks that do not support
    # one safe preselected adjustment.
    return None


def _prepare_return_direction(context, direction, chosen):
    from diffeoforge.guided_feedback import verify_reference
    from diffeoforge.guided_fit_direction import local_quality_note

    identifier = (chosen or {}).get("editing_candidate_id")
    feedback = context["feedback"].get(identifier) or {}
    working = context["working_proposals"].get(identifier)
    reference = (chosen or {}).get("reference")
    if (not reference or not working or feedback.get("selected") != reference
            or feedback["needs_direction"]):
        return direction
    choice = next((row for row in feedback["choices"] if row["reference"] == reference), None)
    if not choice:
        return direction
    quality = local_quality_note(verify_reference(reference), reference)
    start = dict(direction, identifier=identifier, current=reference, start_label=choice["label"],
                 quality_warning=quality, partial=False)
    regions = feedback["problem_regions"].get(reference["target"], [])
    problem = [row for row in regions if row.get("purpose", "problem") == "problem"]
    if not problem:
        return dict(start, reason=" ".join(filter(None, (
            "Mark the area that still needs improvement on this fit.", quality,
        ))))
    symptom = next((row["symptom"] for row in problem if row["symptom"] != "unsure"), "unsure")
    request = "regional:" + symptom
    proposal = working[request]
    if not proposal["available"] or proposal["initialization_reference"] != reference:
        reason = proposal.get("blocked_reason") or "The saved field cannot seed this adjustment."
        return dict(start, reason=" ".join(filter(None, (reason, quality))))
    return dict(
        start, mode="trial",
        title="Work on remaining marked area" if len(problem) == 1 else
              "Work on remaining marked areas",
        reason=" ".join(filter(None, (
            "Prepare a protected local test from this saved fit. "
            "Review the new result before deciding if it is suitable.", quality,
        ))),
        request=dict(request=request, reference=reference, values=proposal["values"],
                     goal=proposal["goal"], regions=regions),
    )


def trial_proposal(snapshot, identifier, symptom, *, context=None):
    """Fresh preparation check; cached GUI previews never authorize a transition."""
    from diffeoforge.guided_search import inputs, propose

    with study.calibration_verification_scope():
        context = context or state(snapshot)
        return propose(snapshot, identifier, symptom, inputs(snapshot, identifier, context))


def verify_strategy(info, record, manifest, study_root=None):
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
    pair = record.get("early_density_comparison")
    if (len(record["methods"]) != (2 if info["phase"] == "screen" or pair else 1)
            or not set(strategy.get("difficult_targets", [])) <= set(info["pilot_order"])):
        return False
    for key in ("preference", "baseline", "control_basis"):
        if strategy.get(key):
            _verify_reference(strategy[key])
    if strategy.get("anchor"):
        from diffeoforge.guided_feedback import verify_reference

        verify_reference(strategy["anchor"])
    if strategy.get("failure_parent_recovery"):
        from diffeoforge.guided_failed_parent import verify_marker

        verify_marker(strategy["failure_parent_recovery"], info, record, manifest)
    optimization = strategy.get("optimization")
    if optimization:
        from diffeoforge.guided_feedback import verify_reference
        from diffeoforge.guided_progress import iteration_limited

        parent = verify_reference(optimization["reference"])
        candidate = next(c for c in parent.candidates
                         if c.candidate_id == optimization["reference"]["candidate_id"])
        from diffeoforge.pilot_common_model import EFFORT_VERSION
        from diffeoforge.pilot_iteration_accounting import branch_total
        from diffeoforge.reference_attachment_comparison import ITERATIONS

        allowance = candidate.metrics["maximum_iterations"] * 2
        if "version" in optimization:
            if (optimization["version"] != EFFORT_VERSION
                    or type(optimization.get("common_model")) is not bool
                    or optimization.get("initial_iterations") != branch_total(parent, candidate)):
                return False
            if optimization["common_model"]:
                allowance = ITERATIONS
            elif strategy.get("regional_continuation"):
                # A same-objective successor gets one additional block of the
                # prior size. The cumulative branch total is recorded separately.
                allowance = candidate.metrics["maximum_iterations"]
        if (info["phase"] != "refine" or info["goal"] != "optimize"
                or parent.plan.pilot_subject_count != 1 or not iteration_limited(candidate)
                or set(record["methods"].values()) != {optimization["reference"]["method"]}
                or record.get("refinement", {}).get("initialization") != "learned"
                or optimization["reference"] != strategy.get("baseline")
                or record["iterations"] != allowance
                or optimization["iterations"] != record["iterations"]
                or manifest["plan"]["baseline_effective_values"]
                != optimization["reference"]["values"]):
            return False
    elif info.get("goal") == "optimize":
        return False
    if strategy.get("regional_continuation"):
        if (not optimization or not strategy.get("regional_recipe")
                or strategy["regional_continuation"]["reference"] != strategy.get("baseline")
                or record.get("refinement", {}).get("regional_continuation")
                != strategy["regional_continuation"]):
            return False
    values = manifest["plan"]["baseline_effective_values"]
    if info["phase"] in {"validate", "joint"} and any(
            r["values"] != values or r["method"] not in record["methods"].values()
            for r in info["approved"]):
        return False
    if strategy.get("shared_model_check"):
        from diffeoforge.guided_shared_check import verify

        verify(info, record, manifest, study_root)
    if strategy.get("form_progress"):
        from diffeoforge.pilot_form_progress import verify

        verify(info, record, manifest, study_root)
    if strategy.get("common_model_step"):
        from diffeoforge.pilot_common_model import verify

        verify(info, record, manifest, study_root)
    if strategy.get("common_diagnosis_test"):
        from diffeoforge.pilot_common_model import verify_diagnostic

        verify_diagnostic(info, record, manifest, study_root)
    if strategy.get("common_basis_step"):
        from diffeoforge.pilot_common_basis import verify

        verify(info, record, manifest, study_root)
    if strategy.get("common_capacity_request"):
        from diffeoforge.pilot_common_capacity import verify

        verify(info, record, manifest, study_root)
    if strategy.get("common_candidate_step"):
        from diffeoforge.pilot_common_candidate import verify

        verify(info, record, manifest, study_root)
    return True


def _plan_transition(snapshot, action, identifier, *, goal=None):
    """Read-only planning; the shared verification scope ends before any writes."""
    info = guided.record(snapshot)
    source, _ = guided._origin(snapshot.study_directory)
    approved = list(info["approved"])
    guided.verify_approvals(approved)
    strategy = dict(info.get("strategy") or {})
    from diffeoforge.pilot_form_progress import retain_review_for_trial

    strategy = retain_review_for_trial(snapshot, identifier, strategy)
    strategy.pop("optimization", None)
    strategy.pop("regional_continuation", None)
    strategy.pop("regional_recipe", None)
    strategy.pop("failure_parent_recovery", None)
    strategy.pop("common_model_step", None)
    strategy.pop("common_diagnosis_test", None)
    strategy.pop("common_basis_step", None)
    strategy.pop("common_capacity_request", None)
    strategy.pop("common_candidate_step", None)
    strategy.pop("common_multiscale", None)
    strategy.pop("control_capacity_request", None)
    strategy["previous"] = dict(directory=str(snapshot.study_directory),
        manifest_sha256=sha256_file(snapshot.study_directory / study.STUDY_MANIFEST))
    history = [*info["history"], dict(**strategy["previous"], outcome="adaptive_" + action)]
    values = snapshot.plan.effective_values
    cases, _last = _context(snapshot)
    feedback = None
    density_comparison = None
    preference = _preference(snapshot)
    if action == "density_comparison":
        density_comparison = state(snapshot)["density_comparisons"].get(identifier)
        if not density_comparison:
            raise ValueError("Choose a reviewed, unsuitable high-disparity single fit")
        from diffeoforge.guided_feedback import region_state, verify_reference

        reference = density_comparison["reference"]
        parent = verify_reference(reference)
        target = reference["target"]
        marked, cleared = region_state(snapshot, identifier, target)
        feedback = capture(parent, reference["candidate_id"], target, regions=marked)
        feedback["regions_cleared"] = cleared
        strategy.update(baseline=reference, anchor=reference, control_basis=reference,
                        search_family="density")
        methods = (reference["method"],)
        values = guided.adjusted_values(reference["values"], "density", conservative=True)
        preference = None
        phase, goal = "refine", "density"
    elif action in {"recover", "recover_from_retained", "recover_start"}:
        bound = action != "recover_from_retained" and isinstance(goal, dict)
        if bound and goal.get("reviewed_next") and any(
            snapshot.visual_reviews.get(c.candidate_id) is not False
            for c in snapshot.candidates if c.status == "completed"
        ):
            raise ValueError("The saved reviews changed. Reopen the next-step guidance.")
        request = goal["request"] if bound else goal or "unsure"
        if action == "recover_from_retained":
            from diffeoforge.guided_failed_parent import trial

            proposed = trial(snapshot, identifier, goal, state(snapshot))
        elif action == "recover_start":
            from diffeoforge.guided_working_fit import trial

            proposed = trial(snapshot, identifier, request)
        else:
            proposed = trial_proposal(snapshot, identifier, request)
        if bound and any(proposed[key] != goal[expected] for key, expected in (
            ("initialization_reference", "reference"), ("values", "values"), ("goal", "goal"),
        )):
            raise ValueError("The suggested trial changed. Reopen the next-step guidance.")
        if not proposed["available"]:
            raise ValueError(proposed.get("blocked_reason", "This unchanged combination was "
                "already tested. Inspect saved alternatives or choose another adjustment; "
                "no fit was prepared."))
        baseline_snapshot, baseline_id = snapshot, identifier
        if proposed["initialization_reference"]:
            from diffeoforge.guided_feedback import verify_reference

            reference = proposed["initialization_reference"]
            baseline_snapshot = verify_reference(reference)
            baseline_id = reference["candidate_id"]
        target, values, methods = proposed["target"], proposed["values"], (proposed["method"],)
        from diffeoforge.guided_feedback import region_state

        comparison = proposed["anchor"]
        comparison_snapshot = verify_reference(comparison)
        marked, cleared = region_state(snapshot, identifier, target)
        if bound and goal["regions"] != marked:
            raise ValueError("The marked areas changed. Reopen the next-step guidance.")
        feedback = capture(comparison_snapshot, comparison["candidate_id"], target, regions=marked)
        feedback["regions_cleared"] = cleared
        strategy["baseline"] = _reference(baseline_snapshot, baseline_id, target)
        if proposed.get("failure_parent_recovery"):
            strategy["failure_parent_recovery"] = proposed["failure_parent_recovery"]
        if proposed.get("regional_continuation"):
            strategy["regional_continuation"] = proposed["regional_continuation"]
        if proposed.get("regional_recipe"):
            strategy["regional_recipe"] = proposed["regional_recipe"]
        strategy["anchor"] = comparison
        strategy["control_basis"] = strategy["baseline"]
        if proposed.get("control_capacity_request"):
            strategy["control_capacity_request"] = proposed["control_capacity_request"]
        strategy["search_family"] = (info.get("strategy") or {}).get(
            "search_family", info.get("goal")) if proposed["numerical_extension"] else (
                proposed["goal"])
        if proposed["numerical_extension"]:
            from diffeoforge.pilot_common_model import EFFORT_VERSION
            from diffeoforge.pilot_iteration_accounting import branch_total

            seed_candidate = next(c for c in baseline_snapshot.candidates
                                  if c.candidate_id == baseline_id)
            strategy["optimization"] = dict(version=EFFORT_VERSION,
                reference=strategy["baseline"], iterations=proposed["optimization_iterations"],
                initial_iterations=branch_total(baseline_snapshot, seed_candidate),
                common_model=proposed.get("common_optimization", False))
        strategy["difficult_targets"] = list(dict.fromkeys(
            [target, *strategy.get("difficult_targets", [])]))
        strategy["hypothesis_count"] = strategy.get("hypothesis_count", 0) + 1
        preference = preference if preference and preference["method"] == methods[0] else None
        approved = _compatible(snapshot, methods[0], values, cases)
        phase, goal = "refine", proposed["goal"]
    elif action == "shared_check":
        from diffeoforge.guided_shared_check import declaration

        marker = declaration(snapshot, identifier)
        strategy["shared_model_check"] = marker
        strategy["baseline"] = marker["reference"]
        strategy["control_basis"] = marker["reference"]
        strategy["anchor"] = marker["reference"]
        strategy.pop("search_family", None)
        preference = None
        approved = []  # Local approval never supplies common-objective coverage.
        target, values, methods = (info["target"], marker["reference"]["values"],
                                   (marker["reference"]["method"],))
        phase, goal = "refine", "shared_check"
    elif action in {"confirm", "confirm_start"}:
        accepted, accepted_id = snapshot, identifier
        if action == "confirm_start":
            from diffeoforge.guided_feedback import selection, verify_reference

            anchor = selection(snapshot, identifier)
            if not anchor:
                raise ValueError("Choose an inspected starting fit first")
            accepted, accepted_id = verify_reference(anchor), anchor["candidate_id"]
        if accepted.attachment_comparison.get("regional_objective"):
            raise ValueError("This fit uses explicit regional constraints. It remains saved and "
                "can be refined or inspected, but is not approval of the common atlas objective. "
                "A shared cohort protocol must be checked separately before atlas/PCA use.")
        row = guided._approved_record(accepted, accepted_id)
        preference = _reference(accepted, accepted_id)
        strategy["control_basis"] = preference
        values, methods = row["values"], (row["method"],)
        approved = list({r["filename"]: r for r in
            [*_compatible(snapshot, methods[0], values, cases), row]}.values())
        covered = {r["filename"] for r in approved}
        order = list(dict.fromkeys([*strategy.get("difficult_targets", []), *info["pilot_order"]]))
        target = next((n for n in order if n not in covered), None)
        phase = "validate" if target else "joint"
        if phase == "joint":
            from diffeoforge.guided_accepted_fit import rejected_joint
            from diffeoforge.guided_joint_initialization import references

            blocked = rejected_joint(snapshot, preference, proposed_references=references(approved))
            if blocked:
                raise ValueError(blocked)
    elif action == "compare_unresolved":
        from diffeoforge.method_comparison_followup import provisional_comparison

        comparison = provisional_comparison(snapshot, context=dict(cases=cases))
        if not comparison["available"]:
            raise ValueError(comparison["explanation"])
        target = comparison["target"]
        # New target, fresh ordinary fields. Prior local terms/marks stay solely
        # in the hash-bound old study/history and cannot leak to another animal.
        for key in ("baseline", "anchor", "control_basis", "search_family"):
            strategy.pop(key, None)
        methods, phase, preference, goal = ("current", "varifold"), "screen", None, None
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
    if target != info["target"] and phase != "refine":
        # Shared method settings/control locations transfer to coverage checks;
        # a previous animal's local comparison and search do not. Recovery into
        # an individual refinement has just bound its own explicit local field.
        for key in ("baseline", "anchor", "search_family"):
            strategy.pop(key, None)
    strategy["preference"] = preference
    return dict(source=source, previous=snapshot, phase=phase, target=target, methods=methods,
        values=values, approved=approved, history=history, spent=info["screen_trials_spent"],
        goal=goal, feedback=feedback, strategy=strategy, density_comparison=density_comparison)


def transition(snapshot, action, identifier, *, goal=None):
    """Called under the existing transition lock; never dispatch an optimizer."""
    if action == "multiscale_detail":
        from diffeoforge.pilot_multiscale_study import prepare_detail

        return prepare_detail(snapshot)
    if action in {"common_continue", "adopt_common_model"}:
        from diffeoforge.pilot_form_progress import transition as common_transition

        return common_transition(snapshot, identifier,
            common_target=goal or guided.record(snapshot)["target"]
                if action == "common_continue" else None,
            revise=action == "adopt_common_model", model=True)
    if action in {"next_form", "form_model_check"}:
        from diffeoforge.pilot_form_progress import transition as next_form

        return next_form(snapshot, identifier, model=action == "form_model_check")
    if action == "confirm_start":
        from diffeoforge.pilot_form_progress import transition as next_form
        from diffeoforge.pilot_form_progress import uses_starting_progress

        if uses_starting_progress(snapshot, identifier):
            return next_form(snapshot, identifier, starting_fit=True)
    if action == "restore_accepted":
        from diffeoforge.guided_accepted_fit import select

        return select(snapshot, identifier, goal)
    if action == "working_start":
        from diffeoforge.guided_working_fit import save

        return save(snapshot.study_directory, identifier, goal)
    if action in {"select_start", "feedback"}:
        from diffeoforge.guided_feedback import save_feedback, select

        return (select(snapshot.study_directory, identifier, goal) if action == "select_start"
                else save_feedback(snapshot.study_directory, identifier, goal))
    if action == "prefer":
        reference = _reference(snapshot, identifier)
        study._append_event(snapshot.study_directory, "guided_method_preference", dict(
            preference=reference, anatomical_approval_created=False, optimizer_started=False))
        return study.load_reference_calibration_study(snapshot.study_directory)
    if guided.record(snapshot)["phase"] == "joint" and action not in {"recover", "recover_start"}:
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
