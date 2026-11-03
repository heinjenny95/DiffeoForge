"""Compare a common field with the explicitly accepted shape; never approve anatomy.

Only completed, identity-bound geometry is read in preparation workers. Scores
rank bounded experiments, not unique causes or permission to change a protocol.
"""
from collections import OrderedDict
from copy import deepcopy
from pathlib import Path
from threading import RLock

VERSION = "accepted-shape-common-diagnosis-v1"
_CACHE = OrderedDict()
_LOCK = RLock()


def _geometry(parent, candidate, target):
    from diffeoforge import reference_calibration_study as study
    from diffeoforge.mesh import sha256_file
    from diffeoforge.regional_evaluation import endpoint
    from diffeoforge.result_report import collect_run_report
    from diffeoforge.surface_io import load_surface_mesh

    manifest = study._verify_manifest(parent.study_directory)
    original = next(r for r in manifest["inputs"]["subjects"] if r["filename"] == target)
    run = study.calibration_candidate_run_directory(candidate)
    report = collect_run_report(run)
    object_id = report.manifest["effective_config"]["model"]["object_id"]
    rows = [r for r in report.inventory
            if ("__Reconstruction__" + object_id + "__subject_") in r["path"]
            and r["path"].endswith("__subject_" + target + ".vtk")]
    if not rows:
        return None  # Explicitly unavailable; never substitute a proxy or an old field.
    if len(rows) != 1:
        raise ValueError("Common diagnosis requires one bound reconstruction")
    row = endpoint(candidate) or dict(
        path=str(study._safe_study_path(run / "output", rows[0]["path"])),
        sha256=rows[0]["sha256"])
    path = Path(row["path"])
    if sha256_file(path) != row["sha256"]:
        raise ValueError("Common diagnosis reconstruction changed")
    loaded = load_surface_mesh(path)
    if loaded.metadata.sha256 != row["sha256"]:
        raise ValueError("Common diagnosis geometry changed while loading")
    return loaded.geometry, original, manifest["inputs"]["template"]["sha256"], report


def _compare(accepted_ref, current_ref, *, regions=None):
    from diffeoforge import reference_calibration_study as study
    from diffeoforge.guided_feedback import verify_reference
    from diffeoforge.reference_attachment_comparison import compare_geometry
    from diffeoforge.reference_calibration import _canonical_hash
    from diffeoforge.surface_io import load_surface_mesh

    accepted, current = (verify_reference(r) for r in (accepted_ref, current_ref))
    if (accepted_ref["target"] != current_ref["target"]
            or accepted.attachment_comparison["guided"]["origin"]
            != current.attachment_comparison["guided"]["origin"]
            or accepted.visual_reviews.get(accepted_ref["candidate_id"]) is not True):
        raise ValueError("Common diagnosis requires this cohort's approved individual shape")
    regions = deepcopy(accepted.problem_regions.get(accepted_ref["candidate_id"], {}).get(
        accepted_ref["target"], []) if regions is None else regions)
    pairs = []
    for parent, ref in ((accepted, accepted_ref), (current, current_ref)):
        candidate = next(c for c in parent.candidates if c.candidate_id == ref["candidate_id"])
        pair = _geometry(parent, candidate, ref["target"])
        if pair is None:
            return None
        pairs.append((parent, candidate, pair))
    first, second = pairs[0][2], pairs[1][2]
    if first[1]["sha256"] != second[1]["sha256"] or first[2] != second[2]:
        raise ValueError("Common diagnosis original or template identity differs")
    original_path = study._safe_study_path(accepted.study_directory, first[1]["copy"])
    original = load_surface_mesh(original_path)
    if original.metadata.sha256 != first[1]["sha256"]:
        raise ValueError("Common diagnosis original changed")
    from diffeoforge.pilot_regions import validate

    validate({accepted_ref["target"]: regions} if regions else {},
             {accepted_ref["target"]: first[1]["sha256"]})
    key = _canonical_hash(dict(version=VERSION, accepted=accepted_ref, current=current_ref,
                               regions=regions))
    with _LOCK:
        if key in _CACHE:
            _CACHE.move_to_end(key)
            return deepcopy(_CACHE[key])
    evidence = []
    for _, candidate, pair in pairs:
        saved = (candidate.metrics or {}).get("attachment_comparison", {}).get(
            "subjects", {}).get(accepted_ref["target"])
        evidence.append(saved if saved and saved.get("repeats") else compare_geometry(
            original.geometry, pair[0], original_key=first[1]["sha256"]))
    from diffeoforge.pilot_common_capacity import count

    result = dict(accepted=evidence[0], current=evidence[1],
        agreement=compare_geometry(first[0], second[0]),
        original_sha256=first[1]["sha256"], template_sha256=first[2],
        objective_tail=[r.log_likelihood for r in second[3].convergence[-6:]],
        accepted_local=bool(accepted.attachment_comparison.get("regional_objective")),
        accepted_controls=count(accepted_ref),
        current_controls=current.attachment_comparison["controls"]["count"])
    if regions:
        from diffeoforge.guided_response import measured

        result["marked_accepted"] = measured(accepted_ref, regions)["baseline"]
        result["marked_current"] = measured(current_ref, regions)["baseline"]
    with _LOCK:
        _CACHE[key] = deepcopy(result)
        while len(_CACHE) > 32:
            _CACHE.popitem(last=False)
    return result


