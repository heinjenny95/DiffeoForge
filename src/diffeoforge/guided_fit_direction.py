"""Find a useful visual comparison from verified, already measured pilot fits."""

from math import isclose, isfinite
from pathlib import Path

from diffeoforge import reference_calibration_study as study
from diffeoforge import reference_guided_pilot as guided
from diffeoforge.guided_density import controls_for
from diffeoforge.guided_feedback import verify_reference
from diffeoforge.pilot_form_progress import is_common_check
from diffeoforge.pilot_regions import EDIT_VERSION, MAX_REGIONS, VERSION
from diffeoforge.reference_attachment_comparison import VERSION as COMPARISON_VERSION


def _input_identity(manifest, target):
    inputs = manifest["inputs"]
    subject = next((row for row in inputs["subjects"] if row["filename"] == target), None)
    if not subject:
        return None
    return inputs["template"]["sha256"], subject["sha256"]


def _evidence(case, origin, source, target):
    ref = case.get("fit")
    if (not ref or not case.get("individual") or case.get("severe")
            or case.get("target") != target or ref.get("target") != target):
        return None
    try:
        parent = verify_reference(ref)
        manifest = study._verify_manifest(parent.study_directory)
    except (OSError, ValueError):
        return None
    record = parent.attachment_comparison
    if (parent.plan.pilot_subject_count != 1 or record.get("regional_objective")
            or Path(record["guided"]["origin"]).resolve() != origin
            or is_common_check(record["guided"])
            or _input_identity(manifest, target) != source):
        return None
    candidate = next(c for c in parent.candidates if c.candidate_id == ref["candidate_id"])
    metrics = candidate.metrics or {}
    comparison = metrics.get("attachment_comparison", {})
    subject = comparison.get("subjects", {}).get(target, {})
    diagonal = subject.get("diagonal", 0)
    repeats = subject.get("repeats", [])
    if (metrics.get("fit_scope") != "full_targets"
            or comparison.get("version") != COMPARISON_VERSION
            or type(diagonal) not in {int, float} or not isfinite(diagonal) or diagonal <= 0
            or len(repeats) != 2
            or any(not (type(row.get(k)) in {int, float} and isfinite(row[k]) and row[k] >= 0)
                   for row in repeats for k in ("mean", "p95", "p99"))):
        return None
    return dict(reference=ref, outcome=case.get("outcome"), goal=case.get("goal"),
                cp=controls_for(record, ref["candidate_id"])["count"], diagonal=diagonal,
                repeats=repeats, warnings=subject.get("warnings", []))


def _series(row, key):
    return [rep[key] for rep in row["repeats"]]


def _lowers(before, after, diagonal):
    """Require the benefit across both independent surface samples."""
    return max(after) + diagonal * 1e-6 < min(before) * .95


def _better(current, alternative):
    diagonal = current["diagonal"]
    return (not alternative["warnings"]
            and alternative["outcome"] != "worse"
            and isclose(diagonal, alternative["diagonal"], rel_tol=1e-9)
            and _lowers(_series(current, "p95"), _series(alternative, "p95"), diagonal)
            and all(not _lowers(_series(alternative, key), _series(current, key), diagonal)
                    for key in ("mean", "p99")))


def _local_samples(row, key):
    bins = [repeat.get("regions", {}).get(key, {}) for repeat in row["repeats"]]
    if any(item.get("count", 0) < 8 or not isfinite(item.get("tail", float("nan")))
           or item["tail"] < 0 for item in bins):
        return None
    return [item["tail"] for item in bins]


def _has_local_regression(current, alternative):
    """Check every measured local bin, including losses not selected as markers."""
    for key in current["repeats"][0].get("regions", {}):
        before, after = _local_samples(current, key), _local_samples(alternative, key)
        if (before is not None and after is not None
                and _lowers(after, before, current["diagonal"])):
            return True
    return False


