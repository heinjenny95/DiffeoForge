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


def preview(snapshot, context):
    """Offer one read-only next view, without remeasuring geometry or changing a fit."""
    record = snapshot.attachment_comparison
    info = guided.record(snapshot)
    if (not info or not info.get("target") or info["phase"] == "joint"
            or snapshot.plan.pilot_subject_count != 1 or is_common_check(info)
            or record.get("regional_objective") or any(snapshot.visual_reviews.values())
            or any(c.status not in {"completed", "failed"} for c in snapshot.candidates)):
        return None
    target = info["target"]
    directory = str(snapshot.study_directory)
    origin = Path(info["origin"]).resolve()
    with study.calibration_verification_scope():
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