def assess(measured, previous=None):
    """Repeat-aware local and whole-shape comparisons; mixed change vetoes continuation."""
    a, b = measured["accepted"], measured["current"]
    floor = a["diagonal"] * 1e-4
    lost = []
    labels = set.intersection(*(set(r.get("regions", {})) for r in b["repeats"]))
    for label in sorted(labels):
        x = [r.get("regions", {}).get(label) for r in a["repeats"]]
        y = [r["regions"][label] for r in b["repeats"]]
        if min(r["count"] for r in y) < 1:
            continue
        # Sparse important features keep their repeat-confirmed maximum. A new
        # reverse-direction cell is compared with the accepted worst envelope.
        baseline = (max(r["tail"] for r in x) if all(x) else
                    max(r["regional_tail"] for r in a["repeats"]))
        if min(r["tail"] for r in y) > baseline * 1.15 + floor:
            lost.append(dict(region=label, accepted=baseline,
                             common=min(r["tail"] for r in y)))
    whole_gap = any(min(r[k] for r in b["repeats"]) >
        max(r[k] for r in a["repeats"]) * 1.15 + floor for k in ("mean", "p95", "p99"))
    for index, (first, second) in enumerate(zip(measured.get("marked_accepted", []),
                                               measured.get("marked_current", []), strict=True)):
        if first["region"] != second["region"]:
            raise ValueError("Accepted/common marked geometry must use the same original areas")
        for key in ("original_to_fit_p95", "fit_to_original_p95"):
            x = [r[key] for r in first["repeats"] if r.get(key) is not None]
            y = [r[key] for r in second["repeats"] if r.get(key) is not None]
            if len(x) == len(y) == 2 and min(y) > max(x) * 1.15 + floor:
                lost.append(dict(region=f"mark:{index}:{key}", accepted=max(x), common=min(y)))
    direct = measured["agreement"]["repeats"]
    trend = "unknown"
    if previous:
        before = previous["agreement"]["repeats"]
        improved = max(r["p95"] for r in direct) + floor < min(
            r["p95"] for r in before) * .95
        regressed = any(min(r[k] for r in b["repeats"]) > max(
            r[k] for r in previous["current"]["repeats"]) * 1.15 + floor
                        for k in ("p95", "p99", "regional_tail"))
        for label in lost:
            values = [r.get("regions", {}).get(label["region"]) for r in
                      previous["current"]["repeats"]]
            if all(values) and label["common"] > max(r["tail"] for r in values) * 1.15 + floor:
                regressed = True
        for first, second in zip(previous.get("marked_current", []),
                                 measured.get("marked_current", []), strict=True):
            if first["region"] != second["region"]:
                raise ValueError("Common trend must keep the same accepted marked regions")
            for key in ("original_to_fit_p95", "fit_to_original_p95"):
                x = [r[key] for r in first["repeats"] if r.get(key) is not None]
                y = [r[key] for r in second["repeats"] if r.get(key) is not None]
                if len(x) == len(y) == 2 and min(y) > max(x) * 1.15 + floor:
                    regressed = True
        trend = "worse" if regressed else "improving" if improved else "plateau"
    marked_progress = None
    critical_marks = [r for r in lost if r['region'].startswith('mark:')]
    if previous and critical_marks:
        progress = []
        for loss in critical_marks:
            _, index, key = loss['region'].split(':', 2)
            now = measured['marked_current'][int(index)]['repeats']
            before = previous['marked_current'][int(index)]['repeats']
            progress.append(max(r[key] for r in now) + floor
                            < min(r[key] for r in before) * .95)
        marked_progress = all(progress)
    tail = measured.get("objective_tail", [])
    numerical_progress = (len(tail) >= 3 and all(
        y >= x for x, y in zip(tail[:-1], tail[1:], strict=True))
                          and tail[-1] - tail[0] > max(abs(tail[0]), 1.) * 1e-6)
    return dict(local_losses=lost, gap=bool(lost or whole_gap), trend=trend,
                marked_progress=marked_progress,
                accepted_local=measured["accepted_local"], numerical_progress=numerical_progress,
                accepted_controls=measured["accepted_controls"],
                current_controls=measured["current_controls"],
                agreement_p95=max(r["p95"] for r in direct),
                accepted_p95=max(r["p95"] for r in a["repeats"]),
                common_p95=max(r["p95"] for r in b["repeats"]),
                warnings=list(b.get("warnings", [])))


