"""Present an eligible saved-field continuation without changing its contract.

The existing proposal owns numerical eligibility and the extra iteration budget.
This read-only layer separates a still-improving objective from measured surface
improvement and refuses a recommendation when the saved geometry regressed.
"""

import math


def _guarded_tail(candidate, marker):
    """Read exact accepted costs only through an already verified guard contract.

    Printed native likelihoods can round several improving states to the same
    number. The regional continuation proposal already verified their exported
    field; its seals let this presentation layer use the actual accepted values.
    """
    from diffeoforge.mesh import sha256_file
    from diffeoforge.reference_calibration_study import calibration_candidate_run_directory
    from diffeoforge.regional_continuation import _json, _json_line, _snapshot_folder

    try:
        guard = calibration_candidate_run_directory(candidate).resolve() / "output/numerical-guard"
        seals = marker["source_seals"]
        paths = [guard / name for name in ("session.json", "events.jsonl", "best-latest.json")]
        if ((guard / "violation.json").exists()
                or any(sha256_file(path) != seals.get(str(path)) for path in paths)):
            return None
        fingerprint = marker["guard_objective_fingerprint"]
        session = _json(paths[0])
        if session.get("provenance", {}).get("objective_fingerprint") != fingerprint:
            return None
        evaluations, accepted, exports, terminals = {}, [], [], []
        for line in paths[1].read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = _json_line(line)
            kind = row["kind"]
            if kind == "terminal_violation":
                return None
            if kind == "objective_evaluation":
                value = float.fromhex(row["f_hex"])
                if (row.get("objective_finite") is not True
                        or row.get("gradient_finite") is not True
                        or row.get("objective_fingerprint") != fingerprint
                        or not math.isfinite(value) or row["evaluation_id"] in evaluations):
                    return None
                evaluations[row["evaluation_id"]] = row
            elif kind in {"initial_accepted", "accepted_callback"}:
                evaluation = evaluations.get(row["evaluation_reference"])
                if (not evaluation or row.get("gradient_finite") is not True
                        or row["parameter_sha256"] != evaluation["parameter_sha256"]
                        or type(row.get("native_iteration")) is not int
                        or (accepted and row["native_iteration"] <= accepted[-1][0])):
                    return None
                value = float.fromhex(evaluation["f_hex"])
                if accepted and value > accepted[-1][1]:
                    return None
                accepted.append((row["native_iteration"], value,
                                 row["parameter_sha256"], row["evaluation_reference"]))
            elif kind == "native_export_parameter_binding" and not row.get("internal_callback"):
                exports.append(row)
            elif kind in {"final_result_bound_to_accepted_evaluation",
                          "native_update_returned_bound_to_accepted"}:
                if kind == "native_update_returned_bound_to_accepted" and (
                    row.get("original_update_returned_normally") is not True
                    or row.get("configured_max_iterations")
                    != candidate.metrics["maximum_iterations"]
                ):
                    return None
                terminals.append(row)
        if len(accepted) < 2 or not exports or not terminals:
            return None
        iteration, value, key, evaluation = accepted[-1]
        if (iteration != candidate.metrics["final_iteration"]
                or key != marker["accepted_parameter_sha256"]
                or any(row["parameter_sha256"] != key
                       or row["evaluation_reference"] != evaluation
                       or (row["kind"] == "native_update_returned_bound_to_accepted"
                           and row.get("native_iteration") != iteration)
                       for row in [exports[-1], *terminals])):
            return None
        pointer = _json(paths[2])
        receipt_path = _snapshot_folder(guard, pointer["directory"]) / "receipt.json"
        if (pointer.get("parameter_sha256") != key
                or pointer.get("f_hex") != value.hex()
                or sha256_file(receipt_path) != pointer["receipt_sha256"]
                or sha256_file(receipt_path) != seals.get(str(receipt_path))):
            return None
        tail = accepted[-6:]
        if tail[-1][1] >= tail[0][1]:
            return None
        return (tail[0][0], -tail[0][1]), (tail[-1][0], -tail[-1][1])
    except (KeyError, OSError, ValueError, TypeError):
        return None


def _objective_tail(candidate):
    from diffeoforge.reference_calibration_study import calibration_candidate_run_directory
    from diffeoforge.result_report import collect_run_report

    try:
        report = collect_run_report(calibration_candidate_run_directory(candidate))
        tail = report.convergence[-6:]
        values = [float(row.log_likelihood) for row in tail]
        if (len(tail) < 2 or tail[-1].iteration != candidate.metrics["final_iteration"]
                or any(not math.isfinite(value) for value in values)
                or any(b.iteration <= a.iteration for a, b in zip(tail, tail[1:], strict=False))):
            return None
        floor = max(1., *(abs(value) for value in values)) * 1e-12
        if (values[-1] <= values[0] + floor
                or any(b < a - floor for a, b in zip(values, values[1:], strict=False))):
            return None
        return (tail[0].iteration, values[0]), (tail[-1].iteration, values[-1])
    except (KeyError, OSError, ValueError, TypeError):
        return None