def _regions(current, alternative):
    """Show at most one clear contrast and one persistent large gap."""
    gains, losses, residual = [], [], []
    diagonal = current["diagonal"]
    for key in current["repeats"][0].get("regions", {}):
        prefix, _, index = key.partition(":")
        if prefix not in {"0", "1"} or not index.isascii() or not index.isdecimal():
            continue
        direction, cell = int(prefix), int(index)
        if cell >= 64:
            continue
        x, y = _local_samples(current, key), _local_samples(alternative, key)
        if x is None or y is None:
            continue
        row = dict(direction=direction, cell=[cell // 16, cell // 4 % 4, cell % 4],
                   current_p95=max(x) * 100 / diagonal,
                   alternative_p95=max(y) * 100 / diagonal)
        if _lowers(x, y, diagonal):
            gains.append((min(x) - max(y), dict(row, change="improved")))
        elif _lowers(y, x, diagonal):
            losses.append((min(y) - max(x), dict(row, change="regressed")))
        if min(*x, *y) > diagonal * 1e-6:
            residual.append((min(*x, *y), dict(row, change="remaining")))
    rows = [max(gains, key=lambda item: item[0])[1]] if gains else []
    competing = [item for item in losses if not rows or item[1]["cell"] != rows[0]["cell"]]
    if competing:
        rows.append(max(competing, key=lambda item: item[0])[1])
    if len(rows) == 2:
        return rows
    other = [item for item in residual if not rows or item[1]["cell"] != rows[0]["cell"]]
    if other:
        rows.append(max(other, key=lambda item: item[0])[1])
    return rows


def _progress_stalled(saved, current):
    """Two separately reviewed refinements, counting paired arms as one test."""
    if current["outcome"] not in {"same", "worse"}:
        return False
    trials = {}
    for row in saved:
        if row["reference"]["method"] == current["reference"]["method"] and row["goal"]:
            trials.setdefault(row["reference"]["directory"], set()).add(row["outcome"])
    stalled = 0
    for outcomes in trials.values():
        if "better" in outcomes:
            stalled = 0
        elif outcomes <= {"same", "worse"}:
            stalled += 1
    return stalled >= 2


def _no_gain(case, marked):
    """Use the visual comparison, or measurements of the exact areas still marked."""
    outcome = case.get("outcome")
    if outcome in {"same", "worse"}:
        return True
    return (outcome == "rejected" and bool(marked) and case.get("regions") == marked
            and case.get("region_outcomes") in (["unclear"], ["regression"]))


def _problem_marks(rows):
    return [row for row in rows if row.get("purpose", "problem") == "problem"]


def _bounds(region):
    if "bounds" in region:
        return region["bounds"]
    return [bound for value in region["center"]
            for bound in (value - region["radius"], value + region["radius"])]


def _overlaps(a, b):
    a, b = _bounds(a), _bounds(b)
    return all(a[i] <= b[i + 1] and b[i] <= a[i + 1] for i in (0, 2, 4))


def partial_mark_draft(snapshot, reference):
    """Draft Retain marks from an explicit narrower review of this exact saved fit."""
    identifier, target = reference["candidate_id"], reference["target"]
    if (not snapshot.attachment_comparison.get("regional_objective")
            or snapshot.visual_reviews.get(identifier) is not False):
        return None
    prepared = (guided.record(snapshot).get("feedback") or {}).get("regions", [])
    reviewed = snapshot.problem_regions.get(identifier, {}).get(target, [])
    problems = _problem_marks(reviewed)
    if not 0 < len(problems) < len(_problem_marks(prepared)):
        return None
    draft = list(reviewed)
    suggested = 0
    for area in _problem_marks(prepared):
        if len(draft) >= MAX_REGIONS:
            break
        if any(_overlaps(area, marked) for marked in draft):
            continue
        retained = dict(area, purpose="fixed")
        if retained["version"] == VERSION:
            retained["version"] = EDIT_VERSION
        draft.append(retained)
        suggested += 1
    return dict(marks=draft, suggested=suggested, remaining=len(problems))


def _return_direction(snapshot, context, identifier, reference, reason, *, draft=None):
    data = context["feedback"].get(identifier) or {}
    choice = next((row for row in data.get("choices", [])
                   if row["reference"] == reference), None)
    if choice and reference["target"] == guided.record(snapshot)["target"]:
        quality = local_quality_note(verify_reference(reference), reference)
        return dict(mode="return", identifier=identifier, current=reference,
                    start_label=choice["label"],
                    reason=" ".join(filter(None, (reason, quality))),
                    quality_warning=quality, partial=draft is not None)
    return None


def _prior_partial(snapshot, context, candidate_id, outcome_note):
    data = context["feedback"].get(candidate_id) or {}
    discounted = [case["fit"] for case in context["cases"]
                  if case.get("outcome") in {"same", "worse"}]
    for row in data.get("choices", []):
        ref = row["reference"]
        if ref in discounted or ref["directory"] == str(snapshot.study_directory):
            continue
        draft = partial_mark_draft(verify_reference(ref), ref)
        if draft is not None:
            return _return_direction(
                snapshot, context, candidate_id, ref,
                outcome_note + " Your earlier local review left fewer areas to improve. "
                "Confirm the remaining Improve and suggested Retain areas on that saved fit.",
                draft=draft,
            )
    return None


def _density_return(snapshot, context, candidate_id, outcome_note):
    retained = _prior_partial(snapshot, context, candidate_id, outcome_note)
    if retained is not None:
        return retained
    seed = snapshot.attachment_comparison["refinement"]["reference"]
    return _return_direction(
        snapshot, context, candidate_id, seed,
        outcome_note + " Return to the exact fit used to start them "
        "and check what still needs improvement.",
    )


def local_quality_note(snapshot, reference):
    """Explain a saved field's checks when it is revisited as a provisional start."""
    candidate = next(c for c in snapshot.candidates
                     if c.candidate_id == reference["candidate_id"])
    quality = ((candidate.metrics or {}).get("attachment_comparison", {}).get("subjects", {})
               .get(reference["target"], {}).get("regional_quality", {}))
    if quality.get("numerical_selection_suitable") is not False:
        return ""
    labels = {
        "outside_preserved": "preservation outside the marked area",
        "transition_preserved": "preservation at the edge of the marked area",
        "shape_preserved": "preservation of the marked part shape",
        "no_new_intersection_flags": "surface intersections",
        "temporal_grid_stable": "time-grid stability",
        "spatial_resolution_sufficient": "original-source spatial resolution",
    }
    failed = [label for key, label in labels.items() if quality.get(key) is False]
    return ("The saved fit failed checks for " + ", ".join(failed) + "." if failed
            else "The saved fit did not pass all numerical checks.")


def _input_direction(snapshot, context, target):
    """Offer a saved start or input check after fully reviewed trials."""
    record = snapshot.attachment_comparison
    regional = record.get("regional_objective")
    density_pair = record.get("early_density_comparison")
    if not (regional or density_pair):
        return None
    candidates = {candidate.candidate_id: candidate for candidate in snapshot.candidates}
    if not all(snapshot.visual_reviews.get(i) is False and context["allowed"].get(i)
               for i in candidates):
        return None

    directory = str(snapshot.study_directory)
    current = {
        ref["candidate_id"]: case
        for case in context["cases"]
        if (ref := case.get("fit")) and ref["directory"] == directory
        and ref["candidate_id"] in candidates and ref["target"] == target
        and case.get("individual") and case.get("target") == target
    }
    if not current or current.keys() != candidates.keys():
        return None
    if regional and len(current) == 1:
        identifier, case = next(iter(current.items()))
        draft = partial_mark_draft(snapshot, case["fit"])
        if case.get("outcome") not in {"same", "worse"} and draft is not None:
            return _return_direction(
                snapshot, context, identifier, case["fit"],
                "Your local review left fewer areas to improve. Confirm the remaining "
                "Improve and suggested Retain areas on this saved fit.",
                draft=draft,
            )
    guarded_local_fit = False
    for identifier, case in current.items():
        feedback = (context.get("feedback", {}).get(identifier) or {})
        marked = feedback.get("problem_regions", {}).get(target, [])
        metrics = candidates[identifier].metrics or {}
        quality = (metrics.get("attachment_comparison", {}).get("subjects", {})
                   .get(target, {}).get("regional_quality", {}))
        guarded_local_fit = (bool(regional) and case.get("outcome") == "rejected"
                             and quality.get("numerical_selection_suitable") is False)
        if not (guarded_local_fit or _no_gain(case, marked)):
            return None

    preferred = context.get("preference")
    reference = next((r["fit"] for r in current.values() if r["fit"] == preferred),
                     next(iter(current.values()))["fit"])
    try:
        verify_reference(reference)
    except (OSError, ValueError):
        return None
    if density_pair:
        outcome_note = ("You rated both control-point trials worse."
                        if all(case["outcome"] == "worse" for case in current.values())
                        else "Both control-point trials still need work.")
        return _density_return(snapshot, context, reference["candidate_id"], outcome_note)
    reason = ("The rejected local fit did not pass its saved quality checks."
              if guarded_local_fit else "This local test did not resolve the problem.")
    retained = _prior_partial(snapshot, context, reference["candidate_id"], reason)
    if retained is not None:
        return retained
    return dict(
        mode="inputs", identifier=reference["candidate_id"], current=reference,
        reason=reason + " Check the pose and the corresponding structure in the original "
        "template and specimen before preparing another fit.",
    )


def _reviewed_alignment(snapshot, context, target):
    """Route a suspected pose or anatomy mismatch to the saved input overlay."""
    for identifier, data in context["feedback"].items():
        if (not data or not context["allowed"].get(identifier)
                or snapshot.visual_reviews.get(identifier) is not False):
            continue
        feedback = data.get("feedback") or {}
        problems = _problem_marks(data.get("problem_regions", {}).get(target, []))
        concerns = {feedback.get("symptom"), *(row["symptom"] for row in problems)}
        if not concerns.intersection({"alignment", "topology"}):
            continue
        current = next((row["reference"] for row in data["choices"] if row["current"]), None)
        if current is None:
            continue
        reason = (
            "Check whether the opening or connection exists in both the starting template "
            "and the original specimen. A mismatch there may limit fitting."
            if "topology" in concerns else
            "Your review flags a possible alignment issue. Compare the starting template "
            "and specimen in their saved coordinates before changing the fitting settings."
        )
        return dict(mode="inputs", identifier=identifier, current=current, reason=reason)
    return None


def preview(snapshot, context):
    """Offer one read-only next view, without remeasuring geometry or changing a fit."""
    record = snapshot.attachment_comparison
    info = guided.record(snapshot)
    if (not info or not info.get("target") or info["phase"] == "joint"
            or snapshot.plan.pilot_subject_count != 1 or is_common_check(info)
            or any(snapshot.visual_reviews.values())
            or any(c.status not in {"completed", "failed"} for c in snapshot.candidates)):
        return None
    target = info["target"]
    directory = str(snapshot.study_directory)
    origin = Path(info["origin"]).resolve()
    with study.calibration_verification_scope():
        inputs = _reviewed_alignment(snapshot, context, target)
        inputs = inputs or _input_direction(snapshot, context, target)
        if inputs is not None or record.get("regional_objective"):
            return inputs
        source = _input_identity(study._verify_manifest(snapshot.study_directory), target)
        if source is None:
            return None
        saved = {}
        for case in context["cases"]:
            evidence = _evidence(case, origin, source, target)
            if evidence is not None:
                ref = evidence["reference"]
                saved[(ref["directory"], ref["candidate_id"])] = evidence
    current_rows = [row for (path, candidate_id), row in saved.items()
                    if path == directory and context["allowed"].get(candidate_id)]
    if not current_rows:
        return None
    comparison = record.get("early_density_comparison") or {}
    current = max(current_rows, key=lambda row: (
        row["reference"] == context.get("preference"),
        row["reference"]["candidate_id"] == comparison.get("denser_candidate_id"),
        row["reference"]["method"] == context.get("preferred"),
    ))
    ref = current["reference"]
    alternatives = [row for row in saved.values()
                    if row["reference"]["method"] != ref["method"] and _better(current, row)]
    result = dict(identifier=ref["candidate_id"], current=ref, target=target,
                  current_cp=current["cp"], alternative=None, alternative_cp=None,
                  current_p95=max(_series(current, "p95")) * 100 / current["diagonal"],
                  alternative_p95=None, regions=[])
    if alternatives:
        other = min(alternatives, key=lambda row: max(_series(row, "p95")))
        regions = _regions(current, other)
        tradeoff = _has_local_regression(current, other)
        return dict(result, mode="compare", alternative=other["reference"],
                    metric_preference=None if tradeoff else "alternative", tradeoff=tradeoff,
                    alternative_cp=other["cp"],
                    alternative_p95=max(_series(other, "p95")) * 100 / other["diagonal"],
                    regions=regions,
                    reason="The saved fit has lower whole-surface distances but a local "
                           "area is farther away. Inspect the trade-off before choosing a fit."
                    if tradeoff else
                    "A saved fit with the other surface-matching method has lower "
                           "surface distances on both samples. Compare the same area before "
                           "choosing a new test.")
    tradeoffs = []
    for other in saved.values():
        if (
            other is current or other["warnings"] or other["outcome"] == "worse"
            or not isclose(other["diagonal"], current["diagonal"], rel_tol=1e-9)
        ):
            continue
        regions = _regions(current, other)
        if {row["change"] for row in regions} == {"improved", "regressed"}:
            strength = min(abs(row["current_p95"] - row["alternative_p95"]) for row in regions)
            tradeoffs.append((strength, other, regions))
    if tradeoffs:
        _, other, regions = max(tradeoffs, key=lambda item: item[0])
        return dict(
            result, mode="compare", tradeoff=True, alternative=other["reference"],
            alternative_cp=other["cp"],
            alternative_p95=max(_series(other, "p95")) * 100 / other["diagonal"],
            regions=regions,
            reason="Each saved fit is closer in a different area. Inspect both marked areas "
                   "and decide which structure matters before preparing another test.",
        )
    if _progress_stalled(saved.values(), current):
        return dict(result, mode="inputs",
                    reason="Several reviewed changes on this form did not help. Compare "
                           "the original and the starting template before another fit.")
    return None