def diagnose(snapshot, value, current_ref, previous_ref=None):
    from diffeoforge.guided_feedback import reference, region_state, verify_reference

    row = next((r for r in value["reviews"] if r["filename"] == current_ref["target"]), None)
    if not row:
        return None
    ref = dict(row)
    ref["target"] = ref.pop("filename")
    parent = verify_reference(ref)
    accepted = reference(parent, row["candidate_id"])
    current = verify_reference(current_ref)
    regions, cleared = region_state(current, current_ref["candidate_id"], current_ref["target"])
    # Use one current annotation set on every compared field. Explicit Clear
    # stays empty; absent legacy annotations retain the accepted-fit fallback.
    regions = regions if regions or cleared else None
    measured = _compare(accepted, current_ref, regions=regions)
    if measured is None:
        return None
    previous = _compare(accepted, previous_ref, regions=regions) if previous_ref else None
    return dict(version=VERSION, accepted=accepted, current=current_ref,
                previous=previous_ref, original_sha256=measured["original_sha256"],
                accepted_test_number=parent.attachment_comparison["guided"]["screen_trials_spent"],
                template_sha256=measured["template_sha256"],
                **assess(measured, previous))


def recommend(diagnosis, *, capped, iteration_tests=0, density_tested=False, veto=False):
    """A bounded experiment choice, explicitly separate from anatomical acceptance."""
    if not diagnosis:
        return None
    if not diagnosis["gap"]:
        return dict(kind="inspect", reason="Sampled surfaces are close to the accepted fit. "
            "Inspect the remaining feature difference; these samples cannot approve anatomy.")
    improving = diagnosis["trend"] == "improving" or (
        diagnosis["trend"] == "unknown" and diagnosis["numerical_progress"]
        and not diagnosis["accepted_local"])
    if (capped and improving and diagnosis.get('marked_progress') is not False
            and iteration_tests < 2 and not veto and not diagnosis["warnings"]):
        return dict(kind="iterations", reason="The common field is still improving toward "
            "the accepted shape without a measured whole-shape regression. Test up to 120 "
            "additional steps with the same basis.")
    if not density_tested and not diagnosis["warnings"]:
        return dict(kind="capacity", reason="The accepted shape exposes unresolved local "
            "or whole-shape differences. Compare additional controls before another unchanged "
            "iteration round. This is a capacity hypothesis, not a proven cause.")
    return dict(kind="stalled", reason="The bounded comparison has not resolved this model. "
        "Keep all accepted fits; review a shared-model revision or another fitting scale "
        "rather than repeating identical tests.")