def _geometry_note(candidate, target, feedback):
    subject = (candidate.metrics or {}).get("attachment_comparison", {}).get(
        "subjects", {}).get(target, {})
    marked = subject.get("marked_regions") or {}
    quality = subject.get("regional_quality") or {}
    regions = feedback.get("problem_regions", {}).get(target, [])
    if ({(feedback.get("feedback") or {}).get("symptom")}
            | {row.get("symptom") for row in regions
               if row.get("purpose", "problem") == "problem"}) & {"alignment", "topology", "view"}:
        return None
    measured_marks = [row.get("region") for row in marked.get("measurements", [])]
    if regions and measured_marks != regions and quality.get("marked_regions") != regions:
        return None  # New marks need a local decision, not a claim about older areas.
    if ((subject.get("refinement_guard") or {}).get("severe") is True
            or (subject.get("refinement_guard") or {}).get("outcome") == "regression"
            or marked.get("outcome") == "regression"
            or any(quality.get(key) is False for key in (
                "outside_preserved", "shape_preserved", "explicit_fixed_preserved",
                "transition_preserved", "no_new_intersection_flags"))
            or (feedback.get("feedback") or {}).get("outcome") in {"worse", "unsure"}):
        return None
    if marked.get("outcome") == "improved" or quality.get("local_improved") is True:
        return "Saved surface measurements improved in the marked area(s)."
    if (feedback.get("feedback") or {}).get("outcome") == "better":
        return "You rated the saved fit Better; local surface improvement is not established here."
    return ("This is objective progress; improved surface fit is not established by that number. "
            "Review the marked areas and protected shape again after continuing.")


def preview(snapshot, context, chosen):
    """Use one already verified proposal, with its exact seed and explicit allowance."""
    from diffeoforge.guided_progress import iteration_limited
    from diffeoforge.pilot_form_progress import is_common_check
    from diffeoforge.reference_guided_pilot import record

    info = record(snapshot)
    if (not info or not info.get("target") or info["phase"] == "joint"
            or snapshot.plan.pilot_subject_count != 1 or is_common_check(info)
            or any(c.status != "completed"
                   or snapshot.visual_reviews.get(c.candidate_id) is not False
                   for c in snapshot.candidates)):
        return None
    choices = []
    for candidate in snapshot.candidates:
        identifier = candidate.candidate_id
        if (not context["allowed"].get(identifier)
                or (chosen and chosen.get("editing_candidate_id") != identifier)
                or (not chosen and context.get("preferred")
                    and snapshot.attachment_comparison["methods"][identifier]
                    != context["preferred"])):
            continue
        feedback = context["feedback"].get(identifier) or {}
        working = context["working_proposals"].get(identifier)
        proposal = (working or context["proposals"].get(identifier, {})).get("goal:optimize")
        if (feedback.get("needs_direction") or not iteration_limited(candidate)
                or not proposal or not proposal["available"]
                or proposal["goal"] != "optimize" or not proposal["numerical_extension"]
                or proposal["target"] != info["target"]):
            continue
        seed = proposal["initialization_reference"]
        # The footer names the completed field that will actually be extended.
        # Merely navigating to an older fit must never extend a different one.
        if (not seed or seed["directory"] != str(snapshot.study_directory)
                or seed["candidate_id"] != identifier
                or (chosen and chosen["reference"] != seed)):
            continue
        choice = next((row for row in feedback.get("choices", [])
                       if row["reference"] == seed), None)
        budget = proposal["optimization_iterations"]
        geometry = _geometry_note(candidate, info["target"], feedback)
        guarded = proposal.get("regional_continuation")
        tail = ((_guarded_tail(candidate, guarded) if guarded else _objective_tail(candidate))
                if geometry is not None else None)
        if (choice is None or tail is None or type(budget) is not int or budget <= 0):
            continue
        (first, before), (last, after) = tail
        before_label, after_label = f"{before:.10g}", f"{after:.10g}"
        if before_label == after_label:
            before_label, after_label = f"{before:.17g}", f"{after:.17g}"
        source = "accepted guard iterations" if guarded else "logged iterations"
        regions = feedback.get("problem_regions", {}).get(info["target"], [])
        choices.append(dict(
            mode="trial", identifier=identifier, current=seed, continuation=True,
            action="adaptive_recover_start" if working else "adaptive_recover",
            title=f"Continue saved fit · up to {budget:,} more iterations",
            start_label=choice["label"],
            reason=(f"Native log-likelihood still improves: {before_label} → {after_label} "
                    f"({source} {first}–{last}; higher is better). {geometry} "
                    f"Keep the saved field and settings; up to {budget:,} new iterations, "
                    "with new optimizer history. Prepare first, then explicitly choose Run."),
            request=dict(request="goal:optimize", reference=seed, values=proposal["values"],
                         goal="optimize", regions=regions, reviewed_next=True,
                         optimization_iterations=budget),
        ))
    return choices[0] if len(choices) == 1 else None
