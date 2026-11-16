"""Find a useful visual comparison from verified, already measured pilot fits."""

from math import isclose, isfinite
from pathlib import Path

from diffeoforge import reference_calibration_study as study
from diffeoforge import reference_guided_pilot as guided
from diffeoforge.guided_density import controls_for
from diffeoforge.guided_feedback import verify_reference
from diffeoforge.pilot_form_progress import is_common_check
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


def _regions(current, alternative):
    """Show at most one clear contrast and one persistent large gap."""
    difference, residual = [], []
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
            difference.append((min(x) - max(y), dict(row, change="improved")))
        elif _lowers(y, x, diagonal):
            difference.append((min(y) - max(x), dict(row, change="regressed")))
        if min(*x, *y) > diagonal * 1e-6:
            residual.append((min(*x, *y), dict(row, change="remaining")))
    rows = [max(difference, key=lambda item: item[0])[1]] if difference else []
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


def _partial_local_fit(snapshot, reference):
    """Use the researcher's narrower review, even when the remaining mark moved."""
    identifier, target = reference["candidate_id"], reference["target"]
    if (not snapshot.attachment_comparison.get("regional_objective")
            or snapshot.visual_reviews.get(identifier) is not False):
        return False
    prepared = (guided.record(snapshot).get("feedback") or {}).get("regions", [])
    reviewed = snapshot.problem_regions.get(identifier, {}).get(target, [])
    return 0 < len(_problem_marks(reviewed)) < len(_problem_marks(prepared))


def _return_direction(snapshot, context, identifier, reference, reason):
    data = context["feedback"].get(identifier) or {}
    choice = next((row for row in data.get("choices", [])
                   if row["reference"] == reference), None)
    if choice and reference["target"] == guided.record(snapshot)["target"]:
        quality = local_quality_note(verify_reference(reference), reference)
        return dict(mode="return", identifier=identifier, current=reference,
                    start_label=choice["label"],
                    reason=" ".join(filter(None, (reason, quality))),
                    quality_warning=quality)
    return None


def _density_return(snapshot, context, candidate_id, outcome_note):
    info = guided.record(snapshot)
    seed = snapshot.attachment_comparison["refinement"]["reference"]
    previous = info["strategy"]["previous"]["directory"]
    data = context["feedback"].get(candidate_id) or {}
    discounted = [case["fit"] for case in context["cases"]
                  if case.get("outcome") in {"same", "worse"}]
    for row in data.get("choices", []):
        ref = row["reference"]
        if (ref["directory"] == previous and ref not in discounted
                and _partial_local_fit(verify_reference(ref), ref)):
            return _return_direction(
                snapshot, context, candidate_id, ref,
                outcome_note + " Your earlier local review left fewer "
                "areas to improve. Open that fit and confirm what to improve and retain.",
            )
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
        if case.get("outcome") not in {"same", "worse"} and _partial_local_fit(
                snapshot, case["fit"]):
            return _return_direction(
                snapshot, context, identifier, case["fit"],
                "Your local review left fewer areas to improve. Open this saved fit "
                "to confirm the remaining problem and mark the good areas to retain.",
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
    return dict(
        mode="inputs", current=reference,
        reason=reason + " Check the pose and the corresponding structure in the original "
        "template and specimen before preparing another fit.",
    )


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
        inputs = _input_direction(snapshot, context, target)
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
        return dict(result, mode="compare", alternative=other["reference"],
                    alternative_cp=other["cp"],
                    alternative_p95=max(_series(other, "p95")) * 100 / other["diagonal"],
                    regions=_regions(current, other),
                    reason="A saved fit with the other surface-matching method has lower "
                           "surface distances on both samples. Compare the same area before "
                           "choosing a new test.")
    if _progress_stalled(saved.values(), current):
        return dict(result, mode="inputs",
                    reason="Several reviewed changes on this form did not help. Compare "
                           "the original and the starting template before another fit.")
    return None
